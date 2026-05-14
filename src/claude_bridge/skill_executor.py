"""Skill execution in a bounded subprocess."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claude_bridge._shell_safety import _check_skill_code_blocked
from claude_bridge.skill_registry import get_registry

DEFAULT_TIMEOUT_SECONDS = 30
SKILL_DIR = Path(".claude-bridge/skills")
ALLOWED_PERMISSIONS = {"read", "analyze", "write", "execute"}


@dataclass
class SkillResult:
    """Result from skill execution."""

    status: str
    output: str = ""
    error: str = ""
    duration: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "duration": self.duration,
        }


class SkillExecutor:
    """Executes approved skills in a bounded subprocess.

    This is not an OS sandbox. Skill code is user-approved Python and is isolated only by
    timeout, context filtering, and a reduced environment.
    """

    def __init__(self, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> None:
        self.timeout = timeout

    def _check_permissions(self, required: list[str]) -> tuple[bool, list[str]]:
        """Verify required permissions are allowed.

        Returns (allowed, denied).
        """
        denied = [p for p in required if p not in ALLOWED_PERMISSIONS]
        return len(denied) == 0, denied

    def _prepare_context(self, context: dict[str, Any]) -> dict[str, Any]:
        """Prepare execution context for the skill.

        Filters sensitive keys and adds safe defaults.
        """
        safe_keys = {
            "project_dir",
            "task",
            "files",
            "user_input",
            "env",
            "cwd",
        }
        return {k: v for k, v in context.items() if k in safe_keys}

    def run_skill(
        self,
        name: str,
        context: dict[str, Any] | None = None,
        *,
        registry_root: Path | None = None,
    ) -> SkillResult:
        """Execute a skill by name with the given context.

        Runs the skill in a bounded subprocess with timeout.
        """
        import subprocess

        registry = get_registry(registry_root)
        loaded = registry.get_loaded().get(name)
        if loaded is None:
            success, _ = registry.load_skill(name)
            if not success:
                return SkillResult(
                    status="error",
                    error=f"Skill '{name}' not found or failed to load",
                )
            loaded = registry.get_loaded().get(name)
            if loaded is None:
                return SkillResult(
                    status="error",
                    error=f"Skill '{name}' failed to load",
                )

        meta = loaded.meta
        allowed, denied = self._check_permissions(meta.permissions)
        if not allowed:
            return SkillResult(
                status="denied",
                error=f"Permissions denied: {denied}",
            )

        context = context or {}
        safe_context = self._prepare_context(context)

        skill_code = loaded.code
        if blocked_reason := _check_skill_code_blocked(skill_code):
            return SkillResult(status="denied", error=blocked_reason)
        start = time.monotonic()

        try:
            SKILL_DIR.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".py",
                delete=False,
                dir=SKILL_DIR,
            ) as f:
                f.write(skill_code)
                skill_file = f.name

            try:
                result = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        self._build_execution_wrapper(skill_file, safe_context),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    cwd=os.getcwd(),
                    env=_skill_env(),
                )
            finally:
                Path(skill_file).unlink(missing_ok=True)

            duration = time.monotonic() - start
            registry.record_hit(name)

            if result.returncode == 0:
                return SkillResult(
                    status="success",
                    output=result.stdout,
                    error=result.stderr,
                    duration=duration,
                )
            else:
                return SkillResult(
                    status="failed",
                    output=result.stdout,
                    error=result.stderr or f"Exit code: {result.returncode}",
                    duration=duration,
                )

        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start
            return SkillResult(
                status="timeout",
                error=f"Skill execution timed out after {self.timeout}s",
                duration=duration,
            )
        except Exception as e:
            duration = time.monotonic() - start
            return SkillResult(
                status="error",
                error=str(e),
                duration=duration,
            )

    def _build_execution_wrapper(self, skill_file: str, context: dict[str, Any]) -> str:
        """Build the execution wrapper code.

        Imports skill module, runs the run() function with context.
        """
        context_json = json.dumps(context)
        return f"""
import sys
import json
sys.path.insert(0, '.')

context = json.loads({context_json!r})

try:
    with open({skill_file!r}, 'r') as f:
        code = f.read()
    ns = {{}}
    exec(compile(code, {skill_file!r}, 'exec'), ns)
    if 'run' in ns:
        result = ns['run'](context)
        if result is not None:
            print(json.dumps(result))
except Exception as e:
    print(json.dumps({{"error": str(e)}}), file=sys.stderr)
    sys.exit(1)
"""


_executor: SkillExecutor | None = None


def _skill_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for key in ("PATH", "SYSTEMROOT", "WINDIR"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    return env


def get_executor() -> SkillExecutor:
    """Return the shared SkillExecutor instance."""
    global _executor
    if _executor is None:
        _executor = SkillExecutor()
    return _executor
