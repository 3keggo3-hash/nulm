"""Tests for skill_schema module."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


import json
from pathlib import Path


from claude_bridge.skill_schema import (
    SkillMeta,
    SkillConfig,
    create_skill_json,
    get_current_timestamp,
    load_skill_json,
    save_skill_json,
    validate_skill_json,
)


class TestSkillMeta:
    def test_to_dict(self) -> None:
        meta = SkillMeta(
            name="test-skill",
            version="1.0",
            trigger_phrases=["test", "run"],
            trigger_context=["shell"],
            auto_load=True,
            permissions=["read"],
        )
        data = meta.to_dict()
        assert data["name"] == "test-skill"
        assert data["version"] == "1.0"
        assert data["trigger_phrases"] == ["test", "run"]
        assert data["trigger_context"] == ["shell"]
        assert data["auto_load"] is True
        assert data["permissions"] == ["read"]

    def test_from_dict(self) -> None:
        data = {
            "name": "my-skill",
            "version": "2.1",
            "trigger_phrases": ["fix", "bug"],
            "trigger_context": ["python"],
            "auto_load": False,
            "permissions": ["read", "analyze"],
        }
        meta = SkillMeta.from_dict(data)
        assert meta.name == "my-skill"
        assert meta.version == "2.1"
        assert meta.trigger_phrases == ["fix", "bug"]
        assert meta.trigger_context == ["python"]
        assert meta.auto_load is False
        assert meta.permissions == ["read", "analyze"]

    def test_roundtrip(self) -> None:
        meta = SkillMeta(
            name="roundtrip-test",
            version="1.0",
            trigger_phrases=["test"],
            description="Roundtrip skill",
            tags=["tests"],
            source="local",
            homepage="https://example.invalid/skill",
            risk_level="medium",
        )
        restored = SkillMeta.from_dict(meta.to_dict())
        assert restored.name == meta.name
        assert restored.version == meta.version
        assert restored.description == "Roundtrip skill"
        assert restored.tags == ["tests"]
        assert restored.source == "local"
        assert restored.homepage == "https://example.invalid/skill"
        assert restored.risk_level == "medium"


class TestSkillConfig:
    def test_to_dict(self) -> None:
        cfg = SkillConfig(
            code="def run(ctx): pass",
            created_at="2026-01-01T00:00:00Z",
            last_used="2026-01-02T00:00:00Z",
            hit_count=5,
        )
        data = cfg.to_dict()
        assert data["code"] == "def run(ctx): pass"
        assert data["created_at"] == "2026-01-01T00:00:00Z"
        assert data["last_used"] == "2026-01-02T00:00:00Z"
        assert data["hit_count"] == 5

    def test_from_dict(self) -> None:
        data = {
            "code": "print('hello')",
            "created_at": "2026-01-01T00:00:00Z",
            "last_used": None,
            "hit_count": 3,
        }
        cfg = SkillConfig.from_dict(data)
        assert cfg.code == "print('hello')"
        assert cfg.hit_count == 3


class TestValidateSkillJson:
    def test_valid_skill(self) -> None:
        data = {
            "name": "valid-skill",
            "version": "1.0",
            "trigger_phrases": ["test"],
        }
        valid, errors = validate_skill_json(data)
        assert valid is True
        assert errors == []

    def test_invalid_name(self) -> None:
        data = {
            "name": "invalid name!",  # spaces not allowed
            "version": "1.0",
            "trigger_phrases": ["test"],
        }
        valid, errors = validate_skill_json(data)
        assert valid is False
        assert len(errors) > 0

    def test_invalid_version(self) -> None:
        data = {
            "name": "test-skill",
            "version": "v1",  # must be digits only
            "trigger_phrases": ["test"],
        }
        valid, errors = validate_skill_json(data)
        assert valid is False

    def test_missing_trigger_phrases(self) -> None:
        data = {
            "name": "test-skill",
            "version": "1.0",
        }
        valid, errors = validate_skill_json(data)
        assert valid is False

    def test_empty_trigger_phrase_rejected(self) -> None:
        data = {
            "name": "test-skill",
            "version": "1.0",
            "trigger_phrases": [""],
        }
        valid, errors = validate_skill_json(data)
        assert valid is False
        assert any("non-empty phrases" in error for error in errors)

    def test_invalid_risk_level_rejected(self) -> None:
        data = {
            "name": "test-skill",
            "version": "1.0",
            "trigger_phrases": ["test"],
            "risk_level": "critical",
        }
        valid, errors = validate_skill_json(data)
        assert valid is False
        assert any("risk_level" in error for error in errors)

    def test_non_list_tags_rejected(self) -> None:
        data = {
            "name": "test-skill",
            "version": "1.0",
            "trigger_phrases": ["test"],
            "tags": "python",
        }
        valid, errors = validate_skill_json(data)
        assert valid is False
        assert any("tags" in error for error in errors)


class TestLoadSkillJson:
    def test_load_valid_file(self, tmp_path: Path) -> None:
        skill_file = tmp_path / "test.v1.json"
        skill_file.write_text(
            json.dumps(
                {
                    "name": "load-test",
                    "version": "1.0",
                    "trigger_phrases": ["load"],
                }
            )
        )

        data, errors = load_skill_json(skill_file)
        assert errors == []
        assert data["name"] == "load-test"

    def test_load_missing_file(self, tmp_path: Path) -> None:
        data, errors = load_skill_json(tmp_path / "nonexistent.json")
        assert data == {}
        assert len(errors) > 0

    def test_load_invalid_json(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not valid json")

        data, errors = load_skill_json(bad_file)
        assert data == {}
        assert len(errors) > 0


class TestSaveSkillJson:
    def test_save_valid_skill(self, tmp_path: Path) -> None:
        data = create_skill_json(
            name="save-test",
            version="1.0",
            trigger_phrases=["save"],
        )
        path = tmp_path / "save-test.v1.json"
        success, errors = save_skill_json(path, data)
        assert success is True
        assert errors == []
        assert path.exists()

    def test_save_invalid_skill(self, tmp_path: Path) -> None:
        data = {"name": "bad", "version": "1"}  # missing trigger_phrases, bad version
        path = tmp_path / "bad.v1.json"
        success, errors = save_skill_json(path, data)
        assert success is False
        assert len(errors) > 0


class TestCreateSkillJson:
    def test_create_minimal(self) -> None:
        data = create_skill_json(
            name="min-skill",
            version="1.0",
            trigger_phrases=["min"],
        )
        assert data["name"] == "min-skill"
        assert data["auto_load"] is False
        assert data["permissions"] == []
        assert data["description"] == ""
        assert data["tags"] == []
        assert data["risk_level"] == "low"

    def test_create_full(self) -> None:
        data = create_skill_json(
            name="full-skill",
            version="2.0",
            trigger_phrases=["full", "test"],
            trigger_context=["python"],
            auto_load=True,
            permissions=["read", "analyze"],
        )
        assert data["trigger_context"] == ["python"]
        assert data["auto_load"] is True
        assert len(data["permissions"]) == 2


def test_get_current_timestamp() -> None:
    ts = get_current_timestamp()
    assert "T" in ts
    assert "+" in ts or "Z" in ts
