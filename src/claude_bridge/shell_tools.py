"""Shell-oriented tool implementations for Claude Bridge."""

from __future__ import annotations

import logging
import re
import shlex
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

from claude_bridge.ai_evaluator import evaluate_tool_with_ai
from claude_bridge.config import current_config
from claude_bridge.guard_policy import (
    DecisionAction,
    DecisionSource,
    PolicyDecision,
    RiskLevel,
    ToolRequestContext,
    custom_shell_block_reason,
    evaluate_rules,
    load_guard_policy,
    make_policy_decision,
)
from claude_bridge.tool_utils import json_response, require_approval

logger = logging.getLogger(__name__)  # FIX: logger for trim warnings

_INTERACTIVE_COMMANDS = {
    "python",
    "python3",
    "bash",
    "sh",
    "zsh",
    "fish",
    "ksh",
    "tcsh",
    "elvish",
    "nu",
    "nushell",
    "vim",
    "vi",
    "nano",
}
_DESTRUCTIVE_GIT_SUBCOMMANDS = {"reset", "clean", "checkout", "restore", "revert"}
# Regex for fork-bomb patterns:
#   :(){ :|:& };:  (classic)  and  f(){ f|f& };f  (named variant)
#   with flexible whitespace and function-name chars.
_FORK_BOMB_RE = re.compile(
    r""":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"""  # classic (spaces ok)
    r"""|(\w+)\s*\(\s*\)\s*\{\s*\1\s*\|\s*\1\s*&\s*\}\s*;\s*\1"""  # named variant
    r"""|(\$\d+)\s*\(\s*\)\s*\{\s*\1\s*\|\s*\1\s*&\s*\}\s*;\s*\1"""  # $N variant
)
_INLINE_INTERPRETER_FLAGS = {
    "bash": {"-c"},
    "lua": {"-e"},
    "node": {"-e"},
    "perl": {"-e"},
    "php": {"-r"},
    "python": {"-c"},
    "python3": {"-c"},
    "ruby": {"-e"},
    "sh": {"-c"},
    "zsh": {"-c"},
}
_BLOCKED_PIPE_TARGETS = {
    "bash",
    "sh",
    "zsh",
    "fish",
    "ksh",
    "tcsh",
    "elvish",
    "nu",
    "nushell",
    "python",
    "python3",
    "perl",
    "ruby",
    "node",
}
_WRAPPER_COMMANDS = {
    "nohup",
    "setsid",
    "script",
    "timeout",
    "nice",
    "unshare",
    "chroot",
    "nsenter",
    "prlimit",
    "taskset",
    "stdbuf",
    "ionice",
    "pkexec",
    "sudoedit",
    "su",
    "watch",
    "flock",
    "systemd-run",
}
_MAX_SHELL_OUTPUT_CHARS = 2000
_MAX_PROCESS_SESSIONS = 16
_MAX_PROCESS_OUTPUT_CHARS = 2000

_LONG_RUNNING_TIMEOUT = 120

_LONG_RUNNING_COMMANDS = {
    "npm install",
    "npm ci",
    "cargo build",
    "cargo test",
    "go build",
    "go test",
    "pip install",
    "pip3 install",
    "make",
    "cmake",
    "docker build",
    "docker compose",
}


class _ProcessSession:
    def __init__(
        self,
        *,
        session_id: str,
        command: str,
        argv: list[str],
        cwd: Path,
        process: subprocess.Popen[str],
        risk_level: str,
        risk_reasons: list[str],
    ) -> None:
        self.session_id = session_id
        self.command = command
        self.argv = argv
        self.cwd = cwd
        self.process = process
        self.risk_level = risk_level
        self.risk_reasons = risk_reasons
        self.started_at = time.time()
        self.completed_at: float | None = None
        self.exit_code: int | None = None
        self.output = ""
        self.lock = threading.Lock()
        self.stdin_closed = False
        self.stdout_done = False
        self.stderr_done = False
        self.input_chars = 0
        self.input_events = 0
        self.last_input_at: float | None = None
        self.last_output_at: float | None = None

    def mark_stream_done(self, *, is_stderr: bool) -> None:
        with self.lock:
            if is_stderr:
                self.stderr_done = True
            else:
                self.stdout_done = True

    def append_output(self, text: str, *, is_stderr: bool) -> None:
        if not text:
            return
        chunk = text
        if is_stderr:
            lines = chunk.splitlines(keepends=True)
            chunk = "".join(f"[stderr] {line}" if line.strip() else line for line in lines)
        with self.lock:
            if len(self.output) >= _MAX_PROCESS_OUTPUT_CHARS:
                return
            remaining = _MAX_PROCESS_OUTPUT_CHARS - len(self.output)
            if len(chunk) > remaining:
                chunk = chunk[:remaining] + "\n... [output truncated]"
            self.output += chunk
            self.last_output_at = time.time()

    def record_input(self, text: str) -> None:
        with self.lock:
            self.input_chars += len(text)
            self.input_events += 1
            self.last_input_at = time.time()

    def mark_stdin_closed(self) -> None:
        with self.lock:
            self.stdin_closed = True

    def snapshot(self) -> dict[str, Any]:
        self.refresh_status()
        with self.lock:
            return {
                "session_id": self.session_id,
                "command": self.command,
                "argv": list(self.argv),
                "cwd": str(self.cwd),
                "pid": self.process.pid,
                "running": self.exit_code is None,
                "exit_code": self.exit_code,
                "started_at": self.started_at,
                "completed_at": self.completed_at,
                "output_chars": len(self.output),
                "input_chars": self.input_chars,
                "input_events": self.input_events,
                "stdin_closed": self.stdin_closed,
                "stdout_closed": self.stdout_done,
                "stderr_closed": self.stderr_done,
                "last_input_at": self.last_input_at,
                "last_output_at": self.last_output_at,
                "risk_level": self.risk_level,
                "risk_reasons": list(self.risk_reasons),
            }

    def refresh_status(self) -> None:
        return_code = self.process.poll()
        if return_code is None:
            return
        with self.lock:
            if self.exit_code is None:
                self.exit_code = return_code
                self.completed_at = time.time()


_PROCESS_SESSIONS: dict[str, _ProcessSession] = {}
_PROCESS_SESSIONS_LOCK = threading.RLock()


def _trim_process_sessions() -> None:
    with _PROCESS_SESSIONS_LOCK:
        completed = [s for s in _PROCESS_SESSIONS.values() if s.exit_code is not None]
        for s in completed:
            output_len = len(s.output)
            s.output = s.output[: min(output_len, 200)]
            s.command = s.command[:200]
        if len(_PROCESS_SESSIONS) <= _MAX_PROCESS_SESSIONS:
            return
        ordered = sorted(_PROCESS_SESSIONS.values(), key=lambda session: session.started_at)
        for session in ordered[:-_MAX_PROCESS_SESSIONS]:
            if session.exit_code is None:
                logger.warning(
                    "Killing oldest process session %s (%s) to stay within limit %d",
                    session.session_id,
                    session.command,
                    _MAX_PROCESS_SESSIONS,
                )
                try:
                    session.process.terminate()
                    session.process.wait(timeout=1)
                except (OSError, subprocess.TimeoutExpired):
                    try:
                        session.process.kill()
                    except OSError:
                        pass
            _PROCESS_SESSIONS.pop(session.session_id, None)


def reset_process_sessions() -> None:
    with _PROCESS_SESSIONS_LOCK:
        sessions = list(_PROCESS_SESSIONS.values())
        _PROCESS_SESSIONS.clear()
    for session in sessions:
        if session.process.poll() is not None:
            continue
        try:
            session.process.terminate()
            session.process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            try:
                session.process.kill()
            except OSError:
                pass


def _pump_process_stream(session: _ProcessSession, stream: Any, *, is_stderr: bool) -> None:
    try:
        while True:
            chunk = stream.readline()
            if chunk == "":
                break
            session.append_output(chunk, is_stderr=is_stderr)
    finally:
        session.mark_stream_done(is_stderr=is_stderr)
        try:
            stream.close()
        except OSError:
            pass


def _start_stream_threads(session: _ProcessSession) -> None:
    stdout = session.process.stdout
    stderr = session.process.stderr
    if stdout is not None:
        threading.Thread(
            target=_pump_process_stream,
            args=(session, stdout),
            kwargs={"is_stderr": False},
            daemon=True,
        ).start()
    else:
        session.mark_stream_done(is_stderr=False)
    if stderr is not None:
        threading.Thread(
            target=_pump_process_stream,
            args=(session, stderr),
            kwargs={"is_stderr": True},
            daemon=True,
        ).start()
    else:
        session.mark_stream_done(is_stderr=True)


def _get_process_session(session_id: str) -> _ProcessSession | None:
    with _PROCESS_SESSIONS_LOCK:
        return _PROCESS_SESSIONS.get(session_id)


def _command_basename(token: str) -> str:
    return Path(token).name.lower()


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


def _interactive_target(tokens: list[str]) -> str | None:
    command_tokens = _tokens_after_env(tokens)
    if not command_tokens:
        return None
    head = _command_basename(command_tokens[0])
    if head in {"command", "exec", "builtin"}:
        if len(command_tokens) > 1:
            return _command_basename(command_tokens[1])
        return None
    return head


def _tokens_after_env(tokens: list[str]) -> list[str]:
    if not tokens or _command_basename(tokens[0]) != "env":
        return tokens
    for index, token in enumerate(tokens[1:], start=1):
        if "=" in token:
            continue
        if token == "-S":
            # FIX: env -S splits the next arg into command
            if index + 1 < len(tokens):
                try:
                    inner = shlex.split(tokens[index + 1])
                except ValueError:
                    inner = [tokens[index + 1]]
                return inner + list(tokens[index + 2 :])
            continue
        if token.startswith("-"):
            continue
        return tokens[index:]
    return []


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
        # FIX: detect python -i as interactive
        if any(tok == "-i" for tok in tokens[executable_index + 1 :]):
            return True
        return len(tokens) == executable_index + 1
    return head in _INTERACTIVE_COMMANDS


def normalize_command_for_safety(command: str) -> str:
    return re.sub(r"\s+", " ", command.strip()).lower()


def _find_unquoted_shell_construct(command: str) -> str | None:
    in_single = False
    in_double = False
    escaped = False

    for index, char in enumerate(command):
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
        # FIX: skip only single-quoted text; double-quoted still evaluates $(), ``, etc.
        if in_single:
            continue
        if char == "`":
            return "backtick substitution"
        if char == "$" and index + 1 < len(command):
            next_char = command[index + 1]
            if next_char == "(":
                # FIX: $(( arithmetic expansion must be checked before $()
                if index + 2 < len(command) and command[index + 2] == "(":
                    return "$(( arithmetic expansion"
                return "$() substitution"
            # FIX: detect ${} parameter expansion
            if next_char == "{":
                return "${} expansion"
        if char == "(":
            prefix = command[:index].rstrip()
            if not prefix or prefix.endswith((";", "&&", "||", "|", "&")):
                return "subshell"
    return None


def _truncate_output(value: str) -> tuple[str, bool]:
    if len(value) <= _MAX_SHELL_OUTPUT_CHARS:
        return value, False
    clipped = value[:_MAX_SHELL_OUTPUT_CHARS]
    return (
        clipped
        + f"\n... [truncated {len(value) - _MAX_SHELL_OUTPUT_CHARS} characters; narrow the command or rerun with a more specific target]",
        True,
    )


# ── per-family blocked-command matchers ────────────────────────────────────


def _blocked_shell_construct(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    return _find_unquoted_shell_construct(stripped)


def _blocked_custom_policy(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    return custom_shell_block_reason(stripped)


def _blocked_whitelist(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    policy = load_guard_policy()
    if not policy.get("default_deny", False):
        return None
    allowed = policy.get("allowed_shell_commands", [])
    if head not in allowed:
        return f"not in shell whitelist: {head}"
    return None


def _blocked_direct_commands(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    if head == "sudo":
        return "sudo"
    if head == "chmod":
        return "chmod"
    if head == "mkfs":
        return "mkfs"
    return None


def _blocked_inline_interpreter(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    if head not in _INLINE_INTERPRETER_FLAGS:
        return None
    if any(token in _INLINE_INTERPRETER_FLAGS[head] for token in lower_tokens[1:]):
        flag = next(token for token in lower_tokens[1:] if token in _INLINE_INTERPRETER_FLAGS[head])
        return f"{head} {flag}"
    return None


_PIPE_TARGET_REGEX = re.compile(
    rf"(?:[|;]|&&)\s*(?:\S*/)?({'|'.join(sorted(_BLOCKED_PIPE_TARGETS))})\b",
    re.IGNORECASE,
)


def _blocked_curl_wget(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    if head not in {"curl", "wget"}:
        return None
    control_tokens_present = any(token in {"|", "&&", ";"} for token in all_lower_tokens)
    output_file_tokens: set[str] = set()
    output_flags = {"-o", "--output"} if head == "curl" else {"-O", "--output-document"}
    for i, token in enumerate(lower_tokens[:-1]):
        if token in output_flags:
            output_file_tokens.add(lower_tokens[i + 1])
    if re.search(r"[|;]|&&", stripped) and _PIPE_TARGET_REGEX.search(stripped):
        return f"{head} to shell"
    if control_tokens_present:
        suspect = [
            t
            for t in lower_tokens
            if _command_basename(t) in _BLOCKED_PIPE_TARGETS and t not in output_file_tokens
        ]
        if suspect:
            return f"{head} to shell"
    return None


def _blocked_dd(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    if head != "dd":
        return None
    for token in lower_tokens[1:]:
        if token.startswith("if="):
            return "dd if="
        if token.startswith("of=") and len(token) > 3 and token[3:].startswith("/dev/"):
            return "dd of=/dev/"
    return None


def _blocked_wrappers(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    if head in _WRAPPER_COMMANDS:
        return f"{head} wrapper"
    return None


def _blocked_tee_pv(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    if head == "tee":
        for token in lower_tokens[1:]:
            if token.startswith("/dev/"):
                return "tee /dev/"
    elif head == "pv":
        for i, token in enumerate(lower_tokens):
            if token in {">", ">>"} and i + 1 < len(lower_tokens):
                if lower_tokens[i + 1].startswith("/dev/"):
                    return "pv > /dev/"
    return None


def _blocked_find_xargs(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    if head == "find":
        if re.search(r"(?:^|\s)find\b.*\|\s*xargs\b.*\brm\b", normalized):
            return "find to xargs rm"
        if any(
            token.startswith("-exec") or token == "-delete" or token == "+"
            for token in lower_tokens[1:]
        ):
            return "find -exec"
    if head == "xargs" and len(lower_tokens) > 1:
        return "xargs"
    return None


def _blocked_rm(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    if head != "rm":
        return None
    option_chars = "".join(token.lstrip("-") for token in lower_tokens[1:] if token.startswith("-"))
    if "r" in option_chars:
        return "rm -r"
    if "--no-preserve-root" in lower_tokens:
        return "rm --no-preserve-root"
    return None


def _blocked_git(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    if head != "git" or len(lower_tokens) < 2:
        return None
    sub_start: int = 1
    while sub_start < len(lower_tokens):
        t = lower_tokens[sub_start]
        if t in {"-c", "-C"} and sub_start + 1 < len(lower_tokens):
            sub_start += 2
            continue
        if t.startswith("-"):
            sub_start += 1
            continue
        break
    subcommand = lower_tokens[sub_start] if sub_start < len(lower_tokens) else ""
    rest = lower_tokens[sub_start + 1 :]
    if subcommand == "reset" and any(token == "--hard" for token in rest):
        return "git reset --hard"
    if subcommand == "clean" and any(
        "f" in token.lstrip("-") for token in rest if token.startswith("-")
    ):
        return "git clean -f"
    if subcommand == "checkout" and any(token == "--" for token in rest):
        return "git checkout --"
    if subcommand == "restore" and any(token.startswith("--source") for token in rest):
        return "git restore --source"
    return None


def _blocked_pipe_targets(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    for index, token in enumerate(all_lower_tokens[:-1]):
        pipe_target = _command_basename(all_lower_tokens[index + 1])
        if token == "|" and pipe_target in _BLOCKED_PIPE_TARGETS:
            return f"| {pipe_target}"
    return None


def _blocked_dev_redirection(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    for idx, token in enumerate(all_lower_tokens):
        if token in {">", ">>"}:
            next_idx = idx + 1
            if next_idx < len(all_lower_tokens) and all_lower_tokens[next_idx].startswith("/dev/"):
                return f"{token} /dev"
        if re.match(r"^[12&]>>?$", token):
            next_idx = idx + 1
            if next_idx < len(all_lower_tokens) and all_lower_tokens[next_idx].startswith("/dev/"):
                return f"{token} /dev"
    dev_redirect_match = re.search(r"[12&]?>>?\s*/dev", normalized)
    if dev_redirect_match:
        match_start = dev_redirect_match.start()
        in_single = False
        in_double = False
        escaped = False
        for i in range(match_start):
            ch = normalized[i]
            if escaped:
                escaped = False
                continue
            if ch == "\\" and not in_single:
                escaped = True
                continue
            if ch == "'" and not in_double:
                in_single = not in_single
                continue
            if ch == '"' and not in_single:
                in_double = not in_double
                continue
        if not in_single and not in_double:
            return "> /dev"
    if normalized.startswith("/dev/"):
        return "/dev/ path"
    return None


def _blocked_fork_bomb(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    if _FORK_BOMB_RE.search(normalized):
        return "fork bomb"
    return None


_BLOCKED_MATCHERS = [
    _blocked_shell_construct,
    _blocked_custom_policy,
    _blocked_whitelist,
    _blocked_direct_commands,
    _blocked_inline_interpreter,
    _blocked_curl_wget,
    _blocked_dd,
    _blocked_wrappers,
    _blocked_tee_pv,
    _blocked_find_xargs,
    _blocked_rm,
    _blocked_git,
    _blocked_pipe_targets,
    _blocked_dev_redirection,
    _blocked_fork_bomb,
]


def blocked_command_reason(stripped: str, tokens: list[str]) -> str | None:
    if not tokens:
        return None

    command_tokens = _tokens_after_env(tokens)
    if not command_tokens:
        return None
    head = _command_basename(command_tokens[0])
    while head in {"command", "exec", "builtin"} and len(command_tokens) > 1:
        command_tokens = command_tokens[1:]
        head = _command_basename(command_tokens[0])

    while head == "env":
        command_tokens = _tokens_after_env(command_tokens)
        if not command_tokens:
            return None
        head = _command_basename(command_tokens[0])
    lower_tokens = [token.lower() for token in command_tokens]
    all_lower_tokens = [token.lower() for token in tokens]
    normalized = normalize_command_for_safety(stripped)

    # ── full-path bypass hardening ──
    raw_head = command_tokens[0]
    if "/" in raw_head:
        raw_basename = _command_basename(raw_head)
        _FULL_PATH_BLOCKED = {"sudo", "chmod", "mkfs"}
        if raw_basename in _FULL_PATH_BLOCKED:
            return f"full-path {raw_basename}"

    # ── env indirection hardening ──
    env_raw = tokens[0]
    if "/" in env_raw:
        env_basename = _command_basename(env_raw)
    else:
        env_basename = env_raw.lower()
    if env_basename == "env":
        env_target = _interactive_target(tokens)
        if env_target is not None and env_target in {"sudo", "chmod", "mkfs"}:
            return f"env {env_target}"

    # ── delegate to per-family matchers ──
    for matcher in _BLOCKED_MATCHERS:
        reason = matcher(head, lower_tokens, all_lower_tokens, stripped, normalized)
        if reason is not None:
            return reason
    return None


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
    # determine git subcommand position (skip -C, -c flags)
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

    # Map existing risk level strings to RiskLevel enum for the decision
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


def _policy_risk_from_shell_risk(risk_level: str) -> RiskLevel:
    if risk_level == "low":
        return RiskLevel.LOW
    if risk_level == "medium":
        return RiskLevel.MEDIUM
    if risk_level == "high":
        return RiskLevel.HIGH
    return RiskLevel.CRITICAL


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
    rule_decision = evaluate_rules(
        ToolRequestContext(
            tool_name="run_shell",
            params={"command": stripped},
            project_dir=str(project_dir()),
        )
    )
    if rule_decision is not None and rule_decision.action == DecisionAction.DENY:
        return json_response(
            False,
            rule_decision.reason,
            code="policy_denied",
            details={
                "command": command,
                "risk_level": analysis["details"]["risk_level"],
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            decision=rule_decision,
            decision_in_details=True,
        )
    if rule_decision is not None and rule_decision.action == DecisionAction.ASK:
        return json_response(
            False,
            rule_decision.reason,
            code="approval_rejected",
            details={
                "command": command,
                "risk_level": analysis["details"]["risk_level"],
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            decision=rule_decision,
            decision_in_details=True,
        )

    # AI evaluator layer (optional, default off)
    config = current_config()
    ai_enabled = bool(config.get("ai_evaluator_enabled", False))
    ai_timeout = int(config.get("ai_evaluator_timeout", 5))
    ai_fallback = str(config.get("ai_evaluator_fallback_action", "ask"))
    ai_decision = await evaluate_tool_with_ai(
        ToolRequestContext(
            tool_name="run_shell",
            params={"command": stripped},
            project_dir=str(project_dir()),
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
                "command": command,
                "risk_level": analysis["details"]["risk_level"],
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            decision=ai_decision,
            decision_in_details=True,
        )
    if ai_decision is not None and ai_decision.action == DecisionAction.ASK:
        return json_response(
            False,
            ai_decision.reason,
            code="approval_rejected",
            details={
                "command": command,
                "risk_level": analysis["details"]["risk_level"],
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            decision=ai_decision,
            decision_in_details=True,
        )
    if ai_decision is not None and ai_decision.action == DecisionAction.ALLOW:
        allow_decision = ai_decision
    elif rule_decision is not None and rule_decision.action == DecisionAction.ALLOW:
        allow_decision = rule_decision
    else:
        rejection = await require_approval(
            "run_shell",
            {"command": stripped},
            rejection_message="Shell command rejected by user",
            rejection_details={
                "command": command,
                "risk_level": analysis["details"]["risk_level"],
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            request_approval_fn=request_approval,
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
                    "command": command,
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
        )
    except subprocess.TimeoutExpired:
        return json_response(
            False,
            f"Shell command timed out after {timeout_seconds} seconds",
            code="command_timeout",
            details={
                "command": command,
                "timeout_seconds": timeout_seconds,
                "risk_level": analysis["details"]["risk_level"],
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
                "command": command,
                "risk_level": analysis["details"]["risk_level"],
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            decision=allow_decision,
            decision_in_details=True,
        )

    stdout, stdout_truncated = _truncate_output(result.stdout)
    stderr, stderr_truncated = _truncate_output(result.stderr)
    details = {
        "command": command,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": result.returncode,
        "risk_level": analysis["details"]["risk_level"],
        "risk_reasons": analysis["details"]["risk_reasons"],
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
        "output_char_limit": _MAX_SHELL_OUTPUT_CHARS,
    }
    if result.returncode != 0:
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
    rule_decision = evaluate_rules(
        ToolRequestContext(
            tool_name="start_process",
            params={"command": stripped},
            project_dir=str(project_dir()),
        )
    )
    if rule_decision is not None and rule_decision.action == DecisionAction.DENY:
        return json_response(
            False,
            rule_decision.reason,
            code="policy_denied",
            details={
                "command": command,
                "risk_level": analysis["details"]["risk_level"],
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            decision=rule_decision,
            decision_in_details=True,
        )
    if rule_decision is not None and rule_decision.action == DecisionAction.ASK:
        return json_response(
            False,
            rule_decision.reason,
            code="approval_rejected",
            details={
                "command": command,
                "risk_level": analysis["details"]["risk_level"],
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            decision=rule_decision,
            decision_in_details=True,
        )

    # AI evaluator layer (optional, default off)
    config = current_config()
    ai_enabled = bool(config.get("ai_evaluator_enabled", False))
    ai_timeout = int(config.get("ai_evaluator_timeout", 5))
    ai_fallback = str(config.get("ai_evaluator_fallback_action", "ask"))
    ai_decision = await evaluate_tool_with_ai(
        ToolRequestContext(
            tool_name="start_process",
            params={"command": stripped},
            project_dir=str(project_dir()),
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
                "command": command,
                "risk_level": analysis["details"]["risk_level"],
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            decision=ai_decision,
            decision_in_details=True,
        )
    if ai_decision is not None and ai_decision.action == DecisionAction.ASK:
        return json_response(
            False,
            ai_decision.reason,
            code="approval_rejected",
            details={
                "command": command,
                "risk_level": analysis["details"]["risk_level"],
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            decision=ai_decision,
            decision_in_details=True,
        )
    if ai_decision is not None and ai_decision.action == DecisionAction.ALLOW:
        allow_decision = ai_decision
    elif rule_decision is not None and rule_decision.action == DecisionAction.ALLOW:
        allow_decision = rule_decision
    else:
        rejection = await require_approval(
            "start_process",
            {"command": stripped},
            rejection_message="Process start rejected by user",
            rejection_details={
                "command": command,
                "risk_level": analysis["details"]["risk_level"],
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            request_approval_fn=request_approval,
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
                    "command": command,
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
        )
    except OSError as exc:
        return json_response(
            False,
            f"Failed to start process: {exc}",
            code="command_error",
            details={
                "command": command,
                "risk_level": analysis["details"]["risk_level"],
                "risk_reasons": analysis["details"]["risk_reasons"],
            },
            decision=allow_decision,
            decision_in_details=True,
        )

    session_id = uuid.uuid4().hex[:12]
    session = _ProcessSession(
        session_id=session_id,
        command=command,
        argv=list(analysis["details"]["argv"]),
        cwd=cwd_snapshot,
        process=process,
        risk_level=str(analysis["details"]["risk_level"]),
        risk_reasons=list(analysis["details"]["risk_reasons"]),
    )
    _start_stream_threads(session)
    with _PROCESS_SESSIONS_LOCK:
        _PROCESS_SESSIONS[session_id] = session
    _trim_process_sessions()
    return json_response(
        True,
        "Process started successfully",
        details=session.snapshot(),
        decision=allow_decision,
        decision_in_details=True,
    )


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

    rejection = await require_approval(
        "kill_process",
        {"session_id": session_id, "command": session.command},
        rejection_message="Process termination rejected by user",
        rejection_details={"session_id": session_id, "command": session.command},
        request_approval_fn=request_approval,
    )
    if rejection is not None:
        return rejection

    if session.process.poll() is None:
        try:
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


_MAX_INTERACT_INPUT_CHARS = 4000


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
            with session.lock:  # FIX: thread-safe stdin write
                stdin_stream.write(input + "\n")  # FIX: auto newline on input
                stdin_stream.flush()
            session.record_input(input)
        if close_stdin:
            with session.lock:  # FIX: thread-safe stdin close
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
