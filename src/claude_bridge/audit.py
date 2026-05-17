# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

"""Structured audit logging for Nulm tool calls.

Backward-compatible re-export wrapper.  All symbols are now defined in the
``_audit_*`` sub-modules; this file re-exports them so that existing
``from claude_bridge.audit import ...`` statements continue to work.
"""

from claude_bridge._audit_core import (  # noqa: F401
    _AUDIT_LOCK,
    _CURRENT_SESSION_ID,
    _MAX_AUDIT_RECORD_SCAN_LINES,
    _MAX_AUDIT_SESSION_SCAN_FILES,
    _SESSION_START_RECORDED,
    _VALID_SESSION_ID_RE,
    _append_audit_record,
    _audit_dir,
    _compute_record_hash,
    _iter_session_ids_newest_first,
    _load_records,
    _load_records_at_offsets,
    _new_session_id,
    _session_file,
    _session_files_newest_first,
    current_session_id,
    ensure_session_start_logged,
    find_audit_record,
    latest_session_id,
    log_policy_change,
    log_session_end,
    log_session_start,
    reset_audit_session,
    verify_audit_integrity,
)

from claude_bridge._audit_redaction import (  # noqa: F401
    _CONTENT_SECRET_PATTERNS,
    _REDACTION_MAX_DEPTH,
    _SENSITIVE_KEYS,
    _SUMMARY_MAX_DEPTH,
    _SUMMARY_MAX_ITEMS,
    _SUMMARY_MAX_STRING,
    _estimate_tokens,
    _has_truncation_marker,
    _is_sensitive_key,
    _mask_secret_value,
    _plain_string,
    _redact_sensitive_values,
    _result_summary,
    _strip_redacted,
    _strip_redacted_value,
    _summarize_value,
    _telemetry_summary,
    _truncate_string,
)

from claude_bridge._audit_activity import (  # noqa: F401
    _ACTIVITY_MAX_ITEMS,
    _COMMAND_TOOLS,
    _PATCH_TOOLS,
    _PATH_PARAM_KEYS,
    _VALID_DECISION_ACTIONS,
    _VALID_DECISION_SOURCES,
    _VALID_RISK_LEVELS,
    _VALIDATION_COMMAND_PREFIXES,
    _WRITE_TOOLS,
    _activity_item,
    _append_unique,
    _build_validation_summary,
    _collect_command,
    _collect_paths,
    _compute_policy_decision_counts,
    _extract_decision_from_record,
    _extract_policy_decision,
    _is_successful_write,
    _is_validation_command,
    _record_params,
    _record_result,
    _record_risk_level,
    _timestamp_compare,
    build_activity_summary,
    filter_audit_records,
)

from claude_bridge._audit_logging import log_tool_call  # noqa: F401

from claude_bridge._audit_query import (  # noqa: F401
    get_recent_tool_calls,
    summarize_session,
)

from claude_bridge._audit_export import (  # noqa: F401
    _DEFAULT_EXPORT_FORMAT,
    _DEFAULT_INCLUDE_REDACTED,
    _DEFAULT_INCLUDE_TELEMETRY,
    _DEFAULT_MAX_SESSIONS,
    _DEFAULT_RETENTION_DAYS,
    AuditExport,
    ExportFormat,
    RetentionConfig,
    _parse_retention_config,
    _timestamp_offset_days,
    apply_retention,
    export_audit_records,
)

from claude_bridge._audit_appeal import (  # noqa: F401
    AppealRequest,
    AppealResult,
    EscalationEvent,
    get_appeal_history,
    get_pending_escalations,
    log_appeal_event,
    log_escalation_event,
    process_appeal,
    validate_appeal_justification,
)
