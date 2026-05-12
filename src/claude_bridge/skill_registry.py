"""Skill registry for indexing and managing skills."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claude_bridge.skill_schema import SkillMeta, load_skill_json, validate_skill_json


SKILLS_DIR = Path(".claude-bridge/skills")
INDEX_FILE = SKILLS_DIR / "index.json"


@dataclass
class LoadedSkill:
    """A skill loaded from disk."""

    meta: SkillMeta
    code: str
    last_used: str | None = None
    hit_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "meta": self.meta.to_dict(),
            "code": self.code,
            "last_used": self.last_used,
            "hit_count": self.hit_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LoadedSkill:
        return cls(
            meta=SkillMeta.from_dict(data["meta"]),
            code=str(data.get("code", "")),
            last_used=data.get("last_used"),
            hit_count=int(data.get("hit_count", 0)),
        )


class SkillRegistry:
    """Registry for managing skills.

    Maintains an index of all available skills and their metadata.
    Storage: .claude-bridge/skills/index.json
    """

    def __init__(self) -> None:
        self._skills_index: dict[str, SkillMeta] = {}
        self._loaded_skills: dict[str, LoadedSkill] = {}
        self._load_index()

    def _load_index(self) -> None:
        """Load the skills index from disk."""
        if not INDEX_FILE.exists():
            return

        try:
            data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
            for name, meta_dict in data.items():
                self._skills_index[name] = SkillMeta.from_dict(meta_dict)
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    def _save_index(self) -> None:
        """Persist the skills index to disk."""
        SKILLS_DIR.mkdir(parents=True, exist_ok=True)
        index_data = {name: meta.to_dict() for name, meta in self._skills_index.items()}
        INDEX_FILE.write_text(
            json.dumps(index_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def register(self, name: str, meta: SkillMeta, code: str) -> tuple[bool, list[str]]:
        """Register a new skill.

        Returns (success, error_messages).
        """
        is_valid, errors = validate_skill_json(meta.to_dict())
        if not is_valid:
            return False, errors

        json_path = SKILLS_DIR / f"{name}.v{meta.version}.json"
        py_path = SKILLS_DIR / f"{name}.py"

        try:
            SKILLS_DIR.mkdir(parents=True, exist_ok=True)

            json_data = meta.to_dict()
            json_data["code"] = code
            json_path.write_text(
                json.dumps(json_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            py_path.write_text(code, encoding="utf-8")

            self._skills_index[name] = meta
            self._loaded_skills[name] = LoadedSkill(
                meta=meta,
                code=code,
                last_used=None,
                hit_count=0,
            )
            self._save_index()
            return True, []
        except OSError as e:
            return False, [f"Failed to write skill files: {e}"]

    def unregister(self, name: str) -> tuple[bool, list[str]]:
        """Unregister a skill by name.

        Returns (success, error_messages).
        """
        if name not in self._skills_index:
            return False, [f"Skill '{name}' not found"]

        try:
            for json_file in SKILLS_DIR.glob(f"{name}.v*.json"):
                json_file.unlink()
            py_file = SKILLS_DIR / f"{name}.py"
            if py_file.exists():
                py_file.unlink()

            del self._skills_index[name]
            self._loaded_skills.pop(name, None)
            self._save_index()
            return True, []
        except OSError as e:
            return False, [f"Failed to remove skill files: {e}"]

    def find_matching(self, query: str, context: list[str] | None = None) -> list[str]:
        """Find skills matching query string and optional context.

        Returns list of skill names ordered by match score.
        """
        query_lower = query.lower()
        context = context or []
        context_lower = [c.lower() for c in context]

        scored: list[tuple[int, str]] = []
        for name, meta in self._skills_index.items():
            score = 0

            for phrase in meta.trigger_phrases:
                if phrase.lower() in query_lower:
                    score += 10

            for ctx in meta.trigger_context:
                if any(ctx.lower() in q for q in context_lower):
                    score += 5

            if score > 0:
                scored.append((score, name))

        scored.sort(reverse=True)
        return [name for _, name in scored]

    def get_loaded(self) -> dict[str, LoadedSkill]:
        """Return all loaded skills with their metadata and code."""
        return dict(self._loaded_skills)

    def get_meta(self, name: str) -> SkillMeta | None:
        """Get metadata for a registered skill."""
        return self._skills_index.get(name)

    def load_skill(self, name: str) -> tuple[bool, list[str]]:
        """Load a skill's code into memory.

        Returns (success, error_messages).
        """
        if name in self._loaded_skills:
            return True, []

        meta = self._skills_index.get(name)
        if meta is None:
            return False, [f"Skill '{name}' not registered"]

        json_files = list(SKILLS_DIR.glob(f"{name}.v*.json"))
        if not json_files:
            return False, [f"Skill '{name}' JSON file not found"]

        latest = max(json_files, key=lambda p: p.stat().st_mtime)
        data, errors = load_skill_json(latest)
        if errors:
            return False, errors

        code = data.get("code", "")
        loaded = LoadedSkill(
            meta=SkillMeta.from_dict(data),
            code=code,
            last_used=None,
            hit_count=0,
        )
        self._loaded_skills[name] = loaded
        return True, []

    def record_hit(self, name: str) -> None:
        """Record that a skill was used."""
        if name in self._loaded_skills:
            skill = self._loaded_skills[name]
            skill.hit_count += 1
            skill.last_used = datetime.now(timezone.utc).isoformat()

    def rebuild_index(self) -> tuple[int, list[str]]:
        """Rebuild the skills index from disk.

        Returns (count, error_messages).
        """
        self._skills_index.clear()
        self._loaded_skills.clear()
        errors: list[str] = []

        if not SKILLS_DIR.exists():
            self._save_index()
            return 0, []

        for json_file in SKILLS_DIR.glob("*.v*.json"):
            data, file_errors = load_skill_json(json_file)
            if file_errors:
                errors.extend(file_errors)
                continue

            meta = SkillMeta.from_dict(data)
            self._skills_index[meta.name] = meta
            self._loaded_skills[meta.name] = LoadedSkill(
                meta=meta,
                code=data.get("code", ""),
                last_used=None,
                hit_count=0,
            )

        self._save_index()
        return len(self._skills_index), errors


_registry: SkillRegistry | None = None


def get_registry() -> SkillRegistry:
    """Return the shared SkillRegistry instance."""
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry