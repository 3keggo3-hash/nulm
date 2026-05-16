"""Tests for skill_builder module."""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from claude_bridge.skill_builder import (
    _extract_context_tags,
    _extract_trigger_phrases,
    _generate_skill_code,
    _generate_skill_name,
    check_and_propose,
    extract_skill,
)


class TestExtractSkill:
    def test_extract_from_successful_workflow(self) -> None:
        result = {
            "task": "Fix the authentication bug",
            "steps": [
                {"action": "diagnose", "status": "completed"},
                {"action": "apply fix", "status": "completed"},
                {"action": "test", "status": "completed"},
            ],
            "outcome": "success",
            "artifacts": {"files": ["auth.py", "test_auth.py"]},
        }
        skill_json, code = extract_skill(result)
        assert skill_json is not None
        assert code is not None
        assert skill_json["name"] is not None
        assert len(skill_json["trigger_phrases"]) >= 1

    def test_no_extract_from_failed_workflow(self) -> None:
        result = {
            "task": "Fix bug",
            "steps": [],
            "outcome": "failure",
        }
        skill_json, code = extract_skill(result)
        assert skill_json is None
        assert code is None

    def test_no_extract_from_short_workflow(self) -> None:
        result = {
            "task": "Simple task",
            "steps": [{"action": "do it"}],
            "outcome": "success",
        }
        skill_json, code = extract_skill(result)
        assert skill_json is None


class TestGenerateSkillName:
    def test_basic_name(self) -> None:
        name = _generate_skill_name("Fix authentication bug")
        assert name is not None
        assert len(name) >= 3
        assert name.replace("_", "").isalnum()

    def test_invalid_task(self) -> None:
        name = _generate_skill_name("   ")
        assert name is None or name == "skill_"

    def test_long_name_truncated(self) -> None:
        name = _generate_skill_name("a b c d e f g h i j k l m n o p")
        assert name is not None
        assert len(name) <= 48


class TestExtractTriggerPhrases:
    def test_basic_extraction(self) -> None:
        phrases = _extract_trigger_phrases("I need to fix the login bug")
        assert len(phrases) >= 1

    def test_short_task_as_phrase(self) -> None:
        phrases = _extract_trigger_phrases("fix login")
        assert any("fix" in p or "login" in p for p in phrases)


class TestExtractContextTags:
    def test_detects_python(self) -> None:
        result = {
            "task": "test",
            "steps": [],
            "artifacts": {"files": ["main.py", "utils.py"]},
        }
        tags = _extract_context_tags(result)
        assert "python" in tags

    def test_detects_shell(self) -> None:
        result = {
            "task": "test",
            "steps": [],
            "artifacts": {"files": ["deploy.sh"]},
        }
        tags = _extract_context_tags(result)
        assert "shell" in tags

    def test_adds_workflow_tag(self) -> None:
        result = {"task": "test", "steps": [], "artifacts": {}}
        tags = _extract_context_tags(result)
        assert "workflow" in tags


class TestGenerateSkillCode:
    def test_fix_template(self) -> None:
        steps = [{"action": "fix bug"}]
        code = _generate_skill_code("Fix the bug", steps)
        assert "run" in code
        assert "context" in code

    def test_create_template(self) -> None:
        steps = [{"action": "create file"}]
        code = _generate_skill_code("Create new component", steps)
        assert "run" in code

    def test_generic_template(self) -> None:
        steps = [{"action": "do something"}]
        code = _generate_skill_code("Do something", steps)
        assert "run" in code


class TestCheckAndPropose:
    def test_check_valid_workflow(self) -> None:
        result = {
            "task": "Analyze performance",
            "steps": [
                {"action": "step1"},
                {"action": "step2"},
                {"action": "step3"},
            ],
            "outcome": "success",
            "artifacts": {},
        }
        proposed, name = check_and_propose(result, request_approval_fn=None)
        assert proposed is True
        assert name is not None
