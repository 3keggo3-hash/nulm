"""Skill registry for indexing and managing skills."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claude_bridge.skill_schema import SkillMeta, load_skill_json, validate_skill_json, versions_compatible

SKILLS_DIR = Path(".claude-bridge/skills")
INDEX_FILE = SKILLS_DIR / "index.json"


@dataclass
class LoadedSkill:
    """A skill loaded from disk."""

    meta: SkillMeta
    code: str
    last_used: str | None = None
    hit_count: int = 0
    acceptance_count: int = 0
    rejection_count: int = 0
    last_accepted: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = self.metadata_dict()
        data["code"] = self.code
        data["acceptance_count"] = self.acceptance_count
        data["rejection_count"] = self.rejection_count
        data["last_accepted"] = self.last_accepted
        return data

    def metadata_dict(self) -> dict[str, Any]:
        return {
            "meta": self.meta.to_dict(),
            "last_used": self.last_used,
            "hit_count": self.hit_count,
            "acceptance_count": self.acceptance_count,
            "rejection_count": self.rejection_count,
            "last_accepted": self.last_accepted,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LoadedSkill:
        return cls(
            meta=SkillMeta.from_dict(data["meta"]),
            code=str(data.get("code", "")),
            last_used=data.get("last_used"),
            hit_count=int(data.get("hit_count", 0)),
            acceptance_count=int(data.get("acceptance_count", 0)),
            rejection_count=int(data.get("rejection_count", 0)),
            last_accepted=data.get("last_accepted"),
        )


@dataclass(frozen=True)
class SkillMatch:
    """A scored skill recommendation."""

    name: str
    score: int
    reasons: list[str]
    meta: SkillMeta

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": self.score,
            "reasons": list(self.reasons),
            "meta": self.meta.to_dict(),
            "permissions": list(self.meta.permissions),
            "risk_level": self.meta.risk_level,
        }


class SkillRegistry:
    """Registry for managing skills.

    Maintains an index of all available skills and their metadata.
    Storage: .claude-bridge/skills/index.json
    """

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path.cwd()).resolve()
        self._skills_dir = self.root / SKILLS_DIR
        self._index_file = self.root / INDEX_FILE
        self._skills_index: dict[str, SkillMeta] = {}
        self._loaded_skills: dict[str, LoadedSkill] = {}
        self._load_index()

    def _load_index(self) -> None:
        """Load the skills index from disk."""
        if not self._index_file.exists():
            return

        try:
            data = json.loads(self._index_file.read_text(encoding="utf-8"))
            for name, meta_dict in data.items():
                self._skills_index[name] = SkillMeta.from_dict(meta_dict)
                self._loaded_skills[name] = LoadedSkill(
                    meta=SkillMeta.from_dict(meta_dict),
                    code="",
                    last_used=meta_dict.get("last_used"),
                    hit_count=int(meta_dict.get("hit_count", 0)),
                    acceptance_count=int(meta_dict.get("acceptance_count", 0)),
                    rejection_count=int(meta_dict.get("rejection_count", 0)),
                    last_accepted=meta_dict.get("last_accepted"),
                )
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    def _save_index(self) -> None:
        """Persist the skills index to disk."""
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        index_data: dict[str, Any] = {}
        for name, meta in self._skills_index.items():
            meta_dict = meta.to_dict()
            loaded = self._loaded_skills.get(name)
            if loaded is not None:
                meta_dict["last_used"] = loaded.last_used
                meta_dict["hit_count"] = loaded.hit_count
                meta_dict["acceptance_count"] = loaded.acceptance_count
                meta_dict["rejection_count"] = loaded.rejection_count
                meta_dict["last_accepted"] = loaded.last_accepted
            index_data[name] = meta_dict
        self._index_file.write_text(
            json.dumps(index_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def register(self, name: str, meta: SkillMeta, code: str) -> tuple[bool, list[str]]:
        """Register a new skill.

        Returns (success, error_messages).
        """
        if name != meta.name:
            return False, ["Skill name must match metadata name"]
        is_valid, errors = validate_skill_json(meta.to_dict())
        if not is_valid:
            return False, errors

        json_path = self._skills_dir / f"{name}.v{meta.version}.json"
        py_path = self._skills_dir / f"{name}.py"

        try:
            self._skills_dir.mkdir(parents=True, exist_ok=True)

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
                acceptance_count=0,
                rejection_count=0,
                last_accepted=None,
            )
            self._save_index()
            return True, []
        except OSError as e:
            return False, [f"Failed to write skill files: {e}"]

    def unregister(self, name: str) -> tuple[bool, list[str]]:
        """Unregister a skill by name.

        Returns (success, error_messages).
        """
        if not _valid_skill_name(name):
            return False, ["Invalid skill name"]
        if name not in self._skills_index:
            return False, [f"Skill '{name}' not found"]

        try:
            for json_file in self._skills_dir.glob(f"{name}.v*.json"):
                json_file.unlink()
            py_file = self._skills_dir / f"{name}.py"
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

    def list_skills(self) -> list[LoadedSkill]:
        """List registered skills without executing or importing skill code."""
        skills: list[LoadedSkill] = []
        for name in sorted(self._skills_index):
            loaded = self._loaded_skills.get(name)
            if loaded is not None:
                skills.append(loaded)
                continue
            skills.append(LoadedSkill(meta=self._skills_index[name], code=""))
        return skills

    def list_skill_metadata(self) -> list[dict[str, Any]]:
        """List registered skills as metadata-only dictionaries."""
        return [skill.metadata_dict() for skill in self.list_skills()]

    def inspect_skill(self, name: str) -> LoadedSkill | None:
        """Return a registered skill's metadata and loaded code when available."""
        loaded = self._loaded_skills.get(name)
        if loaded is not None:
            return loaded
        meta = self._skills_index.get(name)
        if meta is None:
            return None
        return LoadedSkill(meta=meta, code="")

    def _telemetry_boost(self, skill: LoadedSkill) -> tuple[int, list[str]]:
        total = skill.acceptance_count + skill.rejection_count
        if total < 3:
            return 0, []
        acceptance_rate = skill.acceptance_count / total
        boost = int(acceptance_rate * 5) + (1 if skill.last_accepted else 0)
        reasons = [f"acceptance_rate={acceptance_rate:.0%}"]
        return min(boost, 8), reasons

    def recommend(
        self,
        query: str,
        context: list[str] | None = None,
        limit: int = 5,
    ) -> list[SkillMatch]:
        """Recommend registered skills for a task, with deterministic explanations."""
        query_lower = query.lower()
        query_words = _meaningful_words(query_lower)
        context_lower = [item.lower() for item in (context or [])]
        normalized_limit = max(1, limit)

        matches: list[SkillMatch] = []
        for name, meta in self._skills_index.items():
            score = 0
            reasons: list[str] = []

            for phrase in meta.trigger_phrases:
                phrase_lower = phrase.lower()
                if phrase_lower and phrase_lower in query_lower:
                    score += 10
                    reasons.append(f"trigger phrase matched: {phrase}")

            for ctx in meta.trigger_context:
                ctx_lower = ctx.lower()
                if ctx_lower and any(ctx_lower in item for item in context_lower):
                    score += 5
                    reasons.append(f"context matched: {ctx}")

            for tag in meta.tags:
                tag_lower = tag.lower()
                if tag_lower and (tag_lower in query_words or tag_lower in context_lower):
                    score += 3
                    reasons.append(f"tag matched: {tag}")

            description_words = _meaningful_words(meta.description.lower())
            overlap = sorted(query_words & description_words)
            if overlap:
                overlap_score = min(len(overlap), 5)
                score += overlap_score
                reasons.append(f"description overlap: {', '.join(overlap[:5])}")

            loaded_skill = self._loaded_skills.get(name)
            if loaded_skill is not None and score > 0:
                boost, boost_reasons = self._telemetry_boost(loaded_skill)
                score += boost
                reasons.extend(boost_reasons)

            if score > 0:
                matches.append(SkillMatch(name=name, score=score, reasons=reasons, meta=meta))

        matches.sort(key=lambda item: (-item.score, item.name))
        return matches[:normalized_limit]

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

        json_files = list(self._skills_dir.glob(f"{name}.v*.json"))
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
            acceptance_count=int(data.get("acceptance_count", 0)),
            rejection_count=int(data.get("rejection_count", 0)),
            last_accepted=data.get("last_accepted"),
        )
        self._loaded_skills[name] = loaded
        return True, []

    def record_hit(self, name: str) -> None:
        """Record that a skill was used."""
        if name in self._loaded_skills:
            skill = self._loaded_skills[name]
            skill.hit_count += 1
            skill.last_used = datetime.now(timezone.utc).isoformat()
            self._save_index()

    def record_outcome(self, name: str, accepted: bool) -> None:
        """Record whether a skill recommendation resulted in acceptance."""
        if name in self._loaded_skills:
            skill = self._loaded_skills[name]
            if accepted:
                skill.acceptance_count += 1
                skill.last_accepted = datetime.now(timezone.utc).isoformat()
            else:
                skill.rejection_count += 1
            self._save_index()

    def rebuild_index(self) -> tuple[int, list[str]]:
        """Rebuild the skills index from disk.

        Returns (count, error_messages).
        """
        self._skills_index.clear()
        self._loaded_skills.clear()
        errors: list[str] = []

        if not self._skills_dir.exists():
            self._save_index()
            return 0, []

        for json_file in self._skills_dir.glob("*.v*.json"):
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
                acceptance_count=int(data.get("acceptance_count", 0)),
                rejection_count=int(data.get("rejection_count", 0)),
                last_accepted=data.get("last_accepted"),
            )

        self._save_index()
        return len(self._skills_index), errors


_registry: SkillRegistry | None = None
_registries: dict[str, SkillRegistry] = {}


_STOP_WORDS = {
    "a",
    "an",
    "and",
    "for",
    "in",
    "of",
    "on",
    "or",
    "the",
    "this",
    "to",
    "with",
}


def _meaningful_words(text: str) -> set[str]:
    words = {part.strip("._-:/") for part in text.split() if len(part.strip("._-:/")) >= 3}
    return {word for word in words if word not in _STOP_WORDS}


def _valid_skill_name(name: str) -> bool:
    return re.fullmatch(r"[a-zA-Z0-9_-]+", name) is not None


def get_registry(root: Path | None = None) -> SkillRegistry:
    """Return the shared SkillRegistry instance."""
    global _registry
    resolved_root = (root or Path.cwd()).resolve()
    key = str(resolved_root)
    registry = _registries.get(key)
    if registry is None:
        registry = SkillRegistry(resolved_root)
        _registries[key] = registry
    if root is None:
        _registry = registry
    return registry
