"""Internal helpers for file-oriented tools."""

from __future__ import annotations

import ast
import difflib
import errno
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from claude_bridge.tool_utils import (
    find_secret_patterns,
    is_within_root,
    json_response,
    sensitive_path_reason,
)

_MAX_SEARCH_RESULTS = 200
_MAX_READ_FILE_LINES = 50
_MAX_LIST_DIRECTORY_ENTRIES = 200
_WRITE_FILE_WARNING_LINES = 500
_MAX_MULTI_FILE_READS = 20

_LAST_BRIDGE_CHANGE_LOCK = threading.Lock()
_LAST_BRIDGE_CHANGE: dict[str, dict[str, Any]] = {}
_LAST_BRIDGE_CHANGE_VERSION: dict[str, int] = {}


def _remember_bridge_change(
    *,
    target: Path,
    project_dir: Path,
    previous_exists: bool,
    previous_content: str | None,
    new_content: str,
    operation: str,
    git_result: dict[str, Any],
) -> None:
    key = str(project_dir.resolve())
    with _LAST_BRIDGE_CHANGE_LOCK:
        _LAST_BRIDGE_CHANGE[key] = {
            "target": str(target),
            "project_dir": str(project_dir),
            "path": target.relative_to(project_dir).as_posix(),
            "previous_exists": previous_exists,
            "previous_content": previous_content,
            "new_content": new_content,
            "operation": operation,
            "git_result": git_result,
        }
        _LAST_BRIDGE_CHANGE_VERSION[key] = _LAST_BRIDGE_CHANGE_VERSION.get(key, 0) + 1


def _last_bridge_change(*, project_dir: Path | None = None) -> dict[str, Any] | None:
    with _LAST_BRIDGE_CHANGE_LOCK:
        if project_dir is not None:
            key = str(project_dir.resolve())
            entry = _LAST_BRIDGE_CHANGE.get(key)
            return dict(entry) if entry is not None else None
        if not _LAST_BRIDGE_CHANGE_VERSION:
            return None
        best_key = max(_LAST_BRIDGE_CHANGE_VERSION, key=lambda k: _LAST_BRIDGE_CHANGE_VERSION[k])
        return dict(_LAST_BRIDGE_CHANGE[best_key])


def _last_bridge_change_snapshot(
    *, project_dir: Path | None = None
) -> tuple[int, dict[str, Any]] | None:
    with _LAST_BRIDGE_CHANGE_LOCK:
        if project_dir is not None:
            key = str(project_dir.resolve())
            if key not in _LAST_BRIDGE_CHANGE:
                return None
            return (_LAST_BRIDGE_CHANGE_VERSION[key], dict(_LAST_BRIDGE_CHANGE[key]))
        if not _LAST_BRIDGE_CHANGE_VERSION:
            return None
        best_key = max(_LAST_BRIDGE_CHANGE_VERSION, key=lambda k: _LAST_BRIDGE_CHANGE_VERSION[k])
        return (_LAST_BRIDGE_CHANGE_VERSION[best_key], dict(_LAST_BRIDGE_CHANGE[best_key]))


def clear_last_bridge_change(*, project_dir: Path | None = None) -> None:
    with _LAST_BRIDGE_CHANGE_LOCK:
        if project_dir is not None:
            key = str(project_dir.resolve())
            _LAST_BRIDGE_CHANGE.pop(key, None)
            _LAST_BRIDGE_CHANGE_VERSION.pop(key, None)
        else:
            _LAST_BRIDGE_CHANGE.clear()
            _LAST_BRIDGE_CHANGE_VERSION.clear()


def _estimate_patch_risk(file_path: str, original: str, updated: str) -> dict[str, Any]:
    added = max(0, len(updated.splitlines()) - len(original.splitlines()))
    removed = max(0, len(original.splitlines()) - len(updated.splitlines()))
    lowered_path = file_path.lower()
    touches_tests = any(part in lowered_path for part in ("test", "tests"))
    touches_config = any(
        lowered_path.endswith(suffix)
        for suffix in (".json", ".toml", ".yaml", ".yml", ".ini", ".cfg")
    )
    touches_secrets = any(
        lowered_path.endswith(suffix) for suffix in (".env", ".pem", ".key", ".p12", ".pfx")
    )
    public_api_change_possible = lowered_path.endswith(".py") and (
        "def " in original or "class " in original
    )
    large_deletion = removed >= 25
    reasons: list[str] = []
    if touches_config:
        reasons.append("touches configuration")
    if touches_secrets:
        reasons.append("touches sensitive file types")
    if large_deletion:
        reasons.append("large deletion")
    if added + removed > 50:
        reasons.append("large diff")
    if public_api_change_possible and (added + removed) > 15:
        reasons.append("possible public API impact")

    if touches_secrets or large_deletion or (added + removed) > 100:
        risk_level = "high"
    elif touches_config or (added + removed) > 20:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {
        "risk_level": risk_level,
        "risk_reasons": reasons,
        "lines_added": added,
        "lines_removed": removed,
        "files_touched": 1,
        "touches_tests": touches_tests,
        "touches_config": touches_config,
        "touches_secrets": touches_secrets,
        "large_deletion": large_deletion,
        "public_api_change_possible": public_api_change_possible,
    }


def _paginate_text_preview(content: str, *, line_limit: int) -> dict[str, Any]:
    lines = content.splitlines(keepends=True)
    preview_lines = lines[:line_limit]
    truncated = len(lines) > line_limit
    return {
        "content": "".join(preview_lines),
        "line_count": len(lines),
        "returned_line_count": len(preview_lines),
        "truncated": truncated,
        "line_limit": line_limit,
    }


def _line_ending_for_content(content: str) -> str:
    if "\r\n" in content:
        return "\r\n"
    if "\r" in content:
        return "\r"
    return "\n"


def _normalize_line_endings(value: str, *, line_ending: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return normalized.replace("\n", line_ending)


def _slice_text_lines(content: str, *, offset: int, limit: int) -> dict[str, Any]:
    safe_limit = max(1, limit)
    lines = content.splitlines(keepends=True)
    total_lines = len(lines)
    if offset < 0:
        start = max(0, total_lines + offset)
    else:
        start = min(offset, total_lines)
    page = lines[start : start + safe_limit]
    return {
        "content": "".join(page),
        "line_count": total_lines,
        "returned_line_count": len(page),
        "truncated": (start + safe_limit) < total_lines,
        "line_limit": safe_limit,
        "offset": start,
        "has_more": (start + safe_limit) < total_lines,
    }


def _fuzzy_log_path() -> Path:
    override = os.environ.get("CLAUDE_BRIDGE_AUDIT_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve() / "fuzzy-search.log"
    return (Path.home() / ".claude-bridge" / "fuzzy-search.log").resolve()


def _log_fuzzy_match_attempt(*, file: str, search: str, suggestions: list[str]) -> None:
    path = _fuzzy_log_path()
    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "path": file,
        "search_preview": search[:120],
        "search_length": len(search),
        "suggestions": suggestions[:3],
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json_response(True, "fuzzy", details=entry) + "\n")
    except OSError:
        return


def _write_text_exact(target: Path, content: str, *, exclusive: bool = False) -> None:
    data = content.encode("utf-8")
    if exclusive:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(str(target), flags, 0o644)
        except FileExistsError:
            raise FileExistsError(f"File already exists: {target}")
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise OSError(errno.ELOOP, "Symlink loop in path") from exc
            raise
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
    else:
        # Refuse to write through symlinks to prevent arbitrary file overwrite
        if target.is_symlink():
            raise OSError(errno.ELOOP, "Refusing to write through symlink") from None
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(target.parent))
        try:
            os.write(tmp_fd, data)
            os.fsync(tmp_fd)
        finally:
            os.close(tmp_fd)
        try:
            os.replace(tmp_path, str(target))
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                raise OSError(errno.ELOOP, "Symlink loop in target path") from exc
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


def _read_text_preserve_line_endings(target: Path) -> str:
    return target.read_bytes().decode("utf-8")


def _rg_binary() -> str | None:
    return shutil.which("rg")


def _run_ripgrep_search(
    *,
    query: str,
    target: Path,
    root: Path,
    display_root: Path,
    regex: bool,
    case_sensitive: bool,
    include_glob: str | None,
    offset: int,
    limit: int,
) -> dict[str, Any] | None:
    rg = _rg_binary()
    if rg is None:
        return None

    command = [rg, "--json", "--line-number", "--with-filename", "--color", "never"]
    if not case_sensitive:
        command.append("--ignore-case")
    if not regex:
        command.append("--fixed-strings")
    if include_glob:
        command.extend(["-g", include_glob])
    command.extend(["--", query, str(target)])

    try:
        completed = subprocess.run(
            command,
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=root,
            check=False,
        )
    except OSError:
        return None

    if completed.returncode not in {0, 1}:
        return None

    results: list[dict[str, Any]] = []
    unique_files: set[str] = set()
    truncated = False
    match_count = 0
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "match":
            continue
        data = event.get("data", {})
        path_text = str(data.get("path", {}).get("text", ""))
        absolute_path = Path(path_text)
        if not absolute_path.is_absolute():
            absolute_path = (root / absolute_path).resolve()
        else:
            absolute_path = absolute_path.resolve()
        if not is_within_root(absolute_path, root):
            continue
        if sensitive_path_reason(absolute_path) is not None:
            continue
        line_number = int(data.get("line_number", 0) or 0)
        line_text = str(data.get("lines", {}).get("text", ""))
        try:
            relative_path = (
                absolute_path.relative_to(display_root).as_posix()
                if target.is_dir()
                else absolute_path.name
            )
        except ValueError:
            continue
        unique_files.add(relative_path)
        if match_count < offset:
            match_count += 1
            continue
        if len(results) >= limit:
            truncated = True
            break
        results.append(
            {
                "path": relative_path,
                "line_number": line_number,
                "line": line_text.rstrip("\n")[:300],
            }
        )
        match_count += 1

    return {
        "results": results,
        "truncated": truncated,
        "files_searched": max(len(unique_files), 1 if results else 0),
        "search_backend": "ripgrep",
        "offset": offset,
        "next_offset": offset + len(results) if truncated else -1,
    }


def _build_preview_patch_result(
    target: Path,
    original: str,
    file: str,
    search: str,
    replace: str,
) -> dict[str, Any]:
    line_ending = _line_ending_for_content(original)
    original_norm = original.replace("\r\n", "\n").replace("\r", "\n")
    search_norm = search.replace("\r\n", "\n").replace("\r", "\n")
    replace_norm = replace.replace("\r\n", "\n").replace("\r", "\n")
    matches = original_norm.count(search_norm)
    if matches == 0:
        suggestions = difflib.get_close_matches(
            search_norm.strip(),
            [line.strip() for line in original_norm.splitlines() if line.strip()],
            n=3,
            cutoff=0.7,
        )
        if suggestions:
            _log_fuzzy_match_attempt(file=file, search=search_norm, suggestions=suggestions)
            return {
                "ok": False,
                "message": "SEARCH text not found exactly, but similar lines were found",
                "code": "search_fuzzy_match_available",
                "details": {"path": file, "suggestions": suggestions},
            }
        return {
            "ok": False,
            "message": "SEARCH text not found in file",
            "code": "search_not_found",
            "details": {"path": file},
        }
    if matches > 1:
        return {
            "ok": False,
            "message": f"SEARCH text is ambiguous (found {matches} times)",
            "code": "search_ambiguous",
            "details": {"path": file, "matches": matches},
        }

    new_content_norm = original_norm.replace(search_norm, replace_norm, 1)
    new_content_with_original_endings = _normalize_line_endings(
        new_content_norm, line_ending=line_ending
    )
    if target.suffix == ".py":
        try:
            ast.parse(new_content_norm)
        except SyntaxError as exc:
            return {
                "ok": False,
                "message": f"Python syntax error after patch: {exc}",
                "code": "python_syntax_error",
                "details": {"path": file, "error": str(exc)},
            }

    secret_patterns = find_secret_patterns(new_content_with_original_endings)
    if secret_patterns:
        return {
            "ok": False,
            "message": "Patch introduces content that looks sensitive",
            "code": "secret_pattern_detected",
            "details": {"path": file, "patterns": secret_patterns},
        }

    diff = "\n".join(
        difflib.unified_diff(
            original_norm.splitlines(),
            new_content_norm.splitlines(),
            fromfile=file,
            tofile=file,
            lineterm="",
        )
    )
    risk = _estimate_patch_risk(file, original_norm, new_content_norm)
    return {
        "ok": True,
        "message": f"Previewed patch for {file}",
        "details": {
            "path": file,
            "resolved_path": str(target),
            "matches": matches,
            "diff": diff,
            "risk": risk,
            "line_ending": repr(line_ending),
        },
    }
