"""User-configurable guard policy loading and decision model for Claude Bridge."""

from __future__ import annotations

import fnmatch
import importlib.util
import json
import os
import re
import threading
from dataclasses import dataclass, field as dc_field
from enum import Enum
from pathlib import Path
from typing import Any

from claude_bridge.config import project_dir

_POLICY_FILENAME = ".claude-bridge-guard.json"
_RULES_YAML_FILENAME = ".claude-bridge/rules.yaml"
_MAX_ITEMS = 100
_MAX_PATTERN_LENGTH = 500
_MAX_REGEX_PATTERN_LENGTH = 256
_MAX_POLICY_FILE_BYTES = 2 * 1024 * 1024  # FIX: stricter limit for user-defined regexes
_REGEX_QUANTIFIER = r"(?:[*+?]|\{\d+(?:,\d*)?\})"
_NESTED_QUANTIFIER_PATTERN = re.compile(
    rf"\((?:[^()\\]|\\.)*{_REGEX_QUANTIFIER}(?:[^()\\]|\\.)*\)\s*{_REGEX_QUANTIFIER}"
)
_ALTERNATION_QUANTIFIER_PATTERN = re.compile(  # FIX: catch (a|aa)* style ReDoS
    rf"\((?:[^()\\]|\\.)*\|(?:[^()\\]|\\.)*\)\s*{_REGEX_QUANTIFIER}"
)


def _policy_path() -> Path:
    override = os.environ.get("CLAUDE_BRIDGE_GUARD_POLICY", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (project_dir() / _POLICY_FILENAME).resolve()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    patterns: list[str] = []
    for item in value[:_MAX_ITEMS]:
        if isinstance(item, str):
            stripped = item.strip()
            if stripped and len(stripped) <= _MAX_PATTERN_LENGTH:
                patterns.append(stripped)
    return patterns


def _regex_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    patterns: dict[str, str] = {}
    for index, (key, item) in enumerate(value.items()):
        if index >= _MAX_ITEMS:
            break
        if not isinstance(key, str) or not isinstance(item, str):
            continue
        name = key.strip()
        pattern = item.strip()
        if not name or not pattern:
            continue
        if (
            len(name) > _MAX_PATTERN_LENGTH or len(pattern) > _MAX_REGEX_PATTERN_LENGTH
        ):  # FIX: enforce 256 char limit for regex values
            continue
        regex_error = validate_regex_pattern(pattern)
        if regex_error is not None:
            continue
        patterns[name] = pattern
    return patterns


def regex_safety_reason(pattern: str) -> str | None:
    """Return a rejection reason for regex patterns with obvious ReDoS risk."""
    if len(pattern) > _MAX_REGEX_PATTERN_LENGTH:  # FIX: 256 char limit for user-defined regexes
        return "regex pattern exceeds maximum length"
    if _NESTED_QUANTIFIER_PATTERN.search(pattern):
        return "regex pattern contains nested quantifiers with ReDoS risk"
    if _ALTERNATION_QUANTIFIER_PATTERN.search(pattern):  # FIX: catch (a|aa)* style ReDoS
        return "regex pattern contains alternation with outer quantifier (ReDoS risk)"
    return None


def validate_regex_pattern(pattern: str) -> str | None:
    """Validate user-supplied regex syntax and cheap ReDoS heuristics."""
    safety_reason = regex_safety_reason(pattern)
    if safety_reason is not None:
        return safety_reason
    try:
        re.compile(pattern)
    except re.error as exc:
        return f"Invalid regex pattern: {exc}"
    return None


def custom_shell_block_reason(command: str) -> str | None:
    normalized = " ".join(command.strip().split()).lower()
    for pattern in load_guard_policy()["blocked_shell_patterns"]:
        if fnmatch.fnmatchcase(normalized, pattern.lower()):
            return f"custom policy: {pattern}"
    return None


def custom_sensitive_path_reason(target: Path) -> str | None:
    try:
        relative = target.resolve().relative_to(project_dir()).as_posix()
    except (OSError, ValueError):
        relative = target.name
    candidates = {target.name, relative}
    for pattern in load_guard_policy()["sensitive_path_patterns"]:
        if any(fnmatch.fnmatchcase(candidate, pattern) for candidate in candidates):
            return f"custom policy: {pattern}"
    return None


def custom_secret_pattern_matches(content: str) -> list[str]:
    import concurrent.futures

    matches: list[str] = []
    patterns = load_guard_policy()["secret_patterns"]
    for name, pattern in patterns.items():
        try:
            compiled = re.compile(pattern)
        except re.error:
            continue
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(compiled.search, content)
            try:
                if future.result(timeout=2):
                    matches.append(f"custom:{name}")
            except concurrent.futures.TimeoutError:
                continue
    return matches


# ---------------------------------------------------------------------------
# Rule Model and Validation (Paket 2A)
# ---------------------------------------------------------------------------


class RuleAction(str, Enum):
    """Allowed actions for a user-defined guard rule."""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


class ConditionType(str, Enum):
    """Supported condition types for rule matching."""

    TOOL = "tool"
    FIELD_EQUALS = "field_equals"
    FIELD_CONTAINS = "field_contains"
    REGEX = "regex"
    GLOB = "glob"
    EXTENSION = "extension"
    FILE_EXISTS = "file_exists"
    FILE_SIZE = "file_size"
    SENSITIVE_PATH = "sensitive_path"
    CONTENT_CONTAINS = "content_contains"


@dataclass
class RuleCondition:
    """A single condition within a guard rule.

    Each condition evaluates to True or False during rule matching.
    All conditions in a rule must evaluate to True for the rule to match
    (AND semantics).
    """

    type: ConditionType
    field: str = ""
    value: Any = None
    metadata: dict[str, Any] = dc_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        result: dict[str, Any] = {
            "type": self.type.value,
        }
        if self.field:
            result["field"] = self.field
        if self.value is not None:
            result["value"] = self.value
        if self.metadata:
            result["metadata"] = dict(self.metadata)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuleCondition":
        """Deserialize from a dictionary.

        Returns a RuleCondition even if data is incomplete; validation
        should be run separately via validate_rule_condition().
        """
        if not isinstance(data, dict):
            return cls(type=ConditionType.TOOL)
        raw_data = dict(data)
        if "pattern" in raw_data and "value" not in raw_data:
            raw_data["value"] = raw_data["pattern"]
        if "patterns" in raw_data and "value" not in raw_data:
            patterns = raw_data.get("patterns")
            if isinstance(patterns, list) and patterns:
                raw_data["value"] = patterns[0]
        if "values" in raw_data and "value" not in raw_data:
            values = raw_data.get("values")
            if isinstance(values, list) and values:
                raw_data["value"] = values[0]
        cond_type_raw = raw_data.get("type", "tool")
        try:
            cond_type = ConditionType(cond_type_raw)
        except ValueError:
            cond_type = ConditionType.TOOL
        return cls(
            type=cond_type,
            field=str(raw_data.get("field", "")),
            value=raw_data.get("value"),
            metadata=dict(raw_data.get("metadata", {})),
        )


@dataclass
class GuardRule:
    """A user-defined guard rule with conditions and an action."""

    name: str
    description: str = ""
    action: RuleAction = RuleAction.DENY
    priority: int = 100
    enabled: bool = True
    conditions: list[RuleCondition] = dc_field(default_factory=list)
    metadata: dict[str, Any] = dc_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "action": self.action.value,
            "priority": self.priority,
            "enabled": self.enabled,
            "conditions": [c.to_dict() for c in self.conditions],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GuardRule":
        """Deserialize from a dictionary.

        Returns a GuardRule even if data is incomplete; validation
        should be run separately via validate_rule().
        """
        if not isinstance(data, dict):
            return cls(name="")
        action_raw = data.get("action", "deny")
        try:
            action = RuleAction(action_raw)
        except ValueError:
            action = RuleAction.DENY
        conditions_raw = data.get("conditions", [])
        if not isinstance(conditions_raw, list):
            conditions_raw = []
        conditions = [RuleCondition.from_dict(c) for c in conditions_raw if isinstance(c, dict)]
        scope = data.get("scope", data.get("tool"))
        if isinstance(scope, str) and not any(c.type == ConditionType.TOOL for c in conditions):
            conditions.insert(0, RuleCondition(type=ConditionType.TOOL, field="tool", value=scope))
        metadata = dict(data.get("metadata", {}))
        if "risk_level" in data:
            metadata["risk_level"] = data["risk_level"]
        return cls(
            name=str(data.get("name", "")),
            description=str(data.get("description", "")),
            action=action,
            priority=int(data.get("priority", 100)),
            enabled=bool(data.get("enabled", True)),
            conditions=conditions,
            metadata=metadata,
        )


@dataclass
class RuleSet:
    """A collection of guard rules loaded from a policy file."""

    rules: list[GuardRule] = dc_field(default_factory=list)
    metadata: dict[str, Any] = dc_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "rules": [r.to_dict() for r in self.rules],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuleSet":
        """Deserialize from a dictionary."""
        if not isinstance(data, dict):
            return cls()
        rules_raw = data.get("rules", [])
        if not isinstance(rules_raw, list):
            rules_raw = []
        rules = [GuardRule.from_dict(r) for r in rules_raw if isinstance(r, dict)]
        return cls(
            rules=rules,
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class ValidationError:
    """A structured validation error for rule/policy inspection."""

    path: str
    message: str
    code: str = "invalid_value"

    def to_dict(self) -> dict[str, str]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "path": self.path,
            "message": self.message,
            "code": self.code,
        }


_SUPPORTED_CONDITION_TYPES = frozenset(ct.value for ct in ConditionType)


def validate_rule_condition(
    condition: RuleCondition, path: str = "condition"
) -> list[ValidationError]:
    """Validate a single RuleCondition and return any errors found."""
    errors: list[ValidationError] = []

    if condition.type.value not in _SUPPORTED_CONDITION_TYPES:
        errors.append(
            ValidationError(
                path=f"{path}.type",
                message=f"Unsupported condition type: {condition.type.value}",
                code="unsupported_condition_type",
            )
        )

    if condition.type == ConditionType.TOOL:
        if not condition.field and not isinstance(condition.value, str):
            errors.append(
                ValidationError(
                    path=f"{path}.field",
                    message="tool condition requires a non-empty field or value",
                    code="missing_field",
                )
            )

    if condition.type == ConditionType.REGEX:
        if not isinstance(condition.value, str) or not condition.value:
            errors.append(
                ValidationError(
                    path=f"{path}.value",
                    message="regex condition requires a non-empty string value",
                    code="missing_regex_pattern",
                )
            )
        else:
            regex_error = validate_regex_pattern(condition.value)
            if regex_error is not None:
                code = (
                    "unsafe_regex"
                    if "ReDoS" in regex_error or "maximum length" in regex_error
                    else "invalid_regex"
                )
                errors.append(
                    ValidationError(
                        path=f"{path}.value",
                        message=regex_error,
                        code=code,
                    )
                )

    if condition.type in (ConditionType.FIELD_EQUALS, ConditionType.FIELD_CONTAINS):
        if not condition.field:
            errors.append(
                ValidationError(
                    path=f"{path}.field",
                    message=f"{condition.type.value} condition requires a non-empty field",
                    code="missing_field",
                )
            )

    if condition.type == ConditionType.FILE_SIZE:
        if not isinstance(condition.value, (int, float)):
            errors.append(
                ValidationError(
                    path=f"{path}.value",
                    message="file_size condition requires a numeric value (bytes)",
                    code="non_numeric_file_size",
                )
            )
        elif condition.value < 0:
            errors.append(
                ValidationError(
                    path=f"{path}.value",
                    message="file_size condition requires a non-negative value",
                    code="negative_file_size",
                )
            )

    if condition.type in (
        ConditionType.GLOB,
        ConditionType.EXTENSION,
        ConditionType.CONTENT_CONTAINS,
    ):
        if not condition.value:
            errors.append(
                ValidationError(
                    path=f"{path}.value",
                    message=f"{condition.type.value} condition requires a non-empty value",
                    code="missing_value",
                )
            )

    return errors


def validate_rule(rule: GuardRule, index: int = -1) -> list[ValidationError]:
    """Validate a single GuardRule and return any errors found."""
    prefix = f"rules[{index}]" if index >= 0 else "rule"
    errors: list[ValidationError] = []

    if not rule.name or not rule.name.strip():
        errors.append(
            ValidationError(
                path=f"{prefix}.name",
                message="Rule name must not be empty",
                code="empty_rule_name",
            )
        )

    if rule.action.value not in ("allow", "deny", "ask"):
        errors.append(
            ValidationError(
                path=f"{prefix}.action",
                message=f"Invalid rule action: {rule.action.value}",
                code="invalid_rule_action",
            )
        )

    if not isinstance(rule.priority, int) or rule.priority < 0:
        errors.append(
            ValidationError(
                path=f"{prefix}.priority",
                message="Rule priority must be a non-negative integer",
                code="invalid_priority",
            )
        )

    if not rule.conditions:
        errors.append(
            ValidationError(
                path=f"{prefix}.conditions",
                message="Rule must have at least one condition",
                code="empty_conditions",
            )
        )
    else:
        for ci, condition in enumerate(rule.conditions):
            cond_path = f"{prefix}.conditions[{ci}]"
            errors.extend(validate_rule_condition(condition, cond_path))

    return errors


def validate_rule_set(rule_set: RuleSet) -> list[ValidationError]:
    """Validate an entire RuleSet and return all errors found."""
    errors: list[ValidationError] = []
    for ri, rule in enumerate(rule_set.rules):
        errors.extend(validate_rule(rule, ri))

    return errors


def validate_rules_dict(data: dict[str, Any]) -> list[ValidationError]:
    """Parse raw policy dict into a RuleSet and validate it.

    Returns a list of ValidationError; an empty list means the rules are valid.
    """
    if not isinstance(data, dict):
        return [
            ValidationError(
                path="", message="Policy data must be a JSON object", code="invalid_format"
            )
        ]
    rules_raw = data.get("rules")
    if rules_raw is None:
        return []  # No rules section is valid, just empty
    if not isinstance(rules_raw, list):
        return [
            ValidationError(
                path="rules",
                message="'rules' must be a list",
                code="invalid_rules_type",
            )
        ]
    raw_errors: list[ValidationError] = []
    for index, raw_rule in enumerate(rules_raw):
        if not isinstance(raw_rule, dict):
            raw_errors.append(
                ValidationError(
                    path=f"rules[{index}]",
                    message="Rule must be an object",
                    code="invalid_rule_type",
                )
            )
            continue
        action = raw_rule.get("action", "deny")
        if action not in ("allow", "deny", "ask"):
            raw_errors.append(
                ValidationError(
                    path=f"rules[{index}].action",
                    message="Rule action must be one of allow, deny, ask",
                    code="invalid_rule_action",
                )
            )
        conditions = raw_rule.get("conditions", [])
        if isinstance(conditions, list):
            for condition_index, raw_condition in enumerate(conditions):
                if not isinstance(raw_condition, dict):
                    raw_errors.append(
                        ValidationError(
                            path=f"rules[{index}].conditions[{condition_index}]",
                            message="Condition must be an object",
                            code="invalid_condition_type",
                        )
                    )
                    continue
                condition_type = raw_condition.get("type", "tool")
                if condition_type not in _SUPPORTED_CONDITION_TYPES:
                    raw_errors.append(
                        ValidationError(
                            path=f"rules[{index}].conditions[{condition_index}].type",
                            message=f"Unsupported condition type: {condition_type}",
                            code="unsupported_condition_type",
                        )
                    )
    rule_set = RuleSet.from_dict(data)
    return [*raw_errors, *validate_rule_set(rule_set)]


# ---------------------------------------------------------------------------
# Policy Loader with Backward Compatibility (Paket 2B)
# ---------------------------------------------------------------------------


_POLICY_CACHE: dict[str, Any] = {}
_POLICY_CACHE_MTIME: float = 0.0
_POLICY_CACHE_LOCK = threading.RLock()


def _compute_policy_cache_key(policy_files: list[tuple[Path, str]]) -> str:
    """Compute a stable cache key from policy file paths and mtimes.

    Using mtime strings (not hash) avoids Python's process-level hash
    randomization which makes hash() non-deterministic across invocations.
    """
    parts = []
    for path, _ in policy_files:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        parts.append(f"{path}:{mtime:.6f}")
    return "|".join(parts)


def _read_file_with_fallback(path: Path) -> str | None:
    """Read file contents or return None on any error."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if len(raw) > _MAX_POLICY_FILE_BYTES:
        return None
    return raw


def _parse_json_safe(raw: str, path: Path) -> dict[str, Any] | None:
    """Parse JSON string into dict; return None on parse error."""
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(result, dict):
        return None
    return result


def _parse_yaml_safe(raw: str) -> dict[str, Any] | None:
    """Parse YAML string into dict if PyYAML is available; return None otherwise."""
    if len(raw) > 1_048_576:  # FIX: 1MB input size limit to prevent memory exhaustion
        raise ValueError("YAML input exceeds maximum size of 1MB")
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return None
    try:
        result = yaml.safe_load(raw)
    except yaml.YAMLError:
        return None
    if not isinstance(result, dict):
        return None
    return result


def _resolve_policy_files() -> list[tuple[Path, str]]:
    """Return ordered list of (path, format) tuples to check for rules.

    Priority:
    1. CLAUDE_BRIDGE_GUARD_POLICY env override (supports .json and .yaml/.yml)
    2. <project>/.claude-bridge-guard.json
    3. <project>/.claude-bridge/rules.yaml (future, checked if present)
    """
    result: list[tuple[Path, str]] = []
    override = os.environ.get("CLAUDE_BRIDGE_GUARD_POLICY", "").strip()
    if override:
        override_path = Path(override).expanduser().resolve()
        suffix = override_path.suffix.lower()
        if suffix in (".yaml", ".yml"):
            result.append((override_path, "yaml"))
        else:
            result.append((override_path, "json"))
        return result

    project = project_dir()
    json_path = (project / _POLICY_FILENAME).resolve()
    result.append((json_path, "json"))

    yaml_path = (project / _RULES_YAML_FILENAME).resolve()
    if yaml_path.exists():
        result.append((yaml_path, "yaml"))

    return result


def _load_policy_files() -> dict[str, Any]:
    """Load and merge policy files into a unified dict.

    Files are loaded in priority order. Rules from higher-priority files
    take precedence (later files in the list append/add to rules).
    """
    merged: dict[str, Any] = {}
    for path, fmt in _resolve_policy_files():
        raw = _read_file_with_fallback(path)
        if raw is None:
            continue
        if fmt == "yaml":
            parsed = _parse_yaml_safe(raw)
            if parsed is None:
                # YAML validation details are reported by the CLI validator.
                continue
        else:
            parsed = _parse_json_safe(raw, path)
            if parsed is None:
                continue

        # Merge: legacy keys are taken from the first file that provides them
        for key in ("blocked_shell_patterns", "sensitive_path_patterns", "secret_patterns"):
            if key not in merged and key in parsed:
                merged[key] = parsed[key]

        # Rules are accumulated across all files
        if "rules" in parsed and isinstance(parsed["rules"], list):
            existing: list[dict[str, Any]] = merged.get("rules", [])
            existing = list(existing)  # make a copy
            for rule in parsed["rules"]:
                if isinstance(rule, dict):
                    existing.append(rule)
            merged["rules"] = existing

        # Metadata from each file
        if "metadata" in parsed and isinstance(parsed["metadata"], dict):
            existing_meta: dict[str, Any] = dict(merged.get("metadata", {}))
            existing_meta.update(parsed["metadata"])
            merged["metadata"] = existing_meta

    return merged


def _invalidate_policy_cache() -> None:
    """Clear the policy cache (useful in tests)."""
    with _POLICY_CACHE_LOCK:
        _POLICY_CACHE.clear()
        global _POLICY_CACHE_MTIME
        _POLICY_CACHE_MTIME = 0.0


def _policy_mtime(path: Path) -> float:
    """Return file mtime or 0 if file does not exist."""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def load_guard_policy() -> dict[str, Any]:
    """Load the guard policy, maintaining backward compatibility.

    Returns a dict with:
        path: str
        exists: bool
        blocked_shell_patterns: list[str]
        sensitive_path_patterns: list[str]
        secret_patterns: dict[str, str]
        rules: list[dict]  (new in Paket 2B)
        rules_validation: list[dict]  (validation errors, if any)
    """
    global _POLICY_CACHE_MTIME

    primary_path = _policy_path()
    policy_files = _resolve_policy_files()
    cache_key = _compute_policy_cache_key(policy_files)

    with _POLICY_CACHE_LOCK:
        # Use cache if none of the policy files have changed
        if _POLICY_CACHE and cache_key == _POLICY_CACHE_MTIME and cache_key != "":
            return dict(_POLICY_CACHE)

        merged = _load_policy_files()

        # Validate rules if present
        rules_validation: list[dict[str, str]] = []
        if merged.get("rules"):
            validation_errors = validate_rules_dict(merged)
            rules_validation = [e.to_dict() for e in validation_errors]

        result: dict[str, Any] = {
            "path": str(primary_path),
            "exists": primary_path.exists(),
            "blocked_shell_patterns": _string_list(merged.get("blocked_shell_patterns")),
            "sensitive_path_patterns": _string_list(merged.get("sensitive_path_patterns")),
            "secret_patterns": _regex_map(merged.get("secret_patterns")),
            "allowed_shell_commands": _string_list(merged.get("allowed_shell_commands")),
            "default_deny": bool(merged.get("default_deny", False)),
            "rules": merged.get("rules", []),
            "rules_validation": rules_validation,
        }

        _POLICY_CACHE.clear()
        _POLICY_CACHE.update(result)
        _POLICY_CACHE_MTIME = cache_key

        return result


def load_rules() -> RuleSet:
    """Load and validate rules from the policy file.

    Returns a RuleSet. Validation errors are available in the
    'rules_validation' key of load_guard_policy().
    """
    policy = load_guard_policy()
    rules_raw = policy.get("rules", [])
    if not rules_raw:
        return RuleSet()
    data = {"rules": rules_raw}
    return RuleSet.from_dict(data)


# ---------------------------------------------------------------------------
# Policy Decision Model (Paket 1A)
# ---------------------------------------------------------------------------


class DecisionAction(str, Enum):
    """The outcome of a policy decision."""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


class DecisionSource(str, Enum):
    """The origin of the decision (who or what made it)."""

    DEFAULT = "default"
    BUILTIN_GUARD = "builtin_guard"
    RULE = "rule"
    APPROVAL = "approval"
    AI = "ai"


class RiskLevel(str, Enum):
    """Severity level of the risk associated with a tool request."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class PolicyDecision:
    """A structured policy decision produced by any guard layer.

    Every tool request that passes through the policy engine produces one
    PolicyDecision, regardless of whether the decision is ALLOW, DENY, or ASK.
    """

    action: DecisionAction
    source: DecisionSource
    risk_level: RiskLevel = RiskLevel.LOW
    reason: str = ""
    risk_reasons: list[str] = dc_field(default_factory=list)
    metadata: dict[str, Any] = dc_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the decision to a JSON-compatible dictionary.

        Returns a dict with keys matching the structured response format
        expected by the MCP client and audit layer.
        """
        return {
            "action": self.action.value,
            "source": self.source.value,
            "risk_level": self.risk_level.value,
            "reason": self.reason,
            "risk_reasons": list(self.risk_reasons),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PolicyDecision:
        """Deserialize a dictionary back into a PolicyDecision."""
        try:
            action = DecisionAction(data.get("action", "deny"))
        except ValueError:
            action = DecisionAction.DENY
        try:
            source = DecisionSource(data.get("source", "builtin_guard"))
        except ValueError:
            source = DecisionSource.BUILTIN_GUARD
        try:
            risk_level = RiskLevel(data.get("risk_level", "medium"))
        except ValueError:
            risk_level = RiskLevel.MEDIUM
        return cls(
            action=action,
            source=source,
            risk_level=risk_level,
            reason=str(data.get("reason", "")),
            risk_reasons=[str(r) for r in data.get("risk_reasons", [])],
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class ToolRequestContext:
    """Metadata about the tool invocation that triggered a policy check.

    Attributes:
        tool_name: The name of the tool being invoked.
        params: Parameters passed to the tool.
        project_dir: The active project directory.
        allowed_roots: List of allowed workspace roots.
        role: Optional role name for role-based policy evaluation.
        user: Optional user identifier for role-based policy evaluation.
    """

    tool_name: str
    params: dict[str, Any] = dc_field(default_factory=dict)
    project_dir: str | None = None
    allowed_roots: list[str] = dc_field(default_factory=list)
    role: str | None = None
    user: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the context to a JSON-compatible dictionary."""
        result: dict[str, Any] = {
            "tool_name": self.tool_name,
            "params": dict(self.params),
            "project_dir": self.project_dir,
            "allowed_roots": list(self.allowed_roots),
        }
        if self.role is not None:
            result["role"] = self.role
        if self.user is not None:
            result["user"] = self.user
        return result


def make_policy_decision(
    action: DecisionAction,
    source: DecisionSource,
    risk_level: RiskLevel,
    reason: str,
    risk_reasons: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> PolicyDecision:
    return PolicyDecision(
        action=action,
        source=source,
        risk_level=risk_level,
        reason=reason,
        risk_reasons=list(risk_reasons or []),
        metadata=dict(metadata or {}),
    )


def default_allow_decision(reason: str = "Read-only operation allowed") -> PolicyDecision:
    return make_policy_decision(
        DecisionAction.ALLOW,
        DecisionSource.DEFAULT,
        RiskLevel.LOW,
        reason,
        ["read-only operation"],
    )


def builtin_deny_decision(
    reason: str,
    *,
    risk_level: RiskLevel = RiskLevel.HIGH,
    risk_reasons: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> PolicyDecision:
    return make_policy_decision(
        DecisionAction.DENY,
        DecisionSource.BUILTIN_GUARD,
        risk_level,
        reason,
        risk_reasons,
        metadata,
    )


def approval_ask_decision(
    reason: str,
    *,
    risk_level: RiskLevel = RiskLevel.MEDIUM,
    risk_reasons: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> PolicyDecision:
    return make_policy_decision(
        DecisionAction.ASK,
        DecisionSource.APPROVAL,
        risk_level,
        reason,
        risk_reasons,
        metadata,
    )


def approval_allow_decision(
    reason: str,
    *,
    risk_level: RiskLevel = RiskLevel.MEDIUM,
    risk_reasons: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> PolicyDecision:
    return make_policy_decision(
        DecisionAction.ALLOW,
        DecisionSource.APPROVAL,
        risk_level,
        reason,
        risk_reasons,
        metadata,
    )


@dataclass
class GuardPolicy:
    """Validated guard policy file used by CLI and runtime rule evaluation."""

    path: Path
    exists: bool
    rules: list[GuardRule] = dc_field(default_factory=list)
    errors: list[str] = dc_field(default_factory=list)
    warnings: list[str] = dc_field(default_factory=list)

    @property
    def rule_count(self) -> int:
        return len(self.rules)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    @property
    def valid(self) -> bool:
        return self.error_count == 0


def _read_policy_file_for_validation(path: Path) -> tuple[dict[str, Any], list[str], bool]:
    if not path.exists():
        return {}, [f"policy file not found: {path}"], False
    raw = _read_file_with_fallback(path)
    if raw is None:
        return {}, [f"could not read policy file: {path}"], True
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        parsed = _parse_yaml_safe(raw)
        if parsed is None:
            if importlib.util.find_spec("yaml") is None:
                return {}, ["YAML policy files require PyYAML to be installed"], True
            return {}, [f"invalid YAML policy: {path}"], True
        return parsed, [], True
    parsed = _parse_json_safe(raw, path)
    if parsed is None:
        return {}, [f"invalid JSON policy: {path}"], True
    return parsed, [], True


def validate_guard_policy_file(path: Path) -> GuardPolicy:
    """Validate a JSON/YAML policy file and return structured counts."""
    raw, load_errors, exists = _read_policy_file_for_validation(path)
    rule_set = RuleSet.from_dict(raw)
    validation_errors = validate_rules_dict(raw)
    return GuardPolicy(
        path=path,
        exists=exists,
        rules=rule_set.rules,
        errors=[*load_errors, *(error.message for error in validation_errors)],
    )


def evaluate_rules(
    context: ToolRequestContext,
    policy: GuardPolicy | None = None,
) -> PolicyDecision | None:
    """Evaluate loaded user rules for a tool request without executing the tool."""
    if policy is not None:
        selected_policy = policy
    else:
        policy_data = (
            load_guard_policy()
        )  # FIX: use cached load_guard_policy() instead of disk read
        rules_raw = policy_data.get("rules", [])
        rules = RuleSet.from_dict({"rules": rules_raw}).rules if rules_raw else []
        validation_errors = policy_data.get("rules_validation", [])
        selected_policy = GuardPolicy(
            path=Path(policy_data["path"]),
            exists=policy_data["exists"],
            rules=rules,
            errors=[e["message"] for e in validation_errors],
        )
    if not selected_policy.exists and policy is None:
        return None
    if selected_policy.errors:
        return make_policy_decision(
            DecisionAction.DENY,
            DecisionSource.RULE,
            RiskLevel.HIGH,
            "Policy file is invalid",
            list(selected_policy.errors),
            {
                "policy_path": str(selected_policy.path),
                "validation_errors": list(selected_policy.errors),
            },
        )
    if not selected_policy.rules:
        return None
    from claude_bridge.rules_engine import match_rules

    return match_rules(context, selected_policy.rules)
