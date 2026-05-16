"""MCP tool implementations: run_shell, start_process, and process management."""

from __future__ import annotations

import re
import subprocess
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

import os as _os

from claude_bridge.ai_evaluator import evaluate_tool_with_ai
from claude_bridge.config import (
    active_role,
    active_user,
    approval_mode,
    current_config,
    should_auto_approve_risk,
)
from claude_bridge.guard_policy import (
    DecisionAction,
    DecisionSource,
    PolicyDecision,
    ToolRequestContext,
)
from claude_bridge.rules_engine import evaluate_runtime_policy_chain
from claude_bridge.tool_utils import _mask_secrets, json_response, require_approval, PermissionCard

from claude_bridge._process_session import (
    _ProcessSession,
    _get_process_session,
    _process_session_capacity,
    _PROCESS_SESSIONS,
    _PROCESS_SESSIONS_LOCK,
    _register_process_session,
    _start_stream_threads,
)
from claude_bridge._shell_analysis import (
    _is_long_running_command,
    _shell_analysis_decision,
    _truncate_output,
    analyze_shell_command,
)
from claude_bridge._shell_constants import (
    _LONG_RUNNING_TIMEOUT,
    _MAX_INTERACTIVE_INPUT_CHARS,
    _MAX_INTERACTIVE_TOTAL_INPUT,
    _MAX_PROCESS_OUTPUT_CHARS,
    _MAX_SHELL_OUTPUT_CHARS,
)

_MAX_INTERACT_INPUT_CHARS = 4000

_ENV_BLOCK_KEYS = frozenset(
    {
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AZURE_CLIENT_ID",
        "AZURE_CLIENT_SECRET",
        "AZURE_TENANT_ID",
        "AZURE_SUBSCRIPTION_ID",
        "GITHUB_TOKEN",
        "GITHUB_PERSONAL_ACCESS_TOKEN",
        "GITLAB_TOKEN",
        "GITLAB_API_TOKEN",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "HEROKU_API_KEY",
        "HEROKU_API_TOKEN",
        "HEROKU_PASSWORD",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
        "CLAUDE_BRIDGE_AI_EVALUATOR_API_KEY",
        "DATABASE_URL",
        "PGPASSWORD",
        "STRIPE_SECRET_KEY",
        "TWILIO_AUTH_TOKEN",
        "SENDGRID_API_KEY",
        "SLACK_BOT_TOKEN",
        "PRIVATE_KEY",
        "SSH_PRIVATE_KEY",
        "PYTHONSTARTUP",
        "PYTHONOPT",
        "PYTHONPATH",
        "BASH_ENV",
        "ENV",
        "PROMPT_COMMAND",
        "NODE_OPTIONS",
        "NODE_PATH",
        "PERL5OPT",
        "PERL5LIB",
        "RUBYOPT",
        "RUBYLIB",
        "GEM_PATH",
        "GEM_HOME",
        "DOTNET_CLI_HOME",
        "KUBECONFIG",
        "DOCKER_CONFIG",
        "DOCKER_HOST",
        "PATH",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
        "DYLD_INSERT_LIBRARIES",
        "DYLD_LIBRARY_PATH",
        "TMPDIR",
        "TMP",
        "TEMP",
    }
)

_PATH_PATTERN = re.compile(
    r"(?:/[\w\.\-\_]+)+|~/[\w\.\-\_]+(?:/[\w\.\-\_]+)*|[\w\.\-\_]+/[\w\.\-\_]+"
)


def _extract_files_from_command(command: str) -> list[str]:
    """Extract potential file paths from a shell command string."""
    matches = _PATH_PATTERN.findall(command)
    return [m for m in matches if not m.startswith("-")]


def _sanitized_env() -> dict[str, str]:
    env = dict(_os.environ)
    path = env.get("PATH", "")
    for key in _ENV_BLOCK_KEYS:
        env.pop(key, None)
    sanitized_path = _sanitized_path(path)
    if sanitized_path:
        env["PATH"] = sanitized_path
    return env


def _sanitized_path(path_value: str) -> str:
    parts: list[str] = []
    for raw_part in path_value.split(_os.pathsep):
        if not raw_part or raw_part == ".":
            continue
        path = Path(raw_part).expanduser()
        if not path.is_absolute():
            continue
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if not resolved.is_dir():
            continue
        value = str(resolved)
        if value not in parts:
            parts.append(value)
    if not parts:
        return _os.defpath
    return _os.pathsep.join(parts)


async def run_shell(
    command: str,
    *,
    request_approval: Callable[[str, dict[str, Any]], Awaitable[bool]],
    project_dir: Callable[[], Path],
    shell_timeout: Callable[[], int],
    ai_provider: Any = None,
) -> str:
    analysis = analyze_shell_command(command)
    if not analysis["ok"]:
        decision = _shell_analysis_decision(
            analysis,
            action=DecisionAction.DENY,
            source=DecisionSource.BUILTIN_GUARD,
            reason=analysis["message"],
        )
        return json_response(
            False,
            analysis["message"],
            code=analysis["code"],
            details=analysis["details"],
            decision=decision,
            decision_in_details=True,
        )

    stripped = command.strip()
    approval_decision: PolicyDecision | None = None
    policy_context = ToolRequestContext(
        tool_name="run_shell",
        params={"command": stripped},
        project_dir=str(project_dir()),
        role=active_role(),
        user=active_user(),
    )
    rule_decision = evaluate_runtime_policy_chain(policy_context)
    if rule_decision is not None and rule_decision.action == DecisionAction.DENY:
        return json_response(
            False,
            rule_decision.reason,
            code="policy_denied",
            details={
                "command": _mask_secrets(command),
                "risk_level": analysis["details"]["risk_level"],
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            decision=rule_decision,
            decision_in_details=True,
        )
    if rule_decision is not None and rule_decision.action == DecisionAction.ASK:
        rejection = await require_approval(
            "run_shell",
            {"command": stripped},
            rejection_message=rule_decision.reason,
            rejection_details={
                "command": _mask_secrets(command),
                "risk_level": analysis["details"]["risk_level"],
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            request_approval_fn=request_approval,
            card=PermissionCard(
                agent="shell_agent",
                action="Run shell command",
                reason=rule_decision.reason,
                risk={"low": 20, "medium": 50, "high": 70, "critical": 90}.get(
                    rule_decision.risk_level.value, 50
                ),
                files=_extract_files_from_command(stripped),
                tool_name="run_shell",
                params={"command": _mask_secrets(stripped)},
            ),
            allow_auto_approve=False,
        )
        if rejection is not None:
            return json_response(
                False,
                rule_decision.reason,
                code="approval_rejected",
                details={
                    "command": _mask_secrets(command),
                    "risk_level": analysis["details"]["risk_level"],
                    "risk_reasons": analysis["details"]["risk_reasons"],
                },
                decision=rule_decision,
                decision_in_details=True,
            )
        approval_decision = _shell_analysis_decision(
            analysis,
            action=DecisionAction.ALLOW,
            source=DecisionSource.APPROVAL,
            reason="Shell command approved after policy ASK decision",
        )

    config = current_config()
    ai_enabled = bool(config.get("ai_evaluator_enabled", False))
    ai_timeout = int(config.get("ai_evaluator_timeout", 5))
    ai_fallback = str(config.get("ai_evaluator_fallback_action", "ask"))
    ai_decision = await evaluate_tool_with_ai(
        ToolRequestContext(
            tool_name="run_shell",
            params={"command": stripped},
            project_dir=str(project_dir()),
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
            details={
                "command": _mask_secrets(command),
                "risk_level": analysis["details"]["risk_level"],
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            decision=ai_decision,
            decision_in_details=True,
        )
    if ai_decision is not None and ai_decision.action == DecisionAction.ASK:
        ask_decision = _shell_analysis_decision(
            analysis,
            action=DecisionAction.ASK,
            source=DecisionSource.AI,
            reason=ai_decision.reason,
        )
        rejection = await require_approval(
            "run_shell",
            {"command": stripped},
            rejection_message=ai_decision.reason,
            rejection_details={
                "command": _mask_secrets(command),
                "risk_level": analysis["details"]["risk_level"],
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            request_approval_fn=request_approval,
            card=PermissionCard(
                agent="shell_agent",
                action="Run shell command",
                reason=ai_decision.reason,
                risk={"low": 20, "medium": 50, "high": 70, "critical": 90}.get(
                    analysis["details"].get("risk_level", "low"), 50
                ),
                files=_extract_files_from_command(stripped),
                tool_name="run_shell",
                params={"command": _mask_secrets(stripped)},
            ),
            allow_auto_approve=False,
        )
        if rejection is not None:
            return json_response(
                False,
                ai_decision.reason,
                code="approval_rejected",
                details={
                    "command": _mask_secrets(command),
                    "risk_level": analysis["details"]["risk_level"],
                    "risk_reasons": analysis["details"]["risk_reasons"],
                },
                decision=ask_decision,
                decision_in_details=True,
            )
        approval_decision = _shell_analysis_decision(
            analysis,
            action=DecisionAction.ALLOW,
            source=DecisionSource.APPROVAL,
            reason="Shell command approved after AI ASK decision",
        )
    analysis_risk = analysis["details"].get("risk_level", "low")
    auto_approve_on, client_managed = approval_mode()
    if auto_approve_on and not should_auto_approve_risk(analysis_risk):
        ask_decision = _shell_analysis_decision(
            analysis,
            action=DecisionAction.ASK,
            source=DecisionSource.BUILTIN_GUARD,
            reason=f"Shell command risk level {analysis_risk} exceeds auto_approve_risk_level; "
            "approval required",
        )
        return json_response(
            False,
            f"Shell command requires approval (risk: {analysis_risk})",
            code="approval_required",
            details={
                "command": _mask_secrets(command),
                "risk_level": analysis_risk,
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            decision=ask_decision,
            decision_in_details=True,
        )
    risk_score = int(analysis["details"].get("risk_score", 50))
    risk_category = str(analysis["details"].get("risk_category", "Medium"))

    if approval_decision is not None:
        allow_decision = approval_decision
    elif rule_decision is not None and rule_decision.action == DecisionAction.ALLOW:
        allow_decision = rule_decision
    else:
        shell_card = PermissionCard(
            agent="shell_agent",
            action="Run shell command",
            reason=f"Shell command requires approval (risk: {analysis_risk})",
            risk=risk_score,
            files=_extract_files_from_command(stripped),
            tool_name="run_shell",
            params={"command": _mask_secrets(stripped)},
        )
        rejection = await require_approval(
            "run_shell",
            {"command": stripped},
            rejection_message="Shell command rejected by user",
            rejection_details={
                "command": _mask_secrets(command),
                "risk_level": analysis["details"]["risk_level"],
                "risk_score": risk_score,
                "risk_category": risk_category,
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            request_approval_fn=request_approval,
            card=shell_card,
        )
        if rejection is not None:
            ask_decision = _shell_analysis_decision(
                analysis,
                action=DecisionAction.ASK,
                source=DecisionSource.APPROVAL,
                reason="Shell command requires approval",
            )
            return json_response(
                False,
                "Shell command rejected by user",
                code="approval_rejected",
                details={
                    "command": _mask_secrets(command),
                    "risk_level": analysis["details"]["risk_level"],
                    "risk_score": risk_score,
                    "risk_category": risk_category,
                    "risk_reasons": analysis["details"]["risk_reasons"],
                },
                decision=ask_decision,
                decision_in_details=True,
            )

        allow_decision = _shell_analysis_decision(
            analysis,
            action=DecisionAction.ALLOW,
            source=DecisionSource.APPROVAL,
            reason="Shell command approved for execution",
        )

    cwd_snapshot = project_dir()
    timeout_seconds = shell_timeout()
    if _is_long_running_command(analysis["details"]["argv"]):
        timeout_seconds = max(timeout_seconds, _LONG_RUNNING_TIMEOUT)
    try:
        result = subprocess.run(
            analysis["details"]["argv"],
            shell=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd_snapshot,
            timeout=timeout_seconds,
            env=_sanitized_env(),
        )
    except subprocess.TimeoutExpired:
        return json_response(
            False,
            f"Shell command timed out after {timeout_seconds} seconds",
            code="command_timeout",
            details={
                "command": _mask_secrets(command),
                "timeout_seconds": timeout_seconds,
                "risk_level": analysis["details"]["risk_level"],
                "risk_score": risk_score,
                "risk_category": risk_category,
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            decision=allow_decision,
            decision_in_details=True,
        )
    except OSError as exc:
        return json_response(
            False,
            f"Failed to execute shell command: {exc}",
            code="command_error",
            details={
                "command": _mask_secrets(command),
                "risk_level": analysis["details"]["risk_level"],
                "risk_score": risk_score,
                "risk_category": risk_category,
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            decision=allow_decision,
            decision_in_details=True,
        )

    stdout, stdout_truncated = _truncate_output(result.stdout)
    stderr, stderr_truncated = _truncate_output(result.stderr)
    details = {
        "command": _mask_secrets(command),
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": result.returncode,
        "risk_level": analysis["details"]["risk_level"],
        "risk_score": risk_score,
        "risk_category": risk_category,
        "risk_reasons": analysis["details"]["risk_reasons"],
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "output_char_limit": _MAX_SHELL_OUTPUT_CHARS,
    }
    if result.returncode != 0:
        detective_report = await _maybe_detective_hook(stderr, stripped)
        if detective_report is not None:
            details["detective_report"] = detective_report
        return json_response(
            False,
            "Shell command failed",
            code="command_failed",
            details=details,
            decision=allow_decision,
            decision_in_details=True,
        )

    return json_response(
        True,
        "Shell command completed successfully",
        details=details,
        decision=allow_decision,
        decision_in_details=True,
    )


async def _maybe_detective_hook(
    error_output: str,
    command: str,
) -> dict[str, Any] | None:
    """Invoke Bridge Detective if an error pattern is detected."""
    try:
        from claude_bridge.detective import BridgeDetective

        detector = BridgeDetective(error_output, command=command)
        report = await detector.investigate()
        return report.to_dict()
    except Exception:
        return None


async def start_process(
    command: str,
    *,
    request_approval: Callable[[str, dict[str, Any]], Awaitable[bool]],
    project_dir: Callable[[], Path],
    ai_provider: Any = None,
) -> str:
    analysis = analyze_shell_command(command)
    if not analysis["ok"]:
        deny_decision = _shell_analysis_decision(
            analysis,
            action=DecisionAction.DENY,
            source=DecisionSource.BUILTIN_GUARD,
            reason=analysis["message"],
        )
        return json_response(
            False,
            analysis["message"],
            code=analysis["code"],
            details=analysis["details"],
            decision=deny_decision,
            decision_in_details=True,
        )

    stripped = command.strip()
    approval_decision: PolicyDecision | None = None
    policy_context = ToolRequestContext(
        tool_name="start_process",
        params={"command": stripped},
        project_dir=str(project_dir()),
        role=active_role(),
        user=active_user(),
    )
    rule_decision = evaluate_runtime_policy_chain(policy_context)
    if rule_decision is not None and rule_decision.action == DecisionAction.DENY:
        return json_response(
            False,
            rule_decision.reason,
            code="policy_denied",
            details={
                "command": _mask_secrets(command),
                "risk_level": analysis["details"]["risk_level"],
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            decision=rule_decision,
            decision_in_details=True,
        )
    if rule_decision is not None and rule_decision.action == DecisionAction.ASK:
        rejection = await require_approval(
            "start_process",
            {"command": stripped},
            rejection_message=rule_decision.reason,
            rejection_details={
                "command": _mask_secrets(command),
                "risk_level": analysis["details"]["risk_level"],
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            request_approval_fn=request_approval,
            card=PermissionCard(
                agent="process_agent",
                action="Start background process",
                reason=rule_decision.reason,
                risk={"low": 20, "medium": 50, "high": 70, "critical": 90}.get(
                    rule_decision.risk_level.value, 50
                ),
                files=_extract_files_from_command(stripped),
                tool_name="start_process",
                params={"command": _mask_secrets(stripped)},
            ),
            allow_auto_approve=False,
        )
        if rejection is not None:
            return json_response(
                False,
                rule_decision.reason,
                code="approval_rejected",
                details={
                    "command": _mask_secrets(command),
                    "risk_level": analysis["details"]["risk_level"],
                    "risk_reasons": analysis["details"]["risk_reasons"],
                },
                decision=rule_decision,
                decision_in_details=True,
            )
        approval_decision = _shell_analysis_decision(
            analysis,
            action=DecisionAction.ALLOW,
            source=DecisionSource.APPROVAL,
            reason="Process start approved after policy ASK decision",
        )

    config = current_config()
    ai_enabled = bool(config.get("ai_evaluator_enabled", False))
    ai_timeout = int(config.get("ai_evaluator_timeout", 5))
    ai_fallback = str(config.get("ai_evaluator_fallback_action", "ask"))
    ai_decision = await evaluate_tool_with_ai(
        ToolRequestContext(
            tool_name="start_process",
            params={"command": stripped},
            project_dir=str(project_dir()),
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
            details={
                "command": _mask_secrets(command),
                "risk_level": analysis["details"]["risk_level"],
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            decision=ai_decision,
            decision_in_details=True,
        )
    if ai_decision is not None and ai_decision.action == DecisionAction.ASK:
        rejection = await require_approval(
            "start_process",
            {"command": stripped},
            rejection_message=ai_decision.reason,
            rejection_details={
                "command": _mask_secrets(command),
                "risk_level": analysis["details"]["risk_level"],
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            request_approval_fn=request_approval,
            card=PermissionCard(
                agent="process_agent",
                action="Start background process",
                reason=ai_decision.reason,
                risk={"low": 20, "medium": 50, "high": 70, "critical": 90}.get(
                    analysis["details"].get("risk_level", "low"), 50
                ),
                files=_extract_files_from_command(stripped),
                tool_name="start_process",
                params={"command": _mask_secrets(stripped)},
            ),
            allow_auto_approve=False,
        )
        if rejection is not None:
            return json_response(
                False,
                ai_decision.reason,
                code="approval_rejected",
                details={
                    "command": _mask_secrets(command),
                    "risk_level": analysis["details"]["risk_level"],
                    "risk_reasons": analysis["details"]["risk_reasons"],
                },
                decision=ai_decision,
                decision_in_details=True,
            )
        approval_decision = _shell_analysis_decision(
            analysis,
            action=DecisionAction.ALLOW,
            source=DecisionSource.APPROVAL,
            reason="Process start approved after AI ASK decision",
        )
    analysis_risk = analysis["details"].get("risk_level", "low")
    auto_approve_on, client_managed = approval_mode()
    if analysis_risk in ("high", "critical") and auto_approve_on:
        ask_decision = _shell_analysis_decision(
            analysis,
            action=DecisionAction.ASK,
            source=DecisionSource.BUILTIN_GUARD,
            reason=f"Process risk level {analysis_risk} requires approval; "
            "auto_approve is disabled for high+ risk commands",
        )
        return json_response(
            False,
            f"Process start requires approval (risk: {analysis_risk})",
            code="approval_required",
            details={
                "command": _mask_secrets(command),
                "risk_level": analysis_risk,
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            decision=ask_decision,
            decision_in_details=True,
        )
    if approval_decision is not None:
        allow_decision = approval_decision
    elif rule_decision is not None and rule_decision.action == DecisionAction.ALLOW:
        allow_decision = rule_decision
    else:
        risk_score = {"low": 20, "medium": 50, "high": 70, "critical": 90}.get(
            analysis["details"].get("risk_level", "low"), 20
        )
        process_card = PermissionCard(
            agent="process_agent",
            action="Start background process",
            reason=f"Process start requires approval (risk: {analysis_risk})",
            risk=risk_score,
            files=_extract_files_from_command(stripped),
            tool_name="start_process",
            params={"command": _mask_secrets(stripped)},
        )
        rejection = await require_approval(
            "start_process",
            {"command": stripped},
            rejection_message="Process start rejected by user",
            rejection_details={
                "command": _mask_secrets(command),
                "risk_level": analysis["details"]["risk_level"],
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            request_approval_fn=request_approval,
            card=process_card,
        )
        if rejection is not None:
            ask_decision = _shell_analysis_decision(
                analysis,
                action=DecisionAction.ASK,
                source=DecisionSource.APPROVAL,
                reason="Process start requires approval",
            )
            return json_response(
                False,
                "Process start rejected by user",
                code="approval_rejected",
                details={
                    "command": _mask_secrets(command),
                    "risk_level": analysis["details"]["risk_level"],
                    "risk_reasons": analysis["details"]["risk_reasons"],
                },
                decision=ask_decision,
                decision_in_details=True,
            )

        allow_decision = _shell_analysis_decision(
            analysis,
            action=DecisionAction.ALLOW,
            source=DecisionSource.APPROVAL,
            reason="Process start approved",
        )

    capacity = _process_session_capacity()
    if not capacity["available"]:
        return json_response(
            False,
            "Process session limit reached; stop an existing process before starting another.",
            code="process_session_limit_exceeded",
            details=capacity,
            decision=allow_decision,
            decision_in_details=True,
        )

    cwd_snapshot = project_dir()
    try:
        process = subprocess.Popen(
            analysis["details"]["argv"],
            shell=False,
            cwd=cwd_snapshot,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=_sanitized_env(),
        )
    except OSError as exc:
        return json_response(
            False,
            f"Failed to start process: {exc}",
            code="command_error",
            details={
                "command": _mask_secrets(command),
                "risk_level": analysis["details"]["risk_level"],
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            decision=allow_decision,
            decision_in_details=True,
        )

    session_id = uuid.uuid4().hex
    session = _ProcessSession(
        session_id=session_id,
        command=command,
        argv=list(analysis["details"]["argv"]),
        cwd=cwd_snapshot,
        process=process,
        risk_level=str(analysis["details"]["risk_level"]),
        risk_reasons=list(analysis["details"]["risk_reasons"]),
    )
    if not _register_process_session(session):
        _terminate_unregistered_process(process)
        return json_response(
            False,
            "Process session limit reached; stop an existing process before starting another.",
            code="process_session_limit_exceeded",
            details=_process_session_capacity(),
            decision=allow_decision,
            decision_in_details=True,
        )
    _start_stream_threads(session)
    return json_response(
        True,
        "Process started successfully",
        details=session.snapshot(),
        decision=allow_decision,
        decision_in_details=True,
    )


def _terminate_unregistered_process(process: subprocess.Popen[str]) -> None:
    try:
        process.terminate()
        process.wait(timeout=1)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
        except OSError:
            pass
    for stream in (process.stdout, process.stderr, process.stdin):
        if stream is None:
            continue
        try:
            stream.close()
        except OSError:
            pass


async def read_process_output(session_id: str, offset: int = 0, limit: int = 4000) -> str:
    if offset < 0:
        return json_response(
            False,
            "Offset must be 0 or greater",
            code="invalid_offset",
            details={"offset": offset},
        )
    if limit < 1 or limit > _MAX_PROCESS_OUTPUT_CHARS:
        return json_response(
            False,
            f"Limit must be between 1 and {_MAX_PROCESS_OUTPUT_CHARS}",
            code="invalid_limit",
            details={"limit": limit, "max_limit": _MAX_PROCESS_OUTPUT_CHARS},
        )
    session = _get_process_session(session_id)
    if session is None:
        return json_response(
            False,
            f"Process session not found: {session_id}",
            code="process_session_not_found",
            details={"session_id": session_id},
        )
    session.refresh_status()
    with session.lock:
        total_output_chars = len(session.output)
        output = session.output[offset : offset + limit]
        has_more = offset + limit < total_output_chars
        details = {
            "session_id": session.session_id,
            "command": session.command,
            "pid": session.process.pid,
            "running": session.exit_code is None,
            "exit_code": session.exit_code,
            "offset": offset,
            "limit": limit,
            "has_more": has_more,
            "next_offset": offset + len(output) if has_more else -1,
            "total_output_chars": total_output_chars,
            "output": output,
            "output_complete": session.exit_code is not None and not has_more,
            "input_chars": session.input_chars,
            "input_events": session.input_events,
            "stdin_closed": session.stdin_closed,
            "stdout_closed": session.stdout_done,
            "stderr_closed": session.stderr_done,
            "last_input_at": session.last_input_at,
            "last_output_at": session.last_output_at,
        }
    return json_response(True, "Process output loaded", details=details)


async def list_process_sessions() -> str:
    with _PROCESS_SESSIONS_LOCK:
        sessions = list(_PROCESS_SESSIONS.values())
    session_payloads = [session.snapshot() for session in sessions]
    session_payloads.sort(key=lambda item: float(item["started_at"]), reverse=True)
    return json_response(
        True,
        "Process sessions loaded",
        details={"sessions": session_payloads, "count": len(session_payloads)},
    )


async def kill_process(
    session_id: str,
    force: bool = False,
    *,
    request_approval: Callable[[str, dict[str, Any]], Awaitable[bool]],
) -> str:
    session = _get_process_session(session_id)
    if session is None:
        return json_response(
            False,
            f"Process session not found: {session_id}",
            code="process_session_not_found",
            details={"session_id": session_id},
        )

    risk_score = 60 if force else 40
    kill_card = PermissionCard(
        agent="process_agent",
        action="Terminate process",
        reason=f"Process termination requires approval (force={force})",
        risk=risk_score,
        files=_extract_files_from_command(session.command),
        tool_name="kill_process",
        params={
            "session_id": session_id,
            "command": _mask_secrets(session.command),
            "force": force,
        },
    )
    rejection = await require_approval(
        "kill_process",
        {"session_id": session_id, "command": session.command, "force": force},
        rejection_message="Process termination rejected by user",
        rejection_details={"session_id": session_id, "command": session.command, "force": force},
        request_approval_fn=request_approval,
        card=kill_card,
    )
    if rejection is not None:
        return rejection

    if session.process.poll() is None:
        try:
            if force:
                session.process.kill()
            else:
                session.process.terminate()
            session.process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            try:
                session.process.kill()
                session.process.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired) as exc:
                return json_response(
                    False,
                    f"Failed to terminate process: {exc}",
                    code="process_termination_failed",
                    details={"session_id": session_id, "command": session.command},
                )

    session.refresh_status()
    return json_response(True, "Process terminated", details=session.snapshot())


async def interact_with_process(
    session_id: str,
    input: str,
    close_stdin: bool = False,
    *,
    request_approval: Callable[[str, dict[str, Any]], Awaitable[bool]],
) -> str:
    if len(input) > _MAX_INTERACT_INPUT_CHARS:
        return json_response(
            False,
            f"Input exceeds maximum length of {_MAX_INTERACT_INPUT_CHARS} characters",
            code="input_too_long",
            details={"length": len(input), "max": _MAX_INTERACT_INPUT_CHARS},
        )
    session = _get_process_session(session_id)
    if session is None:
        return json_response(
            False,
            f"Process session not found: {session_id}",
            code="process_session_not_found",
            details={"session_id": session_id},
        )
    session.refresh_status()
    if session.exit_code is not None:
        return json_response(
            False,
            f"Process already exited with code {session.exit_code}",
            code="process_already_exited",
            details={"session_id": session_id, "exit_code": session.exit_code},
        )

    risk_score = 45 if close_stdin else 30
    interact_card = PermissionCard(
        agent="process_agent",
        action="Send input to process",
        reason=f"Process interaction requires approval (close_stdin={close_stdin})",
        risk=risk_score,
        files=_extract_files_from_command(session.command),
        tool_name="interact_with_process",
        params={
            "session_id": session_id,
            "command": _mask_secrets(session.command),
            "input_length": len(input),
            "close_stdin": close_stdin,
        },
    )
    rejection = await require_approval(
        "interact_with_process",
        {
            "session_id": session_id,
            "command": session.command,
            "input_length": len(input),
            "close_stdin": close_stdin,
        },
        rejection_message="Process input rejected by user",
        rejection_details={
            "session_id": session_id,
            "command": session.command,
            "input_length": len(input),
            "close_stdin": close_stdin,
        },
        request_approval_fn=request_approval,
        card=interact_card,
    )
    if rejection is not None:
        return rejection

    stdin_stream = session.process.stdin
    if stdin_stream is None:
        return json_response(
            False,
            "Process stdin is not available",
            code="stdin_unavailable",
            details={"session_id": session_id},
        )
    if stdin_stream.closed or session.stdin_closed:
        return json_response(
            False,
            "Process stdin is closed",
            code="stdin_closed",
            details={"session_id": session_id},
        )
    try:
        if input:
            with session.lock:
                stdin_stream.write(input + "\n")
                stdin_stream.flush()
                session.record_input(input)
        if close_stdin:
            with session.lock:
                stdin_stream.close()
                session.mark_stdin_closed()
    except (OSError, BrokenPipeError) as exc:
        return json_response(
            False,
            f"Failed to write to process stdin: {exc}",
            code="stdin_write_failed",
            details={"session_id": session_id, "error": str(exc)},
        )

    return json_response(
        True,
        "Process interaction completed",
        details={
            "session_id": session_id,
            "command": session.command,
            "input_length": len(input),
            "close_stdin": close_stdin,
            "pid": session.process.pid,
            "input_chars": session.input_chars,
            "input_events": session.input_events,
            "stdin_closed": session.stdin_closed,
            "last_input_at": session.last_input_at,
        },
    )


async def interactive_shell(
    command: str,
    *,
    request_approval: Callable[[str, dict[str, Any]], Awaitable[bool]],
    project_dir: Callable[[], Path],
    ai_provider: Any = None,
) -> str:
    analysis = analyze_shell_command(command)
    if not analysis["ok"]:
        if analysis["code"] != "interactive_command_unsupported":
            deny_decision = _shell_analysis_decision(
                analysis,
                action=DecisionAction.DENY,
                source=DecisionSource.BUILTIN_GUARD,
                reason=analysis["message"],
            )
            return json_response(
                False,
                analysis["message"],
                code=analysis["code"],
                details=analysis["details"],
                decision=deny_decision,
                decision_in_details=True,
            )
    elif not analysis["details"].get("is_interactive", False):
        return json_response(
            False,
            "Command is not an interactive shell; use start_process for background processes",
            code="not_interactive_command",
            details={"command": command},
        )

    stripped = command.strip()
    approval_decision: PolicyDecision | None = None
    policy_context = ToolRequestContext(
        tool_name="interactive_shell",
        params={"command": stripped},
        project_dir=str(project_dir()),
        role=active_role(),
        user=active_user(),
    )
    rule_decision = evaluate_runtime_policy_chain(policy_context)
    if rule_decision is not None and rule_decision.action == DecisionAction.DENY:
        return json_response(
            False,
            rule_decision.reason,
            code="policy_denied",
            details={
                "command": _mask_secrets(command),
                "risk_level": analysis["details"]["risk_level"],
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            decision=rule_decision,
            decision_in_details=True,
        )
    if rule_decision is not None and rule_decision.action == DecisionAction.ASK:
        rejection = await require_approval(
            "interactive_shell",
            {"command": stripped},
            rejection_message=rule_decision.reason,
            rejection_details={
                "command": _mask_secrets(command),
                "risk_level": analysis["details"]["risk_level"],
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            request_approval_fn=request_approval,
            card=PermissionCard(
                agent="shell_agent",
                action="Start interactive shell",
                reason=rule_decision.reason,
                risk={"low": 20, "medium": 50, "high": 70, "critical": 90}.get(
                    rule_decision.risk_level.value, 50
                ),
                files=_extract_files_from_command(stripped),
                tool_name="interactive_shell",
                params={"command": _mask_secrets(stripped)},
            ),
            allow_auto_approve=False,
        )
        if rejection is not None:
            return json_response(
                False,
                rule_decision.reason,
                code="approval_rejected",
                details={
                    "command": _mask_secrets(command),
                    "risk_level": analysis["details"]["risk_level"],
                    "risk_reasons": analysis["details"]["risk_reasons"],
                },
                decision=rule_decision,
                decision_in_details=True,
            )
        approval_decision = _shell_analysis_decision(
            analysis,
            action=DecisionAction.ALLOW,
            source=DecisionSource.APPROVAL,
            reason="Interactive shell approved after policy ASK decision",
        )

    config = current_config()
    ai_enabled = bool(config.get("ai_evaluator_enabled", False))
    ai_timeout = int(config.get("ai_evaluator_timeout", 5))
    ai_fallback = str(config.get("ai_evaluator_fallback_action", "ask"))
    ai_decision = await evaluate_tool_with_ai(
        ToolRequestContext(
            tool_name="interactive_shell",
            params={"command": stripped},
            project_dir=str(project_dir()),
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
            details={
                "command": _mask_secrets(command),
                "risk_level": analysis["details"]["risk_level"],
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            decision=ai_decision,
            decision_in_details=True,
        )
    if ai_decision is not None and ai_decision.action == DecisionAction.ASK:
        rejection = await require_approval(
            "interactive_shell",
            {"command": stripped},
            rejection_message=ai_decision.reason,
            rejection_details={
                "command": _mask_secrets(command),
                "risk_level": analysis["details"]["risk_level"],
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            request_approval_fn=request_approval,
            card=PermissionCard(
                agent="shell_agent",
                action="Start interactive shell",
                reason=ai_decision.reason,
                risk={"low": 20, "medium": 50, "high": 70, "critical": 90}.get(
                    analysis["details"].get("risk_level", "low"), 50
                ),
                files=_extract_files_from_command(stripped),
                tool_name="interactive_shell",
                params={"command": _mask_secrets(stripped)},
            ),
            allow_auto_approve=False,
        )
        if rejection is not None:
            return json_response(
                False,
                ai_decision.reason,
                code="approval_rejected",
                details={
                    "command": _mask_secrets(command),
                    "risk_level": analysis["details"]["risk_level"],
                    "risk_reasons": analysis["details"]["risk_reasons"],
                },
                decision=ai_decision,
                decision_in_details=True,
            )
        approval_decision = _shell_analysis_decision(
            analysis,
            action=DecisionAction.ALLOW,
            source=DecisionSource.APPROVAL,
            reason="Interactive shell approved after AI ASK decision",
        )

    analysis_risk = analysis["details"].get("risk_level", "low")
    auto_approve_on, client_managed = approval_mode()
    if analysis_risk in ("high", "critical") and auto_approve_on:
        ask_decision = _shell_analysis_decision(
            analysis,
            action=DecisionAction.ASK,
            source=DecisionSource.BUILTIN_GUARD,
            reason=f"Interactive shell risk level {analysis_risk} requires approval; "
            "auto_approve is disabled for high+ risk commands",
        )
        return json_response(
            False,
            f"Interactive shell requires approval (risk: {analysis_risk})",
            code="approval_required",
            details={
                "command": _mask_secrets(command),
                "risk_level": analysis_risk,
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            decision=ask_decision,
            decision_in_details=True,
        )

    capacity = _process_session_capacity()
    if not capacity["available"]:
        return json_response(
            False,
            "Process session limit reached; stop an existing process before starting another.",
            code="process_session_limit_exceeded",
            details=capacity,
            decision=approval_decision,
            decision_in_details=True,
        )

    cwd_snapshot = project_dir()
    try:
        process = subprocess.Popen(
            analysis["details"]["argv"],
            shell=False,
            cwd=cwd_snapshot,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=_sanitized_env(),
        )
    except OSError as exc:
        return json_response(
            False,
            f"Failed to start interactive shell: {exc}",
            code="command_error",
            details={
                "command": _mask_secrets(command),
                "risk_level": analysis["details"]["risk_level"],
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            decision=approval_decision,
            decision_in_details=True,
        )

    session_id = uuid.uuid4().hex
    session = _ProcessSession(
        session_id=session_id,
        command=command,
        argv=list(analysis["details"]["argv"]),
        cwd=cwd_snapshot,
        process=process,
        risk_level=str(analysis["details"]["risk_level"]),
        risk_reasons=list(analysis["details"]["risk_reasons"]),
    )
    if not _register_process_session(session):
        _terminate_unregistered_process(process)
        return json_response(
            False,
            "Process session limit reached; stop an existing process before starting another.",
            code="process_session_limit_exceeded",
            details=_process_session_capacity(),
            decision=approval_decision,
            decision_in_details=True,
        )
    _start_stream_threads(session)
    return json_response(
        True,
        "Interactive shell started",
        details=session.snapshot(),
        decision=approval_decision,
        decision_in_details=True,
    )


async def send_to_process(
    session_id: str,
    input: str,
    *,
    request_approval: Callable[[str, dict[str, Any]], Awaitable[bool]],
) -> str:
    if len(input) > _MAX_INTERACTIVE_INPUT_CHARS:
        return json_response(
            False,
            f"Input exceeds maximum length of {_MAX_INTERACTIVE_INPUT_CHARS} characters per call",
            code="input_too_long",
            details={"length": len(input), "max": _MAX_INTERACTIVE_INPUT_CHARS},
        )
    session = _get_process_session(session_id)
    if session is None:
        return json_response(
            False,
            f"Process session not found: {session_id}",
            code="process_session_not_found",
            details={"session_id": session_id},
        )
    session.refresh_status()
    if session.exit_code is not None:
        return json_response(
            False,
            f"Process already exited with code {session.exit_code}",
            code="process_already_exited",
            details={"session_id": session_id, "exit_code": session.exit_code},
        )
    total_input = session.input_chars + len(input)
    if total_input > _MAX_INTERACTIVE_TOTAL_INPUT:
        return json_response(
            False,
            f"Total input would exceed {_MAX_INTERACTIVE_TOTAL_INPUT} "
            f"character limit for this session",
            code="session_input_limit_exceeded",
            details={
                "session_id": session_id,
                "current_input_chars": session.input_chars,
                "this_input_length": len(input),
                "max_total": _MAX_INTERACTIVE_TOTAL_INPUT,
            },
        )

    risk_score = 30
    interact_card = PermissionCard(
        agent="process_agent",
        action="Send input to process",
        reason="Process interaction requires approval",
        risk=risk_score,
        files=_extract_files_from_command(session.command),
        tool_name="send_to_process",
        params={
            "session_id": session_id,
            "command": _mask_secrets(session.command),
            "input_length": len(input),
        },
    )
    rejection = await require_approval(
        "send_to_process",
        {
            "session_id": session_id,
            "command": session.command,
            "input_length": len(input),
        },
        rejection_message="Process input rejected by user",
        rejection_details={
            "session_id": session_id,
            "command": session.command,
            "input_length": len(input),
        },
        request_approval_fn=request_approval,
        card=interact_card,
    )
    if rejection is not None:
        return rejection

    stdin_stream = session.process.stdin
    if stdin_stream is None:
        return json_response(
            False,
            "Process stdin is not available",
            code="stdin_unavailable",
            details={"session_id": session_id},
        )
    if stdin_stream.closed or session.stdin_closed:
        return json_response(
            False,
            "Process stdin is closed",
            code="stdin_closed",
            details={"session_id": session_id},
        )
    try:
        with session.lock:
            stdin_stream.write(input)
            stdin_stream.flush()
            session.record_input(input)
    except (OSError, BrokenPipeError) as exc:
        return json_response(
            False,
            f"Failed to write to process stdin: {exc}",
            code="stdin_write_failed",
            details={"session_id": session_id, "error": str(exc)},
        )

    return json_response(
        True,
        "Input sent to process",
        details={
            "session_id": session_id,
            "command": session.command,
            "input_length": len(input),
            "pid": session.process.pid,
            "input_chars": session.input_chars,
            "input_events": session.input_events,
            "stdin_closed": session.stdin_closed,
            "last_input_at": session.last_input_at,
        },
    )


async def get_process_status(session_id: str) -> str:
    session = _get_process_session(session_id)
    if session is None:
        return json_response(
            False,
            f"Process session not found: {session_id}",
            code="process_session_not_found",
            details={"session_id": session_id},
        )
    session.refresh_status()
    return json_response(
        True,
        "Process status retrieved",
        details=session.snapshot(),
    )
