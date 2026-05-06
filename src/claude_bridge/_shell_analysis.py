"""Shell command analysis and risk assessment."""

from __future__ import annotations

import shlex
from typing import Any

from claude_bridge._shell_constants import (
    _DESTRUCTIVE_GIT_SUBCOMMANDS,
    _INTERACTIVE_COMMANDS,
    _LONG_RUNNING_COMMANDS,
    _MAX_SHELL_OUTPUT_CHARS,
)
from claude_bridge._shell_safety import (
    _command_basename,
    _interactive_target,
    _tokens_after_env,
    blocked_command_reason,
)
from claude_bridge.guard_policy import (
    DecisionAction,
    DecisionSource,
    PolicyDecision,
    RiskLevel,
    make_policy_decision,
)


def is_interactive_command(command: str) -> bool:
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    if not tokens:
        return False
    head = _interactive_target(tokens)
    if head is None:
        return False
    if head in {"python", "python3"}:
        executable_index = 0
        if _command_basename(tokens[0]) == "env":
            for index, token in enumerate(tokens[1:], start=1):
                if "=" in token:
                    continue
                if token.startswith("-"):
                    continue
                executable_index = index
                break
        if any(tok == "-i" for tok in tokens[executable_index + 1 :]):
            return True
        return len(tokens) == executable_index + 1
    return head in _INTERACTIVE_COMMANDS


def _is_long_running_command(tokens: list[str]) -> bool:
    command_tokens = _tokens_after_env(tokens)
    if not command_tokens:
        return False
    head = _command_basename(command_tokens[0])
    if head in _LONG_RUNNING_COMMANDS:
        return True
    if len(command_tokens) >= 2:
        sub = command_tokens[1].lower()
        if f"{head} {sub}" in _LONG_RUNNING_COMMANDS:
            return True
    return False


def _truncate_output(value: str) -> tuple[str, bool]:
    if len(value) <= _MAX_SHELL_OUTPUT_CHARS:
        return value, False
    clipped = value[:_MAX_SHELL_OUTPUT_CHARS]
    return (
        clipped + f"\nTRUNCATED: omitted {len(value) - _MAX_SHELL_OUTPUT_CHARS} characters; "
        "narrow the command or rerun with a more specific target.",
        True,
    )


def _policy_risk_from_shell_risk(risk_level: str) -> RiskLevel:
    if risk_level == "low":
        return RiskLevel.LOW
    if risk_level == "medium":
        return RiskLevel.MEDIUM
    if risk_level == "high":
        return RiskLevel.HIGH
    return RiskLevel.CRITICAL


def analyze_shell_command(command: str) -> dict[str, Any]:
    stripped = command.strip()
    if not stripped:
        empty_decision = make_policy_decision(
            DecisionAction.DENY,
            DecisionSource.BUILTIN_GUARD,
            RiskLevel.LOW,
            "Shell command cannot be empty",
            ["empty command string"],
            {"tool": "analyze_shell_command"},
        )
        return {
            "ok": False,
            "code": "empty_command",
            "message": "Shell command cannot be empty",
            "details": {
                "command": command,
                "policy_decision": empty_decision.to_dict(),
            },
        }

    try:
        tokens = shlex.split(stripped)
    except ValueError as exc:
        parse_error_decision = make_policy_decision(
            DecisionAction.DENY,
            DecisionSource.BUILTIN_GUARD,
            RiskLevel.LOW,
            f"Failed to parse shell command: {exc}",
            ["unbalanced quotes or shell parse error"],
            {"tool": "analyze_shell_command"},
        )
        return {
            "ok": False,
            "code": "command_parse_error",
            "message": f"Failed to parse shell command: {exc}",
            "details": {
                "command": command,
                "policy_decision": parse_error_decision.to_dict(),
            },
        }
    if not tokens:
        empty_decision = make_policy_decision(
            DecisionAction.DENY,
            DecisionSource.BUILTIN_GUARD,
            RiskLevel.LOW,
            "Shell command cannot be empty",
            ["empty command string"],
            {"tool": "analyze_shell_command"},
        )
        return {
            "ok": False,
            "code": "empty_command",
            "message": "Shell command cannot be empty",
            "details": {
                "command": command,
                "policy_decision": empty_decision.to_dict(),
            },
        }

    blocked_pattern = blocked_command_reason(stripped, tokens)
    if blocked_pattern is not None:
        blocked_decision = make_policy_decision(
            DecisionAction.DENY,
            DecisionSource.BUILTIN_GUARD,
            RiskLevel.CRITICAL,
            f"Command blocked for safety: contains '{blocked_pattern}'",
            [f"matched blocked pattern: {blocked_pattern}"],
            {"tool": "analyze_shell_command", "blocked_pattern": blocked_pattern},
        )
        return {
            "ok": False,
            "code": "blocked_command",
            "message": f"Command blocked for safety: contains '{blocked_pattern}'",
            "details": {
                "command": command,
                "blocked_pattern": blocked_pattern,
                "risk_level": "blocked",
                "risk_reasons": [f"matched blocked pattern: {blocked_pattern}"],
                "requires_confirmation": False,
                "policy_decision": blocked_decision.to_dict(),
            },
        }

    if is_interactive_command(stripped):
        interactive_decision = make_policy_decision(
            DecisionAction.DENY,
            DecisionSource.BUILTIN_GUARD,
            RiskLevel.HIGH,
            "Interactive commands are not supported",
            ["interactive commands are unsupported in MCP stdio mode"],
            {"tool": "analyze_shell_command"},
        )
        return {
            "ok": False,
            "code": "interactive_command_unsupported",
            "message": "Interactive commands are not supported",
            "details": {
                "command": command,
                "risk_level": "high",
                "risk_reasons": ["interactive commands are unsupported in MCP stdio mode"],
                "requires_confirmation": False,
                "policy_decision": interactive_decision.to_dict(),
            },
        }

    command_tokens = _tokens_after_env(tokens)
    head = _interactive_target(tokens) or tokens[0].lower()
    lower_tokens = [token.lower() for token in tokens]
    _git_sub_start = 1
    while _git_sub_start < len(lower_tokens):
        _t = lower_tokens[_git_sub_start]
        if _t in {"-c", "-C"} and _git_sub_start + 1 < len(lower_tokens):
            _git_sub_start += 2
            continue
        if _t.startswith("-"):
            _git_sub_start += 1
            continue
        break
    _git_sub = lower_tokens[_git_sub_start] if _git_sub_start < len(lower_tokens) else ""

    if (
        head in {"pytest", "ls", "cat"}
        or tokens[:3] == ["python3", "-m", "pytest"]
        or command_tokens[:3] == ["python3", "-m", "pytest"]
        or tokens[:2] == ["git", "status"]
        or tokens[:2] == ["git", "diff"]
        or tokens[:2] == ["ruff", "check"]
    ):
        risk_level = "low"
        risk_reasons = ["read-only or standard validation command"]
    elif head == "git" and _git_sub in (_DESTRUCTIVE_GIT_SUBCOMMANDS | {"push"}):
        risk_level = "high"
        risk_reasons = ["destructive git operation risk"]
    elif head in {"python", "python3", "pip", "pip3", "npm", "pnpm", "yarn", "git"}:
        risk_level = "medium"
        risk_reasons = ["can execute code or modify the workspace depending on arguments"]
    elif head in {"curl", "wget", "ssh", "scp", "rsync", "git-reset", "git-clean"}:
        risk_level = "high"
        risk_reasons = ["network, remote access, or destructive behavior risk"]
    else:
        risk_level = "medium"
        risk_reasons = ["unclassified command; treat cautiously"]

    policy_risk = _policy_risk_from_shell_risk(risk_level)
    if risk_level == "low":
        decision_action = DecisionAction.ALLOW
        decision_source = DecisionSource.DEFAULT
        requires_confirmation = False
    else:
        decision_action = DecisionAction.ASK
        decision_source = DecisionSource.BUILTIN_GUARD
        requires_confirmation = True

    analysis_decision = make_policy_decision(
        decision_action,
        decision_source,
        policy_risk,
        f"Shell command analysis: {risk_level} risk",
        risk_reasons,
        {"tool": "analyze_shell_command", "requires_confirmation": requires_confirmation},
    )

    return {
        "ok": True,
        "message": "Shell command analysis completed",
        "details": {
            "command": command,
            "normalized_command": stripped,
            "argv": tokens,
            "risk_level": risk_level,
            "risk_reasons": risk_reasons,
            "requires_confirmation": requires_confirmation,
            "policy_decision": analysis_decision.to_dict(),
        },
    }


def _shell_analysis_decision(
    analysis: dict[str, Any],
    *,
    action: DecisionAction,
    source: DecisionSource,
    reason: str,
) -> PolicyDecision:
    details = analysis.get("details", {})
    if not isinstance(details, dict):
        details = {}
    risk_level = _policy_risk_from_shell_risk(str(details.get("risk_level", "critical")))
    risk_reasons_raw = details.get("risk_reasons", [])
    risk_reasons = (
        [str(item) for item in risk_reasons_raw] if isinstance(risk_reasons_raw, list) else []
    )
    return make_policy_decision(
        action,
        source,
        risk_level,
        reason,
        risk_reasons,
        {"tool": "run_shell"},
    )
