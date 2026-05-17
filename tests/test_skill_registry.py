"""Tests for skill_registry module."""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from pathlib import Path

import pytest

from claude_bridge.skill_registry import (
    LoadedSkill,
    SkillMatch,
    SkillRegistry,
    get_registry,
)
from claude_bridge.skill_schema import SkillMeta


@pytest.fixture
def temp_skills_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temporary skills directory."""
    skills_dir = tmp_path / ".claude-bridge" / "skills"
    skills_dir.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return skills_dir


class TestSkillRegistry:
    def test_register_new_skill(self, temp_skills_dir: Path) -> None:
        registry = SkillRegistry()
        meta = SkillMeta(
            name="new-skill",
            version="1.0",
            trigger_phrases=["new", "test"],
        )
        code = "def run(ctx): return 'hello'"

        success, errors = registry.register("new-skill", meta, code)
        assert success is True
        assert errors == []

        json_file = temp_skills_dir / "new-skill.v1.0.json"
        assert json_file.exists()
        py_file = temp_skills_dir / "new-skill.py"
        assert py_file.exists()

    def test_register_duplicate(self, temp_skills_dir: Path) -> None:
        registry = SkillRegistry()
        meta = SkillMeta(
            name="dup-skill",
            version="1.0",
            trigger_phrases=["dup"],
        )
        code = "def run(ctx): pass"

        registry.register("dup-skill", meta, code)
        success, errors = registry.register("dup-skill", meta, code)
        assert success is True

    def test_register_rejects_name_mismatch(self, temp_skills_dir: Path) -> None:
        registry = SkillRegistry()
        meta = SkillMeta(name="safe", version="1.0", trigger_phrases=["safe"])

        success, errors = registry.register("../escape", meta, "code")

        assert success is False
        assert any("match metadata" in error for error in errors)
        assert not (temp_skills_dir.parent / "escape.py").exists()

    def test_unregister_skill(self, temp_skills_dir: Path) -> None:
        registry = SkillRegistry()
        meta = SkillMeta(
            name="remove-skill",
            version="1.0",
            trigger_phrases=["remove"],
        )
        registry.register("remove-skill", meta, "code")

        success, errors = registry.unregister("remove-skill")
        assert success is True
        assert errors == []

        assert registry.get_meta("remove-skill") is None

    def test_unregister_nonexistent(self, temp_skills_dir: Path) -> None:
        registry = SkillRegistry()
        success, errors = registry.unregister("nonexistent")
        assert success is False
        assert len(errors) > 0

    def test_unregister_rejects_unsafe_name(self, temp_skills_dir: Path) -> None:
        registry = SkillRegistry()
        success, errors = registry.unregister("../escape")
        assert success is False
        assert any("Invalid skill name" in error for error in errors)

    def test_find_matching(self, temp_skills_dir: Path) -> None:
        registry = SkillRegistry()

        registry.register(
            "fix-bug",
            SkillMeta(name="fix-bug", version="1.0", trigger_phrases=["fix", "bug"]),
            "code1",
        )
        registry.register(
            "check-status",
            SkillMeta(name="check-status", version="1.0", trigger_phrases=["status", "check"]),
            "code2",
        )

        matches = registry.find_matching("I need to fix a bug")
        assert "fix-bug" in matches

    def test_find_matching_no_context(self, temp_skills_dir: Path) -> None:
        registry = SkillRegistry()

        registry.register(
            "analyze-code",
            SkillMeta(
                name="analyze-code",
                version="1.0",
                trigger_phrases=["analyze"],
                trigger_context=["python"],
            ),
            "code",
        )

        matches = registry.find_matching("analyze this", context=["python"])
        assert "analyze-code" in matches

    def test_get_loaded(self, temp_skills_dir: Path) -> None:
        registry = SkillRegistry()
        meta = SkillMeta(name="loaded-skill", version="1.0", trigger_phrases=["load"])
        registry.register("loaded-skill", meta, "print('loaded')")

        loaded = registry.get_loaded()
        assert "loaded-skill" in loaded

    def test_record_hit(self, temp_skills_dir: Path) -> None:
        registry = SkillRegistry()
        meta = SkillMeta(name="hit-skill", version="1.0", trigger_phrases=["hit"])
        registry.register("hit-skill", meta, "code")

        registry.record_hit("hit-skill")
        registry.record_hit("hit-skill")

        loaded = registry.get_loaded()
        assert loaded["hit-skill"].hit_count == 2

    def test_rebuild_index(self, temp_skills_dir: Path) -> None:
        meta = SkillMeta(name="rebuild-skill", version="1.0", trigger_phrases=["rebuild"])
        registry = SkillRegistry()
        registry.register("rebuild-skill", meta, "code")

        fresh = SkillRegistry()
        count, errors = fresh.rebuild_index()
        assert count >= 1
        assert errors == []
        assert fresh.get_meta("rebuild-skill") is not None

    def test_load_skill(self, temp_skills_dir: Path) -> None:
        registry = SkillRegistry()
        meta = SkillMeta(name="loadable", version="1.0", trigger_phrases=["load"])
        registry.register("loadable", meta, "code")

        new_registry = SkillRegistry()
        success, errors = new_registry.load_skill("loadable")
        assert success is True
        assert errors == []

    def test_recommend_returns_scores_and_reasons(self, temp_skills_dir: Path) -> None:
        registry = SkillRegistry()
        registry.register(
            "docs",
            SkillMeta(
                name="docs",
                version="1.0",
                trigger_phrases=["release notes"],
                description="Draft release notes and documentation",
                tags=["docs"],
                permissions=["read"],
                risk_level="low",
            ),
            "code",
        )

        matches = registry.recommend("please write release notes", context=["docs"])

        assert len(matches) == 1
        assert isinstance(matches[0], SkillMatch)
        assert matches[0].name == "docs"
        assert matches[0].score > 0
        assert any("trigger phrase" in reason for reason in matches[0].reasons)
        assert matches[0].to_dict()["permissions"] == ["read"]

    def test_recommend_limit_and_tie_sort(self, temp_skills_dir: Path) -> None:
        registry = SkillRegistry()
        for name in ("b-skill", "a-skill"):
            registry.register(
                name,
                SkillMeta(name=name, version="1.0", trigger_phrases=["same"]),
                "code",
            )

        matches = registry.recommend("same", limit=1)

        assert [match.name for match in matches] == ["a-skill"]


class TestLoadedSkill:
    def test_to_dict(self) -> None:
        meta = SkillMeta(name="test", version="1.0", trigger_phrases=["t"])
        loaded = LoadedSkill(
            meta=meta,
            code="print('hi')",
            last_used="2026-01-01T00:00:00Z",
            hit_count=3,
        )
        data = loaded.to_dict()
        assert data["code"] == "print('hi')"
        assert data["hit_count"] == 3

    def test_from_dict(self) -> None:
        data = {
            "meta": {"name": "from-dict", "version": "1.0", "trigger_phrases": ["d"]},
            "code": "x = 1",
            "last_used": None,
            "hit_count": 1,
        }
        loaded = LoadedSkill.from_dict(data)
        assert loaded.meta.name == "from-dict"
        assert loaded.code == "x = 1"


def test_get_registry_singleton() -> None:
    reg1 = get_registry()
    reg2 = get_registry()
    assert reg1 is reg2
