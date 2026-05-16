"""Git helper functions for Claude Bridge."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

_GIT_TIMEOUT = 30

_GIT_ROOT_CACHE: dict[str, str] = {}
_GIT_ROOT_CACHE_LOCK = threading.Lock()


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


def _git_root(cwd: Path) -> str | None:
    """Return the git repository root for *cwd*, with caching."""
    cwd_str = str(cwd)
    with _GIT_ROOT_CACHE_LOCK:
        cached = _GIT_ROOT_CACHE.get(cwd_str)
    if cached is not None:
        return cached
    result = _run_git(["git", "rev-parse", "--show-toplevel"], cwd=cwd)
    if result.returncode != 0:
        return None
    root = result.stdout.strip()
    with _GIT_ROOT_CACHE_LOCK:
        _GIT_ROOT_CACHE[cwd_str] = root
    return root


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
    root = _git_root(project_dir)
    if root is None:
        result["output"] += (
            "No git repository found. Initialize a git repo first with:\n"
            "  git init && git add . && git commit -m 'initial'\n"
        )
        return result
    repo_root = Path(root).resolve()

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

    commit_message = message or f"bridge: update {relative_file}"
    try:
        add_result = subprocess.run(
            ["git", "add", relative_file],
            text=True,
            capture_output=True,
            cwd=repo_root,
            timeout=_GIT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        add_result = subprocess.CompletedProcess(
            args=["git", "add", relative_file],
            returncode=-1,
            stdout="",
            stderr=f"git add timed out after {_GIT_TIMEOUT}s",
        )
    result["add"] = add_result.returncode == 0
    result["output"] += add_result.stdout + add_result.stderr

    if add_result.returncode != 0:
        return result

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
        tmp.write(commit_message)
        tmp_path = tmp.name
        os.chmod(tmp_path, 0o600)
    try:
        try:
            commit_result = subprocess.run(
                ["git", "commit", "-F", tmp_path],
                text=True,
                capture_output=True,
                cwd=repo_root,
                timeout=_GIT_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            commit_result = subprocess.CompletedProcess(
                args=["git", "commit", "-F", tmp_path],
                returncode=-1,
                stdout="",
                stderr=f"git commit timed out after {_GIT_TIMEOUT}s",
            )
    finally:
        os.unlink(tmp_path)

    result["commit"] = commit_result.returncode == 0
    result["output"] += commit_result.stdout + commit_result.stderr
    return result


def git_status_snapshot(project_dir: Path) -> dict[str, Any]:
    result = _run_git(["git", "status", "--short"], cwd=project_dir)
    return {
        "ok": result.returncode == 0,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.returncode,
    }


def commit_changes(
    message: str,
    *,
    project_dir: Path,
) -> dict[str, Any]:
    project_dir = project_dir.resolve()
    result: dict[str, Any] = {
        "add": False,
        "commit": False,
        "output": "",
    }

    root = _git_root(project_dir)
    if root is None:
        result["output"] += (
            "No git repository found. Initialize a git repo first with:\n"
            "  git init && git add . && git commit -m 'initial'\n"
        )
        return result
    repo_root = Path(root).resolve()

    add = _run_git(["git", "add", "-A"], cwd=repo_root)
    result["add"] = add.returncode == 0
    result["output"] += add.stdout + add.stderr

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
        tmp.write(message)
        tmp_path = tmp.name
        os.chmod(tmp_path, 0o600)
    try:
        commit = _run_git(["git", "commit", "-F", tmp_path], cwd=repo_root)
    finally:
        os.unlink(tmp_path)
    result["commit"] = commit.returncode == 0
    result["output"] += commit.stdout + commit.stderr
    return result


_CHANGED_FILE_RE = re.compile(r"^\+\+\+\s+b/(.*)")
_HUNK_HEADER_RE = re.compile(r"^@@\s+-?\d+,?\d*\s+\+?\d+,?\d*\s+@@")
_ADDED_LINE_RE = re.compile(r"^\+[^+]")
_REMOVED_LINE_RE = re.compile(r"^\-[^-]")


def generate_pr_description(diff_text: str) -> dict[str, Any]:
    changed_files: list[str] = []
    additions = 0
    deletions = 0
    seen_files: set[str] = set()

    for line in diff_text.splitlines():
        # Changed files (new file path in +++ b/...)
        m = _CHANGED_FILE_RE.match(line)
        if m:
            fname = m.group(1)
            if fname not in seen_files:
                seen_files.add(fname)
                changed_files.append(fname)
            continue

        # Skip hunk headers
        if _HUNK_HEADER_RE.match(line):
            continue

        # Count additions / deletions
        if _ADDED_LINE_RE.match(line):
            additions += 1
        elif _REMOVED_LINE_RE.match(line):
            deletions += 1

    extensions: set[str] = set()
    for fname in changed_files:
        stem = fname.rsplit("/", 1)[-1]
        if "." in stem:
            ext = stem.rsplit(".", 1)[-1].lower()
            if ext:
                extensions.add(ext)
    affected_languages = sorted(extensions)

    summary = diff_text[:200]

    return {
        "changed_files": changed_files,
        "additions": additions,
        "deletions": deletions,
        "affected_languages": affected_languages,
        "summary": summary,
    }


def git_blame(file_path: str, *, project_dir: Path) -> list[dict[str, Any]]:
    """Return git blame info for each line in the file."""
    from datetime import datetime, timezone

    blame_entries: list[dict[str, Any]] = []
    root = _git_root(project_dir)
    if root is None:
        return blame_entries
    repo_root = Path(root).resolve()

    target_path = Path(file_path)
    try:
        if target_path.is_absolute():
            relative_file = target_path.resolve().relative_to(repo_root).as_posix()
        else:
            relative_file = (project_dir / target_path).resolve().relative_to(repo_root).as_posix()
    except ValueError:
        return blame_entries

    if not _is_safe_git_path(relative_file):
        return blame_entries

    result = _run_git(["git", "blame", "--line-porcelain", relative_file], cwd=repo_root)
    if result.returncode != 0:
        return blame_entries

    current_entry: dict[str, Any] = {}
    for line in result.stdout.splitlines():
        if line.startswith("hash "):
            current_entry["hash"] = line[5:]
        elif line.startswith("author "):
            current_entry["author"] = line[8:]
        elif line.startswith("committer-time "):
            try:
                ts = int(line.split(" ", 1)[1])
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                current_entry["time"] = dt.isoformat()
            except (ValueError, IndexError):
                pass
        elif line.startswith("\t"):
            current_entry["content"] = line[1:]
            if current_entry.get("hash"):
                blame_entries.append(current_entry)
            current_entry = {}
    if current_entry.get("hash"):
        blame_entries.append(current_entry)

    return blame_entries


_BRANCE_NAME_RE = re.compile(r"^[a-zA-Z0-9._/-]+$")


def git_branch_list(project_dir: Path) -> dict[str, Any]:
    """List local branches with current HEAD indicator and tracking info."""
    root = _git_root(project_dir)
    if root is None:
        return {"ok": False, "branches": [], "output": "No git repository found"}
    repo_root = Path(root).resolve()

    result = _run_git(["git", "branch", "-v"], cwd=repo_root)
    if result.returncode != 0:
        return {"ok": False, "branches": [], "output": result.stderr}

    branches: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        current = line.startswith("*")
        parts = line[2:].split(None, 1)
        name = parts[0] if parts else ""
        tracking = parts[1] if len(parts) > 1 else ""
        branches.append({"name": name, "current": current, "tracking": tracking})

    return {"ok": True, "branches": branches, "output": result.stdout}


def git_branch_create(
    name: str,
    *,
    project_dir: Path,
    base_branch: str | None = None,
) -> dict[str, Any]:
    """Create a new branch with optional base branch."""
    root = _git_root(project_dir)
    if root is None:
        return {"ok": False, "output": "No git repository found"}

    if not _BRANCE_NAME_RE.match(name):
        return {
            "ok": False,
            "output": f"Invalid branch name '{name}'. Use alphanumeric, dots, underscores, hyphens, slashes.",
        }

    repo_root = Path(root).resolve()
    base = base_branch or "HEAD"
    result = _run_git(["git", "branch", name, base], cwd=repo_root)
    if result.returncode != 0:
        return {"ok": False, "output": result.stderr}
    return {"ok": True, "output": f"Created branch '{name}' from {base}"}


def git_merge(
    target: str,
    *,
    project_dir: Path,
    no_fast_forward: bool = False,
    squash: bool = False,
) -> dict[str, Any]:
    """Merge a branch into the current branch with conflict detection."""
    root = _git_root(project_dir)
    if root is None:
        return {"ok": False, "output": "No git repository found"}

    repo_root = Path(root).resolve()
    cmd = ["git", "merge"]
    if no_fast_forward:
        cmd.append("--no-ff")
    if squash:
        cmd.append("--squash")
    cmd.append(target)

    result = _run_git(cmd, cwd=repo_root)
    has_conflicts = result.returncode != 0 and "CONFLICT" in result.stdout + result.stderr

    conflicts: list[str] = []
    if has_conflicts:
        status = _run_git(["git", "status", "--porcelain"], cwd=repo_root)
        for line in status.stdout.splitlines():
            if line.startswith("UU ") or line.startswith("AA ") or line.startswith("DD "):
                parts = line[3:].strip().split(" -> ")
                if parts:
                    conflicts.append(parts[-1])

    return {
        "ok": result.returncode == 0,
        "merged": target,
        "conflicts": conflicts,
        "has_conflicts": has_conflicts,
        "output": result.stdout + result.stderr,
    }


def git_stash(
    *,
    project_dir: Path,
    message: str | None = None,
    include_untracked: bool = True,
) -> dict[str, Any]:
    """Stash working directory changes with optional message."""
    root = _git_root(project_dir)
    if root is None:
        return {"ok": False, "output": "No git repository found"}
    repo_root = Path(root).resolve()

    cmd = ["git", "stash"]
    if include_untracked:
        cmd.append("-u")
    if message:
        cmd.extend(["-m", message])

    result = _run_git(cmd, cwd=repo_root)
    return {
        "ok": result.returncode == 0,
        "stashed": result.returncode == 0,
        "output": result.stdout + result.stderr,
    }


def git_stash_pop(
    *,
    project_dir: Path,
    restore_conflicts: bool = False,
) -> dict[str, Any]:
    """Pop the most recent stash, optionally with conflict restoration."""
    root = _git_root(project_dir)
    if root is None:
        return {"ok": False, "output": "No git repository found"}
    repo_root = Path(root).resolve()

    cmd = ["git", "stash", "pop"]
    result = _run_git(cmd, cwd=repo_root)
    return {
        "ok": result.returncode == 0,
        "output": result.stdout + result.stderr,
    }
