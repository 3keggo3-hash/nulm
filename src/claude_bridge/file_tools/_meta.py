"""Metadata and directory-oriented file tools."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

from typing import Any

from claude_bridge.tool_utils import (
    json_response,
    path_outside_project_details,
    resolve_path_safe,
    sensitive_file_blocked_details,
    sensitive_path_reason,
)


async def path_exists(path: str) -> str:
    """Check whether a workspace path exists without exposing file content."""
    try:
        target = resolve_path_safe(path)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(path),
        )

    exists = target.exists()
    if not exists:
        return json_response(True, "Path does not exist", details={"path": path, "exists": False})

    if target.is_symlink():
        return json_response(
            True,
            "Path exists as a symlink",
            details={"path": path, "exists": True, "type": "symlink"},
        )

    path_type = "directory" if target.is_dir() else "file" if target.is_file() else "other"
    return json_response(
        True,
        f"Path exists: {path_type}",
        details={"path": path, "exists": True, "type": path_type},
    )


async def stat_file(path: str) -> str:
    """Return basic metadata for a workspace file or directory."""
    try:
        target = resolve_path_safe(path)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(path),
        )

    sensitive_reason = sensitive_path_reason(target)
    if sensitive_reason is not None:
        return json_response(
            False,
            "Sensitive paths cannot be inspected",
            code="sensitive_file_blocked",
            details=sensitive_file_blocked_details(path),
        )
    if not target.exists():
        return json_response(
            False,
            f"Path does not exist: {path}",
            code="path_not_found",
            details={"path": path},
        )

    try:
        stat_result = target.stat()
    except OSError as exc:
        return json_response(
            False,
            f"Failed to stat path: {exc}",
            code="stat_failed",
            details={"path": path, "error": str(exc)},
        )

    details: dict[str, Any] = {
        "path": path,
        "type": "directory" if target.is_dir() else "file" if target.is_file() else "other",
        "size": stat_result.st_size,
        "mtime": stat_result.st_mtime,
        "mode": oct(stat_result.st_mode)[-3:],
        "symlink": target.is_symlink(),
    }
    return json_response(True, f"Metadata for: {path}", details=details)


async def mkdir(path: str, parents: bool = False) -> str:
    """Create a directory within the workspace."""
    try:
        target = resolve_path_safe(path)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(path),
        )

    sensitive_reason = sensitive_path_reason(target)
    if sensitive_reason is not None:
        return json_response(
            False,
            "Cannot create a sensitive path",
            code="sensitive_file_blocked",
            details=sensitive_file_blocked_details(path),
        )
    if target.exists():
        if target.is_dir():
            return json_response(True, "Directory already exists", details={"path": path})
        return json_response(
            False,
            f"Path exists but is not a directory: {path}",
            code="not_a_directory",
            details={"path": path},
        )

    try:
        target.mkdir(parents=parents, exist_ok=False)
    except OSError as exc:
        return json_response(
            False,
            f"Failed to create directory: {exc}",
            code="mkdir_failed",
            details={"path": path, "error": str(exc)},
        )
    return json_response(True, f"Created directory: {path}", details={"path": path})
