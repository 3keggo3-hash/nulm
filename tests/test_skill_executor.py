"""Tests for skill_executor module."""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations


from claude_bridge.skill_executor import (
    SkillExecutor,
    SkillResult,
    _skill_env,
    get_executor,
)


class TestSkillExecutor:
    def test_check_permissions_allowed(self) -> None:
        executor = SkillExecutor()
        allowed, denied = executor._check_permissions(["read", "analyze"])
        assert allowed is True
        assert denied == []

    def test_check_permissions_denied(self) -> None:
        executor = SkillExecutor()
        allowed, denied = executor._check_permissions(["invalid", "also_bad"])
        assert allowed is False
        assert "invalid" in denied
        assert "also_bad" in denied

    def test_prepare_context_filters_keys(self) -> None:
        executor = SkillExecutor()
        context = {
            "project_dir": "/path",
            "task": "test",
            "password": "secret",
            "api_key": "key123",
            "unwanted": "value",
        }
        result = executor._prepare_context(context)
        assert "project_dir" in result
        assert "task" in result
        assert "password" not in result
        assert "api_key" not in result
        assert "unwanted" not in result

    def test_prepare_context_empty(self) -> None:
        executor = SkillExecutor()
        result = executor._prepare_context({})
        assert result == {}

    def test_build_execution_wrapper_uses_json_context(self) -> None:
        executor = SkillExecutor()
        wrapper = executor._build_execution_wrapper(
            "/tmp/skill.py",
            {"flag": True, "items": ["a", "b"]},
        )
        assert '"flag": true' in wrapper
        assert "'flag': True" not in wrapper

    def test_skill_env_drops_secret_environment(self, monkeypatch) -> None:
        monkeypatch.setenv("PATH", "/bin")
        monkeypatch.setenv("PYTHONPATH", "/tmp/malicious")
        monkeypatch.setenv("SECRET_TOKEN", "abc123")

        env = _skill_env()

        assert env["PATH"] == "/bin"
        assert "PYTHONPATH" not in env
        assert "SECRET_TOKEN" not in env


class TestSkillResult:
    def test_to_dict(self) -> None:
        result = SkillResult(
            status="success",
            output="hello",
            error="",
            duration=1.5,
        )
        data = result.to_dict()
        assert data["status"] == "success"
        assert data["output"] == "hello"
        assert data["duration"] == 1.5

    def test_default_values(self) -> None:
        result = SkillResult(status="error", error="something went wrong")
        assert result.output == ""
        assert result.duration == 0.0


def test_get_executor_singleton() -> None:
    exec1 = get_executor()
    exec2 = get_executor()
    assert exec1 is exec2
