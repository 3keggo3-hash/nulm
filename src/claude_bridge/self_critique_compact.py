"""Deterministic self-critique / code review via AST, regex, and text analysis."""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from claude_bridge.config import project_dir

_EXT = {".py", ".js", ".ts", ".rs", ".go"}
_IGNORE = {"node_modules", ".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", "venv", ".venv", ".tox", "dist", "build", "target", "vendor", "archive"}
_COMPLEXITY_THRESHOLD = 50

_DANGER: dict[str, str] = {
    "eval_call": r"\beval\s*\(",
    "exec_call": r"\bexec\s*\(",
    "subprocess_call": r"\bsubprocess\.call\s*\(",
    "os_system": r"\bos\.system\s*\(",
    "subprocess_shell_true": r"\bsubprocess\.\w+\s*\([^)]*\bshell\s*=\s*True",
    "pickle_load": r"\bpickle\.loads?\s*\(",
    "yaml_load": r"\byaml\.load\s*\(",
}

_SECRET: dict[str, str] = {
    "api_key_assignment": r"(?i)\bapi[_-]?key\s*[:=]\s*['\"][^'\"]{8,}['\"]",
    "secret_assignment": r"(?i)\bsecret\s*[:=]\s*['\"][^'\"]{8,}['\"]",
    "token_assignment": r"(?i)\btoken\s*[:=]\s*['\"][^'\"]{8,}['\"]",
    "password_assignment": r"(?i)\bpassword\s*[:=]\s*['\"][^'\"]{8,}['\"]",
    "aws_access_key": r"AKIA[0-9A-Z]{16}",
    "github_token": r"ghp_[A-Za-z0-9]{20,}",
    "jwt_token": r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
}

_PERF: dict[str, str] = {
    "range_len": r"range\s*\(\s*len\s*\(",
    "dict_keys_iter": r"for\s+\w+\s+in\s+\w+\.keys\s*\(\s*\)\s*:",
}

_SNAKE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_PASCAL_RE = re.compile(r"^[A-Z][a-zA-Z0-9]*$")
_DUNDER_RE = re.compile(r"^__.+__$")
_PRIVATE_RE = re.compile(r"^_[a-z][a-z0-9_]*$")

VALID_CRITERIA = frozenset({"complexity", "style", "security", "performance", "naming", "duplication", "test_coverage"})
DEFAULT_CRITERIA = ["complexity", "style"]

_MAX_DEPTH = 10
_MAX_FILES = 500
_F = "file"
_L = "line"
_SV = "severity"
_CAT = "category"
_DESC = "description"
_OK = "ok"
_MSG = "message"
_DET = "details"
_TOT = "total_issues"
_BY_CAT = "by_category"
_BY_SEV = "by_severity"


def _collect_files(scope: str) -> tuple[list[Path], str | None]:
    if scope == "project":
        root = project_dir()
        files: list[Path] = []
        warning: str | None = None
        for entry in root.rglob("*"):
            if any(part in _IGNORE for part in entry.parts):
                continue
            depth = len(entry.relative_to(root).parts)
            if depth > _MAX_DEPTH:
                continue
            if not entry.is_file() or entry.suffix not in _EXT:
                continue
            if len(files) >= _MAX_FILES:
                warning = f"Reached file limit ({_MAX_FILES}); results may be incomplete"
                break
            files.append(entry)
        return files, warning

    path = Path(scope)
    if not path.is_absolute():
        path = project_dir() / path
    resolved = path.resolve()
    try:
        resolved.relative_to(project_dir().resolve())
    except ValueError:
        return [], None
    if resolved.is_file() and resolved.suffix in _EXT:
        return [resolved], None
    return [], None


def _read_file(path: Path) -> tuple[str, list[str]] | None:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        return content, content.splitlines()
    except (OSError, UnicodeError):
        return None


def _check_complexity_python(path: Path, content: str, lines: list[str]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return issues

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        start = node.lineno
        end = node.end_lineno or len(lines)
        func_lines = end - start + 1
        if func_lines <= _COMPLEXITY_THRESHOLD:
            continue
        kind = "Function" if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else "Class"
        issues.append({_F: str(path), _L: start, _SV: "warning", _CAT: "complexity", _DESC: f"{kind} '{node.name}' is {func_lines} lines (> {_COMPLEXITY_THRESHOLD})"})
    return issues


_FUNC_DEF_RE = re.compile(r"^\s*(?:async\s+)?(?:function|def|func|fn)\s+(\w+)")
_CURLY_OPEN_RE = re.compile(r"\{")
_CURLY_CLOSE_RE = re.compile(r"\}")


def _check_complexity_generic(path: Path, lines: list[str]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        m = _FUNC_DEF_RE.match(lines[i])
        if not m:
            i += 1
            continue
        name = m.group(1)
        start = i + 1
        bracket_balance = 0
        found_open = False
        end = len(lines) - 1
        for j in range(i, len(lines)):
            opens = len(_CURLY_OPEN_RE.findall(lines[j]))
            closes = len(_CURLY_CLOSE_RE.findall(lines[j]))
            bracket_balance += opens - closes
            if opens:
                found_open = True
            if found_open and bracket_balance <= 0:
                end = j
                break
        func_lines = end - i + 1
        if func_lines > _COMPLEXITY_THRESHOLD:
            issues.append({_F: str(path), _L: start, _SV: "warning", _CAT: "complexity", _DESC: f"Function '{name}' is {func_lines} lines (> {_COMPLEXITY_THRESHOLD})"})
        i = end + 1
    return issues


def _check_complexity(path: Path, content: str, lines: list[str]) -> list[dict[str, Any]]:
    if path.suffix == ".py":
        return _check_complexity_python(path, content, lines)
    return _check_complexity_generic(path, lines)


def _check_style(path: Path, _content: str, lines: list[str]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    has_tabs = False

    for i, line in enumerate(lines, start=1):
        if len(line) > 100:
            issues.append({_F: str(path), _L: i, _SV: "info", _CAT: "style", _DESC: f"Line exceeds 100 characters ({len(line)} chars)"})
        if line != line.rstrip():
            issues.append({_F: str(path), _L: i, _SV: "info", _CAT: "style", _DESC: "Trailing whitespace"})
        if "\t" in line:
            has_tabs = True

    if has_tabs:
        issues.append({_F: str(path), _L: 1, _SV: "warning", _CAT: "style", _DESC: "File contains tab characters (use spaces)"})

    return issues


def _check_security(path: Path, content: str, _lines: list[str]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    for pattern_name, pattern in _DANGER.items():
        for match in re.finditer(pattern, content):
            line_no = content[: match.start()].count("\n") + 1
            issues.append({_F: str(path), _L: line_no, _SV: "warning", _CAT: "security", _DESC: f"Potentially dangerous call: {pattern_name}"})

    for pattern_name, pattern in _SECRET.items():
        if re.search(pattern, content):
            issues.append({_F: str(path), _L: 1, _SV: "error", _CAT: "security", _DESC: f"Potential hardcoded secret: {pattern_name}"})

    return issues


def _check_naming_python(path: Path, content: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return issues

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name
            if _DUNDER_RE.match(name) or _PRIVATE_RE.match(name):
                continue
            if not _SNAKE_RE.match(name):
                issues.append({_F: str(path), _L: node.lineno, _SV: "info", _CAT: "naming", _DESC: f"Function '{name}' is not snake_case"})
        elif isinstance(node, ast.ClassDef):
            if not _PASCAL_RE.match(node.name):
                issues.append({_F: str(path), _L: node.lineno, _SV: "info", _CAT: "naming", _DESC: f"Class '{node.name}' is not PascalCase"})

    return issues


_JS_FUNC_UPPER_RE = re.compile(r"\b(?:function|async\s+function)\s+([A-Z][a-zA-Z0-9]*)")
_GO_METHOD_RE = re.compile(r"\)\s+([a-z][a-zA-Z0-9]*)\s*\(.*\)\s*\{")
_RS_FN_UPPER_RE = re.compile(r"\bfn\s+([A-Z][a-zA-Z0-9]*)")


def _check_naming_generic(path: Path, content: str, _lines: list[str]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    ext = path.suffix

    if ext in {".js", ".ts"}:
        for match in _JS_FUNC_UPPER_RE.finditer(content):
            line_no = content[: match.start()].count("\n") + 1
            issues.append({_F: str(path), _L: line_no, _SV: "info", _CAT: "naming", _DESC: f"Function '{match.group(1)}' starts with uppercase (use camelCase)"})
    elif ext == ".rs":
        for match in _RS_FN_UPPER_RE.finditer(content):
            line_no = content[: match.start()].count("\n") + 1
            issues.append({_F: str(path), _L: line_no, _SV: "info", _CAT: "naming", _DESC: f"Function '{match.group(1)}' starts with uppercase (use snake_case)"})

    return issues


def _check_naming(path: Path, content: str, lines: list[str]) -> list[dict[str, Any]]:
    if path.suffix == ".py":
        return _check_naming_python(path, content)
    return _check_naming_generic(path, content, lines)


_LINE_MIN_LENGTH = 12


def _check_duplication(file_data: list[tuple[Path, list[str]]]) -> list[dict[str, Any]]:
    line_to_locs: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for path, lines in file_data:
        for i, raw in enumerate(lines, start=1):
            stripped = raw.strip()
            if len(stripped) < _LINE_MIN_LENGTH:
                continue
            if stripped.startswith(("#", "//", "/*", "*")):
                continue
            if stripped in ("pass", "return", "break", "continue", "None", "true", "false"):
                continue
            line_to_locs[stripped][str(path)].append(i)

    issues: list[dict[str, Any]] = []
    for stripped, file_map in line_to_locs.items():
        if len(file_map) <= 1:
            continue
        preview = stripped if len(stripped) <= 60 else stripped[:57] + "..."
        locations = sorted(f"{fname}:{sorted(lns)[0]}" for fname, lns in file_map.items())
        issues.append({_F: list(file_map.keys())[0], _L: next(iter(file_map.values()))[0], _SV: "info", _CAT: "duplication", _DESC: f"Line in {len(file_map)} files: '{preview}' ({', '.join(locations[:3])})"})

    return issues


def _check_performance(path: Path, content: str) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for pattern_name, pattern in _PERF.items():
        for match in re.finditer(pattern, content):
            line_no = content[: match.start()].count("\n") + 1
            issues.append({_F: str(path), _L: line_no, _SV: "info", _CAT: "performance", _DESC: f"Potential performance issue: {pattern_name}"})
    return issues


def _check_test_coverage(files: list[Path]) -> list[dict[str, Any]]:
    root = project_dir()
    test_dir = root / "tests"
    issues: list[dict[str, Any]] = []

    if not test_dir.is_dir():
        issues.append({_F: str(root), _L: 1, _SV: "warning", _CAT: "test_coverage", _DESC: "No tests/ directory found"})
        return issues

    test_names: set[str] = set()
    for entry in test_dir.rglob("test_*.py"):
        if entry.is_file():
            test_names.add(entry.name)

    source_modules: dict[str, Path] = {}
    for f in sorted(files):
        if f.suffix == ".py":
            test_name = f"test_{f.stem}.py"
            source_modules[test_name] = f

    found = test_names & set(source_modules.keys())
    missing = set(source_modules.keys()) - test_names

    for test_name in sorted(missing):
        issues.append({_F: str(source_modules[test_name]), _L: 1, _SV: "info", _CAT: "test_coverage", _DESC: f"Missing test file: tests/{test_name}"})

    coverage_pct = round(len(found) / max(len(source_modules), 1) * 100, 1)
    if coverage_pct < 50:
        issues.append({_F: str(root), _L: 1, _SV: "warning", _CAT: "test_coverage", _DESC: f"Low test coverage: {coverage_pct}% of modules have tests"})

    return issues


def self_critique(scope: str, criteria: list[str] | None = None) -> dict[str, Any]:
    selected = list(criteria) if criteria is not None else list(DEFAULT_CRITERIA)

    invalid = [c for c in selected if c not in VALID_CRITERIA]
    if invalid:
        return {_OK: False, _MSG: f"Invalid criteria: {', '.join(sorted(invalid))}", _DET: {"issues": [], "summary": {_TOT: 0, _BY_CAT: {}, _BY_SEV: {}}}}

    files, collection_warning = _collect_files(scope)
    if not files:
        return {_OK: False, _MSG: f"No supported files found for scope: {scope}", _DET: {"issues": [], "summary": {_TOT: 0, _BY_CAT: {}, _BY_SEV: {}}}}

    all_issues: list[dict[str, Any]] = []
    file_data: list[tuple[Path, list[str]]] = []

    for path in files:
        result = _read_file(path)
        if result is None:
            continue
        content, lines = result
        file_data.append((path, lines))

        for criterion in selected:
            if criterion == "complexity":
                all_issues.extend(_check_complexity(path, content, lines))
            elif criterion == "style":
                all_issues.extend(_check_style(path, content, lines))
            elif criterion == "security":
                all_issues.extend(_check_security(path, content, lines))
            elif criterion == "naming":
                all_issues.extend(_check_naming(path, content, lines))
            elif criterion == "performance":
                all_issues.extend(_check_performance(path, content))

    if "duplication" in selected:
        all_issues.extend(_check_duplication(file_data))

    if "test_coverage" in selected:
        py_files = [f for f in files if f.suffix == ".py"]
        if py_files:
            all_issues.extend(_check_test_coverage(py_files))

    by_category: dict[str, int] = defaultdict(int)
    by_severity: dict[str, int] = defaultdict(int)
    for issue in all_issues:
        by_category[issue[_CAT]] += 1
        by_severity[issue[_SV]] += 1

    total = len(all_issues)

    base_message = f"Code review complete: {total} issue(s) found" if total > 0 else "Code review complete: no issues found"
    message = f"{base_message}. Warning: {collection_warning}" if collection_warning else base_message

    return {_OK: total == 0, _MSG: message, _DET: {"issues": all_issues, "summary": {_TOT: total, _BY_CAT: dict(by_category), _BY_SEV: dict(by_severity)}}}


def self_critique_compact(scope: str, criteria: list[str] | None = None) -> dict[str, Any]:
    result = self_critique(scope, criteria)
    details = result.get(_DET, {})
    summary = details.get("summary", {})
    return {
        _OK: result.get(_OK),
        _MSG: result.get(_MSG),
        _TOT: summary.get(_TOT, 0),
        _BY_CAT: summary.get(_BY_CAT, {}),
        _BY_SEV: summary.get(_BY_SEV, {}),
        "top_issues": [{"f": i.get(_F), "l": i.get(_L), "c": i.get(_CAT), "s": i.get(_SV), "d": i.get(_DESC)[:80]} for i in details.get("issues", [])[:10]],
    }