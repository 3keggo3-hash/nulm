"""Git worktree awareness for parallel development workflows."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def _run_git(args: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            shell=False,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return -1, "", "git not found"


def is_worktree(repo_root: Path | None = None) -> bool:
    """Check if current directory is a git worktree (not main)."""
    if repo_root is None:
        repo_root = Path.cwd()
    rc, stdout, _ = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=repo_root)
    if rc != 0 or stdout != "true":
        return False
    rc2, main_or_worktree, _ = _run_git(
        ["rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo_root,
    )
    if rc2 == 0:
        return main_or_worktree != "HEAD"
    return False


def list_worktrees(repo_root: Path | None = None) -> list[dict[str, Any]]:
    """List all worktrees in the repository."""
    if repo_root is None:
        repo_root = Path.cwd()
    rc, stdout, _ = _run_git(
        ["worktree", "list", "--porcelain"],
        cwd=repo_root,
    )
    if rc != 0:
        return []
    worktrees = []
    current: dict[str, Any] = {}
    for line in stdout.splitlines():
        if line.startswith("path "):
            if current:
                worktrees.append(current)
            current = {"path": line[5:]}
        elif line.startswith("HEAD "):
            current["head"] = line[5:]
        elif line.startswith("branch "):
            current["branch"] = line[7:]
        elif line == "detached":
            current["detached"] = True
    if current:
        worktrees.append(current)
    return worktrees


def get_active_branch_name(repo_root: Path | None = None) -> str | None:
    """Get the current branch name for the repository."""
    if repo_root is None:
        repo_root = Path.cwd()
    rc, stdout, _ = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root)
    if rc == 0:
        return stdout
    return None


def has_dirty_worktree_context(repo_root: Path | None = None) -> bool:
    """Check if any worktree has uncommitted changes that could pollute context."""
    if repo_root is None:
        repo_root = Path.cwd()
    worktrees = list_worktrees(repo_root)
    for wt in worktrees:
        wt_path = Path(wt["path"])
        if not wt_path.exists():
            continue
        rc, stdout, _ = _run_git(["status", "--porcelain"], cwd=wt_path)
        if rc == 0 and stdout.strip():
            return True
    return False


def worktree_status(repo_root: Path | None = None) -> dict[str, Any]:
    """Get comprehensive worktree status."""
    if repo_root is None:
        repo_root = Path.cwd()
    is_in_worktree = is_worktree(repo_root)
    worktrees = list_worktrees(repo_root)
    current_branch = get_active_branch_name(repo_root)
    dirty = has_dirty_worktree_context(repo_root)

    return {
        "is_worktree": is_in_worktree,
        "current_branch": current_branch,
        "worktrees": worktrees,
        "has_dirty_context": dirty,
        "repo_root": str(repo_root.resolve()),
    }
