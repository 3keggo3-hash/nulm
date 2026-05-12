"""Snapshot/rollback guarantee for Claude Bridge.

Every modification creates a checkpoint before changes. Snapshots can be:
- pre_task: modified files only (retention: until task complete)
- pre_session: all project (retention: until session end)
- named: user-specified (retention: until explicitly deleted)

Storage: .claude-bridge/snapshots/ (tar/gz format)
"""

from __future__ import annotations

import json
import os
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from claude_bridge.config import project_dir


class SnapshotType(Enum):
    """Snapshot type enumeration."""

    PRE_TASK = "pre_task"
    PRE_SESSION = "pre_session"
    NAMED = "named"


@dataclass
class Snapshot:
    """Snapshot metadata."""

    name: str
    type: SnapshotType
    created_at: str
    files: list[str]
    size_bytes: int
    path: Path

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type.value,
            "created_at": self.created_at,
            "files": self.files,
            "size_bytes": self.size_bytes,
            "path": str(self.path),
        }


def _safe_filename(name: str) -> str:
    """Sanitize a snapshot name for use as a filename."""
    keep = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
    sanitized = "".join(c if c in keep else "_" for c in name)
    return sanitized.strip("_") or "unnamed"


def _snapshots_dir() -> Path:
    """Return the snapshots directory, creating it if needed."""
    pd = project_dir()
    snap_dir = pd / ".claude-bridge" / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    return snap_dir


def _snapshot_index_path() -> Path:
    """Return the path to the snapshot index file."""
    return _snapshots_dir() / "index.json"


def _load_index() -> dict[str, Any]:
    """Load the snapshot index from disk."""
    idx_path = _snapshot_index_path()
    if not idx_path.is_file():
        return {"snapshots": []}
    try:
        payload = json.loads(idx_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
        return {"snapshots": []}
    except (json.JSONDecodeError, OSError):
        return {"snapshots": []}


def _save_index(index: dict[str, Any]) -> None:
    """Save the snapshot index to disk."""
    idx_path = _snapshot_index_path()
    idx_path.write_text(json.dumps(index, indent=2), encoding="utf-8")


def _relativize_path(path: Path) -> Path:
    """Return path relative to project directory."""
    try:
        return path.relative_to(project_dir())
    except ValueError:
        return path


def _collect_files_for_snapshot(
    files: list[str] | None,
    snapshot_type: SnapshotType,
) -> list[Path]:
    """Collect files to include in snapshot based on type."""
    pd = project_dir()
    if files:
        return [pd / f for f in files]

    if snapshot_type == SnapshotType.PRE_SESSION:
        collected: list[Path] = []
        for root, dirs, filenames in os.walk(pd):
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(".")
                and d not in {"__pycache__", "node_modules", ".git", "venv", ".venv"}
            ]
            for fname in filenames:
                if not fname.startswith("."):
                    collected.append(Path(root) / fname)
        return collected

    return []


def _create_tar_gz(snapshot_path: Path, files: list[Path]) -> int:
    """Create a tar.gz archive from the given files."""
    with tarfile.open(snapshot_path, "w:gz") as tar:
        for file_path in files:
            if not file_path.is_file():
                continue
            try:
                arcname = str(_relativize_path(file_path))
                tar.add(file_path, arcname=arcname)
            except (OSError, tarfile.TarError):
                continue
    return snapshot_path.stat().st_size


def _extract_tar_gz(snapshot_path: Path, target_dir: Path) -> list[Path]:
    """Extract a tar.gz archive to the target directory."""
    extracted: list[Path] = []
    with tarfile.open(snapshot_path, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            try:
                tar.extract(member, path=target_dir)
                extracted.append(target_dir / member.name)
            except (OSError, tarfile.TarError):
                continue
    return extracted


class SnapshotManager:
    """Manager for creating, listing, restoring, and deleting snapshots."""

    SNAPSHOT_DIR = Path(".claude-bridge/snapshots")

    def create(
        self,
        name: str,
        snapshot_type: SnapshotType,
        files: list[str] | None = None,
    ) -> Snapshot:
        """Create a tar/gz snapshot of specified files."""
        sanitized = _safe_filename(name)
        files_to_archive = _collect_files_for_snapshot(files, snapshot_type)

        timestamp = datetime.now(timezone.utc).isoformat()
        snap_dir = _snapshots_dir()
        archive_path = snap_dir / f"{sanitized}.tar.gz"

        size_bytes = 0
        if files_to_archive:
            size_bytes = _create_tar_gz(archive_path, files_to_archive)

        relative_files = [str(_relativize_path(f)) for f in files_to_archive]

        snapshot = Snapshot(
            name=name,
            type=snapshot_type,
            created_at=timestamp,
            files=relative_files,
            size_bytes=size_bytes,
            path=archive_path,
        )

        index = _load_index()
        index["snapshots"] = [s for s in index.get("snapshots", []) if s.get("name") != name]
        index["snapshots"].append(snapshot.to_dict())
        _save_index(index)

        return snapshot

    def list(self) -> list[Snapshot]:
        """List all snapshots sorted by creation time (newest first)."""
        index = _load_index()
        snapshots: list[Snapshot] = []

        for item in index.get("snapshots", []):
            try:
                snap = Snapshot(
                    name=item["name"],
                    type=SnapshotType(item["type"]),
                    created_at=item["created_at"],
                    files=item.get("files", []),
                    size_bytes=item.get("size_bytes", 0),
                    path=Path(item["path"]),
                )
                snapshots.append(snap)
            except (ValueError, KeyError):
                continue

        snapshots.sort(key=lambda s: s.created_at, reverse=True)
        return snapshots

    def restore(self, name: str) -> bool:
        """Restore from snapshot. Returns True if successful."""
        index = _load_index()
        target: dict[str, Any] | None = None

        for item in index.get("snapshots", []):
            if item.get("name") == name:
                target = item
                break

        if not target:
            return False

        archive_path = Path(target["path"])
        if not archive_path.is_file():
            return False

        pd = project_dir()
        try:
            _extract_tar_gz(archive_path, pd)
            return True
        except Exception:
            return False

    def delete(self, name: str) -> bool:
        """Delete snapshot. Returns True if deleted, False if not found."""
        index = _load_index()
        updated_snapshots: list[dict[str, Any]] = []
        found = False

        for item in index.get("snapshots", []):
            if item.get("name") == name:
                found = True
                archive_path = Path(item["path"])
                if archive_path.is_file():
                    archive_path.unlink()
            else:
                updated_snapshots.append(item)

        if not found:
            return False

        index["snapshots"] = updated_snapshots
        _save_index(index)
        return True

    def get_snapshot_path(self, name: str) -> Path | None:
        """Return path to snapshot file or None if not found."""
        index = _load_index()
        for item in index.get("snapshots", []):
            if item.get("name") == name:
                path = Path(item["path"])
                if path.is_file():
                    return path
                return None
        return None
