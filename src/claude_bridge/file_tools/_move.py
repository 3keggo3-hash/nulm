"""Move and copy file tools."""

from __future__ import annotations

import shutil
from typing import Any, Callable

from claude_bridge.git_ops import git_commit as _git_commit
from claude_bridge.tool_utils import (
    allowed_roots,
    infer_project_root,
    is_within_root,
    json_response,
    path_guard_decision,
    path_outside_project_details,
    require_approval,
    resolve_path,
    sensitive_file_blocked_details,
    sensitive_path_reason,
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
        source_project_dir = infer_project_root(source_path)
        destination_project_dir = infer_project_root(destination_path)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(destination),
        )
    git_results = [
        git_commit_fn(
            source_path.relative_to(source_project_dir).as_posix(),
            project_dir=source_project_dir,
        ),
        git_commit_fn(
            destination_path.relative_to(destination_project_dir).as_posix(),
            project_dir=destination_project_dir,
        ),
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
    git_result = git_commit_fn(
        destination_path.relative_to(target_project_dir).as_posix(),
        project_dir=target_project_dir,
    )
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
