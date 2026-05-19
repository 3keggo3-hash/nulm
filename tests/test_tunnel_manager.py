"""Tests for Cloudflare tunnel lifecycle helpers."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import time

import pytest

from claude_bridge import _tunnel_manager


class _BlockingStdout:
    def readline(self) -> str:
        time.sleep(2)
        return ""


class _UrlStdout:
    def __init__(self) -> None:
        self._sent = False

    def readline(self) -> str:
        if self._sent:
            return ""
        self._sent = True
        return "Visit https://mobile-control.trycloudflare.com for your tunnel\n"


class _FakeProcess:
    returncode = None

    def __init__(self, stdout: object) -> None:
        self.stdout = stdout

    def poll(self) -> None:
        return None


def test_wait_for_url_does_not_block_on_silent_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_tunnel_manager, "_TUNNEL_STARTUP_TIMEOUT", 0.2)
    manager = _tunnel_manager.TunnelManager()

    started = time.monotonic()
    with pytest.raises(RuntimeError, match="Timeout waiting for tunnel URL"):
        manager._wait_for_url(_FakeProcess(_BlockingStdout()))  # noqa: SLF001

    assert time.monotonic() - started < 1.0


def test_wait_for_url_extracts_trycloudflare_url() -> None:
    manager = _tunnel_manager.TunnelManager()

    url = manager._wait_for_url(_FakeProcess(_UrlStdout()))  # noqa: SLF001

    assert url == "https://mobile-control.trycloudflare.com"


def test_start_does_not_create_stdout_logfile(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    class FakePopen:
        stdout = _UrlStdout()

        def __init__(self, command: list[str], **kwargs: object) -> None:
            commands.append(command)

        def poll(self) -> None:
            return None

    monkeypatch.setattr(_tunnel_manager.TunnelManager, "is_available", staticmethod(lambda: True))
    monkeypatch.setattr(_tunnel_manager.subprocess, "Popen", FakePopen)

    url = _tunnel_manager.TunnelManager().start(8765)

    assert url == "https://mobile-control.trycloudflare.com"
    assert commands
    assert "--logfile" not in commands[0]
    assert "STDOUT" not in commands[0]
