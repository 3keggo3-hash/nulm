"""Audit session management, file I/O, and directory scanning."""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import uuid
from functools import lru_cache
from hashlib import sha256
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
_SESSION_START_RECORDED = False
_LAST_RECORD_HASH: dict[str, str] = {}
_GENESIS_HASH = sha256(b"GENESIS").hexdigest()

_VALID_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


@lru_cache(maxsize=1)
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
    global _SESSION_START_RECORDED
    with _AUDIT_LOCK:
        if not _CURRENT_SESSION_ID:
            session_id = reset_audit_session()
            _SESSION_START_RECORDED = False
            return session_id
        return _CURRENT_SESSION_ID


def log_session_start(session_id: str, agent_id: str | None = None) -> int | None:
    record: dict[str, Any] = {
        "record_id": uuid.uuid4().hex,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "session_id": session_id,
        "tool_name": "session_start",
        "params": {"agent_id": agent_id} if agent_id else {},
        "params_hash": sha256(
            json.dumps({"agent_id": agent_id}, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "duration_ms": 0.0,
        "result": {"ok": True, "message": "session started"},
        "result_hash": sha256(b"session_start").hexdigest(),
        "telemetry": {
            "input_chars": 0,
            "output_chars": 0,
            "estimated_input_tokens": 0,
            "estimated_output_tokens": 0,
            "estimated_total_tokens": 0,
            "result_truncated": False,
        },
    }
    path = _session_file(session_id)
    return _append_audit_record(path, record, session_id=session_id)


def log_session_end(session_id: str, reason: str = "normal") -> int | None:
    record: dict[str, Any] = {
        "record_id": uuid.uuid4().hex,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "session_id": session_id,
        "tool_name": "session_end",
        "params": {"reason": reason},
        "params_hash": sha256(
            json.dumps({"reason": reason}, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "duration_ms": 0.0,
        "result": {"ok": True, "message": f"session ended: {reason}"},
        "result_hash": sha256(f"session_end:{reason}".encode("utf-8")).hexdigest(),
        "telemetry": {
            "input_chars": 0,
            "output_chars": 0,
            "estimated_input_tokens": 0,
            "estimated_output_tokens": 0,
            "estimated_total_tokens": 0,
            "result_truncated": False,
        },
    }
    path = _session_file(session_id)
    return _append_audit_record(path, record, session_id=session_id)


def ensure_session_start_logged(session_id: str, agent_id: str | None = None) -> None:
    global _SESSION_START_RECORDED
    with _AUDIT_LOCK:
        if not _SESSION_START_RECORDED:
            log_session_start(session_id, agent_id)
            _SESSION_START_RECORDED = True


def _session_file(session_id: str) -> Path:
    if not _VALID_SESSION_ID_RE.match(session_id):
        raise ValueError(f"invalid session_id: {session_id!r}")
    return _audit_dir() / f"{session_id}.jsonl"


def _compute_record_hash(record: dict[str, Any], prev_hash: str) -> str:
    content = json.dumps(record, ensure_ascii=False, sort_keys=True)
    return sha256((content + prev_hash).encode("utf-8")).hexdigest()


def _append_audit_record(
    path: Path,
    record_or_line: dict[str, Any] | str,
    *,
    session_id: str | None = None,
    skip_hash_chain: bool = False,
) -> int | None:
    """Append a record to an audit file with hash chain and process locking.

    Args:
        path: Path to the audit file.
        record_or_line: Either a record dict (for hash chain) or a pre-serialized line.
        session_id: Session ID for hash chain tracking (required if record is a dict).
        skip_hash_chain: If True, skip hash chain logic (for index/ops files).
    """
    try:
        with _AUDIT_LOCK:
            if isinstance(record_or_line, dict):
                if not skip_hash_chain and session_id is None:
                    raise ValueError("session_id required for hash chain")
                if not skip_hash_chain:
                    prev_hash = _LAST_RECORD_HASH.get(session_id, _GENESIS_HASH)  # type: ignore[arg-type]
                    record_or_line["prev_hash"] = prev_hash
                    record_hash = _compute_record_hash(record_or_line, prev_hash)
                    _LAST_RECORD_HASH[session_id] = record_hash  # type: ignore[index]
                line = json.dumps(record_or_line, ensure_ascii=False, sort_keys=True)
            else:
                line = record_or_line

            path.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(path.parent, 0o700)
            is_new = not path.exists()
            if is_new:
                fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
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


@lru_cache(maxsize=8)
def _cached_session_files(limit: int) -> tuple[str, ...]:
    """Cache session file listing to avoid repeated glob+sort."""
    return tuple(path.stem for path in _session_files_newest_first(limit=limit))


def _iter_session_ids_newest_first() -> list[str]:
    return list(_cached_session_files(_MAX_AUDIT_SESSION_SCAN_FILES))


def find_audit_record(record_id: str) -> dict[str, Any] | None:
    session_ids = _cached_session_files(_MAX_AUDIT_SESSION_SCAN_FILES)
    if not session_ids:
        return None
    for session_id in session_ids:
        for record in _load_records(session_id, max_lines=_MAX_AUDIT_RECORD_SCAN_LINES):
            if record.get("record_id") == record_id:
                return record
    return None


def log_policy_change(
    policy_name: str,
    action: str,
    old_rules_count: int | None = None,
    new_rules_count: int | None = None,
    *,
    agent_id: str | None = None,
    reason: str | None = None,
) -> int | None:
    """Log a policy change audit event.

    Args:
        policy_name: Name of the policy that changed.
        action: Type of change (e.g., "created", "updated", "deleted", "enabled", "disabled").
        old_rules_count: Number of rules before the change.
        new_rules_count: Number of rules after the change.
        agent_id: Optional agent that made the change.
        reason: Optional explanation for the change.

    Returns:
        The file offset where the record was written, or None on error.
    """
    from claude_bridge._audit_redaction import _redact_sensitive_values, _summarize_value
    from claude_bridge._audit_index import append_audit_index_record

    session_id = current_session_id()
    ensure_session_start_logged(session_id, agent_id)

    params = {
        "policy_name": policy_name,
        "action": action,
    }
    if old_rules_count is not None:
        params["old_rules_count"] = old_rules_count
    if new_rules_count is not None:
        params["new_rules_count"] = new_rules_count
    if reason:
        params["reason"] = reason

    params_redacted = _redact_sensitive_values(_summarize_value(params))

    record: dict[str, Any] = {
        "record_id": uuid.uuid4().hex,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "session_id": session_id,
        "tool_name": "policy_change",
        "params": params_redacted,
        "params_hash": sha256(
            json.dumps(params_redacted, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "duration_ms": 0.0,
        "result": {
            "ok": True,
            "message": f"policy {action}: {policy_name}",
        },
        "result_hash": sha256(f"policy_change:{policy_name}:{action}".encode("utf-8")).hexdigest(),
        "telemetry": {
            "input_chars": len(json.dumps(params_redacted, ensure_ascii=False, sort_keys=True)),
            "output_chars": 0,
            "estimated_input_tokens": 0,
            "estimated_output_tokens": 0,
            "estimated_total_tokens": 0,
            "result_truncated": False,
        },
        "policy_name": policy_name,
        "policy_action": action,
    }
    if agent_id is not None:
        record["agent_id"] = agent_id

    path = _session_file(session_id)
    offset = _append_audit_record(path, record, session_id=session_id)
    append_audit_index_record(session_id, record, offset=offset)
    return offset


def verify_audit_integrity(
    session_id: str,
) -> dict[str, Any]:
    """Verify the hash chain integrity of audit records for a session.

    Args:
        session_id: The session ID to verify.

    Returns:
        A dict with 'valid' (bool), 'error' (str or None), 'record_index' (int),
        and 'expected_hash' (str or None) describing the verification result.
    """
    records = _load_records(session_id)
    if not records:
        return {
            "valid": False,
            "error": "no records found",
            "record_index": -1,
            "expected_hash": None,
        }

    expected_prev_hash = _GENESIS_HASH
    for i, record in enumerate(records):
        stored_prev_hash = record.get("prev_hash")
        if stored_prev_hash is None:
            return {
                "valid": False,
                "error": "missing prev_hash field",
                "record_index": i,
                "expected_hash": expected_prev_hash,
            }
        if stored_prev_hash != expected_prev_hash:
            return {
                "valid": False,
                "error": "prev_hash mismatch",
                "record_index": i,
                "expected_hash": expected_prev_hash,
            }
        computed_hash = _compute_record_hash(record, expected_prev_hash)
        expected_prev_hash = computed_hash

    return {"valid": True, "error": None, "record_index": -1, "expected_hash": None}
