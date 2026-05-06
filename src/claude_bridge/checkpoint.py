"""Git-based checkpointing with plan state snapshots for Claude Bridge."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claude_bridge.config import project_dir


def _checkpoints_dir() -> Path:
    """Return the checkpoints directory, creating it if needed."""
    pd = project_dir()
    cp_dir = pd / ".claude-bridge" / "checkpoints"
    cp_dir.mkdir(parents=True, exist_ok=True)
    return cp_dir


def _plans_dir() -> Path | None:
    """Return the plans directory if it exists, otherwise None."""
    pd = project_dir()
    plans = pd / ".claude-bridge" / "plans"
    return plans if plans.is_dir() else None


def _run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, cwd=project_dir(), timeout=30)


def _safe_filename(name: str) -> str:
    """Sanitize a checkpoint name for use as a filename."""
    keep = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
    sanitized = "".join(c if c in keep else "_" for c in name)
    return sanitized.strip("_") or "unnamed"


def _collect_plan_state() -> list[dict[str, Any]]:
    """Collect plan IDs and statuses from .claude-bridge/plans/."""
    plans = _plans_dir()
    if plans is None:
        return []
    plan_list: list[dict[str, Any]] = []
    for item in sorted(plans.iterdir()):
        if not item.is_file():
            continue
        plan_id = item.stem
        try:
            data = json.loads(item.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            plan_list.append({"id": plan_id, "status": "unknown"})
            continue
        status = data.get("status", "unknown") if isinstance(data, dict) else "unknown"
        plan_list.append({"id": plan_id, "status": status})
    return plan_list


def create_checkpoint(name: str) -> dict[str, Any]:
    """Create a git commit checkpoint with a plan state snapshot.

    Runs ``git add -A`` and ``git commit`` in the project directory, then
    saves a snapshot of the current ``.claude-bridge/plans/`` state under
    ``.claude-bridge/checkpoints/{name}.json``.
    """
    sanitized = _safe_filename(name)

    add_result = _run_git(["git", "add", "-A"])
    if add_result.returncode != 0:
        return {
            "ok": False,
            "error": f"git add failed: {add_result.stderr.strip()}",
            "name": name,
            "step": "add",
        }

    commit_result = _run_git(["git", "commit", "-m", f"checkpoint: {name}"])
    if commit_result.returncode != 0:
        return {
            "ok": False,
            "error": f"git commit failed: {commit_result.stderr.strip()}",
            "name": name,
            "step": "commit",
        }

    rev_result = _run_git(["git", "rev-parse", "HEAD"])
    commit_hash = rev_result.stdout.strip() if rev_result.returncode == 0 else "unknown"

    plan_state = _collect_plan_state()
    timestamp = datetime.now(timezone.utc).isoformat()

    snapshot: dict[str, Any] = {
        "timestamp": timestamp,
        "name": name,
        "git_commit_hash": commit_hash,
        "plans": plan_state,
    }

    cp_dir = _checkpoints_dir()
    snapshot_path = cp_dir / f"{sanitized}.json"
    snapshot_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    return {
        "ok": True,
        "name": name,
        "timestamp": timestamp,
        "git_commit_hash": commit_hash,
        "plan_count": len(plan_state),
        "snapshot_file": str(snapshot_path),
    }


def restore_checkpoint(name: str) -> dict[str, Any]:
    """Restore a previously saved checkpoint.

    Loads the checkpoint snapshot from disk, checks out the associated git
    commit, and returns the restored snapshot info.

    WARNING: This is a potentially destructive operation.  All uncommitted
    changes in the working tree will be overwritten by ``git checkout``.
    """
    sanitized = _safe_filename(name)
    cp_dir = _checkpoints_dir()
    snapshot_path = cp_dir / f"{sanitized}.json"

    if not snapshot_path.is_file():
        return {
            "ok": False,
            "error": f"Checkpoint not found: {name}",
            "name": name,
        }

    try:
        snapshot: dict[str, Any] = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {
            "ok": False,
            "error": f"Failed to read checkpoint snapshot: {exc}",
            "name": name,
        }

    commit_hash = snapshot.get("git_commit_hash", "")
    if not commit_hash:
        return {
            "ok": False,
            "error": "Checkpoint snapshot missing git_commit_hash",
            "name": name,
        }

    status_result = _run_git(["git", "status", "--porcelain"])
    if status_result.stdout.strip():
        return {
            "ok": False,
            "error": ("Uncommitted changes exist. " "Commit or stash before restoring checkpoint."),
            "name": name,
        }

    checkout_result = _run_git(["git", "checkout", str(commit_hash)])
    if checkout_result.returncode != 0:
        return {
            "ok": False,
            "error": f"git checkout failed: {checkout_result.stderr.strip()}",
            "name": name,
            "git_commit_hash": commit_hash,
        }

    return {
        "ok": True,
        "name": snapshot.get("name", name),
        "timestamp": snapshot.get("timestamp", ""),
        "git_commit_hash": commit_hash,
        "plan_count": len(snapshot.get("plans", [])),
        "plans": snapshot.get("plans", []),
    }


def list_checkpoints() -> dict[str, Any]:
    """List all saved checkpoints.

    Scans ``.claude-bridge/checkpoints/`` for JSON snapshot files and
    returns a summary list with name, timestamp, commit hash, and plan count.
    """
    cp_dir = _checkpoints_dir()
    entries: list[dict[str, Any]] = []

    if not cp_dir.is_dir():
        return {"ok": True, "checkpoints": entries, "count": 0}

    for item in sorted(cp_dir.iterdir()):
        if not item.is_file() or not item.suffix == ".json":
            continue
        try:
            data = json.loads(item.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        entries.append(
            {
                "name": data.get("name", item.stem),
                "timestamp": data.get("timestamp", ""),
                "commit_hash": data.get("git_commit_hash", ""),
                "plan_count": len(data.get("plans", [])),
            }
        )

    return {"ok": True, "checkpoints": entries, "count": len(entries)}
