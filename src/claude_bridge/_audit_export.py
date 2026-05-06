"""Audit export formats, retention configuration, and session cleanup."""

from __future__ import annotations

import datetime
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from claude_bridge._audit_core import (
    latest_session_id,
    current_session_id,
    _load_records,
    _session_files_newest_first,
)
from claude_bridge._audit_query import summarize_session
from claude_bridge._audit_redaction import _strip_redacted


class ExportFormat(str, Enum):
    """Supported audit export formats.

    - JSONL: one JSON object per line (raw records, same as on-disk format)
    - SUMMARY_JSON: a single JSON object with metadata and activity summary

    Default retention is 90 days and 100 sessions (see RetentionConfig).
    """

    JSONL = "jsonl"
    SUMMARY_JSON = "summary-json"


_DEFAULT_RETENTION_DAYS = 90
_DEFAULT_MAX_SESSIONS = 100
_DEFAULT_EXPORT_FORMAT = ExportFormat.JSONL
_DEFAULT_INCLUDE_TELEMETRY = True
_DEFAULT_INCLUDE_REDACTED = True


@dataclass
class RetentionConfig:
    """Audit retention and export configuration.

    Defaults:
        retention_days: 90 — records older than this are eligible for
            cleanup by :func:`apply_retention`.
        max_sessions: 100 — when exceeded, the oldest sessions are
            eligible for cleanup.
        export_format: :class:`ExportFormat`.JSONL — the default format
            used by :func:`export_audit_records`.
        include_telemetry: True — include token/cost telemetry in
            exports.
        include_redacted: True — include redacted (masked) sensitive
            values rather than stripping them entirely.
    """

    retention_days: int = _DEFAULT_RETENTION_DAYS
    max_sessions: int = _DEFAULT_MAX_SESSIONS
    export_format: ExportFormat = _DEFAULT_EXPORT_FORMAT
    include_telemetry: bool = _DEFAULT_INCLUDE_TELEMETRY
    include_redacted: bool = _DEFAULT_INCLUDE_REDACTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "retention_days": self.retention_days,
            "max_sessions": self.max_sessions,
            "export_format": self.export_format.value,
            "include_telemetry": self.include_telemetry,
            "include_redacted": self.include_redacted,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RetentionConfig":
        export_raw = data.get("export_format", _DEFAULT_EXPORT_FORMAT.value)
        if isinstance(export_raw, ExportFormat):
            export_fmt = export_raw
        else:
            try:
                export_fmt = ExportFormat(str(export_raw))
            except ValueError:
                export_fmt = _DEFAULT_EXPORT_FORMAT
        return cls(
            retention_days=int(data.get("retention_days", _DEFAULT_RETENTION_DAYS)),
            max_sessions=int(data.get("max_sessions", _DEFAULT_MAX_SESSIONS)),
            export_format=export_fmt,
            include_telemetry=bool(data.get("include_telemetry", _DEFAULT_INCLUDE_TELEMETRY)),
            include_redacted=bool(data.get("include_redacted", _DEFAULT_INCLUDE_REDACTED)),
        )

    def is_record_expired(self, record: dict[str, Any], *, now_iso: str | None = None) -> bool:
        now = now_iso or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        record_ts: str = str(record.get("timestamp", ""))
        if not record_ts:
            return False
        cutoff = _timestamp_offset_days(now, self.retention_days)
        return record_ts < cutoff


@dataclass
class AuditExport:
    """A packaged audit export with metadata.

    Attributes:
        session_id: The session that was exported.
        export_format: The format used for :attr:`records_payload`.
        records_payload: Raw JSONL lines (when jsonl) or summary dict
            (when summary-json).
        record_count: Number of records in the export.
        exported_at: ISO-8601 timestamp of when the export was created.
        retention_config: The retention configuration applied.
    """

    session_id: str
    export_format: ExportFormat
    records_payload: list[dict[str, Any]] | dict[str, Any]
    record_count: int
    exported_at: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    )
    retention_config: RetentionConfig = field(default_factory=RetentionConfig)

    def to_dict(self) -> dict[str, Any]:
        payload: Any
        if isinstance(self.records_payload, list):
            payload = self.records_payload
        else:
            payload = self.records_payload
        return {
            "session_id": self.session_id,
            "export_format": self.export_format.value,
            "records_payload": payload,
            "record_count": self.record_count,
            "exported_at": self.exported_at,
            "retention_config": self.retention_config.to_dict(),
        }

    def to_jsonl(self) -> str:
        if self.export_format != ExportFormat.JSONL:
            raise ValueError("to_jsonl only valid for JSONL export format")
        assert isinstance(self.records_payload, list)
        lines: list[str] = []
        for record in self.records_payload:
            lines.append(json.dumps(record, ensure_ascii=False, sort_keys=True))
        return "\n".join(lines) + "\n" if lines else ""

    def to_summary_json(self) -> str:
        if self.export_format != ExportFormat.SUMMARY_JSON:
            raise ValueError("to_jsonl only valid for summary-json export format")
        assert isinstance(self.records_payload, dict)
        return json.dumps(self.records_payload, ensure_ascii=False, sort_keys=True, indent=2)


def _timestamp_offset_days(reference_iso: str, days: int) -> str:
    """Return an ISO-8601 timestamp *days* before *reference_iso*."""
    dt = datetime.datetime.strptime(reference_iso, "%Y-%m-%dT%H:%M:%SZ")
    offset = dt - datetime.timedelta(days=days)
    return offset.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_retention_config(
    config: RetentionConfig | dict[str, Any] | None,
) -> RetentionConfig:
    if config is None:
        return RetentionConfig()
    if isinstance(config, RetentionConfig):
        return config
    return RetentionConfig.from_dict(config)


def export_audit_records(
    session_id: str | None = None,
    *,
    export_format: ExportFormat | None = None,
    retention_config: RetentionConfig | dict[str, Any] | None = None,
    limit: int | None = None,
) -> AuditExport:
    """Export audit records for a session in the requested format.

    Args:
        session_id: Session to export. Uses the latest session when None.
        export_format: Output format (defaults to the retention config
            format, which defaults to JSONL).
        retention_config: RetentionConfig or dict to control export.
        limit: Optional max number of records to include.

    Returns:
        An :class:`AuditExport` with the packaged records.
    """
    cfg = _parse_retention_config(retention_config)
    fmt = export_format or cfg.export_format

    selected_session = session_id or latest_session_id() or current_session_id()
    records = _load_records(selected_session)
    if limit is not None:
        records = records[: max(1, limit)]

    if not cfg.include_telemetry:
        records = [{k: v for k, v in r.items() if k != "telemetry"} for r in records]
    if not cfg.include_redacted:
        records = [_strip_redacted(r) for r in records]

    if fmt == ExportFormat.SUMMARY_JSON:
        summary = summarize_session(selected_session, limit=limit or 20)
        payload: list[dict[str, Any]] | dict[str, Any] = summary
    else:
        payload = records

    return AuditExport(
        session_id=selected_session,
        export_format=fmt,
        records_payload=payload,
        record_count=len(records),
        retention_config=cfg,
    )


def apply_retention(
    *,
    retention_config: RetentionConfig | dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply retention policy: remove expired sessions and trim old records.

    Defaults (see :class:`RetentionConfig`):
        - retention_days = 90
        - max_sessions = 100

    Args:
        retention_config: Override defaults with a RetentionConfig or dict.
        dry_run: When True, report what would be removed without deleting.

    Returns:
        A dict with ``sessions_removed``, ``records_expired``, and
        ``dry_run`` keys.
    """
    cfg = _parse_retention_config(retention_config)
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    all_sessions = _session_files_newest_first()
    sessions_removed = 0
    records_expired = 0

    excess_sessions = all_sessions[cfg.max_sessions :]
    for path in excess_sessions:
        if not dry_run:
            try:
                path.unlink()
            except OSError:
                continue
        sessions_removed += 1

    for path in all_sessions[: cfg.max_sessions]:
        sid = path.stem
        records = _load_records(sid)
        expired_indices: list[int] = []
        for idx, record in enumerate(records):
            if cfg.is_record_expired(record, now_iso=now_iso):
                expired_indices.append(idx)
        if not expired_indices:
            continue
        records_expired += len(expired_indices)
        kept = [r for i, r in enumerate(records) if i not in expired_indices]
        if not dry_run:
            try:
                with path.open("w", encoding="utf-8") as handle:
                    for record in kept:
                        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            except OSError:
                continue

    return {
        "sessions_removed": sessions_removed,
        "records_expired": records_expired,
        "dry_run": dry_run,
        "retention_config": cfg.to_dict(),
    }
