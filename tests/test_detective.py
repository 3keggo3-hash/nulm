"""Tests for Bridge Detective error investigation workflow."""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_bridge._detective_classifiers import classify_error, extract_error_location
from claude_bridge._detective_locator import find_related_files, get_recent_changes
from claude_bridge._detective_learner import (
    add_lesson,
    find_similar_lesson,
    load_lessons,
    save_lessons,
)
from claude_bridge._detective_report import format_detective_report
from claude_bridge.detective import BridgeDetective, DetectiveReport, DetectiveState, ErrorType


class TestClassifiers:
    def test_classify_syntax_error(self) -> None:
        output = "SyntaxError: invalid syntax\n  File 'test.py', line 1"
        assert classify_error(output) == "SYNTAX_ERROR"

    def test_classify_runtime_error(self) -> None:
        output = "Traceback (most recent call last):\n  File 'test.py', line 2\nNameError"
        assert classify_error(output) == "RUNTIME_ERROR"

    def test_classify_module_not_found(self) -> None:
        output = "ModuleNotFoundError: No module named 'yaml'"
        assert classify_error(output) == "RUNTIME_ERROR"

    def test_classify_python_module_runner_missing_module(self) -> None:
        output = "/usr/bin/python3: No module named missing_package"
        assert classify_error(output) == "RUNTIME_ERROR"

    def test_classify_security_error(self) -> None:
        output = "SecurityError: Access denied"
        assert classify_error(output) == "SECURITY_ERROR"

    def test_classify_network_error(self) -> None:
        output = "ConnectionError: Connection refused"
        assert classify_error(output) == "NETWORK_ERROR"

    def test_classify_unknown(self) -> None:
        output = "Something went wrong"
        assert classify_error(output) == "UNKNOWN"

    def test_extract_error_location(self) -> None:
        output = '  File "/path/to/file.py", line 42\n    code'
        loc = extract_error_location(output)
        assert loc["file"] == "/path/to/file.py"
        assert loc["line"] == "42"

    def test_extract_error_location_no_match(self) -> None:
        output = "Some generic error"
        loc = extract_error_location(output)
        assert loc["file"] == ""
        assert loc["line"] == ""


class TestLocator:
    def test_find_related_files_nonexistent(self, tmp_path: Path) -> None:
        result = find_related_files("/nonexistent/file.py", tmp_path)
        assert result == []

    def test_get_recent_changes_no_git(self, tmp_path: Path) -> None:
        result = get_recent_changes("/nonexistent/file.py", tmp_path)
        assert result == []


class TestLearner:
    def test_save_and_load_lessons(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import claude_bridge._detective_learner as learner

        monkeypatch.setattr(learner, "project_dir", lambda: tmp_path)
        test_lessons = [
            {"pattern": "ModuleNotFoundError", "solution": "pip install foo", "hits": 2},
        ]
        save_lessons(test_lessons)
        loaded = load_lessons()
        assert len(loaded) == 1
        assert loaded[0]["pattern"] == "ModuleNotFoundError"

    def test_add_lesson_new(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import claude_bridge._detective_learner as learner

        monkeypatch.setattr(learner, "project_dir", lambda: tmp_path)
        add_lesson("TestError", "do something", "RUNTIME_ERROR", "/test/file.py")
        lessons = load_lessons()
        assert len(lessons) == 1
        assert lessons[0]["pattern"] == "TestError"
        assert lessons[0]["solution"] == "do something"

    def test_add_lesson_increment_hit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import claude_bridge._detective_learner as learner

        monkeypatch.setattr(learner, "project_dir", lambda: tmp_path)
        add_lesson("TestError", "do something", "RUNTIME_ERROR")
        add_lesson("TestError", "do something", "RUNTIME_ERROR")
        lessons = load_lessons()
        assert len(lessons) == 1
        assert lessons[0]["hits"] == 2

    def test_find_similar_lesson(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import claude_bridge._detective_learner as learner

        monkeypatch.setattr(learner, "project_dir", lambda: tmp_path)
        test_lessons = [
            {"pattern": "ModuleNotFoundError", "solution": "pip install foo", "hits": 1}
        ]
        save_lessons(test_lessons)
        result = find_similar_lesson("ModuleNotFoundError: No module named 'bar'")
        assert result is not None
        assert result["pattern"] == "ModuleNotFoundError"

    def test_find_similar_lesson_not_found(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import claude_bridge._detective_learner as learner

        monkeypatch.setattr(learner, "project_dir", lambda: tmp_path)
        save_lessons([])
        result = find_similar_lesson("Unrelated error message")
        assert result is None


class TestReport:
    def test_format_detective_report(self) -> None:
        report_data = {
            "error_message": "ModuleNotFoundError: No module named 'yaml'",
            "file_path": "src/config.py",
            "line_number": "12",
            "error_type": "RUNTIME_ERROR",
            "likelihood": "high",
            "related_files": ["src/utils.py"],
            "recent_changes": [{"hash": "abc123", "message": "added yaml import"}],
            "diagnostics": [{"command": "python --version", "returncode": 0, "stdout": "3.10"}],
            "similar_lesson": {"pattern": "ModuleNotFoundError", "solution": "pip install pyyaml"},
            "suggested_fix": "pip install pyyaml",
        }
        output = format_detective_report(report_data)
        assert "ModuleNotFoundError" in output
        assert "src/config.py" in output
        assert "pip install pyyaml" in output


class TestBridgeDetective:
    @pytest.mark.asyncio
    async def test_investigate_syntax_error(self) -> None:
        error_output = "SyntaxError: invalid syntax\n  File 'test.py', line 1\n    x ="
        detective = BridgeDetective(error_output)
        report = await detective.investigate()
        assert report.state == DetectiveState.DONE
        assert report.error_type == "SYNTAX_ERROR"
        assert report.likelihood == "high"

    @pytest.mark.asyncio
    async def test_investigate_runtime_error(self) -> None:
        error_output = "ModuleNotFoundError: No module named 'yaml'\n  File 'test.py', line 5"
        detective = BridgeDetective(error_output)
        report = await detective.investigate()
        assert report.state == DetectiveState.DONE
        assert report.error_type == "RUNTIME_ERROR"
        assert "pip install" in report.suggested_fix or report.suggested_fix

    @pytest.mark.asyncio
    async def test_investigate_populates_context_sections(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import claude_bridge.detective as detective_module

        test_file = tmp_path / "test.py"
        test_file.write_text("print('broken')\n", encoding="utf-8")

        async def fake_run_diagnostics(
            file_path: str,
            error_type: str,
            project_dir_path: Path,
            *,
            allow_commands: bool = False,
        ) -> dict[str, object]:
            assert allow_commands is True
            return {
                "diagnostics": [
                    {
                        "command": "python -m py_compile",
                        "returncode": 1,
                        "stdout": "",
                        "stderr": error_type,
                    }
                ]
            }

        monkeypatch.setattr(detective_module, "project_dir", lambda: tmp_path)
        monkeypatch.setattr(detective_module, "find_related_files", lambda *_: ["src/related.py"])
        monkeypatch.setattr(
            detective_module,
            "get_recent_changes",
            lambda *_: [{"hash": "abc123", "message": "touch test.py"}],
        )
        monkeypatch.setattr(detective_module, "run_diagnostics", fake_run_diagnostics)
        monkeypatch.setattr(detective_module, "check_dependencies", lambda *_: {"ok": True})
        monkeypatch.setattr(detective_module, "create_checkpoint", lambda *_: {"ok": True})

        error_output = 'SyntaxError: invalid syntax\n  File "test.py", line 1'
        detective = BridgeDetective(
            error_output,
            allow_diagnostics=True,
            allow_side_effects=True,
        )
        report = await detective.investigate()

        assert report.related_files == ["src/related.py"]
        assert report.recent_changes == [{"hash": "abc123", "message": "touch test.py"}]
        assert report.diagnostics[0]["command"] == "python -m py_compile"
        assert report.checkpoint_created is True

    @pytest.mark.asyncio
    async def test_investigate_is_passive_by_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import claude_bridge.detective as detective_module

        (tmp_path / "test.py").write_text("x =\n", encoding="utf-8")
        monkeypatch.setattr(detective_module, "project_dir", lambda: tmp_path)

        def fail_checkpoint(*_args: object, **_kwargs: object) -> dict[str, object]:
            raise AssertionError("checkpoint should not be created by passive detective")

        monkeypatch.setattr(detective_module, "create_checkpoint", fail_checkpoint)

        error_output = 'SyntaxError: invalid syntax\n  File "test.py", line 1'
        detective = BridgeDetective(error_output)
        report = await detective.investigate()

        assert report.checkpoint_created is False
        assert report.diagnostics
        assert report.diagnostics[0]["executed"] is False

    @pytest.mark.asyncio
    async def test_investigate_unknown_error(self) -> None:
        error_output = "Something unexpected happened"
        detective = BridgeDetective(error_output)
        report = await detective.investigate()
        assert report.state == DetectiveState.DONE
        assert report.error_type == "UNKNOWN"

    @pytest.mark.asyncio
    async def test_format_report(self) -> None:
        error_output = "SyntaxError: unexpected EOF"
        detective = BridgeDetective(error_output)
        report = await detective.investigate()
        formatted = detective.format_report(report)
        assert "Bridge Detective Report" in formatted
        assert "SyntaxError" in formatted

    def test_detective_state_enum(self) -> None:
        assert DetectiveState.IDLE.value == "IDLE"
        assert DetectiveState.CLASSIFY.value == "CLASSIFY"
        assert DetectiveState.DONE.value == "DONE"

    def test_error_type_enum(self) -> None:
        assert ErrorType.SYNTAX_ERROR.value == "SYNTAX_ERROR"
        assert ErrorType.UNKNOWN.value == "UNKNOWN"

    def test_detective_report_to_dict(self) -> None:
        report = DetectiveReport(
            state=DetectiveState.DONE,
            error_message="Test error",
            error_type="RUNTIME_ERROR",
            file_path="test.py",
            line_number="10",
        )
        data = report.to_dict()
        assert data["state"] == "DONE"
        assert data["error_message"] == "Test error"
        assert data["error_type"] == "RUNTIME_ERROR"
