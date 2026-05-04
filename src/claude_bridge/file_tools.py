"""File-oriented tool implementations for Claude Bridge."""

from __future__ import annotations

import ast
import concurrent.futures
import difflib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from claude_bridge.ai_evaluator import evaluate_tool_with_ai
from claude_bridge.config import current_config
from claude_bridge.git_ops import git_commit
from claude_bridge.guard_policy import (
    DecisionAction,
    RiskLevel,
    ToolRequestContext,
    approval_allow_decision,
    approval_ask_decision,
    builtin_deny_decision,
    evaluate_rules,
)
from claude_bridge.indexing import iter_searchable_files
from claude_bridge.smart import DEFAULT_CONTEXT_BUDGET_TOKENS, budget_metadata, estimate_token_count
from claude_bridge.tool_utils import (
    allowed_roots,
    find_secret_patterns,
    infer_project_root,
    is_within_root,
    json_response,
    path_guard_decision,
    path_outside_project_details,
    request_approval,
    require_approval,
    resolve_path,
    safe_read_text,
    sensitive_file_blocked_details,
    sensitive_path_reason,
)

_MAX_SEARCH_RESULTS = 200
_MAX_READ_FILE_LINES = 50
_MAX_LIST_DIRECTORY_ENTRIES = 200
_WRITE_FILE_WARNING_LINES = 500
_MAX_MULTI_FILE_READS = 20
_git_commit = git_commit
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
        try:
            fd = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_WRONLY)
        except FileExistsError:
            raise FileExistsError(f"File already exists: {target}")
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
    else:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(target.parent))
        try:
            os.write(tmp_fd, data)
            os.fsync(tmp_fd)
        finally:
            os.close(tmp_fd)
        try:
            if target.is_symlink():
                try:
                    os.unlink(str(target))
                except OSError:
                    pass
            os.rename(tmp_path, str(target))
        except OSError:
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


async def read_file(
    path: str,
    offset: int = 0,
    limit: int = _MAX_READ_FILE_LINES,
    budget_tokens: int = DEFAULT_CONTEXT_BUDGET_TOKENS,
) -> str:
    try:
        target = resolve_path(path)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(path),
            decision=path_guard_decision(path, "read", outside_workspace=True),
        )

    sensitive_reason = sensitive_path_reason(target)
    if sensitive_reason is not None:
        return json_response(
            False,
            "Sensitive files are blocked from direct reading",
            code="sensitive_file_blocked",
            details=sensitive_file_blocked_details(path),
            decision=path_guard_decision(path, "read", sensitive_reason=sensitive_reason),
        )
    if not target.exists():
        return json_response(
            False,
            f"File not found: {path}",
            code="file_not_found",
            details={"path": path},
        )
    if not target.is_file():
        return json_response(
            False,
            f"Not a file: {path}",
            code="not_a_file",
            details={"path": path},
        )

    try:
        content = safe_read_text(target)
    except (OSError, UnicodeDecodeError) as exc:
        return json_response(
            False,
            f"Failed to read file: {exc}",
            code="file_read_error",
            details={"path": path},
        )

    preview = _slice_text_lines(
        content, offset=offset, limit=min(max(1, limit), _MAX_READ_FILE_LINES)
    )
    budget = budget_metadata(
        estimated_tokens=estimate_token_count(preview["content"]),
        budget_tokens=budget_tokens,
        recommended_next_step=(
            "Use read_file with a narrower offset/limit or switch to find_relevant_files before reading more."
        ),
    )
    return json_response(
        True,
        f"Read file: {path}",
        details={
            "path": path,
            "resolved_path": str(target),
            "content": preview["content"],
            "line_count": preview["line_count"],
            "returned_line_count": preview["returned_line_count"],
            "truncated": preview["truncated"],
            "line_limit": preview["line_limit"],
            "offset": preview["offset"],
            "has_more": preview["has_more"],
            **budget,
        },
    )


async def read_multiple_files(
    paths: list[str],
    offset: int = 0,
    limit: int = _MAX_READ_FILE_LINES,
    budget_tokens: int = DEFAULT_CONTEXT_BUDGET_TOKENS,
) -> str:
    if not paths:
        return json_response(
            False,
            "At least one path is required",
            code="empty_paths",
            details={"paths": paths},
        )
    if len(paths) > _MAX_MULTI_FILE_READS:
        return json_response(
            False,
            f"At most {_MAX_MULTI_FILE_READS} files can be read at once",
            code="too_many_paths",
            details={"max_paths": _MAX_MULTI_FILE_READS, "requested_paths": len(paths)},
        )

    files: list[dict[str, Any]] = []
    estimated_total_tokens = 0
    for path in paths:
        try:
            target = resolve_path(path)
        except PermissionError:
            files.append(
                {
                    "path": path,
                    "ok": False,
                    "code": "path_outside_project",
                    "details": path_outside_project_details(path),
                }
            )
            continue
        if not target.exists():
            files.append({"path": path, "ok": False, "code": "file_not_found"})
            continue
        if not target.is_file():
            files.append({"path": path, "ok": False, "code": "not_a_file"})
            continue
        sensitive_reason = sensitive_path_reason(target)
        if sensitive_reason is not None:
            files.append(
                {
                    "path": path,
                    "ok": False,
                    "code": "sensitive_file_blocked",
                    "details": sensitive_file_blocked_details(path),
                }
            )
            continue
        try:
            content = safe_read_text(target)
        except (OSError, UnicodeDecodeError) as exc:
            files.append({"path": path, "ok": False, "code": "file_read_error", "error": str(exc)})
            continue
        preview = _slice_text_lines(
            content,
            offset=offset,
            limit=min(max(1, limit), _MAX_READ_FILE_LINES),
        )
        files.append(
            {
                "path": path,
                "resolved_path": str(target),
                "ok": True,
                **preview,
            }
        )
        estimated_total_tokens += estimate_token_count(preview["content"])
    return json_response(
        True,
        f"Read {len(files)} files",
        details={
            "files": files,
            "requested_paths": len(paths),
            **budget_metadata(
                estimated_tokens=estimated_total_tokens,
                budget_tokens=budget_tokens,
                recommended_next_step="Prefer narrow_context or build_context_pack before reading more files.",
            ),
        },
    )


async def list_directory(path: str = ".") -> str:
    try:
        target = resolve_path(path)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(path),
        )

    if not target.exists():
        return json_response(
            False,
            f"Directory not found: {path}",
            code="directory_not_found",
            details={"path": path},
        )
    if not target.is_dir():
        return json_response(
            False,
            f"Not a directory: {path}",
            code="not_a_directory",
            details={"path": path},
        )

    try:
        raw_entries = sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name))
    except OSError as exc:
        return json_response(
            False,
            f"Failed to list directory: {exc}",
            code="directory_read_error",
            details={"path": path},
        )

    entries: list[dict[str, Any]] = []
    for entry in raw_entries:
        entry_type: str
        entry_size: int | None = None
        try:
            is_sym = entry.is_symlink()
        except OSError:
            # Can't stat the entry at all; skip it rather than crash the whole listing
            continue
        if is_sym:
            try:
                resolved_target = entry.resolve()
            except (OSError, RuntimeError):
                # Broken or inaccessible symlink; mark as symlink but don't leak target
                entry_type = "symlink"
            else:
                if any(is_within_root(resolved_target, root) for root in allowed_roots()):
                    # Symlink points within allowed roots; report as file/directory
                    try:
                        entry_type = "directory" if entry.is_dir() else "file"
                        if entry_type == "file":
                            entry_size = entry.stat().st_size
                    except OSError:
                        entry_type = "symlink"
                else:
                    # Symlink target is outside allowed roots; don't leak info
                    entry_type = "symlink"
        else:
            try:
                entry_type = "directory" if entry.is_dir() else "file"
                if entry_type == "file":
                    entry_size = entry.stat().st_size
            except OSError:
                # Can't stat; skip this entry
                continue
        entries.append(
            {
                "name": entry.name,
                "type": entry_type,
                "size": entry_size,
            }
        )

    return json_response(
        True,
        f"Listed directory: {path}",
        details={
            "path": path,
            "resolved_path": str(target),
            "entries": entries[:_MAX_LIST_DIRECTORY_ENTRIES],
            "entry_count": len(entries),
            "returned_entry_count": min(len(entries), _MAX_LIST_DIRECTORY_ENTRIES),
            "truncated": len(entries) > _MAX_LIST_DIRECTORY_ENTRIES,
            "entry_limit": _MAX_LIST_DIRECTORY_ENTRIES,
        },
    )


async def write_file(
    path: str,
    content: str,
    overwrite: bool = False,
    create_parents: bool = False,
    max_lines: int = _WRITE_FILE_WARNING_LINES,
    auto_commit: bool = True,
    *,
    git_commit_fn: Callable[..., dict[str, Any]] = _git_commit,
    ai_provider: Any = None,
) -> str:
    if max_lines < 1:
        return json_response(
            False,
            "max_lines must be at least 1",
            code="invalid_max_lines",
            details={"path": path, "max_lines": max_lines},
        )

    try:
        target = resolve_path(path)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(path),
            decision=builtin_deny_decision(
                "Path is outside the active workspace",
                risk_level=RiskLevel.CRITICAL,
                risk_reasons=["path outside allowed project roots"],
                metadata={"tool": "write_file", "path": path},
            ),
            decision_in_details=True,
        )

    sensitive_reason = sensitive_path_reason(target)
    if sensitive_reason is not None:
        return json_response(
            False,
            "Sensitive file types cannot be written through this tool",
            code="sensitive_file_blocked",
            details=sensitive_file_blocked_details(path),
            decision=builtin_deny_decision(
                "Sensitive path is blocked",
                risk_level=RiskLevel.HIGH,
                risk_reasons=[f"sensitive path: {sensitive_reason}"],
                metadata={"tool": "write_file", "path": path},
            ),
            decision_in_details=True,
        )

    secret_patterns = find_secret_patterns(content)
    if secret_patterns:
        return json_response(
            False,
            "Content looks sensitive and was blocked",
            code="secret_pattern_detected",
            details={"path": path, "patterns": secret_patterns},
            decision=builtin_deny_decision(
                "Content matched sensitive data patterns",
                risk_level=RiskLevel.HIGH,
                risk_reasons=[f"secret pattern: {pattern}" for pattern in secret_patterns],
                metadata={"tool": "write_file", "path": path},
            ),
            decision_in_details=True,
        )

    rule_decision = evaluate_rules(
        ToolRequestContext(
            tool_name="write_file",
            params={
                "path": path,
                "file": path,
                "content": content,
                "overwrite": overwrite,
                "create_parents": create_parents,
            },
            project_dir=str(infer_project_root(target.parent if not target.exists() else target)),
        )
    )
    if rule_decision is not None and rule_decision.action == DecisionAction.DENY:
        return json_response(
            False,
            rule_decision.reason,
            code="policy_denied",
            details={"path": path},
            decision=rule_decision,
            decision_in_details=True,
        )
    if rule_decision is not None and rule_decision.action == DecisionAction.ASK:
        return json_response(
            False,
            rule_decision.reason,
            code="approval_rejected",
            details={"path": path},
            decision=rule_decision,
            decision_in_details=True,
        )

    # AI evaluator layer (optional, default off)
    config = current_config()
    ai_enabled = bool(config.get("ai_evaluator_enabled", False))
    ai_timeout = int(config.get("ai_evaluator_timeout", 5))
    ai_fallback = str(config.get("ai_evaluator_fallback_action", "ask"))
    ai_decision = await evaluate_tool_with_ai(
        ToolRequestContext(
            tool_name="write_file",
            params={
                "path": path,
                "file": path,
                "content": content,
                "overwrite": overwrite,
                "create_parents": create_parents,
            },
            project_dir=str(infer_project_root(target.parent if not target.exists() else target)),
        ),
        provider=ai_provider,
        enabled=ai_enabled,
        timeout=ai_timeout,
        fallback_action=ai_fallback,
    )
    if ai_decision is not None and ai_decision.action == DecisionAction.DENY:
        return json_response(
            False,
            ai_decision.reason,
            code="policy_denied",
            details={"path": path},
            decision=ai_decision,
            decision_in_details=True,
        )
    if ai_decision is not None and ai_decision.action == DecisionAction.ASK:
        return json_response(
            False,
            ai_decision.reason,
            code="approval_rejected",
            details={"path": path},
            decision=ai_decision,
            decision_in_details=True,
        )

    if target.exists() and target.is_dir():
        return json_response(
            False,
            f"Not a file: {path}",
            code="not_a_file",
            details={"path": path},
        )
    if target.exists() and not overwrite:
        return json_response(
            False,
            f"File already exists: {path}",
            code="file_exists",
            details={"path": path},
        )
    if not target.parent.exists() and not create_parents:
        return json_response(
            False,
            f"Parent directory does not exist: {target.parent}",
            code="parent_directory_missing",
            details={"path": path, "parent": str(target.parent)},
        )

    if target.suffix == ".py":
        try:
            ast.parse(content)
        except SyntaxError as exc:
            return json_response(
                False,
                f"Python syntax error in file content: {exc}",
                code="python_syntax_error",
                details={"path": path, "error": str(exc)},
            )

    line_count = len(content.splitlines())
    approval_params = {"file": path, "overwrite": overwrite, "line_count": line_count}
    decision_risk_reasons = ["writes modify workspace contents"]
    if overwrite:
        decision_risk_reasons.append("overwrite requested")
    if ai_decision is not None and ai_decision.action == DecisionAction.ALLOW:
        allow_decision = ai_decision
    elif rule_decision is not None and rule_decision.action == DecisionAction.ALLOW:
        allow_decision = rule_decision
    else:
        approved = await request_approval("write_file", approval_params)
        if not approved:
            return json_response(
                False,
                "Write rejected by user",
                code="approval_rejected",
                details={"path": path},
                decision=approval_ask_decision(
                    "File write requires approval",
                    risk_level=RiskLevel.MEDIUM,
                    risk_reasons=decision_risk_reasons,
                    metadata={"tool": "write_file", "path": path},
                ),
                decision_in_details=True,
            )
        allow_decision = approval_allow_decision(
            "File write approved",
            risk_level=RiskLevel.MEDIUM,
            risk_reasons=decision_risk_reasons,
            metadata={"tool": "write_file", "path": path},
        )

    if create_parents:
        target.parent.mkdir(parents=True, exist_ok=True)
    previous_exists = target.exists()
    previous_content = None
    if previous_exists:
        try:
            previous_content = safe_read_text(target)
        except (OSError, UnicodeDecodeError):
            previous_content = None
    if target.exists() and target.is_dir():
        return json_response(
            False,
            f"Not a file: {path}",
            code="not_a_file",
            details={"path": path},
        )
    # FIX: TOCTOU symlink check — reject symlink write targets before opening
    if target.is_symlink():
        return json_response(
            False,
            f"Refusing to write to symlink: {path}",
            code="symlink_blocked",
            details={"path": path},
        )
    try:
        _write_text_exact(target, content, exclusive=not overwrite)
    except FileExistsError:
        if target.is_dir():
            return json_response(
                False,
                f"Not a file: {path}",
                code="not_a_file",
                details={"path": path},
            )
        return json_response(
            False,
            f"File already exists: {path}",
            code="file_exists",
            details={"path": path},
        )
    except IsADirectoryError:
        return json_response(
            False,
            f"Not a file: {path}",
            code="not_a_file",
            details={"path": path},
        )
    except OSError as exc:
        return json_response(
            False,
            f"Failed to write file: {exc}",
            code="file_write_error",
            details={"path": path},
            decision=allow_decision,
            decision_in_details=True,
        )

    try:
        target_project_dir = infer_project_root(target)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(path),
        )
    if auto_commit:
        git_result = git_commit_fn(
            target.relative_to(target_project_dir).as_posix(),
            project_dir=target_project_dir,
        )
    else:
        git_result = {
            "auto_commit": False,
            "init": False,
            "add": False,
            "commit": False,
            "output": "",
        }
    _remember_bridge_change(
        target=target,
        project_dir=target_project_dir,
        previous_exists=previous_exists,
        previous_content=previous_content,
        new_content=content,
        operation="write_file",
        git_result=git_result,
    )
    warning = None
    warnings: list[dict[str, Any]] = []
    if previous_exists:
        warning = "Prefer patch_file for existing files when making targeted edits so the model can keep changes small and reviewable."
        warnings.append(
            {
                "code": "prefer_patch_file_for_overwrite",
                "message": warning,
                "recommended_next_tool": "patch_file",
            }
        )
    if line_count > max_lines:
        max_lines_warning = (
            f"Content has {line_count} lines (max_lines={max_lines}); consider patch_file "
            "for targeted edits or increase max_lines."
        )
        if warning is None:
            warning = max_lines_warning
        warnings.append(
            {
                "code": "content_exceeds_max_lines",
                "message": max_lines_warning,
                "line_count": line_count,
                "max_lines": max_lines,
                "recommended_next_tool": "patch_file",
            }
        )

    return json_response(
        True,
        f"Wrote file: {path}",
        details={
            "path": path,
            "resolved_path": str(target),
            "bytes_written": len(content.encode("utf-8")),
            "created": not previous_exists,
            "overwritten": previous_exists and overwrite,
            "git": git_result,
            "warning": warning,
            "warnings": warnings,
        },
        decision=allow_decision,
        decision_in_details=True,
    )


async def move_file(
    source: str,
    destination: str,
    overwrite: bool = False,
    create_parents: bool = False,
    *,
    git_commit_fn: Callable[..., dict[str, Any]] = _git_commit,
) -> str:
    try:
        source_path = resolve_path(source)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(source),
            decision=path_guard_decision(source, "move", outside_workspace=True),
        )
    try:
        destination_path = resolve_path(destination)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(destination),
            decision=path_guard_decision(destination, "move", outside_workspace=True),
        )

    for user_path, target in ((source, source_path), (destination, destination_path)):
        sensitive_reason = sensitive_path_reason(target)
        if sensitive_reason is not None:
            return json_response(
                False,
                "Sensitive paths cannot be moved through this tool",
                code="sensitive_file_blocked",
                details=sensitive_file_blocked_details(user_path),
                decision=path_guard_decision(user_path, "move", sensitive_reason=sensitive_reason),
            )

    if not source_path.exists():
        return json_response(
            False,
            f"Source not found: {source}",
            code="source_not_found",
            details={"source": source},
        )
    if source_path == destination_path:
        return json_response(
            False,
            "Source and destination must be different",
            code="same_path",
            details={"source": source, "destination": destination},
        )
    if destination_path.exists() and not overwrite:
        return json_response(
            False,
            f"Destination already exists: {destination}",
            code="destination_exists",
            details={"destination": destination},
        )
    if not destination_path.parent.exists() and not create_parents:
        return json_response(
            False,
            f"Parent directory does not exist: {destination_path.parent}",
            code="parent_directory_missing",
            details={"destination": destination, "parent": str(destination_path.parent)},
        )

    rejection = await require_approval(
        "move_file",
        {"source": source, "destination": destination, "overwrite": overwrite},
        rejection_message="Move rejected by user",
        rejection_details={"source": source, "destination": destination},
    )
    if rejection is not None:
        return rejection

    if create_parents:
        destination_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if destination_path.exists() and overwrite:
            if destination_path.is_dir():
                # FIX: rmtree on symlink directory — reject to prevent following symlink
                if destination_path.is_symlink():
                    return json_response(
                        False,
                        "Refusing to rmtree on a symlink directory",
                        code="symlink_rmtree_blocked",
                        details={"destination": destination},
                    )
                shutil.rmtree(destination_path)
            else:
                destination_path.unlink()
        shutil.move(str(source_path), str(destination_path))
    except OSError as exc:
        return json_response(
            False,
            f"Failed to move path: {exc}",
            code="move_failed",
            details={"source": source, "destination": destination},
        )

    try:
        target_project_dir = infer_project_root(destination_path)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(destination),
        )
    git_results = [
        git_commit_fn(source_path.as_posix(), project_dir=target_project_dir),
        git_commit_fn(destination_path.as_posix(), project_dir=target_project_dir),
    ]
    return json_response(
        True,
        f"Moved path: {source} -> {destination}",
        details={
            "source": source,
            "destination": destination,
            "resolved_source": str(source_path),
            "resolved_destination": str(destination_path),
            "overwritten": overwrite,
            "git": git_results,
        },
    )


async def copy_path(
    source: str,
    destination: str,
    overwrite: bool = False,
    create_parents: bool = False,
    *,
    git_commit_fn: Callable[..., dict[str, Any]] = _git_commit,
) -> str:
    try:
        source_path = resolve_path(source)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(source),
            decision=path_guard_decision(source, "copy", outside_workspace=True),
        )
    try:
        destination_path = resolve_path(destination)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(destination),
            decision=path_guard_decision(destination, "copy", outside_workspace=True),
        )

    for user_path, target in ((source, source_path), (destination, destination_path)):
        sensitive_reason = sensitive_path_reason(target)
        if sensitive_reason is not None:
            return json_response(
                False,
                "Sensitive paths cannot be copied through this tool",
                code="sensitive_file_blocked",
                details=sensitive_file_blocked_details(user_path),
                decision=path_guard_decision(user_path, "copy", sensitive_reason=sensitive_reason),
            )

    if not source_path.exists():
        return json_response(
            False,
            f"Source not found: {source}",
            code="source_not_found",
            details={"source": source},
        )
    if source_path == destination_path:
        return json_response(
            False,
            "Source and destination must be different",
            code="same_path",
            details={"source": source, "destination": destination},
        )
    if destination_path.exists() and not overwrite:
        return json_response(
            False,
            f"Destination already exists: {destination}",
            code="destination_exists",
            details={"destination": destination},
        )
    if not destination_path.parent.exists() and not create_parents:
        return json_response(
            False,
            f"Parent directory does not exist: {destination_path.parent}",
            code="parent_directory_missing",
            details={"destination": destination, "parent": str(destination_path.parent)},
        )

    rejection = await require_approval(
        "copy_path",
        {"source": source, "destination": destination, "overwrite": overwrite},
        rejection_message="Copy rejected by user",
        rejection_details={"source": source, "destination": destination},
    )
    if rejection is not None:
        return rejection

    if create_parents:
        destination_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if source_path.is_dir():
            if destination_path.exists() and overwrite:
                if destination_path.is_dir():
                    # FIX: rmtree on symlink directory — reject to prevent following symlink
                    if destination_path.is_symlink():
                        return json_response(
                            False,
                            "Refusing to rmtree on a symlink directory",
                            code="symlink_rmtree_blocked",
                            details={"destination": destination},
                        )
                    shutil.rmtree(destination_path)
                else:
                    destination_path.unlink()
            # FIX: copy_path directory size limit — reject dirs larger than 500MB
            # FIX: check each rglob result stays within allowed roots
            total_size = 0
            roots = allowed_roots()
            for f in source_path.rglob("*"):
                resolved_f = f
                try:
                    resolved_f = f.resolve()
                except OSError:
                    continue
                if not any(is_within_root(resolved_f, root) for root in roots):
                    continue
                if f.is_file() and not f.is_symlink():
                    try:
                        total_size += f.stat().st_size
                    except OSError:
                        pass
            if total_size > 500 * 1024 * 1024:
                return json_response(
                    False,
                    "Directory size exceeds 500MB limit",
                    code="dir_too_large",
                    details={
                        "source": source,
                        "size_bytes": total_size,
                        "limit_bytes": 500 * 1024 * 1024,
                    },
                )
            # FIX: copytree symlink following — use symlinks=True to copy not follow
            shutil.copytree(source_path, destination_path, symlinks=True)
        else:
            if destination_path.exists() and destination_path.is_dir():
                return json_response(
                    False,
                    f"Destination is a directory: {destination}",
                    code="destination_is_directory",
                    details={"destination": destination},
                )
            shutil.copy2(source_path, destination_path)
    except OSError as exc:
        return json_response(
            False,
            f"Failed to copy path: {exc}",
            code="copy_failed",
            details={"source": source, "destination": destination},
        )

    try:
        target_project_dir = infer_project_root(destination_path)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(destination),
        )
    git_result = git_commit_fn(destination_path.as_posix(), project_dir=target_project_dir)
    return json_response(
        True,
        f"Copied path: {source} -> {destination}",
        details={
            "source": source,
            "destination": destination,
            "resolved_source": str(source_path),
            "resolved_destination": str(destination_path),
            "overwritten": overwrite,
            "git": git_result,
        },
    )


async def search_in_files(
    query: str,
    path: str = ".",
    regex: bool = False,
    case_sensitive: bool = False,
    include_glob: str | None = None,
    offset: int = 0,
    limit: int = 20,
    budget_tokens: int = DEFAULT_CONTEXT_BUDGET_TOKENS,
) -> str:
    stripped = query.strip()
    if not stripped:
        return json_response(
            False,
            "Query cannot be empty",
            code="empty_query",
            details={"query": query},
        )
    if offset < 0:
        return json_response(
            False,
            "Offset must be 0 or greater",
            code="invalid_offset",
            details={"offset": offset},
        )
    if limit < 1 or limit > _MAX_SEARCH_RESULTS:
        return json_response(
            False,
            f"Limit must be between 1 and {_MAX_SEARCH_RESULTS}",
            code="invalid_limit",
            details={"limit": limit, "max_limit": _MAX_SEARCH_RESULTS},
        )
    # FIX: include_glob ReDoS prevention — max 256 characters for glob patterns
    if include_glob is not None and len(include_glob) > 256:
        return json_response(
            False,
            "include_glob pattern exceeds 256 character limit",
            code="glob_too_long",
            details={"include_glob_length": len(include_glob), "max_length": 256},
        )

    try:
        target = resolve_path(path)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(path),
        )

    if not target.exists():
        return json_response(
            False,
            f"Path not found: {path}",
            code="path_not_found",
            details={"path": path},
        )

    project_root = infer_project_root(target)
    root = target if target.is_dir() else target.parent
    rg_payload = _run_ripgrep_search(
        query=query,
        target=target,
        root=project_root,
        display_root=root,
        regex=regex,
        case_sensitive=case_sensitive,
        include_glob=include_glob,
        offset=offset,
        limit=limit,
    )
    if rg_payload is not None:
        estimated_tokens = estimate_token_count(
            "\n".join(
                f"{item['path']}:{item['line_number']}:{item['line']}"
                for item in rg_payload["results"]
            )
        )
        return json_response(
            True,
            f"Search completed for query: {query}",
            details={
                "query": query,
                "path": path,
                "regex": regex,
                "case_sensitive": case_sensitive,
                "include_glob": include_glob,
                "offset": rg_payload["offset"],
                "next_offset": rg_payload["next_offset"],
                "results": rg_payload["results"],
                "truncated": rg_payload["truncated"],
                "files_searched": rg_payload["files_searched"],
                "search_backend": rg_payload["search_backend"],
                **budget_metadata(
                    estimated_tokens=estimated_tokens,
                    budget_tokens=budget_tokens,
                    recommended_next_step="Use find_relevant_files or read_file on the strongest match instead of broad follow-up reads.",
                ),
            },
        )

    try:
        files = iter_searchable_files(
            target,
            project_root,
            is_within_root=is_within_root,
            include_glob=include_glob,
        )
    except OSError as exc:
        return json_response(
            False,
            f"Failed to search files: {exc}",
            code="search_error",
            details={"path": path},
        )

    flags = 0 if case_sensitive else re.IGNORECASE
    # FIX: ReDoS protection — re.compile with 2s timeout via ThreadPoolExecutor
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(re.compile, query if regex else re.escape(query), flags)
        try:
            pattern = future.result(timeout=2)
        except concurrent.futures.TimeoutError:
            return json_response(
                False,
                "Regular expression compilation timed out (potential ReDoS)",
                code="regex_timeout",
                details={"query": query},
            )
        except re.error as exc:
            return json_response(
                False,
                f"Invalid regular expression: {exc}",
                code="invalid_regex",
                details={"query": query},
            )

    MAX_SEARCH_SCAN_MS = 5000
    results: list[dict[str, Any]] = []
    files_searched = 0
    truncated = False
    match_count = 0
    import time as _time

    scan_deadline = _time.monotonic() + MAX_SEARCH_SCAN_MS / 1000.0
    for file_path in files:
        if _time.monotonic() > scan_deadline:
            truncated = True
            break
        if sensitive_path_reason(file_path) is not None:
            continue
        try:
            content = safe_read_text(file_path)
        except (OSError, UnicodeDecodeError):
            continue
        files_searched += 1
        try:
            relative_path = (
                file_path.relative_to(root).as_posix() if target.is_dir() else file_path.name
            )
        except ValueError:
            # file_path may not be under root (e.g. symlink escape); skip
            continue
        for line_number, line in enumerate(content.splitlines(), start=1):
            if not pattern.search(line):
                continue
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
                    "line": line[:300],
                }
            )
            match_count += 1
        if len(results) >= limit:
            break

    return json_response(
        True,
        f"Search completed for query: {query}",
        details={
            "query": query,
            "path": path,
            "regex": regex,
            "case_sensitive": case_sensitive,
            "include_glob": include_glob,
            "offset": offset,
            "next_offset": offset + len(results) if truncated else -1,
            "results": results,
            "truncated": truncated,
            "files_searched": files_searched,
            "search_backend": "python",
            **budget_metadata(
                estimated_tokens=estimate_token_count(
                    "\n".join(
                        f"{item['path']}:{item['line_number']}:{item['line']}" for item in results
                    )
                ),
                budget_tokens=budget_tokens,
                recommended_next_step="Use find_relevant_files or read_file on the strongest match instead of broad follow-up reads.",
            ),
        },
    )


async def patch_file(
    file: str,
    search: str,
    replace: str,
    auto_commit: bool = True,
    *,
    git_commit_fn: Callable[..., dict[str, Any]] = _git_commit,
    ai_provider: Any = None,
) -> str:
    try:
        target = resolve_path(file)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(file),
            decision=path_guard_decision(file, "patch", outside_workspace=True),
        )

    try:
        target_project_dir = infer_project_root(target)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(file),
            decision=path_guard_decision(file, "patch", outside_workspace=True),
        )
    if not target.exists():
        return json_response(
            False,
            f"File not found: {file}",
            code="file_not_found",
            details={"path": file},
        )
    if not target.is_file():
        return json_response(
            False,
            f"Not a file: {file}",
            code="not_a_file",
            details={"path": file},
        )
    if target.is_symlink():
        return json_response(
            False,
            f"Refusing to patch symlink: {file}",
            code="symlink_blocked",
            details={"path": file},
        )

    sensitive_reason = sensitive_path_reason(target)
    if sensitive_reason is not None:
        return json_response(
            False,
            "Sensitive files are blocked from direct patching",
            code="sensitive_file_blocked",
            details=sensitive_file_blocked_details(file),
            decision=path_guard_decision(file, "patch", sensitive_reason=sensitive_reason),
        )

    try:
        original = _read_text_preserve_line_endings(target)
    except (OSError, UnicodeDecodeError) as exc:
        return json_response(
            False,
            f"Failed to read file: {exc}",
            code="file_read_error",
            details={"path": file},
        )

    preview_payload = _build_preview_patch_result(target, original, file, search, replace)
    if not preview_payload["ok"]:
        return json_response(
            False,
            preview_payload["message"],
            code=preview_payload["code"],
            details=preview_payload["details"],
        )

    rule_decision = evaluate_rules(
        ToolRequestContext(
            tool_name="patch_file",
            params={
                "file": file,
                "search": search,
                "replace": replace,
            },
            project_dir=str(target_project_dir),
        )
    )
    if rule_decision is not None and rule_decision.action == DecisionAction.DENY:
        return json_response(
            False,
            rule_decision.reason,
            code="policy_denied",
            details={"path": file},
            decision=rule_decision,
            decision_in_details=True,
        )
    if rule_decision is not None and rule_decision.action == DecisionAction.ASK:
        return json_response(
            False,
            rule_decision.reason,
            code="approval_rejected",
            details={"path": file},
            decision=rule_decision,
            decision_in_details=True,
        )

    # AI evaluator layer (optional, default off)
    config = current_config()
    ai_enabled = bool(config.get("ai_evaluator_enabled", False))
    ai_timeout = int(config.get("ai_evaluator_timeout", 5))
    ai_fallback = str(config.get("ai_evaluator_fallback_action", "ask"))
    ai_decision = await evaluate_tool_with_ai(
        ToolRequestContext(
            tool_name="patch_file",
            params={
                "file": file,
                "search": search,
                "replace": replace,
            },
            project_dir=str(target_project_dir),
        ),
        provider=ai_provider,
        enabled=ai_enabled,
        timeout=ai_timeout,
        fallback_action=ai_fallback,
    )
    if ai_decision is not None and ai_decision.action == DecisionAction.DENY:
        return json_response(
            False,
            ai_decision.reason,
            code="policy_denied",
            details={"path": file},
            decision=ai_decision,
            decision_in_details=True,
        )
    if ai_decision is not None and ai_decision.action == DecisionAction.ASK:
        return json_response(
            False,
            ai_decision.reason,
            code="approval_rejected",
            details={"path": file},
            decision=ai_decision,
            decision_in_details=True,
        )

    if ai_decision is not None and ai_decision.action == DecisionAction.ALLOW:
        pass  # bypass approval for AI-allow matches
    elif rule_decision is not None and rule_decision.action == DecisionAction.ALLOW:
        pass  # bypass approval for rule-allow matches
    else:
        rejection = await require_approval(
            "patch_file",
            {"file": file},
            rejection_message="Patch rejected by user",
            rejection_details={"path": file},
        )
        if rejection is not None:
            return rejection

    line_ending = _line_ending_for_content(original)
    original_norm = original.replace("\r\n", "\n").replace("\r", "\n")
    search_norm = search.replace("\r\n", "\n").replace("\r", "\n")
    replace_norm = replace.replace("\r\n", "\n").replace("\r", "\n")
    new_content_norm = original_norm.replace(search_norm, replace_norm, 1)
    new_content = _normalize_line_endings(new_content_norm, line_ending=line_ending)
    try:
        _write_text_exact(target, new_content)
    except OSError as exc:
        return json_response(
            False,
            f"Failed to write file: {exc}",
            code="file_write_error",
            details={"path": file},
        )

    if auto_commit:
        git_result = git_commit_fn(
            target.relative_to(target_project_dir).as_posix(),
            project_dir=target_project_dir,
        )
    else:
        git_result = {
            "auto_commit": False,
            "init": False,
            "add": False,
            "commit": False,
            "output": "",
        }
    _remember_bridge_change(
        target=target,
        project_dir=target_project_dir,
        previous_exists=True,
        previous_content=original,
        new_content=new_content,
        operation="patch_file",
        git_result=git_result,
    )
    message = f"Patched {file}"
    if not git_result.get("commit"):
        message += (
            f" (git commit failed: {git_result.get('output', '').strip() or 'unknown error'})"
        )

    return json_response(
        True,
        message,
        details={
            "path": file,
            "resolved_path": str(target),
            "git": git_result,
            "risk": preview_payload["details"]["risk"],
            "diff": preview_payload["details"]["diff"],
        },
    )


async def preview_patch(file: str, search: str, replace: str) -> str:
    try:
        target = resolve_path(file)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(file),
            decision=path_guard_decision(file, "preview_patch", outside_workspace=True),
        )

    if not target.exists():
        return json_response(
            False,
            f"File not found: {file}",
            code="file_not_found",
            details={"path": file},
        )
    if not target.is_file():
        return json_response(
            False,
            f"Not a file: {file}",
            code="not_a_file",
            details={"path": file},
        )
    sensitive_reason = sensitive_path_reason(target)
    if sensitive_reason is not None:
        return json_response(
            False,
            "Sensitive files are blocked from direct previewing",
            code="sensitive_file_blocked",
            details=sensitive_file_blocked_details(file),
            decision=path_guard_decision(file, "preview_patch", sensitive_reason=sensitive_reason),
        )

    try:
        original = _read_text_preserve_line_endings(target)
    except (OSError, UnicodeDecodeError) as exc:
        return json_response(
            False,
            f"Failed to read file: {exc}",
            code="file_read_error",
            details={"path": file},
        )

    preview_payload = _build_preview_patch_result(target, original, file, search, replace)
    return json_response(
        preview_payload["ok"],
        preview_payload["message"],
        code=preview_payload.get("code"),
        details=preview_payload["details"],
    )


async def undo_last_patch(
    confirm: bool = False,
    *,
    request_approval_fn: Callable[[str, dict[str, Any]], Awaitable[bool]] = request_approval,
    git_commit_fn: Callable[..., dict[str, Any]] = _git_commit,
) -> str:
    snapshot = _last_bridge_change_snapshot()
    if snapshot is None:
        return json_response(
            False,
            "No Bridge-managed change is available to undo",
            code="no_undo_state",
            details={},
        )
    version, change = snapshot

    target = Path(change["target"])
    project_dir_path = Path(change["project_dir"])
    previous_exists = bool(change["previous_exists"])
    previous_content = change["previous_content"]
    details = {
        "path": change["path"],
        "resolved_path": str(target),
        "project_dir": str(project_dir_path),
        "operation": change["operation"],
        "git": change["git_result"],
        "previous_exists": previous_exists,
        "current_exists": target.exists(),
    }

    try:
        resolved_target = resolve_path(change["path"])
        if resolved_target.resolve() != target.resolve():
            details["warning"] = "Undo target path differs from resolved path; skipping for safety"
            return json_response(
                False,
                "Undo target path validation failed",
                code="undo_path_mismatch",
                details=details,
            )
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(change["path"]),
        )

    if not confirm:
        return json_response(
            False,
            "Undo requires explicit confirmation",
            code="confirmation_required",
            details=details,
        )

    rejection = await require_approval(
        "undo_last_patch",
        {
            "path": change["path"],
            "operation": change["operation"],
            "previous_exists": previous_exists,
        },
        rejection_message="Undo rejected by user",
        rejection_details=details,
        request_approval_fn=request_approval_fn,
    )
    if rejection is not None:
        return rejection

    key = str(project_dir_path.resolve())
    with _LAST_BRIDGE_CHANGE_LOCK:
        if key not in _LAST_BRIDGE_CHANGE or _LAST_BRIDGE_CHANGE_VERSION.get(key) != version:
            return json_response(
                False,
                "Bridge change state was modified; cannot undo safely",
                code="undo_stale_state",
                details=details,
            )
        _LAST_BRIDGE_CHANGE.pop(key, None)
        _LAST_BRIDGE_CHANGE_VERSION.pop(key, None)

    if previous_exists:
        if previous_content is None:
            return json_response(
                False,
                "Original file content is unavailable; cannot undo safely",
                code="undo_snapshot_unavailable",
                details=details,
            )
        secret_patterns = find_secret_patterns(previous_content)
        if secret_patterns:
            return json_response(
                False,
                "Content looks sensitive and was blocked",
                code="secret_pattern_detected",
                details={"path": change["path"], "patterns": secret_patterns},
                decision=builtin_deny_decision(
                    "Content matched sensitive data patterns",
                    risk_level=RiskLevel.HIGH,
                    risk_reasons=[f"secret pattern: {pattern}" for pattern in secret_patterns],
                    metadata={"tool": "undo_last_patch", "path": change["path"]},
                ),
                decision_in_details=True,
            )
        try:
            _write_text_exact(target, previous_content)
        except OSError as exc:
            return json_response(
                False,
                f"Failed to restore previous file content: {exc}",
                code="file_write_error",
                details=details,
            )
    else:
        try:
            if target.exists():
                target.unlink()
        except OSError as exc:
            return json_response(
                False,
                f"Failed to remove file created by the last Bridge change: {exc}",
                code="file_write_error",
                details=details,
            )

    git_result = git_commit_fn(
        change["path"],
        project_dir=project_dir_path,
        message=f"bridge: undo {change['path']}",
    )
    details["undo_git"] = git_result
    details["restored_to_exists"] = previous_exists
    details["restored_bytes"] = (
        len(previous_content.encode("utf-8")) if previous_content is not None else 0
    )

    return json_response(
        True,
        f"Undid last Bridge change for {change['path']}",
        details=details,
    )
