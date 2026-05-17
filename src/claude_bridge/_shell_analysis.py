"""Shell command analysis and risk assessment."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import re
import shlex
from typing import Any

from claude_bridge._shell_constants import (
    _COMPOUND_CONTROL_COMMANDS,
    _COMPOUND_OPERATOR_REGEX,
    _DANGEROUS_GLOB_COMMANDS,
    _DESTRUCTIVE_GIT_SUBCOMMANDS,
    _INTERACTIVE_COMMANDS,
    _LONG_RUNNING_COMMANDS,
    _MAX_SHELL_OUTPUT_CHARS,
    _UNQUOTED_GLOB_CHARS,
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


def compute_risk_score(risk_level: str, risk_reasons: list[str]) -> int:
    """Convert risk level to 0-100 score with reason-based adjustments."""
    base_scores = {"low": 20, "medium": 50, "high": 75, "critical": 100, "blocked": 100}
    base = base_scores.get(risk_level, 50)
    for reason in risk_reasons:
        lreason = reason.lower()
        if "destructive" in lreason or "rm -rf" in lreason or "fork bomb" in lreason:
            base = max(base, 85)
        elif "recursive delete" in lreason or "git reset --hard" in lreason:
            base = max(base, 80)
        elif "network" in lreason or "remote access" in lreason:
            base = max(base, 70)
        elif "execute code" in lreason or "modify workspace" in lreason:
            base = max(base, 45)
        elif "read-only" in lreason or "standard validation" in lreason:
            base = min(base, 15)
        elif "unclassified" in lreason or "treat cautiously" in lreason:
            base = max(base, 55)
    return min(base, 100)


def risk_score_category(score: int) -> tuple[str, str]:
    """Return (category, emoji) for a risk score."""
    if score <= 20:
        return "Safe", "🔒"
    elif score <= 40:
        return "Low Risk", "🔓"
    elif score <= 60:
        return "Medium", "⚠️"
    elif score <= 80:
        return "High", "🚨"
    elif score < 100:
        return "Critical", "🚨"
    else:
        return "Blocked", "🚫"


def _policy_risk_from_shell_risk(risk_level: str) -> RiskLevel:
    if risk_level == "low":
        return RiskLevel.LOW
    if risk_level == "medium":
        return RiskLevel.MEDIUM
    if risk_level == "high":
        return RiskLevel.HIGH
    return RiskLevel.CRITICAL


def _parse_error_details(command: str, exc: ValueError) -> dict[str, Any]:
    """Extract useful context from a shlex parse error."""
    error_msg = str(exc)
    details: dict[str, Any] = {"error": error_msg}
    match = re.search(r"position (\d+)", error_msg)
    if match:
        pos = int(match.group(1))
        details["character_position"] = pos
        if pos < len(command):
            details["problematic_character"] = repr(command[pos])
            start = max(0, pos - 10)
            end = min(len(command), pos + 10)
            details["context"] = command[start:pos] + "<ERROR>" + command[pos + 1 : end]
    return details


def _extract_git_subcommand(tokens: list[str]) -> tuple[int, str, list[str]]:
    """Extract git subcommand and return (start_index, subcommand, rest_tokens)."""
    lower_tokens = [t.lower() for t in tokens]
    sub_start = 1
    while sub_start < len(lower_tokens):
        t = lower_tokens[sub_start]
        if t in {"-c", "-C"} and sub_start + 1 < len(lower_tokens):
            sub_start += 2
            continue
        if t.startswith("-"):
            sub_start += 1
            continue
        break
    sub = lower_tokens[sub_start] if sub_start < len(lower_tokens) else ""
    return sub_start, sub, lower_tokens[sub_start + 1 :]


def _analyze_compound_command(tokens: list[str], head: str) -> tuple[bool, list[str]]:
    """Analyze compound commands for chained risky operations."""
    if not tokens:
        return False, []
    risk_reasons: list[str] = []
    for i, token in enumerate(tokens):
        if token in _COMPOUND_CONTROL_COMMANDS:
            if i > 0 and i < len(tokens) - 1:
                prev = tokens[i - 1].lower()
                nxt = tokens[i + 1].lower()
                if prev in {"rm", "git"} or nxt in {"rm", "git", "chmod", "chown"}:
                    risk_reasons.append(f"compound command with {token} around risky operation")
    return bool(risk_reasons), risk_reasons


def _analyze_dangerous_glob(command: str, tokens: list[str], head: str) -> tuple[bool, list[str]]:
    """Detect dangerous glob patterns in risky commands."""
    if head not in _DANGEROUS_GLOB_COMMANDS:
        return False, []
    risk_reasons: list[str] = []
    for token in tokens[1:]:
        if any(c in token for c in _UNQUOTED_GLOB_CHARS) and not token.startswith("-"):
            if _COMPOUND_OPERATOR_REGEX.search(token):
                continue
            risk_reasons.append(f"dangerous glob pattern in {head}: {token}")
            break
    return bool(risk_reasons), risk_reasons


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
        parse_details = _parse_error_details(stripped, exc)
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
                "parse_error": parse_details,
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
    git_idx, git_sub, git_rest = _extract_git_subcommand(lower_tokens)

    has_compound, compound_reasons = _analyze_compound_command(lower_tokens, head)
    has_glob, glob_reasons = _analyze_dangerous_glob(stripped, lower_tokens, head)

    if (
        head in {"pytest", "ls", "cat", "echo", "pwd"}
        or tokens[:3] == ["python3", "-m", "pytest"]
        or command_tokens[:3] == ["python3", "-m", "pytest"]
        or tokens[:2] == ["git", "status"]
        or tokens[:2] == ["git", "diff"]
        or tokens[:2] == ["ruff", "check"]
    ):
        risk_level = "low"
        risk_reasons = ["read-only or standard validation command"]
    elif head == "git" and git_sub in (_DESTRUCTIVE_GIT_SUBCOMMANDS | {"push"}):
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

    if has_compound:
        risk_level = "high"
        risk_reasons.extend(compound_reasons)
    if has_glob:
        risk_level = "medium" if risk_level == "low" else risk_level
        risk_reasons.extend(glob_reasons)

    risk_score = compute_risk_score(risk_level, risk_reasons)
    risk_category, risk_emoji = risk_score_category(risk_score)

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
            "risk_score": risk_score,
            "risk_category": risk_category,
            "risk_emoji": risk_emoji,
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
    risk_score = details.get("risk_score", 50)
    return make_policy_decision(
        action,
        source,
        risk_level,
        reason,
        risk_reasons,
        {"tool": "run_shell", "risk_score": risk_score},
    )
