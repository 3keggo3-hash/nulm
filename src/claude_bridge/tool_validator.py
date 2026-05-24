"""Tool schema validator for MCP tool security validation.

Validates incoming tool schemas from discovered MCP peers to ensure
they meet security requirements before being registered or used.
"""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from claude_bridge._detective_classifiers import get_prompt_injection_classifier

UNICODE_CONTROL_CHARS = (
    "\u202e",
    "\u202d",
    "\u200b",
    "\u200c",
    "\u200d",
    "\ufeff",
)

HOMOGLYPHS: dict[str, str] = {
    "a": "\u0430",
    "e": "\u0435",
    "o": "\u043e",
    "c": "\u0441",
    "p": "\u0440",
    "y": "\u0443",
    "x": "\u0445",
    "A": "\u0410",
    "B": "\u0412",
    "C": "\u0421",
    "E": "\u0415",
    "H": "\u041d",
    "K": "\u041a",
    "M": "\u041c",
    "O": "\u041e",
    "P": "\u0420",
    "T": "\u0422",
    "X": "\u0425",
    "Y": "\u0423",
}

LATIN_HOMOGLYPHS: dict[str, str] = {v: k for k, v in HOMOGLYPHS.items()}

ALLOWED_TYPES = {"string", "integer", "boolean", "array", "object"}
MAX_PARAM_COUNT = 20
MAX_DESCRIPTION_LENGTH = 500
BLOCKED_PATTERNS = [
    "eval(",
    "exec(",
    "import os",
    "__import__",
    "subprocess",
    "open(",
    "rm -",
    "DROP TABLE",
    "DELETE FROM",
    "INSERT INTO",
    "UPDATE ",
    "CREATE USER",
    "GRANT ",
]


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    reason: str
    risk_level: str
    blocked_patterns: tuple[str, ...] = ()
    prompt_injection: tuple[str, ...] = ()
    unicode_issues: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "reason": self.reason,
            "risk_level": self.risk_level,
            "blocked_patterns": list(self.blocked_patterns),
            "prompt_injection": list(self.prompt_injection),
            "unicode_issues": list(self.unicode_issues),
        }

    def __str__(self) -> str:
        parts = [f"valid={self.valid}", f"reason={self.reason}", f"risk_level={self.risk_level}"]
        if self.blocked_patterns:
            parts.append(f"blocked_patterns={self.blocked_patterns}")
        if self.prompt_injection:
            parts.append(f"prompt_injection={self.prompt_injection}")
        if self.unicode_issues:
            parts.append(f"unicode_issues={self.unicode_issues}")
        return "ValidationResult(" + ", ".join(parts) + ")"


_RISK_KEYWORDS_FILE = frozenset(
    [
        "file",
        "filesystem",
        "read",
        "write",
        "delete",
        "rm",
        "mkdir",
        "exec",
        "execute",
        "run",
        "shell",
        "bash",
        "sh",
        "terminal",
        "sudo",
        "admin",
        "root",
        "password",
        "secret",
        "key",
        "token",
        "credential",
        "auth",
        "sql",
        "query",
        "database",
        "db",
        "spawn",
        "child",
        "process",
        "kill",
        "terminate",
    ]
)

_RISK_KEYWORDS_HIGH = frozenset(
    [
        "exec",
        "execute",
        "run",
        "sudo",
        "admin",
        "root",
        "shell",
        "bash",
        "terminal",
        "kill",
        "terminate",
        "process",
    ]
)


def _check_blocked_patterns(text: str) -> list[str]:
    text_lower = text.lower()
    found: list[str] = []
    for pattern in BLOCKED_PATTERNS:
        if pattern.lower() in text_lower:
            found.append(pattern)
    return found


def _assess_risk_level(name: str, description: str, input_schema: dict[str, Any]) -> str:
    combined = f"{name} {description}".lower()

    if any(kw in combined for kw in _RISK_KEYWORDS_HIGH):
        return "high"

    if any(kw in combined for kw in _RISK_KEYWORDS_FILE):
        return "medium"

    permissions = input_schema.get("properties", {})
    if any("path" in p or "file" in p or "cmd" in p for p in permissions):
        return "medium"

    return "low"


class ToolSchemaValidator:
    allowed_types: frozenset[str] = frozenset(ALLOWED_TYPES)
    max_param_count: int = MAX_PARAM_COUNT
    max_description_length: int = MAX_DESCRIPTION_LENGTH
    blocked_patterns: tuple[str, ...] = tuple(BLOCKED_PATTERNS)

    def __init__(
        self,
        allowed_types: frozenset[str] | None = None,
        max_param_count: int = MAX_PARAM_COUNT,
        max_description_length: int = MAX_DESCRIPTION_LENGTH,
        blocked_patterns: tuple[str, ...] | None = None,
    ) -> None:
        if allowed_types is not None:
            self.allowed_types = frozenset(allowed_types)
        if blocked_patterns is not None:
            self.blocked_patterns = tuple(blocked_patterns)
        self.max_param_count = max_param_count
        self.max_description_length = max_description_length

    def validate(self, tool_schema: dict[str, Any]) -> ValidationResult:
        if "name" not in tool_schema:
            return ValidationResult(
                valid=False,
                reason="missing required field: name",
                risk_level="unknown",
            )

        if "description" not in tool_schema:
            return ValidationResult(
                valid=False,
                reason="missing required field: description",
                risk_level="unknown",
            )

        if "inputSchema" not in tool_schema and "parameters" not in tool_schema:
            return ValidationResult(
                valid=False,
                reason="missing required field: inputSchema or parameters",
                risk_level="unknown",
            )

        name = str(tool_schema.get("name", ""))
        description = str(tool_schema.get("description", ""))

        blocked_name = _check_blocked_patterns(name)
        if blocked_name:
            return ValidationResult(
                valid=False,
                reason=f"blocked pattern in name: {blocked_name[0]}",
                risk_level="high",
                blocked_patterns=tuple(blocked_name),
            )

        blocked_desc = _check_blocked_patterns(description)
        if blocked_desc:
            return ValidationResult(
                valid=False,
                reason=f"blocked pattern in description: {blocked_desc[0]}",
                risk_level="high",
                blocked_patterns=tuple(blocked_desc),
            )

        if len(description) > self.max_description_length:
            return ValidationResult(
                valid=False,
                reason=f"description exceeds {self.max_description_length} chars",
                risk_level="medium",
            )

        schema = tool_schema.get("inputSchema") or tool_schema.get("parameters", {})
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}

        if len(properties) > self.max_param_count:
            return ValidationResult(
                valid=False,
                reason=f"parameter count {len(properties)} exceeds max {self.max_param_count}",
                risk_level="medium",
            )

        for param_name, param_def in properties.items():
            blocked_param = _check_blocked_patterns(param_name)
            if blocked_param:
                return ValidationResult(
                    valid=False,
                    reason=f"blocked pattern in parameter name: {blocked_param[0]}",
                    risk_level="high",
                    blocked_patterns=tuple(blocked_param),
                )

            param_type = (
                param_def.get("type", "string") if isinstance(param_def, dict) else "string"
            )
            if param_type not in self.allowed_types:
                return ValidationResult(
                    valid=False,
                    reason=f"invalid parameter type '{param_type}' for '{param_name}'",
                    risk_level="medium",
                )

        risk_level = _assess_risk_level(name, description, schema)
        if risk_level == "high":
            return ValidationResult(
                valid=False,
                reason="high-risk discovered tool requires explicit manual integration",
                risk_level=risk_level,
            )

        classifier = get_prompt_injection_classifier()
        combined_text = f"{name} {description}"
        is_pi, reason_pi, score_pi = classifier.classify(combined_text)
        unicode_issues = self._detect_unicode_issues(name, description)
        if is_pi or unicode_issues:
            return ValidationResult(
                valid=False,
                reason=(
                    f"prompt_injection_detected: {reason_pi}"
                    if is_pi
                    else f"unicode_issues: {unicode_issues}"
                ),
                risk_level=risk_level,
                prompt_injection=(f"score:{score_pi}", reason_pi) if is_pi else (),
                unicode_issues=tuple(unicode_issues),
            )

        return ValidationResult(
            valid=True,
            reason="ok",
            risk_level=risk_level,
            unicode_issues=tuple(unicode_issues),
        )

    def validate_many(self, tool_schemas: list[dict[str, Any]]) -> list[ValidationResult]:
        return [self.validate(schema) for schema in tool_schemas]

    def _normalize_text_for_comparison(self, text: str) -> str:
        import unicodedata

        normalized = unicodedata.normalize("NFKC", text)
        result = []
        for char in normalized:
            if char in LATIN_HOMOGLYPHS:
                result.append(LATIN_HOMOGLYPHS[char])
            else:
                result.append(char)
        return "".join(result)

    def _detect_unicode_issues(self, name: str, description: str) -> list[str]:
        issues: list[str] = []
        for char in name + description:
            if char in UNICODE_CONTROL_CHARS:
                code = hex(ord(char)).upper()
                issues.append(f"unicode_control_char:{code}")
            if char in LATIN_HOMOGLYPHS:
                issues.append(f"homoglyph:{char}→{LATIN_HOMOGLYPHS[char]}")
        return issues

    def sanitize_tool_metadata(self, name: str, description: str) -> tuple[str, str]:
        cleaned_name = "".join(c for c in name if c not in UNICODE_CONTROL_CHARS)
        cleaned_desc = "".join(c for c in description if c not in UNICODE_CONTROL_CHARS)
        return cleaned_name, cleaned_desc
