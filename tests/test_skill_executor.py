"""Tests for skill_executor module."""


from claude_bridge.skill_executor import (
    SkillExecutor,
    SkillResult,
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