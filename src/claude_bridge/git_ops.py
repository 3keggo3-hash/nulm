"""Git helper functions for Claude Bridge."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def git_commit(file_path: str, *, project_dir: Path, message: str | None = None) -> dict[str, Any]:
    project_dir = project_dir.resolve()
    result: dict[str, Any] = {"init": True, "add": False, "commit": False, "output": ""}

    repo_root = project_dir
    top_level = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    if top_level.returncode == 0:
        repo_root = Path(top_level.stdout.strip()).resolve()
    else:
        init = subprocess.run(
            ["git", "init"],
            cwd=project_dir,
            capture_output=True,
            text=True,
        )
        result["init"] = init.returncode == 0
        result["output"] += init.stdout + init.stderr

    target_path = Path(file_path)
    try:
        if target_path.is_absolute():
            relative_file = target_path.resolve().relative_to(repo_root).as_posix()
        else:
            relative_file = ((project_dir / target_path).resolve()).relative_to(repo_root).as_posix()
    except ValueError as exc:
        result["output"] += f"Resolved path is outside git repo root: {exc}"
        return result

    add = subprocess.run(
        ["git", "add", relative_file],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    result["add"] = add.returncode == 0
    result["output"] += add.stdout + add.stderr

    commit = subprocess.run(
        ["git", "commit", "-m", message or f"bridge: update {relative_file}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    result["commit"] = commit.returncode == 0
    result["output"] += commit.stdout + commit.stderr
    return result


def git_status_snapshot(project_dir: Path) -> dict[str, Any]:
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    return {
        "ok": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.returncode,
    }
