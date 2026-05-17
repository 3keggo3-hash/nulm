"""Smoke test for launching Nulm over stdio."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


class TestStdioSmoke:
    def test_python_module_mcp_server_starts_under_stdio(self, tmp_path: Path):
        env = dict(os.environ)
        env["CLAUDE_BRIDGE_PROJECT_DIR"] = str(tmp_path)
        proc = subprocess.Popen(
            [sys.executable, "-m", "claude_bridge.mcp_server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        try:
            time.sleep(0.3)
            assert proc.poll() is None, "mcp server exited immediately during stdio startup"
        finally:
            proc.terminate()
            stdout, stderr = proc.communicate(timeout=5)

        assert stderr == ""
        assert stdout == ""
