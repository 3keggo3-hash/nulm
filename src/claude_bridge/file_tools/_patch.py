"""Patch-oriented file tools."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable

from claude_bridge.ai_evaluator import evaluate_tool_with_ai
from claude_bridge.config import active_role, active_user, current_config
from claude_bridge.git_ops import git_commit as _git_commit
from claude_bridge.guard_policy import (
    DecisionAction,
    RiskLevel,
    ToolRequestContext,
    approval_allow_decision,
    builtin_deny_decision,
)
from claude_bridge.rules_engine import evaluate_runtime_policy_chain
from claude_bridge.tool_utils import (
    find_secret_patterns,
    infer_project_root,
    json_response,
    path_guard_decision,
    path_outside_project_details,
    request_approval,
    require_approval,
    resolve_path,
    resolve_path_safe,
    sensitive_file_blocked_details,
    sensitive_path_reason,
)

from claude_bridge.file_tools._helpers import (
    _build_preview_patch_result,
    _last_bridge_change_snapshot,
    _line_ending_for_content,
    _normalize_line_endings,
    _read_text_preserve_line_endings,
    _remember_bridge_change,
    _write_text_exact,
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
        target = resolve_path_safe(file)
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

    policy_context = ToolRequestContext(
        tool_name="patch_file",
        params={
            "file": file,
            "search": search,
            "replace": replace,
        },
        project_dir=str(target_project_dir),
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
            details={"path": file},
            decision=rule_decision,
            decision_in_details=True,
        )
    if rule_decision is not None and rule_decision.action == DecisionAction.ASK:
        rejection = await require_approval(
            "patch_file",
            {"file": file, "reason": rule_decision.reason},
            rejection_message=rule_decision.reason,
            rejection_details={"path": file},
            allow_auto_approve=False,
        )
        if rejection is not None:
            return json_response(
                False,
                rule_decision.reason,
                code="approval_rejected",
                details={"path": file},
                decision=rule_decision,
                decision_in_details=True,
            )
        approval_decision = approval_allow_decision(
            "Patch approved after policy ASK decision",
            risk_level=rule_decision.risk_level,
            risk_reasons=list(rule_decision.risk_reasons),
            metadata={"tool": "patch_file", "path": file, **dict(rule_decision.metadata)},
        )

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
            role=active_role(),
            user=active_user(),
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
        rejection = await require_approval(
            "patch_file",
            {"file": file, "reason": ai_decision.reason},
            rejection_message=ai_decision.reason,
            rejection_details={"path": file},
            allow_auto_approve=False,
        )
        if rejection is not None:
            return json_response(
                False,
                ai_decision.reason,
                code="approval_rejected",
                details={"path": file},
                decision=ai_decision,
                decision_in_details=True,
            )
        approval_decision = approval_allow_decision(
            "Patch approved after AI ASK decision",
            risk_level=ai_decision.risk_level,
            risk_reasons=list(ai_decision.risk_reasons),
            metadata={"tool": "patch_file", "path": file, **dict(ai_decision.metadata)},
        )

    if approval_decision is not None:
        pass
    elif rule_decision is not None and rule_decision.action == DecisionAction.ALLOW:
        pass
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
        decision=approval_decision if approval_decision is not None else rule_decision,
        decision_in_details=approval_decision is not None or rule_decision is not None,
    )


async def preview_patch(file: str, search: str, replace: str) -> str:
    try:
        target = resolve_path_safe(file)
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

    from claude_bridge.file_tools._helpers import (
        _LAST_BRIDGE_CHANGE,
        _LAST_BRIDGE_CHANGE_LOCK,
        _LAST_BRIDGE_CHANGE_VERSION,
    )

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
