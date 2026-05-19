"""Terminal WebSocket server for the control plane dashboard."""

from __future__ import annotations

import fcntl
import json
import os
import pty
import select
import signal
import subprocess
import sys
import threading
from typing import Any

try:
    import websockets  # type: ignore[import]
except ImportError:
    websockets = None  # type: ignore[assignment]


DASHBOARD_TOKEN_HEADER = "X-Claude-Bridge-Token"


class TerminalSession:
    def __init__(self, token: str) -> None:
        self.token = token
        self.master_fd: int | None = None
        self.slave_fd: int | None = None
        self.process: subprocess.Popen | None = None
        self.running = False
        self.lock = threading.Lock()

    def start(self, shell: str | None = None) -> bool:
        if self.running:
            return False
        shell = shell or os.environ.get("SHELL", "/bin/bash")
        try:
            self.master_fd, self.slave_fd = pty.openpty()
            self.process = subprocess.Popen(
                [shell],
                stdin=self.slave_fd,
                stdout=self.slave_fd,
                stderr=self.slave_fd,
                start_new_session=True,
                env=self._build_env(),
            )
            self.running = True
            for fd in (self.master_fd, self.slave_fd):
                if fd is not None:
                    fl = fcntl.fcntl(fd, fcntl.F_GETFL)
                    fcntl.fcntl(fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
            return True
        except Exception:
            self._cleanup()
            return False

    def _build_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update({
            "TERM": "xterm-256color",
            "COLORTERM": "truecolor",
            "LC_ALL": "en_US.UTF-8",
        })
        return env

    def write(self, data: bytes) -> int:
        with self.lock:
            if not self.running or self.master_fd is None:
                return 0
            try:
                return os.write(self.master_fd, data)
            except OSError:
                return 0

    def read(self, timeout: float = 0.1) -> bytes:
        if not self.running or self.master_fd is None:
            return b""
        try:
            ready, _, _ = select.select([self.master_fd], [], [], timeout)
            if ready:
                return os.read(self.master_fd, 4096)
        except OSError:
            pass
        return b""

    def resize(self, rows: int, cols: int) -> bool:
        if not self.running or self.slave_fd is None:
            return False
        try:
            import fcntl
            import struct
            import termios
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self.slave_fd, termios.TIOCSWINSZ, winsize)
            return True
        except Exception:
            return False

    def is_alive(self) -> bool:
        if not self.running:
            return False
        if self.process is None:
            return False
        return self.process.poll() is None

    def close(self) -> None:
        self._cleanup()

    def _cleanup(self) -> None:
        with self.lock:
            self.running = False
            if self.process:
                try:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                except (OSError, ProcessLookupError):
                    pass
                self.process = None
            for fd in (self.master_fd, self.slave_fd):
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
            self.master_fd = None
            self.slave_fd = None


_ACTIVE_SESSIONS: dict[str, TerminalSession] = {}
_SESSIONS_LOCK = threading.Lock()


def create_terminal_session(session_id: str, token: str) -> TerminalSession:
    with _SESSIONS_LOCK:
        if session_id in _ACTIVE_SESSIONS:
            _ACTIVE_SESSIONS[session_id].close()
        session = TerminalSession(token)
        _ACTIVE_SESSIONS[session_id] = session
        return session


def get_terminal_session(session_id: str) -> TerminalSession | None:
    with _SESSIONS_LOCK:
        return _ACTIVE_SESSIONS.get(session_id)


def close_terminal_session(session_id: str) -> None:
    with _SESSIONS_LOCK:
        if session_id in _ACTIVE_SESSIONS:
            _ACTIVE_SESSIONS[session_id].close()
            del _ACTIVE_SESSIONS[session_id]


async def terminal_handler(
    websocket: Any,
    path: str,
    token: str,
) -> None:
    if path != "/api/terminal":
        await websocket.close(4004, "Invalid path")
        return
    session_id = None
    try:
        await websocket.accept()
        auth_header = websocket.request_headers.get(DASHBOARD_TOKEN_HEADER, "")
        auth_token = auth_header or ""
        if not hmac_compare(auth_token, token):
            await websocket.close(4003, "Unauthorized")
            return
        session_id = str(websocket.id) if hasattr(websocket, "id") else str(id(websocket))
        session = create_terminal_session(session_id, token)
        if not session.start():
            await websocket.close(4005, "Failed to start shell")
            return
        output_thread = threading.Thread(
            target=_read_output,
            args=(session, websocket),
            daemon=True,
        )
        output_thread.start()
        async for message in websocket:
            if isinstance(message, bytes):
                session.write(message)
            else:
                try:
                    data = json.loads(message)
                    if data.get("type") == "resize":
                        rows = data.get("rows", 24)
                        cols = data.get("cols", 80)
                        session.resize(rows, cols)
                    elif data.get("type") == "input":
                        input_data = data.get("data", "")
                        if isinstance(input_data, str):
                            session.write(input_data.encode("utf-8"))
                        elif isinstance(input_data, bytes):
                            session.write(input_data)
                except (json.JSONDecodeError, KeyError):
                    session.write(message.encode("utf-8") if isinstance(message, str) else message)
    except Exception:
        pass
    finally:
        if session_id:
            close_terminal_session(session_id)


def _read_output(session: TerminalSession, websocket: Any) -> None:
    while session.is_alive():
        data = session.read(timeout=0.05)
        if data:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(websocket.send(data))
                else:
                    loop.run_until_complete(websocket.send(data))
            except Exception:
                pass


def hmac_compare(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b):
        result |= ord(x) ^ ord(y)
    return result == 0


if __name__ == "__main__":
    print("This module should be imported, not run directly.")
    sys.exit(1)