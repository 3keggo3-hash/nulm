"""Cloudflare Tunnel manager for exposing local services externally."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import queue
import shutil
import subprocess
import threading
import time
from typing import Any

_TUNNEL_STARTUP_TIMEOUT = 30


class TunnelManager:
    """Manages cloudflared tunnel lifecycle."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[Any] | None = None
        self._lock = threading.Lock()
        self._url: str | None = None
        self._stopped = False

    @staticmethod
    def is_available() -> bool:
        """Check if cloudflared is installed."""
        return shutil.which("cloudflared") is not None

    def start(self, port: int) -> str:
        """Start cloudflared tunnel and return the tunnel URL."""
        with self._lock:
            if self._process is not None:
                raise RuntimeError("Tunnel already started")
            if self._stopped:
                raise RuntimeError("Tunnel manager has been stopped")

            if not self.is_available():
                raise RuntimeError(
                    "cloudflared not found. Install with:\n"
                    "  macOS:  brew install cloudflared\n"
                    "  Linux:  curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o ~/.local/bin/cloudflared && chmod +x ~/.local/bin/cloudflared\n"
                    "  Win:    winget install cloudflare.cloudflared\n"
                    "Or download from: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
                )

            command = [
                "cloudflared",
                "tunnel",
                "--url",
                f"http://localhost:{port}",
                "--metrics",
                "localhost:0",
            ]
            self._process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            self._url = self._wait_for_url(self._process)
            return self._url

    def _wait_for_url(self, process: subprocess.Popen[Any]) -> str:
        """Wait for cloudflared to output the tunnel URL."""
        start_time = time.monotonic()
        url: str | None = None
        lines: queue.Queue[str] = queue.Queue()

        def read_stdout() -> None:
            stdout = process.stdout
            if stdout is None:
                return
            while True:
                line = stdout.readline()
                if not line:
                    return
                lines.put(line)

        reader = threading.Thread(target=read_stdout, daemon=True)
        reader.start()

        while time.monotonic() - start_time < _TUNNEL_STARTUP_TIMEOUT:
            if process.poll() is not None:
                raise RuntimeError(f"cloudflared exited unexpectedly: {process.returncode}")
            try:
                line = lines.get(timeout=0.1)
            except queue.Empty:
                time.sleep(0.1)
                continue
            if "trycloudflare.com" in line or "cloudflared tunnel" in line.lower():
                for word in line.split():
                    if "trycloudflare.com" in word:
                        url = word.strip().rstrip("/")
                        break
                    if word.startswith("https://") and "cloudflare" in word:
                        url = word.strip().rstrip("/")
                        break
            if url:
                break
            if "ERR" in line.upper() and "Failed" in line:
                raise RuntimeError(f"cloudflared error: {line.strip()}")

        if not url:
            raise RuntimeError("Timeout waiting for tunnel URL from cloudflared")
        return url

    def stop(self) -> None:
        """Gracefully stop the tunnel."""
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            if self._process is None:
                return
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    self._process.kill()
                except OSError:
                    pass
            self._process = None

    def __enter__(self) -> "TunnelManager":
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop()
