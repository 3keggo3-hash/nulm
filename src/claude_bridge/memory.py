"""Three-layer memory system for Claude Bridge.

Stores user profile, project memory, and lessons learned with encrypted storage.
"""

from __future__ import annotations

import json
import os
import stat
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

try:
    from cryptography.fernet import Fernet as _ImportedFernet  # type: ignore[import-not-found]

    _Fernet: Any | None = _ImportedFernet
except ImportError:  # pragma: no cover - exercised only in minimal installs
    _Fernet = None

MEMORY_DIR = Path(".claude-bridge")
MEMORY_FILE = MEMORY_DIR / "memory.json.enc"
KEY_FILE = MEMORY_DIR / ".memory.key"
_MEMORY_LOCK = threading.RLock()

_ENV_KEY_VAR = "CLAUDE_BRIDGE_MEMORY_KEY"


def _get_key() -> bytes:
    if _Fernet is None:
        raise RuntimeError(
            "Memory encryption requires the optional 'cryptography' package. "
            "Install claude-bridge-mcp with the memory extra before using memory."
        )
    env_key = os.environ.get(_ENV_KEY_VAR, "").strip()
    if env_key:
        return env_key.encode("utf-8")

    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)

    if KEY_FILE.exists():
        try:
            key_bytes = KEY_FILE.read_bytes()
            if key_bytes.strip():
                return key_bytes.strip()
        except OSError:
            pass

    new_key = _Fernet.generate_key()
    KEY_FILE.write_bytes(new_key)
    try:
        KEY_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return cast(bytes, new_key)


def _load_fernet() -> Any:
    if _Fernet is None:
        raise RuntimeError(
            "Memory encryption requires the optional 'cryptography' package. "
            "Install claude-bridge-mcp with the memory extra before using memory."
        )
    return _Fernet(_get_key())


@dataclass
class UserMemory:
    name: str = ""
    language: str = "en"
    skill_level: str = "intermediate"
    preferences: dict[str, Any] = field(default_factory=dict)
    trusted_agents: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserMemory:
        return cls(
            name=str(data.get("name", "")),
            language=str(data.get("language", "en")),
            skill_level=str(data.get("skill_level", "intermediate")),
            preferences=dict(data.get("preferences", {})),
            trusted_agents=list(data.get("trusted_agents", [])),
        )


@dataclass
class ProjectMemory:
    path: str = ""
    language: str = ""
    entry_points: list[str] = field(default_factory=list)
    test_command: str = ""
    risk_areas: list[str] = field(default_factory=list)
    custom_rules: list[str] = field(default_factory=list)
    last_updated: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectMemory:
        return cls(
            path=str(data.get("path", "")),
            language=str(data.get("language", "")),
            entry_points=list(data.get("entry_points", [])),
            test_command=str(data.get("test_command", "")),
            risk_areas=list(data.get("risk_areas", [])),
            custom_rules=list(data.get("custom_rules", [])),
            last_updated=str(data.get("last_updated", "")),
        )

    def populate_from_project(self, project_dir: Path) -> None:
        from claude_bridge.project_map import ProjectMapper

        mapper = ProjectMapper()
        info = mapper.generate(project_dir)

        self.path = str(project_dir.resolve())
        self.language = info.language
        self.entry_points = list(info.entry_points)
        self.risk_areas = list(info.risk_areas)
        self.custom_rules = list(info.custom_guards)
        self.test_command = _detect_test_command(project_dir, info.language)
        self.last_updated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _detect_test_command(project_dir: Path, language: str) -> str:
    if language == "Python":
        if (project_dir / "pytest.ini").exists():
            return "pytest"
        if (project_dir / "pyproject.toml").exists():
            return "pytest"
        if (project_dir / "setup.cfg").exists():
            return "pytest"
        return "python -m pytest"
    if language in ("JavaScript", "TypeScript"):
        if (project_dir / "package.json").exists():
            try:
                data = json.loads((project_dir / "package.json").read_text(encoding="utf-8"))
                scripts = data.get("scripts", {})
                if "test" in scripts:
                    return "npm test"
            except (OSError, json.JSONDecodeError):
                pass
        return "npm test"
    return ""


@dataclass
class LessonLearned:
    pattern: str = ""
    solution: str = ""
    project: str = ""
    timestamp: str = ""
    hits: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LessonLearned:
        return cls(
            pattern=str(data.get("pattern", "")),
            solution=str(data.get("solution", "")),
            project=str(data.get("project", "")),
            timestamp=str(data.get("timestamp", "")),
            hits=int(data.get("hits", 0)),
        )

    def increment_hit(self) -> None:
        self.hits += 1


class MemoryStore:
    _storage_path: Path = MEMORY_FILE

    def __init__(self) -> None:
        self._fernet = _load_fernet()

    def _read_raw(self) -> dict[str, Any]:
        if not MEMORY_FILE.exists():
            return {}
        try:
            encrypted = MEMORY_FILE.read_bytes()
            decrypted = self._fernet.decrypt(encrypted)
            parsed: dict[str, Any] = json.loads(decrypted.decode("utf-8"))
            return parsed
        except Exception:
            return {}

    def _write_raw(self, data: dict[str, Any]) -> None:
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        json_bytes = json.dumps(data, indent=2).encode("utf-8")
        encrypted = self._fernet.encrypt(json_bytes)
        MEMORY_FILE.write_bytes(encrypted)
        try:
            MEMORY_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    def load(self) -> dict[str, Any]:
        with _MEMORY_LOCK:
            return self._read_raw()

    def save(self, data: dict[str, Any]) -> None:
        with _MEMORY_LOCK:
            self._write_raw(data)

    def get_user_memory(self) -> UserMemory:
        with _MEMORY_LOCK:
            data = self._read_raw()
            raw = data.get("user_profile", {})
            return UserMemory.from_dict(raw)

    def update_user_memory(self, user_memory: UserMemory) -> None:
        with _MEMORY_LOCK:
            data = self._read_raw()
            data["user_profile"] = user_memory.to_dict()
            self._write_raw(data)

    def get_project_memory(self) -> ProjectMemory:
        with _MEMORY_LOCK:
            data = self._read_raw()
            raw = data.get("project_memory", {})
            return ProjectMemory.from_dict(raw)

    def update_project_memory(self, project_memory: ProjectMemory) -> None:
        with _MEMORY_LOCK:
            data = self._read_raw()
            data["project_memory"] = project_memory.to_dict()
            self._write_raw(data)

    def add_lesson(
        self,
        pattern: str,
        solution: str,
        project: str = "",
    ) -> LessonLearned:
        with _MEMORY_LOCK:
            data = self._read_raw()
            lessons_raw = data.get("lessons_learned", [])
            lessons = [LessonLearned.from_dict(entry) for entry in lessons_raw]

            existing_idx = -1
            pattern_lower = pattern.lower()
            for i, lesson in enumerate(lessons):
                if lesson.pattern.lower() == pattern_lower:
                    existing_idx = i
                    break

            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            if existing_idx >= 0:
                lessons[existing_idx].increment_hit()
                if solution and solution != lessons[existing_idx].solution:
                    lessons[existing_idx].solution = solution
                lessons[existing_idx].timestamp = timestamp
                result = lessons[existing_idx]
            else:
                new_lesson = LessonLearned(
                    pattern=pattern,
                    solution=solution,
                    project=project,
                    timestamp=timestamp,
                    hits=1,
                )
                lessons.append(new_lesson)
                result = new_lesson

            data["lessons_learned"] = [entry.to_dict() for entry in lessons]
            self._write_raw(data)
            return result

    def search_lessons(self, query: str) -> list[LessonLearned]:
        with _MEMORY_LOCK:
            data = self._read_raw()
            lessons_raw = data.get("lessons_learned", [])
            lessons = [LessonLearned.from_dict(entry) for entry in lessons_raw]

            query_lower = query.lower()
            scored: list[tuple[int, LessonLearned]] = []

            for lesson in lessons:
                if query_lower in lesson.pattern.lower():
                    scored.append((lesson.hits, lesson))

            scored.sort(key=lambda x: x[0], reverse=True)
            return [lesson for _, lesson in scored]


_memory_store: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    global _memory_store
    if _memory_store is None:
        _memory_store = MemoryStore()
    return _memory_store
