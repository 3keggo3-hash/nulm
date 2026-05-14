"""File location and git history utilities for Bridge Detective."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def find_related_files(file_path: str, project_dir_path: Path) -> list[str]:
    """Find files related to the given file by import/name patterns."""
    related: list[str] = []
    target = Path(file_path)
    if not target.exists():
        target = project_dir_path / file_path
    if not target.exists():
        return related

    stem = target.stem
    suffix = target.suffix

    seen: set[str] = set()
    for pattern in (f"*{stem}*", f"*{stem}.py", f"test_{stem}.py", f"{stem}_test.py"):
        for match in project_dir_path.rglob(pattern):
            if match.is_file():
                match_str = str(match)
                if match_str not in seen and match_str != str(target):
                    seen.add(match_str)
                    related.append(match_str)

    if suffix == ".py":
        for match in project_dir_path.rglob("*.py"):
            if match.is_file() and str(match) not in seen:
                try:
                    content = match.read_text(encoding="utf-8", errors="replace")
                    if stem in content or target.name in content:
                        seen.add(str(match))
                        related.append(str(match))
                except OSError:
                    pass

    return list(related)[:15]


def get_recent_changes(
    file_path: str, project_dir_path: Path, limit: int = 5
) -> list[dict[str, Any]]:
    """Get recent git commits that modified the file."""
    changes: list[dict[str, Any]] = []
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", f"-n{limit}", "--", file_path],
            capture_output=True,
            text=True,
            cwd=project_dir_path,
            timeout=15,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                parts = line.split(" ", 1)
                if len(parts) == 2:
                    changes.append({"hash": parts[0], "message": parts[1]})
    except (subprocess.TimeoutExpired, OSError):
        pass
    return changes


def git_blame(file_path: str, project_dir_path: Path) -> list[dict[str, Any]]:
    """Return git blame info for each line in the file."""
    blame_entries: list[dict[str, Any]] = []
    try:
        result = subprocess.run(
            ["git", "blame", "--line-porcelain", file_path],
            capture_output=True,
            text=True,
            cwd=project_dir_path,
            timeout=30,
        )
        if result.returncode == 0:
            current_entry: dict[str, Any] = {}
            for line in result.stdout.splitlines():
                if line.startswith("hash "):
                    current_entry["hash"] = line[5:]
                elif line.startswith("author "):
                    current_entry["author"] = line[8:]
                elif line.startswith("committer-time "):
                    ts = int(line.split(" ", 1)[1])
                    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                    current_entry["time"] = dt.isoformat()
                elif line.startswith("\t"):
                    current_entry["content"] = line[1:]
                    if current_entry.get("hash"):
                        blame_entries.append(current_entry)
                    current_entry = {}
            if current_entry.get("hash"):
                blame_entries.append(current_entry)
    except (subprocess.TimeoutExpired, OSError):
        pass
    return blame_entries
