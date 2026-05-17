"""Write-oriented file tools."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import ast
import errno
from typing import Any, Callable

from claude_bridge.ai_evaluator import evaluate_tool_with_ai
from claude_bridge.config import active_role, active_user, current_config
from claude_bridge.git_ops import git_commit as _git_commit
from claude_bridge.guard_policy import (
    DecisionAction,
    RiskLevel,
    ToolRequestContext,
    approval_allow_decision,
    approval_ask_decision,
    builtin_deny_decision,
)
from claude_bridge.rules_engine import evaluate_runtime_policy_chain
from claude_bridge.tool_utils import (
    find_secret_patterns,
    infer_project_root,
    json_response,
    path_outside_project_details,
    request_approval,
    require_approval,
    resolve_path_safe,
    safe_read_text,
    sensitive_file_blocked_details,
    sensitive_path_reason,
)

from claude_bridge.file_tools._helpers import (
    _WRITE_FILE_WARNING_LINES,
    _remember_bridge_change,
    _write_text_exact,
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
        target = resolve_path_safe(path)
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

    policy_context = ToolRequestContext(
        tool_name="write_file",
        params={
            "path": path,
            "file": path,
            "content": content,
            "overwrite": overwrite,
            "create_parents": create_parents,
        },
        project_dir=str(infer_project_root(target.parent if not target.exists() else target)),
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
            details={"path": path},
            decision=rule_decision,
            decision_in_details=True,
        )
    if rule_decision is not None and rule_decision.action == DecisionAction.ASK:
        rejection = await require_approval(
            "write_file",
            {"file": path, "reason": rule_decision.reason},
            rejection_message=rule_decision.reason,
            rejection_details={"path": path},
            allow_auto_approve=False,
        )
        if rejection is not None:
            return json_response(
                False,
                rule_decision.reason,
                code="approval_rejected",
                details={"path": path},
                decision=rule_decision,
                decision_in_details=True,
            )
        approval_decision = approval_allow_decision(
            "File write approved after policy ASK decision",
            risk_level=rule_decision.risk_level,
            risk_reasons=list(rule_decision.risk_reasons),
            metadata={"tool": "write_file", "path": path, **dict(rule_decision.metadata)},
        )

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
            details={"path": path},
            decision=ai_decision,
            decision_in_details=True,
        )
    if ai_decision is not None and ai_decision.action == DecisionAction.ASK:
        rejection = await require_approval(
            "write_file",
            {"file": path, "reason": ai_decision.reason},
            rejection_message=ai_decision.reason,
            rejection_details={"path": path},
            allow_auto_approve=False,
        )
        if rejection is not None:
            return json_response(
                False,
                ai_decision.reason,
                code="approval_rejected",
                details={"path": path},
                decision=ai_decision,
                decision_in_details=True,
            )
        approval_decision = approval_allow_decision(
            "File write approved after AI ASK decision",
            risk_level=ai_decision.risk_level,
            risk_reasons=list(ai_decision.risk_reasons),
            metadata={"tool": "write_file", "path": path, **dict(ai_decision.metadata)},
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
    if approval_decision is not None:
        allow_decision = approval_decision
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
        if exc.errno == errno.ELOOP:
            return json_response(
                False,
                f"Refusing to write to symlink: {path}",
                code="symlink_blocked",
                details={"path": path},
            )
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
        warning = "Prefer patch_file for existing files to keep changes small and reviewable."
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
