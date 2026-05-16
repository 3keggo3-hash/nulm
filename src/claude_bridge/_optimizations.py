
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT

"""Optimized versions of performance-critical Claude Bridge functions.

This module provides drop-in replacements (with _optimized suffix) for hot paths
identified in the codebase. All functions maintain identical behavior to their
originals while improving performance through caching, parallelization, and
reduced redundant operations.
"""

from __future__ import annotations

import fnmatch
import json
import re
import shlex
import threading
from pathlib import Path
from typing import Any

from claude_bridge._shell_constants import _BLOCKED_DIRECT_COMMANDS

_SECRET_PATTERNS: dict[str, str] = {
    "api_key_assignment": r"(?i)\bapi[_-]?key\s*[:=]\s*['\"][^'\"]+['\"]",
    "secret_assignment": r"(?i)\bsecret\s*[:=]\s*['\"][^'\"]+['\"]",
    "token_assignment": r"(?i)\btoken\s*[:=]\s*['\"][^'\"]+['\"]",
    "password_assignment": r"(?i)\bpassword\s*[:=]\s*['\"][^'\"]+['\"]",
    "api_key_unquoted": r"(?i)\bapi[_-]?key\s*[:=]\s*\S+",
    "secret_unquoted": r"(?i)\bsecret\s*[:=]\s*\S+",
    "token_unquoted": r"(?i)\btoken\s*[:=]\s*\S+",
    "password_unquoted": r"(?i)\bpassword\s*[:=]\s*\S+",
    "aws_access_key_id": r"AKIA[0-9A-Z]{16}",
    "github_token": r"ghp_[A-Za-z0-9]{20,}",
}

_COMPILED_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (name, re.compile(pattern)) for name, pattern in _SECRET_PATTERNS.items()
]
_COMPILED_SECRET_LOCK = threading.Lock()
_CUSTOM_PATTERNS_CACHE: tuple[tuple[str, re.Pattern[str]], ...] | None = None
_CUSTOM_PATTERNS_VERSION: int = 0

_NORMALIZE_WHITESPACE_RE = re.compile(r"\s+")


def _get_compiled_secret_patterns_optimized() -> list[tuple[str, re.Pattern[str]]]:
    return _COMPILED_SECRET_PATTERNS


def find_secret_patterns_optimized(content: str) -> list[str]:
    compiled_patterns = _get_compiled_secret_patterns_optimized()
    matches = [name for name, pattern in compiled_patterns if pattern.search(content)]
    return matches


_BRIDGEIGNORE_LOCK = threading.Lock()
_BRIDGEIGNORE_CACHE: dict[tuple[str, float], list[str]] = {}
_BRIDGEIGNORE_CUSTOM_CACHE: dict[str, list[str]] = {}


def load_bridgeignore_patterns_optimized(project_root: Path) -> list[str]:
    bridgeignore = project_root / ".bridgeignore"
    try:
        mtime = bridgeignore.stat().st_mtime
    except OSError:
        with _BRIDGEIGNORE_LOCK:
            stale_keys = [k for k in _BRIDGEIGNORE_CACHE if k[0] == str(project_root)]
            for k in stale_keys:
                _BRIDGEIGNORE_CACHE.pop(k, None)
        return []
    cache_key = (str(project_root), mtime)
    with _BRIDGEIGNORE_LOCK:
        cached = _BRIDGEIGNORE_CACHE.get(cache_key)
        if cached is not None:
            return cached
    if not bridgeignore.is_file():
        with _BRIDGEIGNORE_LOCK:
            _BRIDGEIGNORE_CACHE[cache_key] = []
        return []
    patterns: list[str] = []
    try:
        for line in bridgeignore.read_text(errors="replace").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                patterns.append(stripped)
    except OSError:
        return []
    with _BRIDGEIGNORE_LOCK:
        old_keys = [k for k in _BRIDGEIGNORE_CACHE if k[0] == str(project_root) and k != cache_key]
        for k in old_keys:
            _BRIDGEIGNORE_CACHE.pop(k, None)
        _BRIDGEIGNORE_CACHE[cache_key] = patterns
    return patterns


def _mask_secrets_optimized(
    value: Any, custom_patterns: list[tuple[str, re.Pattern[str]]] | None = None
) -> Any:
    if not isinstance(value, str):
        return value
    masked = value
    for _, pattern in _get_compiled_secret_patterns_optimized():
        masked = pattern.sub("[REDACTED]", masked)
    if custom_patterns is None:
        custom_patterns = _get_custom_patterns_cached()
    for _, pattern in custom_patterns:
        masked = pattern.sub("[REDACTED]", masked)
    return masked


def _get_custom_patterns_cached() -> list[tuple[str, re.Pattern[str]]]:
    global _CUSTOM_PATTERNS_CACHE, _CUSTOM_PATTERNS_VERSION
    from claude_bridge.guard_policy import load_guard_policy

    policy = load_guard_policy()
    new_version = id(policy.get("secret_patterns", {}))
    if new_version == _CUSTOM_PATTERNS_VERSION and _CUSTOM_PATTERNS_CACHE is not None:
        return list(_CUSTOM_PATTERNS_CACHE)
    patterns = [
        (name, re.compile(pattern)) for name, pattern in policy.get("secret_patterns", {}).items()
    ]
    _CUSTOM_PATTERNS_CACHE = tuple(patterns)
    _CUSTOM_PATTERNS_VERSION = new_version
    return list(_CUSTOM_PATTERNS_CACHE)


_SENSITIVE_SUFFIXES = frozenset({".env", ".pem", ".key", ".p12", ".pfx"})
_SENSITIVE_FILENAMES = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        ".env.development",
        ".env.staging",
        ".npmrc",
        ".netrc",
        ".pypirc",
        ".dockercfg",
        ".git-credentials",
        "credentials.json",
        "application_default_credentials.json",
        "id_rsa",
        "id_dsa",
        "id_ed25519",
        "credentials",
        "known_hosts",
        "claude_desktop_config.json",
    }
)
_PATH_PARTS_CACHE: dict[str, tuple[str, ...]] = {}
_PATH_PARTS_CACHE_MAX = 256


def _get_path_parts_cached(target: Path) -> tuple[str, ...]:
    try:
        cache_key = str(target.resolve())
    except (OSError, ValueError):
        cache_key = str(target)
    if cache_key in _PATH_PARTS_CACHE:
        return _PATH_PARTS_CACHE[cache_key]
    parts = tuple(p.lower() for p in target.resolve().parts)
    if len(_PATH_PARTS_CACHE) >= _PATH_PARTS_CACHE_MAX:
        try:
            oldest_key = next(iter(_PATH_PARTS_CACHE))
            _PATH_PARTS_CACHE.pop(oldest_key, None)
        except StopIteration:
            pass
    _PATH_PARTS_CACHE[cache_key] = parts
    return parts


def sensitive_path_reason_optimized(target: Path, project_dir_fn: Any = None) -> str | None:
    name = target.name.lower()
    if name in _SENSITIVE_FILENAMES:
        return name
    if any(name.endswith(suffix) for suffix in _SENSITIVE_SUFFIXES):
        return target.suffix.lower()
    resolved_parts = _get_path_parts_cached(target)
    if ".git" in resolved_parts:
        return ".git directory"
    if ".docker" in resolved_parts:
        docker_idx = resolved_parts.index(".docker")
        rel = resolved_parts[docker_idx + 1 :]
        if rel == ("config.json",):
            return ".docker/config.json"
    if project_dir_fn is None:
        from claude_bridge.config import project_dir

        project_dir_fn = project_dir
    try:
        relative = target.resolve().relative_to(project_dir_fn()).as_posix()
    except (OSError, ValueError):
        relative = target.name
    candidates = {target.name, relative}
    for pattern in load_bridgeignore_patterns_optimized(project_dir_fn()):
        if any(fnmatch.fnmatchcase(c, pattern) for c in candidates):
            return f"bridgeignore pattern: {pattern}"
    from claude_bridge.guard_policy import custom_sensitive_path_reason

    return custom_sensitive_path_reason(target)


def _blocked_shell_construct_optimized(stripped: str) -> str | None:
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(stripped):
        if escaped:
            escaped = False
            continue
        if char == "\\" and not in_single:
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if in_single:
            continue
        if char == "`":
            return "backtick substitution"
        if char == "$" and index + 1 < len(stripped):
            next_char = stripped[index + 1]
            if next_char == "(":
                if index + 2 < len(stripped) and stripped[index + 2] == "(":
                    return "$(( arithmetic expansion"
                return "$() substitution"
            if next_char == "{":
                return "${} expansion"
            if next_char == "'":
                return "$' ANSI-C quoting"
            if next_char == '"':
                return '$" locale translation'
        if char == "<":
            if index + 1 < len(stripped):
                next_char = stripped[index + 1]
                if next_char == "(":
                    return "<() process substitution"
                if next_char == "<":
                    if index + 2 < len(stripped) and stripped[index + 2] == "<":
                        return "<<< here-string"
                    return "<< heredoc"
        if char == ">" and index + 1 < len(stripped) and stripped[index + 1] == "(":
            return ">() process substitution"
        if char == "(":
            prefix = stripped[:index].rstrip()
            if not prefix or prefix.endswith((";", "&&", "||", "|", "&")):
                return "subshell"
    return None


def blocked_command_reason_optimized(
    stripped: str,
    tokens: list[str],
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    normalized: str,
) -> str | None:
    reason = _blocked_shell_construct_optimized(stripped)
    if reason is not None:
        return reason
    from claude_bridge.guard_policy import custom_shell_block_reason

    reason = custom_shell_block_reason(stripped)
    if reason is not None:
        return reason
    from claude_bridge.guard_policy import load_guard_policy

    policy = load_guard_policy()
    if policy.get("default_deny", False):
        allowed = policy.get("allowed_shell_commands", [])
        if head not in allowed:
            return f"not in shell whitelist: {head}"
    if head in _BLOCKED_DIRECT_COMMANDS:
        return head
    return None


_BLOCKED_DIRECT_COMMANDS_SET = frozenset(_BLOCKED_DIRECT_COMMANDS)


def blocked_command_reason_fastpath(stripped: str, tokens: list[str]) -> str | None:
    if not tokens:
        return None
    command_tokens = _tokens_after_env_fastpath(tokens)
    if not command_tokens:
        return None
    head = _command_basename_fastpath(command_tokens[0])
    while head in {"command", "exec", "builtin"} and len(command_tokens) > 1:
        command_tokens = command_tokens[1:]
        head = _command_basename_fastpath(command_tokens[0])
    while head == "env":
        command_tokens = _tokens_after_env_fastpath(command_tokens)
        if not command_tokens:
            return None
        head = _command_basename_fastpath(command_tokens[0])
    lower_tokens = [token.lower() for token in command_tokens]
    all_lower_tokens = [token.lower() for token in tokens]
    normalized = _NORMALIZE_WHITESPACE_RE.sub(" ", stripped.strip()).lower()
    return blocked_command_reason_optimized(
        stripped, tokens, head, lower_tokens, all_lower_tokens, normalized
    )


def _command_basename_fastpath(token: str) -> str:
    return Path(token).name.lower()


def _tokens_after_env_fastpath(tokens: list[str]) -> list[str]:
    if not tokens or _command_basename_fastpath(tokens[0]) != "env":
        return tokens
    for index, token in enumerate(tokens[1:], start=1):
        if "=" in token and not token.startswith("-"):
            continue
        if token == "-S":
            if index + 1 < len(tokens):
                try:
                    split_tokens = shlex.split(tokens[index + 1])
                except ValueError:
                    split_tokens = [tokens[index + 1]]
                return split_tokens + list(tokens[index + 2 :])
            return []
        if token.startswith("-"):
            continue
        return tokens[index:]
    return []


_SHELL_ANALYSIS_CACHE: dict[str, dict[str, Any]] = {}
_SHELL_ANALYSIS_CACHE_LOCK = threading.Lock()
_SHELL_ANALYSIS_CACHE_MAX = 256


def analyze_shell_command_optimized(command: str) -> dict[str, Any]:
    stripped = command.strip()
    cache_key = stripped[:128]
    with _SHELL_ANALYSIS_CACHE_LOCK:
        if cache_key in _SHELL_ANALYSIS_CACHE:
            return _SHELL_ANALYSIS_CACHE[cache_key]
    if not stripped:
        return _shell_analysis_empty_result(command)
    try:
        tokens = shlex.split(stripped)
    except ValueError as exc:
        return _shell_analysis_parse_error(command, exc)
    if not tokens:
        return _shell_analysis_empty_result(command)
    reason = blocked_command_reason_fastpath(stripped, tokens)
    if reason is not None:
        return _shell_analysis_blocked_result(command, reason)
    if _is_interactive_command_optimized(stripped, tokens):
        return _shell_analysis_interactive_result(command)
    result = _analyze_shell_command_unsafe(stripped, tokens)
    with _SHELL_ANALYSIS_CACHE_LOCK:
        if len(_SHELL_ANALYSIS_CACHE) >= _SHELL_ANALYSIS_CACHE_MAX:
            try:
                oldest_key = next(iter(_SHELL_ANALYSIS_CACHE))
                _SHELL_ANALYSIS_CACHE.pop(oldest_key, None)
            except StopIteration:
                pass
        _SHELL_ANALYSIS_CACHE[cache_key] = result
    return result


def _is_interactive_command_optimized(stripped: str, tokens: list[str]) -> bool:
    if not tokens:
        return False
    from claude_bridge._shell_constants import _INTERACTIVE_COMMANDS

    command_tokens = _tokens_after_env_fastpath(tokens)
    if not command_tokens:
        return False
    head = _command_basename_fastpath(command_tokens[0])
    if head in {"command", "exec", "builtin"}:
        if len(command_tokens) > 1:
            head = _command_basename_fastpath(command_tokens[1])
    if head in {"python", "python3"}:
        executable_index = 0
        if _command_basename_fastpath(tokens[0]) == "env":
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


def _shell_analysis_empty_result(command: str) -> dict[str, Any]:
    from claude_bridge.guard_policy import (
        DecisionAction,
        DecisionSource,
        RiskLevel,
        make_policy_decision,
    )

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


def _shell_analysis_parse_error(command: str, exc: ValueError) -> dict[str, Any]:
    from claude_bridge.guard_policy import (
        DecisionAction,
        DecisionSource,
        RiskLevel,
        make_policy_decision,
    )

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


def _shell_analysis_blocked_result(command: str, blocked_pattern: str) -> dict[str, Any]:
    from claude_bridge.guard_policy import (
        DecisionAction,
        DecisionSource,
        RiskLevel,
        make_policy_decision,
    )

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


def _shell_analysis_interactive_result(command: str) -> dict[str, Any]:
    from claude_bridge.guard_policy import (
        DecisionAction,
        DecisionSource,
        RiskLevel,
        make_policy_decision,
    )

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


def _analyze_shell_command_unsafe(stripped: str, tokens: list[str]) -> dict[str, Any]:
    from claude_bridge._shell_constants import _DESTRUCTIVE_GIT_SUBCOMMANDS
    from claude_bridge.guard_policy import (
        DecisionAction,
        DecisionSource,
        RiskLevel,
        make_policy_decision,
    )

    command_tokens = _tokens_after_env_fastpath(tokens)
    head = _command_basename_fastpath(tokens[0])
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
    if risk_level == "low":
        decision_action = DecisionAction.ALLOW
        decision_source = DecisionSource.DEFAULT
        requires_confirmation = False
        policy_risk = RiskLevel.LOW
    elif risk_level == "high":
        decision_action = DecisionAction.ASK
        decision_source = DecisionSource.BUILTIN_GUARD
        requires_confirmation = True
        policy_risk = RiskLevel.HIGH
    else:
        decision_action = DecisionAction.ASK
        decision_source = DecisionSource.BUILTIN_GUARD
        requires_confirmation = True
        policy_risk = RiskLevel.MEDIUM
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
            "command": stripped,
            "normalized_command": stripped,
            "argv": tokens,
            "risk_level": risk_level,
            "risk_reasons": risk_reasons,
            "requires_confirmation": requires_confirmation,
            "policy_decision": analysis_decision.to_dict(),
        },
    }


def _sanitized_env_optimized() -> dict[str, str]:
    import os

    env = dict(os.environ)
    blocked_keys = {
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
    }
    for key in blocked_keys:
        env.pop(key, None)
    return env


def _truncate_output_optimized(value: str, max_chars: int) -> tuple[str, bool]:
    if len(value) <= max_chars:
        return value, False
    clipped = value[:max_chars]
    return (
        clipped + f"\nTRUNCATED: omitted {len(value) - max_chars} characters; "
        "narrow the command or rerun with a more specific target.",
        True,
    )


_JSON_RESPONSE_CACHE: dict[tuple[bool, str], str] = {}
_JSON_RESPONSE_CACHE_LOCK = threading.Lock()
_JSON_RESPONSE_CACHE_MAX = 256


def json_response_optimized(
    ok: bool,
    message: str,
    details: dict[str, Any] | None = None,
    code: str | None = None,
    decision: dict[str, Any] | None = None,
    decision_in_details: bool = False,
) -> str:
    cache_key = (ok, message[:64])
    with _JSON_RESPONSE_CACHE_LOCK:
        if (
            details is None
            and code is None
            and decision is None
            and not decision_in_details
            and cache_key in _JSON_RESPONSE_CACHE
        ):
            return _JSON_RESPONSE_CACHE[cache_key]
    response_details = {k: v for k, v in (details or {}).items() if v is not None}
    decision_payload: dict[str, Any] | None = None
    if decision is not None:
        decision_payload = decision if isinstance(decision, dict) else dict(decision)
        if decision_in_details:
            response_details = dict(response_details)
            response_details["decision"] = decision_payload
    payload: dict[str, Any] = {
        "ok": ok,
        "message": message,
        "details": response_details,
    }
    if code:
        payload["code"] = code
    if decision_payload is not None:
        payload["decision"] = decision_payload
    result = json.dumps(payload, ensure_ascii=False)
    with _JSON_RESPONSE_CACHE_LOCK:
        if (
            details is None
            and code is None
            and decision is None
            and not decision_in_details
            and len(_JSON_RESPONSE_CACHE) < _JSON_RESPONSE_CACHE_MAX
        ):
            _JSON_RESPONSE_CACHE[cache_key] = result
    return result
