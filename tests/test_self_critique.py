"""Tests for deterministic self_critique code review."""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

from pathlib import Path

import pytest

from claude_bridge.self_critique import (
    VALID_CRITERIA,
    _check_complexity,
    _check_duplication,
    _check_naming,
    _check_performance,
    _check_security,
    _check_style,
    _check_test_coverage,
    _collect_files,
    self_critique,
)

# ---------------------------------------------------------------------------
# File collection
# ---------------------------------------------------------------------------


def test_collect_files_project_finds_py(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from claude_bridge import server as mcp_server

    mcp_server.set_config(project_dir=tmp_path)
    (tmp_path / "a.py").write_text("x = 1")
    (tmp_path / "b.ts").write_text("const x = 1")
    (tmp_path / "not_source.txt").write_text("hello")

    files, _warn = _collect_files("project")
    names = {f.name for f in files}
    assert names == {"a.py", "b.ts"}


def test_collect_files_single_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from claude_bridge import server as mcp_server

    mcp_server.set_config(project_dir=tmp_path)
    target = tmp_path / "mod.py"
    target.write_text("x = 1")

    files, _warn = _collect_files(str(target))
    assert len(files) == 1
    assert files[0] == target


def test_collect_files_relative(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from claude_bridge import server as mcp_server

    mcp_server.set_config(project_dir=tmp_path)
    (tmp_path / "mod.py").write_text("x = 1")

    files, _warn = _collect_files("mod.py")
    assert len(files) == 1


def test_collect_files_unsupported_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from claude_bridge import server as mcp_server

    mcp_server.set_config(project_dir=tmp_path)
    (tmp_path / "notes.txt").write_text("hello")

    files, _warn = _collect_files("notes.txt")
    assert files == []


def test_collect_files_skips_ignored_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from claude_bridge import server as mcp_server

    mcp_server.set_config(project_dir=tmp_path)
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.py").write_text("x = 1")
    (tmp_path / "src.py").write_text("x = 1")

    files, _warn = _collect_files("project")
    names = {f.name for f in files}
    assert "lib.py" not in names
    assert "src.py" in names


# ---------------------------------------------------------------------------
# Complexity
# ---------------------------------------------------------------------------


def test_complexity_flags_long_function(tmp_path: Path) -> None:
    lines = ["def long_func():"] + ["    x = i" for _ in range(51)]
    content = "\n".join(lines)
    issues = _check_complexity(tmp_path / "a.py", content, lines)
    assert len(issues) == 1
    assert issues[0]["severity"] == "warning"
    assert "long_func" in issues[0]["description"]
    assert "lines" in issues[0]["description"]


def test_complexity_ignores_short_function(tmp_path: Path) -> None:
    lines = ["def short():", "    return 1"]
    content = "\n".join(lines)
    issues = _check_complexity(tmp_path / "a.py", content, lines)
    assert len(issues) == 0


def test_complexity_syntax_error_handled(tmp_path: Path) -> None:
    content = "def broken("
    issues = _check_complexity(tmp_path / "a.py", content, content.splitlines())
    assert len(issues) == 0


def test_complexity_generic_js(tmp_path: Path) -> None:
    lines = ["function bigFunc() {"] + [f"  console.log({i});" for i in range(52)] + ["}"]
    content = "\n".join(lines)
    issues = _check_complexity(tmp_path / "a.js", content, lines)
    assert len(issues) == 1
    assert issues[0]["category"] == "complexity"


# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------


def test_style_long_lines(tmp_path: Path) -> None:
    content = "x" * 101
    lines = [content]
    issues = _check_style(tmp_path / "a.py", content, lines)
    assert any("exceeds 100" in i["description"] for i in issues)


def test_style_trailing_whitespace(tmp_path: Path) -> None:
    content = "x = 1   "
    lines = [content]
    issues = _check_style(tmp_path / "a.py", content, lines)
    assert any("Trailing whitespace" == i["description"] for i in issues)


def test_style_tabs(tmp_path: Path) -> None:
    content = "\tx = 1"
    lines = [content]
    issues = _check_style(tmp_path / "a.py", content, lines)
    assert any("tab" in i["description"].lower() for i in issues)


def test_style_clean(tmp_path: Path) -> None:
    content = "x = 1"
    lines = [content]
    issues = _check_style(tmp_path / "a.py", content, lines)
    assert len(issues) == 0


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------


def test_security_eval(tmp_path: Path) -> None:
    content = "eval('1+1')"
    issues = _check_security(tmp_path / "a.py", content, content.splitlines())
    assert any("eval" in i["description"] for i in issues)


def test_security_exec(tmp_path: Path) -> None:
    content = "exec('x=1')"
    issues = _check_security(tmp_path / "a.py", content, content.splitlines())
    assert any("exec" in i["description"] for i in issues)


def test_security_os_system(tmp_path: Path) -> None:
    content = "os.system('ls')"
    issues = _check_security(tmp_path / "a.py", content, content.splitlines())
    assert any("os_system" in i["description"] for i in issues)


def test_security_secret(tmp_path: Path) -> None:
    content = 'password = "superSecret123"'
    issues = _check_security(tmp_path / "a.py", content, content.splitlines())
    assert any("secret" in i["description"].lower() for i in issues)


def test_security_clean(tmp_path: Path) -> None:
    content = "print('hello')"
    issues = _check_security(tmp_path / "a.py", content, content.splitlines())
    assert len(issues) == 0


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------


def test_naming_python_bad_function(tmp_path: Path) -> None:
    content = "def MyFunc(): pass"
    issues = _check_naming(tmp_path / "a.py", content, content.splitlines())
    assert any("MyFunc" in i["description"] for i in issues)


def test_naming_python_good_function(tmp_path: Path) -> None:
    content = "def my_func(): pass"
    issues = _check_naming(tmp_path / "a.py", content, content.splitlines())
    assert len(issues) == 0


def test_naming_python_bad_class(tmp_path: Path) -> None:
    content = "class my_class: pass"
    issues = _check_naming(tmp_path / "a.py", content, content.splitlines())
    assert any("my_class" in i["description"] for i in issues)


def test_naming_python_dunder_ignored(tmp_path: Path) -> None:
    content = "def __init__(self): pass"
    issues = _check_naming(tmp_path / "a.py", content, content.splitlines())
    assert len(issues) == 0


def test_naming_python_private_ignored(tmp_path: Path) -> None:
    content = "def _helper(): pass"
    issues = _check_naming(tmp_path / "a.py", content, content.splitlines())
    assert len(issues) == 0


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------


def test_performance_range_len(tmp_path: Path) -> None:
    content = "for i in range(len(x)): pass"
    issues = _check_performance(tmp_path / "a.py", content)
    assert any("range_len" in i["description"] for i in issues)


def test_performance_clean(tmp_path: Path) -> None:
    content = "for item in items: pass"
    issues = _check_performance(tmp_path / "a.py", content)
    assert len(issues) == 0


# ---------------------------------------------------------------------------
# Duplication
# ---------------------------------------------------------------------------


def test_duplication_across_files(tmp_path: Path) -> None:
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    shared = "    duplicated_line_unique_xyz = 42"
    file_data = [
        (a, ["def foo():", shared, "    return 1"]),
        (b, ["def bar():", shared, "    return 2"]),
    ]
    issues = _check_duplication(file_data)
    assert any("2 files" in i["description"] for i in issues)


def test_duplication_short_lines_ignored(tmp_path: Path) -> None:
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    file_data = [
        (a, ["x = 1"]),
        (b, ["x = 1"]),
    ]
    issues = _check_duplication(file_data)
    assert len(issues) == 0


def test_duplication_no_dupes(tmp_path: Path) -> None:
    a = tmp_path / "a.py"
    b = tmp_path / "b.py"
    file_data = [
        (a, ["def helper_long_enough(): return 42"]),
        (b, ["def other_func_here(): return 99"]),
    ]
    issues = _check_duplication(file_data)
    assert len(issues) == 0


# ---------------------------------------------------------------------------
# Test coverage
# ---------------------------------------------------------------------------


def test_test_coverage_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from claude_bridge import server as mcp_server

    mcp_server.set_config(project_dir=tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "mod.py").write_text("x = 1")
    (tmp_path / "other.py").write_text("y = 1")
    (tmp_path / "tests" / "test_other.py").write_text("def test(): pass")

    issues = _check_test_coverage([tmp_path / "mod.py", tmp_path / "other.py"])
    assert any("mod" in i["description"] for i in issues)
    assert not any("other" in i["description"] for i in issues)


def test_test_coverage_no_tests_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from claude_bridge import server as mcp_server

    mcp_server.set_config(project_dir=tmp_path)
    issues = _check_test_coverage([])
    assert any("tests/" in i["description"] for i in issues)


# ---------------------------------------------------------------------------
# Full self_critique integration
# ---------------------------------------------------------------------------


def test_self_critique_invalid_criteria(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from claude_bridge import server as mcp_server

    mcp_server.set_config(project_dir=tmp_path)
    result = self_critique("project", ["bogus"])
    assert result["ok"] is False
    assert "bogus" in result["message"]


def test_self_critique_no_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from claude_bridge import server as mcp_server

    mcp_server.set_config(project_dir=tmp_path)
    result = self_critique("project")
    assert result["ok"] is False
    assert "No supported files" in result["message"]


def test_self_critique_clean_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from claude_bridge import server as mcp_server

    mcp_server.set_config(project_dir=tmp_path)
    (tmp_path / "mod.py").write_text("def hello():\n    return 1\n")
    result = self_critique("mod.py", ["complexity", "style", "security", "naming"])
    assert result["ok"] is True
    assert "no issues" in result["message"].lower()


def test_self_critique_flags_issues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from claude_bridge import server as mcp_server

    mcp_server.set_config(project_dir=tmp_path)
    content = "eval('x')\n" + ("x = 'long' + 'line'" * 10) + "\n"
    (tmp_path / "mod.py").write_text(content)
    result = self_critique("mod.py", ["security", "style"])
    assert result["ok"] is False
    assert result["details"]["summary"]["total_issues"] > 0


def test_self_critique_all_criteria(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from claude_bridge import server as mcp_server

    mcp_server.set_config(project_dir=tmp_path)
    (tmp_path / "mod.py").write_text("def hello():\n    return 1\n")
    result = self_critique("mod.py", list(VALID_CRITERIA))
    # Should still return a valid structure even with all criteria
    assert "ok" in result
    assert "details" in result
    assert "summary" in result["details"]


def test_self_critique_default_criteria(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from claude_bridge import server as mcp_server

    mcp_server.set_config(project_dir=tmp_path)
    (tmp_path / "mod.py").write_text("def hello():\n    return 1\n")
    result = self_critique("mod.py")
    assert result["ok"] is True
    assert "no issues" in result["message"].lower()


def test_self_critique_summary_structure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from claude_bridge import server as mcp_server

    mcp_server.set_config(project_dir=tmp_path)
    (tmp_path / "mod.py").write_text("eval('bad')\n")
    result = self_critique("mod.py", ["security"])
    summary = result["details"]["summary"]
    assert "total_issues" in summary
    assert "by_category" in summary
    assert "by_severity" in summary
    assert summary["total_issues"] > 0


def test_self_critique_issue_structure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from claude_bridge import server as mcp_server

    mcp_server.set_config(project_dir=tmp_path)
    (tmp_path / "mod.py").write_text("eval('bad')\n")
    result = self_critique("mod.py", ["security"])
    issue = result["details"]["issues"][0]
    for key in ("file", "line", "severity", "category", "description"):
        assert key in issue
