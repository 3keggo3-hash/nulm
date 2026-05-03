"""Git helper functions for Claude Bridge."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

_GIT_TIMEOUT = 30


def _run_git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a git subprocess with standard options and TimeoutExpired handling."""
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_GIT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        # Return a synthetic CompletedProcess that signals failure so
        # callers can treat this the same as any other git error.
        return subprocess.CompletedProcess(
            args=args,
            returncode=-1,
            stdout="",
            stderr=f"git command timed out after {_GIT_TIMEOUT}s: {' '.join(args)}",
        )


def _is_safe_git_path(relative_path: str) -> bool:
    """Check that a relative path does not contain traversal components.

    Compares each path component exactly, so names like ``some..file`` are
    not incorrectly blocked.
    """
    # FIX: normalize backslashes (Windows bypass) and reject absolute paths
    normalized = relative_path.replace("\\", "/")
    if normalized.startswith("/"):
        return False
    return ".." not in normalized.split("/")


def git_commit(
    file_path: str,
    *,
    project_dir: Path,
    message: str | None = None,
) -> dict[str, Any]:
    project_dir = project_dir.resolve()
    result: dict[str, Any] = {
        "init": False,
        "add": False,
        "commit": False,
        "output": "",
    }

    # Locate git repository root
    top_level = _run_git(["git", "rev-parse", "--show-toplevel"], cwd=project_dir)
    if top_level.returncode != 0:
        result["output"] += (
            "No git repository found. Initialize a git repo first with:\n"
            "  git init && git add . && git commit -m 'initial'\n"
        )
        return result
    repo_root = Path(top_level.stdout.strip()).resolve()

    # Resolve the target file relative to the repo root
    target_path = Path(file_path)
    try:
        if target_path.is_absolute():
            relative_file = target_path.resolve().relative_to(repo_root).as_posix()
        else:
            relative_file = (project_dir / target_path).resolve().relative_to(repo_root).as_posix()
    except ValueError as exc:
        result["output"] += f"Resolved path is outside git repo root: {exc}"
        return result

    if not _is_safe_git_path(relative_file):
        result["output"] += "Path traversal detected: relative path references outside project"
        return result

    add = _run_git(["git", "add", relative_file], cwd=repo_root)
    result["add"] = add.returncode == 0
    result["output"] += add.stdout + add.stderr

    commit_message = message or f"bridge: update {relative_file}"
    # Write the message to a temporary file so that content starting with
    # "--" (or any other special sequence) can never be interpreted as a
    # git command-line option.
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
        tmp.write(commit_message)
        tmp_path = tmp.name
        # FIX: restrict file permissions so other users cannot read the message
        os.chmod(tmp_path, 0o600)
    try:
        commit = _run_git(["git", "commit", "-F", tmp_path], cwd=repo_root)
    finally:
        os.unlink(tmp_path)
    result["commit"] = commit.returncode == 0
    result["output"] += commit.stdout + commit.stderr
    return result


def git_status_snapshot(project_dir: Path) -> dict[str, Any]:
    result = _run_git(["git", "status", "--short"], cwd=project_dir)
    return {
        "ok": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.returncode,
    }
