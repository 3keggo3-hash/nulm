"""Process session management for long-running shell processes."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from claude_bridge import _shell_constants as _const

logger = logging.getLogger(__name__)


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
        self.lock = threading.RLock()
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
            if len(self.output) >= _const._MAX_PROCESS_OUTPUT_CHARS:
                return
            remaining = _const._MAX_PROCESS_OUTPUT_CHARS - len(self.output)
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
        sessions = list(_PROCESS_SESSIONS.values())
    for session in sessions:
        session.refresh_status()
    completed = [s for s in sessions if s.exit_code is not None]
    for s in completed:
        with s.lock:
            output_len = len(s.output)
            s.output = s.output[: min(output_len, 200)]
            s.command = s.command[:200]
    with _PROCESS_SESSIONS_LOCK:
        if len(_PROCESS_SESSIONS) <= _const._MAX_PROCESS_SESSIONS:
            return
        completed.sort(key=lambda session: session.completed_at or session.started_at)
        for session in completed:
            _PROCESS_SESSIONS.pop(session.session_id, None)
            if len(_PROCESS_SESSIONS) <= _const._MAX_PROCESS_SESSIONS:
                return
        logger.warning(
            "Process session limit %d reached with %d running sessions; refusing new sessions",
            _const._MAX_PROCESS_SESSIONS,
            len(_PROCESS_SESSIONS),
        )


def _process_session_capacity() -> dict[str, int | bool]:
    _trim_process_sessions()
    with _PROCESS_SESSIONS_LOCK:
        running_count = 0
        for session in _PROCESS_SESSIONS.values():
            session.refresh_status()
            if session.exit_code is None:
                running_count += 1
        count = len(_PROCESS_SESSIONS)
    return {
        "available": count < _const._MAX_PROCESS_SESSIONS,
        "count": count,
        "running_count": running_count,
        "max_sessions": _const._MAX_PROCESS_SESSIONS,
    }


def _register_process_session(session: _ProcessSession) -> bool:
    """Register a new process session atomically with session-limit trimming."""
    with _PROCESS_SESSIONS_LOCK:
        _trim_process_sessions()
        if len(_PROCESS_SESSIONS) >= _const._MAX_PROCESS_SESSIONS:
            return False
        _PROCESS_SESSIONS[session.session_id] = session
        return True


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
