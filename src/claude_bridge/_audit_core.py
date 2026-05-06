"""Audit session management, file I/O, and directory scanning."""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    import msvcrt  # type: ignore[import-untyped]
else:
    import fcntl  # type: ignore[import-untyped]

_AUDIT_LOCK = threading.RLock()
_CURRENT_SESSION_ID = ""
_MAX_AUDIT_SESSION_SCAN_FILES = 256
_MAX_AUDIT_RECORD_SCAN_LINES = 10000

_VALID_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _audit_dir() -> Path:
    override = os.environ.get("CLAUDE_BRIDGE_AUDIT_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".claude-bridge" / "audit").resolve()


def _new_session_id() -> str:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return f"{stamp}-{uuid.uuid4().hex[:12]}"


def reset_audit_session() -> str:
    global _CURRENT_SESSION_ID
    with _AUDIT_LOCK:
        _CURRENT_SESSION_ID = _new_session_id()
        return _CURRENT_SESSION_ID


def current_session_id() -> str:
    with _AUDIT_LOCK:
        if not _CURRENT_SESSION_ID:
            return reset_audit_session()
        return _CURRENT_SESSION_ID


def _session_file(session_id: str) -> Path:
    if not _VALID_SESSION_ID_RE.match(session_id):
        raise ValueError(f"invalid session_id: {session_id!r}")
    return _audit_dir() / f"{session_id}.jsonl"


def _append_audit_record(path: Path, line: str) -> int | None:
    """Append a line to an audit file with process locking and restricted permissions."""
    try:
        with _AUDIT_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            is_new = not path.exists()
            with path.open("a", encoding="utf-8") as handle:
                if sys.platform == "win32":
                    try:
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    except (ImportError, OSError):
                        pass
                else:
                    try:
                        fcntl.flock(handle, fcntl.LOCK_EX)
                    except (ImportError, OSError):
                        pass
                offset = handle.tell()
                handle.write(line + "\n")
                if is_new:
                    os.chmod(path, 0o600)
                return offset
    except OSError:
        return None


def _load_records(session_id: str, *, max_lines: int | None = None) -> list[dict[str, Any]]:
    path = _session_file(session_id)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for index, line in enumerate(handle):
                if max_lines is not None and index >= max_lines:
                    break
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(raw, dict):
                    records.append(raw)
    except OSError:
        return []
    return records


def _load_records_at_offsets(session_id: str, offsets: list[int]) -> list[dict[str, Any]]:
    path = _session_file(session_id)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for offset in offsets:
                if offset < 0:
                    continue
                handle.seek(offset)
                line = handle.readline()
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(raw, dict):
                    records.append(raw)
    except OSError:
        return []
    return records


def latest_session_id() -> str | None:
    candidates = _session_files_newest_first(limit=_MAX_AUDIT_SESSION_SCAN_FILES)
    if not candidates:
        return None
    return candidates[0].stem


def _session_files_newest_first(*, limit: int | None = None) -> list[Path]:
    audit_dir = _audit_dir()
    if not audit_dir.exists():
        return []
    candidates: list[tuple[float, Path]] = []
    try:
        paths = list(audit_dir.glob("*.jsonl"))
    except OSError:
        return []
    for path in paths:
        try:
            if path.is_file() and not path.name.endswith(".index.jsonl"):
                candidates.append((path.stat().st_mtime, path))
        except OSError:
            continue
    candidates.sort(key=lambda item: item[0], reverse=True)
    selected = candidates[:limit] if limit is not None else candidates
    return [path for _, path in selected]


def _iter_session_ids_newest_first() -> list[str]:
    return [path.stem for path in _session_files_newest_first(limit=_MAX_AUDIT_SESSION_SCAN_FILES)]


def find_audit_record(record_id: str) -> dict[str, Any] | None:
    for session_id in _iter_session_ids_newest_first():
        for record in _load_records(session_id, max_lines=_MAX_AUDIT_RECORD_SCAN_LINES):
            if record.get("record_id") == record_id:
                return record
    return None
