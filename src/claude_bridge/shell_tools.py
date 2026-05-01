"""Shell-oriented tool implementations for Claude Bridge."""

from __future__ import annotations

import re
import shlex
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

from claude_bridge.tool_utils import json_response, require_approval

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
_DESTRUCTIVE_GIT_SUBCOMMANDS = {"reset", "clean", "checkout", "restore"}
_MAX_SHELL_OUTPUT_CHARS = 12000
_MAX_PROCESS_OUTPUT_READ_CHARS = 12000
_MAX_PROCESS_SESSIONS = 16
_MAX_PROCESS_OUTPUT_CHARS = 200000


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
        if len(_PROCESS_SESSIONS) <= _MAX_PROCESS_SESSIONS:
            return
        ordered = sorted(_PROCESS_SESSIONS.values(), key=lambda session: session.started_at)
        for session in ordered[:-_MAX_PROCESS_SESSIONS]:
            if session.exit_code is None:
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


def _interactive_target(tokens: list[str]) -> str | None:
    if not tokens:
        return None
    head = _command_basename(tokens[0])
    if head != "env":
        return head
    for token in tokens[1:]:
        if "=" in token:
            continue
        return _command_basename(token)
    return None


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
                executable_index = index
                break
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
        if in_single or in_double:
            continue
        if char == "`":
            return "backtick substitution"
        if char == "$" and index + 1 < len(command) and command[index + 1] == "(":
            return "$() substitution"
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


def blocked_command_reason(stripped: str, tokens: list[str]) -> str | None:
    if not tokens:
        return None

    head = _command_basename(tokens[0])
    lower_tokens = [token.lower() for token in tokens]
    normalized = normalize_command_for_safety(stripped)
    shell_construct = _find_unquoted_shell_construct(stripped)
    if shell_construct is not None:
        return shell_construct
    control_tokens_present = any(token in {"|", "&&", ";"} for token in lower_tokens)

    if head == "sudo":
        return "sudo"
    if head == "chmod":
        return "chmod"
    if head == "mkfs":
        return "mkfs"
    if head == "curl" and re.search(r"[|;]|&&", stripped):
        if re.search(r"(?:[|;]|&&)\s*(bash|sh|zsh|python|python3)\b", stripped, re.IGNORECASE):
            return "curl to shell"
    if head == "curl" and control_tokens_present:
        if any(
            shell_name in lower_tokens for shell_name in {"bash", "sh", "zsh", "python", "python3"}
        ):
            return "curl to shell"
    if head == "wget" and re.search(r"[|;]|&&", stripped):
        if re.search(r"(?:[|;]|&&)\s*(bash|sh|zsh|python|python3)\b", stripped, re.IGNORECASE):
            return "wget to shell"
    if head == "wget" and control_tokens_present:
        if any(
            shell_name in lower_tokens for shell_name in {"bash", "sh", "zsh", "python", "python3"}
        ):
            return "wget to shell"
    if head == "dd" and any(token.startswith("if=") for token in lower_tokens[1:]):
        return "dd if="
    _WRAPPER_COMMANDS = {"nohup", "setsid", "script", "timeout"}
    if head in _WRAPPER_COMMANDS:
        return f"{head} wrapper"
    if head == "find" and re.search(
        r"(?:^|\s)find\b.*\|\s*xargs\b.*\brm\b",
        normalized,
    ):
        return "find to xargs rm"
    if head == "find" and any(
        token.startswith("-exec") or token == "-delete" or token == "+"
        for token in lower_tokens[1:]
    ):
        return "find -exec"
    if head == "xargs" and len(lower_tokens) > 1:
        return "xargs"
    if head == "rm":
        option_chars = "".join(
            token.lstrip("-") for token in lower_tokens[1:] if token.startswith("-")
        )
        if "r" in option_chars:
            return "rm -r"
    if head == "git" and len(lower_tokens) > 1:
        subcommand = lower_tokens[1]
        if subcommand == "reset" and any(token == "--hard" for token in lower_tokens[2:]):
            return "git reset --hard"
        if subcommand == "clean" and any(
            "f" in token.lstrip("-") for token in lower_tokens[2:] if token.startswith("-")
        ):
            return "git clean -f"
        if subcommand == "checkout" and any(token == "--" for token in lower_tokens[2:]):
            return "git checkout --"
        if subcommand == "restore" and any(
            token.startswith("--source") for token in lower_tokens[2:]
        ):
            return "git restore --source"
    for index, token in enumerate(lower_tokens[:-1]):
        if token == "|" and lower_tokens[index + 1] in {"bash", "sh", "zsh", "python", "python3"}:
            return f"| {lower_tokens[index + 1]}"
    if any(token in {">", ">>"} for token in tokens) and "/dev" in normalized:
        return "> /dev"
    if ":(){" in normalized:
        return ":(){"
    return None


def analyze_shell_command(command: str) -> dict[str, Any]:
    stripped = command.strip()
    if not stripped:
        return {
            "ok": False,
            "code": "empty_command",
            "message": "Shell command cannot be empty",
            "details": {"command": command},
        }

    try:
        tokens = shlex.split(stripped)
    except ValueError as exc:
        return {
            "ok": False,
            "code": "command_parse_error",
            "message": f"Failed to parse shell command: {exc}",
            "details": {"command": command},
        }
    if not tokens:
        return {
            "ok": False,
            "code": "empty_command",
            "message": "Shell command cannot be empty",
            "details": {"command": command},
        }

    blocked_pattern = blocked_command_reason(stripped, tokens)
    if blocked_pattern is not None:
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
            },
        }

    if is_interactive_command(stripped):
        return {
            "ok": False,
            "code": "interactive_command_unsupported",
            "message": "Interactive commands are not supported",
            "details": {
                "command": command,
                "risk_level": "high",
                "risk_reasons": ["interactive commands are unsupported in MCP stdio mode"],
                "requires_confirmation": False,
            },
        }

    head = _interactive_target(tokens) or tokens[0].lower()
    if (
        head in {"pytest", "ls", "cat"}
        or tokens[:3] == ["python3", "-m", "pytest"]
        or tokens[:2] == ["git", "status"]
        or tokens[:2] == ["git", "diff"]
        or tokens[:2] == ["ruff", "check"]
    ):
        risk_level = "low"
        risk_reasons = ["read-only or standard validation command"]
    elif (
        head == "git"
        and len(tokens) > 1
        and tokens[1].lower() in {"reset", "clean", "push", "checkout", "restore", "revert"}
    ):
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

    return {
        "ok": True,
        "message": "Shell command analysis completed",
        "details": {
            "command": command,
            "normalized_command": stripped,
            "argv": tokens,
            "risk_level": risk_level,
            "risk_reasons": risk_reasons,
            "requires_confirmation": True,
        },
    }


async def run_shell(
    command: str,
    *,
    request_approval: Callable[[str, dict[str, Any]], Awaitable[bool]],
    project_dir: Callable[[], Path],
    shell_timeout: Callable[[], int],
) -> str:
    analysis = analyze_shell_command(command)
    if not analysis["ok"]:
        return json_response(
            False,
            analysis["message"],
            code=analysis["code"],
            details=analysis["details"],
        )

    stripped = command.strip()
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
        return rejection

    cwd_snapshot = project_dir()
    timeout_seconds = shell_timeout()
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
        )

    return json_response(True, "Shell command completed successfully", details=details)


async def start_process(
    command: str,
    *,
    request_approval: Callable[[str, dict[str, Any]], Awaitable[bool]],
    project_dir: Callable[[], Path],
) -> str:
    analysis = analyze_shell_command(command)
    if not analysis["ok"]:
        return json_response(
            False,
            analysis["message"],
            code=analysis["code"],
            details=analysis["details"],
        )

    stripped = command.strip()
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
        return rejection

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
    )


async def read_process_output(session_id: str, offset: int = 0, limit: int = 4000) -> str:
    if offset < 0:
        return json_response(
            False,
            "Offset must be 0 or greater",
            code="invalid_offset",
            details={"offset": offset},
        )
    if limit < 1 or limit > _MAX_PROCESS_OUTPUT_READ_CHARS:
        return json_response(
            False,
            f"Limit must be between 1 and {_MAX_PROCESS_OUTPUT_READ_CHARS}",
            code="invalid_limit",
            details={"limit": limit, "max_limit": _MAX_PROCESS_OUTPUT_READ_CHARS},
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
            "next_offset": offset + len(output) if has_more else None,
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
            stdin_stream.write(input)
            stdin_stream.flush()
            session.record_input(input)
        if close_stdin:
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
