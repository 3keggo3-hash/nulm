"""Move and copy file tools."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import errno
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

from claude_bridge.ai_evaluator import evaluate_tool_with_ai
from claude_bridge.config import active_role, active_user, current_config
from claude_bridge.git_ops import git_commit as _git_commit
from claude_bridge.guard_policy import (
    DecisionAction,
    ToolRequestContext,
    approval_allow_decision,
)
from claude_bridge.rules_engine import evaluate_runtime_policy_chain
from claude_bridge.tool_utils import (
    allowed_roots,
    infer_project_root,
    is_within_root,
    json_response,
    path_guard_decision,
    path_outside_project_details,
    require_approval,
    resolve_path_safe,
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
    ai_provider: Any = None,
) -> str:
    try:
        source_path = resolve_path_safe(source)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(source),
            decision=path_guard_decision(source, "move", outside_workspace=True),
        )
    try:
        destination_path = resolve_path_safe(destination)
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
    if not destination_path.parent.exists() and not create_parents:
        return json_response(
            False,
            f"Parent directory does not exist: {destination_path.parent}",
            code="parent_directory_missing",
            details={"destination": destination, "parent": str(destination_path.parent)},
        )

    policy_context = ToolRequestContext(
        tool_name="move_file",
        params={
            "source": source,
            "destination": destination,
            "file": destination,
            "overwrite": overwrite,
            "create_parents": create_parents,
        },
        project_dir=str(infer_project_root(destination_path.parent)),
        role=active_role(),
        user=active_user(),
    )
    approval_decision = None
    rule_decision = evaluate_runtime_policy_chain(policy_context)
    if rule_decision is not None and rule_decision.action == DecisionAction.DENY:
        return json_response(
            False,
            rule_decision.reason,
            code="policy_denied",
            details={"source": source, "destination": destination},
            decision=rule_decision,
            decision_in_details=True,
        )
    if rule_decision is not None and rule_decision.action == DecisionAction.ASK:
        rejection = await require_approval(
            "move_file",
            {"source": source, "destination": destination, "reason": rule_decision.reason},
            rejection_message=rule_decision.reason,
            rejection_details={"source": source, "destination": destination},
            allow_auto_approve=False,
        )
        if rejection is not None:
            return json_response(
                False,
                rule_decision.reason,
                code="approval_rejected",
                details={"source": source, "destination": destination},
                decision=rule_decision,
                decision_in_details=True,
            )
        approval_decision = approval_allow_decision(
            "Move approved after policy ASK decision",
            risk_level=rule_decision.risk_level,
            risk_reasons=list(rule_decision.risk_reasons),
            metadata={"tool": "move_file", **dict(rule_decision.metadata)},
        )

    config = current_config()
    ai_decision = await evaluate_tool_with_ai(
        policy_context,
        provider=ai_provider,
        enabled=bool(config.get("ai_evaluator_enabled", False)),
        timeout=int(config.get("ai_evaluator_timeout", 5)),
        fallback_action=str(config.get("ai_evaluator_fallback_action", "ask")),
    )
    if ai_decision is not None and ai_decision.action == DecisionAction.DENY:
        return json_response(
            False,
            ai_decision.reason,
            code="policy_denied",
            details={"source": source, "destination": destination},
            decision=ai_decision,
            decision_in_details=True,
        )
    if ai_decision is not None and ai_decision.action == DecisionAction.ASK:
        rejection = await require_approval(
            "move_file",
            {"source": source, "destination": destination, "reason": ai_decision.reason},
            rejection_message=ai_decision.reason,
            rejection_details={"source": source, "destination": destination},
            allow_auto_approve=False,
        )
        if rejection is not None:
            return json_response(
                False,
                ai_decision.reason,
                code="approval_rejected",
                details={"source": source, "destination": destination},
                decision=ai_decision,
                decision_in_details=True,
            )
        approval_decision = approval_allow_decision(
            "Move approved after AI ASK decision",
            risk_level=ai_decision.risk_level,
            risk_reasons=list(ai_decision.risk_reasons),
            metadata={"tool": "move_file", **dict(ai_decision.metadata)},
        )

    if approval_decision is None and not (
        rule_decision is not None and rule_decision.action == DecisionAction.ALLOW
    ):
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
        if overwrite:
            os.replace(str(source_path), str(destination_path))
        else:
            if source_path.is_dir():
                if destination_path.exists():
                    return json_response(
                        False,
                        f"Destination already exists: {destination}",
                        code="destination_exists",
                        details={"destination": destination},
                    )
                os.rename(str(source_path), str(destination_path))
            else:
                try:
                    os.link(str(source_path), str(destination_path))
                except FileExistsError:
                    return json_response(
                        False,
                        f"Destination already exists: {destination}",
                        code="destination_exists",
                        details={"destination": destination},
                    )
                try:
                    os.unlink(str(source_path))
                except OSError:
                    try:
                        os.unlink(str(destination_path))
                    except OSError:
                        pass
                    raise
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
        decision=approval_decision if approval_decision is not None else rule_decision,
        decision_in_details=approval_decision is not None or rule_decision is not None,
    )


async def copy_path(
    source: str,
    destination: str,
    overwrite: bool = False,
    create_parents: bool = False,
    *,
    git_commit_fn: Callable[..., dict[str, Any]] = _git_commit,
    ai_provider: Any = None,
) -> str:
    try:
        source_path = resolve_path_safe(source)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(source),
            decision=path_guard_decision(source, "copy", outside_workspace=True),
        )
    try:
        destination_path = resolve_path_safe(destination)
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
    if not destination_path.parent.exists() and not create_parents:
        return json_response(
            False,
            f"Parent directory does not exist: {destination_path.parent}",
            code="parent_directory_missing",
            details={"destination": destination, "parent": str(destination_path.parent)},
        )

    policy_context = ToolRequestContext(
        tool_name="copy_path",
        params={
            "source": source,
            "destination": destination,
            "file": destination,
            "overwrite": overwrite,
            "create_parents": create_parents,
        },
        project_dir=str(infer_project_root(destination_path.parent)),
        role=active_role(),
        user=active_user(),
    )
    approval_decision = None
    rule_decision = evaluate_runtime_policy_chain(policy_context)
    if rule_decision is not None and rule_decision.action == DecisionAction.DENY:
        return json_response(
            False,
            rule_decision.reason,
            code="policy_denied",
            details={"source": source, "destination": destination},
            decision=rule_decision,
            decision_in_details=True,
        )
    if rule_decision is not None and rule_decision.action == DecisionAction.ASK:
        rejection = await require_approval(
            "copy_path",
            {"source": source, "destination": destination, "reason": rule_decision.reason},
            rejection_message=rule_decision.reason,
            rejection_details={"source": source, "destination": destination},
            allow_auto_approve=False,
        )
        if rejection is not None:
            return json_response(
                False,
                rule_decision.reason,
                code="approval_rejected",
                details={"source": source, "destination": destination},
                decision=rule_decision,
                decision_in_details=True,
            )
        approval_decision = approval_allow_decision(
            "Copy approved after policy ASK decision",
            risk_level=rule_decision.risk_level,
            risk_reasons=list(rule_decision.risk_reasons),
            metadata={"tool": "copy_path", **dict(rule_decision.metadata)},
        )

    config = current_config()
    ai_decision = await evaluate_tool_with_ai(
        policy_context,
        provider=ai_provider,
        enabled=bool(config.get("ai_evaluator_enabled", False)),
        timeout=int(config.get("ai_evaluator_timeout", 5)),
        fallback_action=str(config.get("ai_evaluator_fallback_action", "ask")),
    )
    if ai_decision is not None and ai_decision.action == DecisionAction.DENY:
        return json_response(
            False,
            ai_decision.reason,
            code="policy_denied",
            details={"source": source, "destination": destination},
            decision=ai_decision,
            decision_in_details=True,
        )
    if ai_decision is not None and ai_decision.action == DecisionAction.ASK:
        rejection = await require_approval(
            "copy_path",
            {"source": source, "destination": destination, "reason": ai_decision.reason},
            rejection_message=ai_decision.reason,
            rejection_details={"source": source, "destination": destination},
            allow_auto_approve=False,
        )
        if rejection is not None:
            return json_response(
                False,
                ai_decision.reason,
                code="approval_rejected",
                details={"source": source, "destination": destination},
                decision=ai_decision,
                decision_in_details=True,
            )
        approval_decision = approval_allow_decision(
            "Copy approved after AI ASK decision",
            risk_level=ai_decision.risk_level,
            risk_reasons=list(ai_decision.risk_reasons),
            metadata={"tool": "copy_path", **dict(ai_decision.metadata)},
        )

    if approval_decision is None and not (
        rule_decision is not None and rule_decision.action == DecisionAction.ALLOW
    ):
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
            total_size = 0
            file_count = 0
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
                    file_count += 1
                    if file_count > 10000:
                        return json_response(
                            False,
                            "Directory contains too many files (>10000)",
                            code="too_many_files",
                            details={"source": source, "file_count": file_count},
                        )
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

            tmp_parent = Path(tempfile.mkdtemp(dir=str(destination_path.parent)))
            tmp_dst = tmp_parent / "dst"
            backup = None
            try:
                shutil.copytree(source_path, tmp_dst, symlinks=True)
                if overwrite and destination_path.exists():
                    backup = destination_path.with_name(
                        destination_path.name + f".backup.{os.getpid()}"
                    )
                    os.rename(str(destination_path), str(backup))
                os.rename(str(tmp_dst), str(destination_path))
            except OSError as exc:
                if exc.errno in (
                    errno.EEXIST,
                    errno.ENOTEMPTY,
                    errno.ENOTDIR,
                    errno.EISDIR,
                ):
                    return json_response(
                        False,
                        f"Destination already exists: {destination}",
                        code="destination_exists",
                        details={"destination": destination},
                    )
                return json_response(
                    False,
                    f"Failed to copy path: {exc}",
                    code="copy_failed",
                    details={"source": source, "destination": destination},
                )
            finally:
                if backup is not None:
                    try:
                        if Path(backup).exists():
                            shutil.rmtree(backup)
                    except OSError:
                        pass
                try:
                    if tmp_parent.exists():
                        shutil.rmtree(tmp_parent)
                except OSError:
                    pass
        else:
            tmp_fd, tmp_path_str = tempfile.mkstemp(dir=str(destination_path.parent))
            os.close(tmp_fd)
            tmp_path = Path(tmp_path_str)
            try:
                shutil.copy2(source_path, tmp_path)
                if overwrite:
                    os.replace(str(tmp_path), str(destination_path))
                else:
                    try:
                        os.link(str(tmp_path), str(destination_path))
                    except FileExistsError:
                        return json_response(
                            False,
                            f"Destination already exists: {destination}",
                            code="destination_exists",
                            details={"destination": destination},
                        )
                    try:
                        os.unlink(str(tmp_path))
                    except OSError:
                        try:
                            os.unlink(str(destination_path))
                        except OSError:
                            pass
                        raise
            except OSError as exc:
                if exc.errno == errno.EEXIST:
                    return json_response(
                        False,
                        f"Destination already exists: {destination}",
                        code="destination_exists",
                        details={"destination": destination},
                    )
                return json_response(
                    False,
                    f"Failed to copy path: {exc}",
                    code="copy_failed",
                    details={"source": source, "destination": destination},
                )
            finally:
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except OSError:
                    pass
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
        decision=approval_decision if approval_decision is not None else rule_decision,
        decision_in_details=approval_decision is not None or rule_decision is not None,
    )
