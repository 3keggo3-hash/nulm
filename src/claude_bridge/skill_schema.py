"""Skill JSON schema validation and data models."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class SkillMeta:
    """Metadata for a skill."""

    name: str
    version: str
    trigger_phrases: list[str] = field(default_factory=list)
    trigger_context: list[str] = field(default_factory=list)
    auto_load: bool = False
    permissions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "trigger_phrases": list(self.trigger_phrases),
            "trigger_context": list(self.trigger_context),
            "auto_load": self.auto_load,
            "permissions": list(self.permissions),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillMeta:
        return cls(
            name=str(data.get("name", "")),
            version=str(data.get("version", "1.0")),
            trigger_phrases=list(data.get("trigger_phrases", [])),
            trigger_context=list(data.get("trigger_context", [])),
            auto_load=bool(data.get("auto_load", False)),
            permissions=list(data.get("permissions", [])),
        )


@dataclass
class SkillConfig:
    """Configuration and state for a skill."""

    code: str
    created_at: str = ""
    last_used: str | None = None
    hit_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "created_at": self.created_at,
            "last_used": self.last_used,
            "hit_count": self.hit_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillConfig:
        return cls(
            code=str(data.get("code", "")),
            created_at=str(data.get("created_at", "")),
            last_used=data.get("last_used"),
            hit_count=int(data.get("hit_count", 0)),
        )


SKILL_JSON_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["name", "version", "trigger_phrases"],
    "properties": {
        "name": {
            "type": "string",
            "pattern": "^[a-zA-Z0-9_-]+$",
            "description": "Skill identifier (alphanumeric, underscore, hyphen)",
        },
        "version": {
            "type": "string",
            "pattern": r"^\d+\.\d+$",
            "description": "Semantic version (e.g., 1.0, 2.1)",
        },
        "trigger_phrases": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": "Phrases that trigger this skill",
        },
        "trigger_context": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Context tags for matching",
        },
        "auto_load": {
            "type": "boolean",
            "default": False,
        },
        "permissions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Required permissions (read, analyze, write, execute)",
        },
    },
}


def validate_skill_json(data: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate skill JSON data against schema.

    Returns (is_valid, error_messages).
    """
    errors: list[str] = []
    if not isinstance(data.get("name"), str) or not re.fullmatch(
        r"[a-zA-Z0-9_-]+", str(data.get("name", ""))
    ):
        errors.append("Validation error: name must match ^[a-zA-Z0-9_-]+$")
    if not isinstance(data.get("version"), str) or not re.fullmatch(
        r"\d+\.\d+", str(data.get("version", ""))
    ):
        errors.append("Validation error: version must match ^\\d+\\.\\d+$")
    trigger_phrases = data.get("trigger_phrases")
    if (
        not isinstance(trigger_phrases, list)
        or not trigger_phrases
        or not all(isinstance(item, str) for item in trigger_phrases)
    ):
        errors.append("Validation error: trigger_phrases must be a non-empty string array")
    for key in ("trigger_context", "permissions"):
        value = data.get(key, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            errors.append(f"Validation error: {key} must be a string array")
    if "auto_load" in data and not isinstance(data["auto_load"], bool):
        errors.append("Validation error: auto_load must be a boolean")
    return not errors, errors


def load_skill_json(path: Path) -> tuple[dict[str, Any], list[str]]:
    """Load and validate a skill JSON file.

    Returns (data, error_messages). Empty data if errors occur.
    """
    errors: list[str] = []
    try:
        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
    except (OSError, json.JSONDecodeError) as e:
        errors.append(f"Failed to read/parse JSON: {e}")
        return {}, errors

    if not isinstance(data, dict):
        errors.append("Skill JSON must be an object")
        return {}, errors

    is_valid, validation_errors = validate_skill_json(data)
    if not is_valid:
        return {}, validation_errors

    return data, []


def create_skill_json(
    name: str,
    version: str,
    trigger_phrases: list[str],
    trigger_context: list[str] | None = None,
    auto_load: bool = False,
    permissions: list[str] | None = None,
) -> dict[str, Any]:
    """Create a skill JSON dictionary."""
    return {
        "name": name,
        "version": version,
        "trigger_phrases": trigger_phrases,
        "trigger_context": trigger_context or [],
        "auto_load": auto_load,
        "permissions": permissions or [],
    }


def save_skill_json(path: Path, data: dict[str, Any]) -> tuple[bool, list[str]]:
    """Save skill JSON to file after validation.

    Returns (success, error_messages).
    """
    is_valid, errors = validate_skill_json(data)
    if not is_valid:
        return False, errors

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(data, indent=2, ensure_ascii=False)
        path.write_text(content, encoding="utf-8")
        return True, []
    except OSError as e:
        return False, [f"Failed to write file: {e}"]


def get_current_timestamp() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()
