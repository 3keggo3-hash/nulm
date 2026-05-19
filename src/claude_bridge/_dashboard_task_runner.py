"""Dashboard task runner — runs agent tasks via CLI."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from claude_bridge.control_plane import create_task, update_task_status

_ACTIVE_AGENT_TASKS: dict[str, dict[str, Any]] = {}
_ACTIVE_AGENT_TASKS_LOCK = threading.Lock()


def run_dashboard_task(task: str, *, mode: str = "agent_loop") -> dict[str, Any]:
    """Start an agent task from the dashboard."""
    task_record = create_task(
        title=task[:80],
        summary=f"Agent task: {task[:50]}...",
        status="planning",
        metadata={"source": "dashboard", "kind": "agent_task", "mode": mode, "task": task},
    )
    task_id = task_record["id"]
    with _ACTIVE_AGENT_TASKS_LOCK:
        _ACTIVE_AGENT_TASKS[task_id] = {
            "task_id": task_id,
            "task": task,
            "mode": mode,
            "status": "planning",
            "output": [],
            "started_at": time.time(),
            "updated_at": time.time(),
        }
    threading.Thread(
        target=_run_agent_task_background,
        args=(task_id, task, mode),
        daemon=True,
    ).start()
    return {"ok": True, "task_id": task_id, "record": task_record}


def get_dashboard_task_status(task_id: str) -> dict[str, Any]:
    """Get status + output for a dashboard agent task."""
    with _ACTIVE_AGENT_TASKS_LOCK:
        session = _ACTIVE_AGENT_TASKS.get(task_id)
    if session is None:
        create_task(title="unknown", summary="", status="failed", metadata={})
        return {"ok": False, "error": "task_not_found", "task_id": task_id}
    return {
        "ok": True,
        "task_id": task_id,
        "status": session["status"],
        "output": session["output"] if "output" in session else [],
        "updated_at": session.get("updated_at"),
    }


def _run_agent_task_background(task_id: str, task: str, mode: str) -> None:
    try:
        update_task_status(task_id, "running", metadata={"source": "dashboard"})
        with _ACTIVE_AGENT_TASKS_LOCK:
            _ACTIVE_AGENT_TASKS[task_id]["status"] = "running"
            _ACTIVE_AGENT_TASKS[task_id]["updated_at"] = time.time()

        result = subprocess.run(
            [sys.executable, "-m", "claude_bridge", "workflow-preview", "--mode", mode, "--target", task],
            cwd=Path.cwd(),
            env=dict(__import__("os").environ),
            capture_output=True,
            text=True,
            timeout=120,
            shell=False,
        )
        output_lines = []
        if result.stdout.strip():
            output_lines.append(result.stdout.strip()[:500])
        if result.stderr.strip():
            output_lines.append("stderr: " + result.stderr.strip()[:200])
        output_lines.append(f"exit={result.returncode}")

        with _ACTIVE_AGENT_TASKS_LOCK:
            _ACTIVE_AGENT_TASKS[task_id]["status"] = "completed" if result.returncode == 0 else "failed"
            _ACTIVE_AGENT_TASKS[task_id]["output"] = output_lines
            _ACTIVE_AGENT_TASKS[task_id]["updated_at"] = time.time()

        update_task_status(
            task_id,
            "completed" if result.returncode == 0 else "failed",
            summary=output_lines[0] if output_lines else f"Done (exit={result.returncode})",
            metadata={
                "source": "dashboard",
                "returncode": result.returncode,
            },
        )
    except subprocess.TimeoutExpired:
        with _ACTIVE_AGENT_TASKS_LOCK:
            _ACTIVE_AGENT_TASKS[task_id]["status"] = "failed"
            _ACTIVE_AGENT_TASKS[task_id]["output"] = ["Task timed out after 120s"]
            _ACTIVE_AGENT_TASKS[task_id]["updated_at"] = time.time()
        update_task_status(task_id, "failed", summary="Task timed out after 120s", metadata={"source": "dashboard"})
    except Exception as exc:
        with _ACTIVE_AGENT_TASKS_LOCK:
            _ACTIVE_AGENT_TASKS[task_id]["status"] = "failed"
            _ACTIVE_AGENT_TASKS[task_id]["output"] = [f"Error: {str(exc)}"]
            _ACTIVE_AGENT_TASKS[task_id]["updated_at"] = time.time()
        update_task_status(task_id, "failed", summary=str(exc), metadata={"source": "dashboard", "error": str(exc)})