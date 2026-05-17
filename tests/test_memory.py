"""Tests for memory module."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet

from claude_bridge.memory import (
    LessonLearned,
    MemoryStore,
    ProjectMemory,
    UserMemory,
)


@pytest.fixture
def temp_memory_home(tmp_path):
    memory_dir = tmp_path / ".claude-bridge"
    memory_dir.mkdir(parents=True, exist_ok=True)
    yield tmp_path
    for f in memory_dir.glob("*"):
        try:
            f.unlink()
        except OSError:
            pass


@pytest.fixture
def memory_store(temp_memory_home):
    os.environ["CLAUDE_BRIDGE_MEMORY_KEY"] = Fernet.generate_key().decode()
    from claude_bridge import memory as memory_module

    orig_storage = memory_module.MEMORY_FILE
    orig_key_file = memory_module.KEY_FILE
    orig_mem_dir = memory_module.MEMORY_DIR

    memory_module.MEMORY_FILE = temp_memory_home / ".claude-bridge" / "memory.json.enc"
    memory_module.KEY_FILE = temp_memory_home / ".claude-bridge" / ".memory.key"
    memory_module.MEMORY_DIR = temp_memory_home / ".claude-bridge"

    memory_module._memory_store = None

    store = memory_module.get_memory_store()
    yield store

    memory_module.MEMORY_FILE = orig_storage
    memory_module.KEY_FILE = orig_key_file
    memory_module.MEMORY_DIR = orig_mem_dir
    memory_module._memory_store = None

    if "CLAUDE_BRIDGE_MEMORY_KEY" in os.environ:
        del os.environ["CLAUDE_BRIDGE_MEMORY_KEY"]


class TestUserMemory:
    def test_to_dict(self):
        user = UserMemory(
            name="Test User",
            language="tr",
            skill_level="advanced",
            preferences={"theme": "dark"},
            trusted_agents=["git", "debug"],
        )
        d = user.to_dict()
        assert d["name"] == "Test User"
        assert d["language"] == "tr"
        assert d["skill_level"] == "advanced"
        assert d["preferences"] == {"theme": "dark"}
        assert d["trusted_agents"] == ["git", "debug"]

    def test_from_dict(self):
        data = {
            "name": "Jane",
            "language": "en",
            "skill_level": "beginner",
            "preferences": {"font": "mono"},
            "trusted_agents": ["research"],
        }
        user = UserMemory.from_dict(data)
        assert user.name == "Jane"
        assert user.language == "en"
        assert user.skill_level == "beginner"
        assert user.preferences == {"font": "mono"}
        assert user.trusted_agents == ["research"]

    def test_from_dict_defaults(self):
        user = UserMemory.from_dict({})
        assert user.name == ""
        assert user.language == "en"
        assert user.skill_level == "intermediate"


class TestProjectMemory:
    def test_to_dict(self):
        proj = ProjectMemory(
            path="/tmp/test",
            language="Python",
            entry_points=["src/main.py"],
            test_command="pytest",
            risk_areas=[".env"],
            custom_rules=["no rm -rf"],
        )
        d = proj.to_dict()
        assert d["path"] == "/tmp/test"
        assert d["language"] == "Python"
        assert d["entry_points"] == ["src/main.py"]
        assert d["test_command"] == "pytest"
        assert d["risk_areas"] == [".env"]
        assert d["custom_rules"] == ["no rm -rf"]

    def test_from_dict(self):
        data = {
            "path": "/home/user/project",
            "language": "Go",
            "entry_points": ["cmd/main.go"],
            "test_command": "go test",
            "risk_areas": [],
            "custom_rules": [],
            "last_updated": "2026-05-01",
        }
        proj = ProjectMemory.from_dict(data)
        assert proj.path == "/home/user/project"
        assert proj.language == "Go"
        assert proj.test_command == "go test"

    def test_populate_from_project(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("fastapi\npytest\n", encoding="utf-8")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__main__.py").write_text("# main", encoding="utf-8")

        proj = ProjectMemory()
        proj.populate_from_project(tmp_path)

        assert proj.path == str(tmp_path.resolve())
        assert proj.language == "Python"
        assert len(proj.entry_points) >= 1
        assert "pytest" in proj.test_command or proj.test_command == "pytest"
        assert proj.last_updated != ""


class TestLessonLearned:
    def test_to_dict(self):
        lesson = LessonLearned(
            pattern="ModuleNotFoundError",
            solution="pip install thepackage",
            project="my-project",
            timestamp="2026-05-12T10:00:00Z",
            hits=5,
        )
        d = lesson.to_dict()
        assert d["pattern"] == "ModuleNotFoundError"
        assert d["solution"] == "pip install thepackage"
        assert d["hits"] == 5

    def test_from_dict(self):
        data = {
            "pattern": "SyntaxError",
            "solution": "check parentheses",
            "project": "testproj",
            "timestamp": "2026-05-11",
            "hits": 2,
        }
        lesson = LessonLearned.from_dict(data)
        assert lesson.pattern == "SyntaxError"
        assert lesson.hits == 2

    def test_increment_hit(self):
        lesson = LessonLearned(pattern="test", solution="fix", hits=3)
        lesson.increment_hit()
        assert lesson.hits == 4


class TestMemoryStore:
    def test_get_user_memory_empty(self, memory_store):
        user = memory_store.get_user_memory()
        assert user.name == ""
        assert user.language == "en"

    def test_update_user_memory(self, memory_store):
        user = UserMemory(name="Alice", language="tr", skill_level="expert")
        memory_store.update_user_memory(user)

        retrieved = memory_store.get_user_memory()
        assert retrieved.name == "Alice"
        assert retrieved.language == "tr"
        assert retrieved.skill_level == "expert"

    def test_get_project_memory_empty(self, memory_store):
        proj = memory_store.get_project_memory()
        assert proj.path == ""

    def test_update_project_memory(self, memory_store):
        proj = ProjectMemory(
            path="/workspace/myapp",
            language="Python",
            test_command="pytest",
        )
        memory_store.update_project_memory(proj)

        retrieved = memory_store.get_project_memory()
        assert retrieved.path == "/workspace/myapp"
        assert retrieved.language == "Python"

    def test_add_lesson(self, memory_store):
        lesson = memory_store.add_lesson(
            pattern="ImportError: No module named yaml",
            solution="pip install pyyaml",
            project="test-project",
        )
        assert lesson.pattern == "ImportError: No module named yaml"
        assert lesson.hits == 1
        assert lesson.project == "test-project"

        same = memory_store.add_lesson(
            pattern="ImportError: No module named yaml",
            solution="pip install pyyaml",
        )
        assert same.hits == 2

    def test_search_lessons(self, memory_store):
        memory_store.add_lesson("ModuleNotFoundError: yaml", "pip install pyyaml")
        memory_store.add_lesson("SyntaxError: invalid syntax", "check syntax")
        memory_store.add_lesson("TimeoutError", "increase timeout")

        results = memory_store.search_lessons("ModuleNotFoundError")
        assert len(results) >= 1
        assert "ModuleNotFoundError" in results[0].pattern

        empty = memory_store.search_lessons("nonexistent pattern xyz")
        assert len(empty) == 0

    def test_load_save(self, memory_store):
        user = UserMemory(name="Bob", skill_level="advanced")
        memory_store.update_user_memory(user)

        store2 = MemoryStore()
        retrieved = store2.get_user_memory()
        assert retrieved.name == "Bob"

    def test_thread_safety(self, memory_store):
        import threading

        errors: list[Exception] = []

        def write_user(i: int):
            try:
                user = UserMemory(name=f"User{i}")
                memory_store.update_user_memory(user)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write_user, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"


class TestKeyManagement:
    def test_get_key_from_env(self):
        test_key = Fernet.generate_key().decode()
        os.environ["CLAUDE_BRIDGE_MEMORY_KEY"] = test_key

        try:
            from claude_bridge import memory as memory_module

            orig_key = memory_module._get_key()
            assert orig_key == test_key.encode()
        finally:
            del os.environ["CLAUDE_BRIDGE_MEMORY_KEY"]

    def test_get_key_file_generation(self, temp_memory_home):
        key_file = temp_memory_home / ".claude-bridge" / ".memory.key"

        if key_file.exists():
            key_file.unlink()

        from claude_bridge import memory as memory_module

        orig_file = memory_module.KEY_FILE
        memory_module.KEY_FILE = key_file

        try:
            key = memory_module._get_key()
            assert len(key) == 44
            assert key_file.exists()
        finally:
            memory_module.KEY_FILE = orig_file
            if key_file.exists():
                key_file.unlink()


class TestMemoryCleanup:
    def test_cleanup_removes_old_lessons(self, memory_store):
        from unittest.mock import patch
        from datetime import datetime, timezone

        memory_store.add_lesson("old_pattern", "old_solution", project="test")
        memory_store.add_lesson("new_pattern", "new_solution", project="test")

        old_timestamp = "2020-01-01T00:00:00Z"
        with patch.object(memory_store, "_read_raw") as mock_read:
            mock_read.return_value = {
                "lessons_learned": [
                    {
                        "pattern": "old_pattern",
                        "solution": "old_solution",
                        "project": "test",
                        "timestamp": old_timestamp,
                        "hits": 1,
                    },
                    {
                        "pattern": "new_pattern",
                        "solution": "new_solution",
                        "project": "test",
                        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "hits": 1,
                    },
                ]
            }
            result = memory_store.cleanup_lessons(ttl_days=30)

        assert result["expired_removed"] == 1
        assert result["remaining"] == 1

    def test_cleanup_removes_overflow(self, memory_store):
        for i in range(10):
            memory_store.add_lesson(f"pattern_{i}", f"solution_{i}")

        result = memory_store.cleanup_lessons(max_lessons=5)

        assert result["overflow_removed"] >= 5
        assert result["remaining"] == 5

    def test_cleanup_keeps_high_hits(self, memory_store):
        memory_store.add_lesson("low_hit", "solution_a")
        for _ in range(5):
            memory_store.add_lesson("high_hit", "solution_b")

        memory_store.cleanup_lessons(max_lessons=2)

        lessons = memory_store.search_lessons("")
        patterns = [lesson.pattern for lesson in lessons]
        assert "high_hit" in patterns

    def test_clear_all(self, memory_store):
        memory_store.add_lesson("pattern", "solution")
        memory_store.clear_all()

        assert not memory_store.load()

    def test_backup(self, memory_store):
        memory_store.add_lesson("pattern", "solution")

        from claude_bridge import memory as memory_module

        orig_backup = memory_module._BACKUP_FILE
        memory_module._BACKUP_FILE = memory_store._storage_path.parent / "backup_test.bak"
        try:
            backup_path = memory_store.backup()
            assert backup_path.exists()
        finally:
            memory_module._BACKUP_FILE = orig_backup
            if backup_path.exists():
                backup_path.unlink()
