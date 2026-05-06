"""Read-oriented file tools."""

from __future__ import annotations

from typing import Any

from claude_bridge.tool_utils import (
    allowed_roots,
    is_within_root,
    json_response,
    path_guard_decision,
    path_outside_project_details,
    resolve_path,
    safe_read_text,
    sensitive_file_blocked_details,
    sensitive_path_reason,
)

from claude_bridge.file_tools._helpers import (
    _MAX_LIST_DIRECTORY_ENTRIES,
    _MAX_MULTI_FILE_READS,
    _MAX_READ_FILE_LINES,
    _slice_text_lines,
)

DEFAULT_CONTEXT_BUDGET_TOKENS = 4000


def _budget_metadata(
    *, estimated_tokens: int, budget_tokens: int, recommended_next_step: str
) -> dict[str, Any]:
    from claude_bridge.smart import budget_metadata

    return budget_metadata(
        estimated_tokens=estimated_tokens,
        budget_tokens=budget_tokens,
        recommended_next_step=recommended_next_step,
    )


def _estimate_token_count(text: str) -> int:
    from claude_bridge.smart import estimate_token_count

    return estimate_token_count(text)


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
    budget = _budget_metadata(
        estimated_tokens=_estimate_token_count(preview["content"]),
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
        estimated_total_tokens += _estimate_token_count(preview["content"])
    return json_response(
        True,
        f"Read {len(files)} files",
        details={
            "files": files,
            "requested_paths": len(paths),
            **_budget_metadata(
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
