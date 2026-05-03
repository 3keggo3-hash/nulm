"""Anomaly feature extraction and rule-based scoring from audit records."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from typing import Counter as CounterType

try:
    import yaml  # type: ignore[import-untyped]

    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False
    yaml = None


@dataclass
class AnomalyFeature:
    """Feature vector extracted from an audit record for anomaly detection.

    Attributes:
        tool_name: Name of the tool that was called.
        hour: Hour of the day (0-23) when the tool was called.
        path_count: Number of file paths referenced in the tool call.
        command_length: Length of the command string (0 if no command).
        decision_action: Policy decision action (allow, deny, ask, or unknown).
        risk_level: Risk level from the decision (low, medium, high, critical, or unknown).
        record_id: Original audit record ID for reference.
        timestamp: Original timestamp string for reference.
    """

    tool_name: str
    hour: int
    path_count: int
    command_length: int
    decision_action: str
    risk_level: str
    record_id: str = ""
    timestamp: str = ""

    @classmethod
    def from_audit_record(cls, record: dict[str, Any]) -> AnomalyFeature:
        """Extract features from an audit record.

        Args:
            record: Audit record dictionary.

        Returns:
            AnomalyFeature instance with extracted features.
        """
        tool_name = _extract_tool_name(record)
        hour = _extract_hour(record)
        path_count = _extract_path_count(record)
        command_length = _extract_command_length(record)
        decision_action = _extract_decision_action(record)
        risk_level = _extract_risk_level(record)
        record_id = str(record.get("record_id", ""))
        timestamp = str(record.get("timestamp", ""))

        return cls(
            tool_name=tool_name,
            hour=hour,
            path_count=path_count,
            command_length=command_length,
            decision_action=decision_action,
            risk_level=risk_level,
            record_id=record_id,
            timestamp=timestamp,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-compatible dictionary."""
        return {
            "tool_name": self.tool_name,
            "hour": self.hour,
            "path_count": self.path_count,
            "command_length": self.command_length,
            "decision_action": self.decision_action,
            "risk_level": self.risk_level,
            "record_id": self.record_id,
            "timestamp": self.timestamp,
        }


def _extract_tool_name(record: dict[str, Any]) -> str:
    """Extract tool name from audit record.

    Returns 'unknown' if tool_name is missing or masked.
    """
    tool_name = record.get("tool_name")
    if tool_name is None or _is_masked_value(tool_name):
        return "unknown"
    if isinstance(tool_name, str):
        return tool_name.strip() or "unknown"
    return "unknown"


def _extract_hour(record: dict[str, Any]) -> int:
    """Extract hour (0-23) from audit record timestamp.

    Returns -1 if timestamp is missing, masked, or unparseable.
    """
    timestamp = record.get("timestamp")
    if timestamp is None or _is_masked_value(timestamp):
        return -1
    if not isinstance(timestamp, str):
        return -1

    try:
        dt = _parse_timestamp(timestamp)
        if dt is not None:
            return dt.hour
    except (ValueError, TypeError):
        pass

    return -1


def _extract_path_count(record: dict[str, Any]) -> int:
    """Extract count of file paths from audit record.

    Checks params and result details for path-related fields.
    Returns 0 if no paths found or if data is masked.
    """
    path_keys = {"file", "path", "source", "destination", "target", "from_path", "to_path"}
    paths: set[str] = set()

    params = record.get("params", {})
    if isinstance(params, dict) and not _is_masked_value(params):
        for key in path_keys:
            value = params.get(key)
            if value is not None and not _is_masked_value(value):
                if isinstance(value, str) and value.strip():
                    paths.add(value.strip())
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, str) and item.strip():
                            paths.add(item.strip())

    result = record.get("result", {})
    if isinstance(result, dict):
        details = result.get("details", {})
        if isinstance(details, dict) and not _is_masked_value(details):
            for key in path_keys:
                value = details.get(key)
                if value is not None and not _is_masked_value(value):
                    if isinstance(value, str) and value.strip():
                        paths.add(value.strip())

    return len(paths)


def _extract_command_length(record: dict[str, Any]) -> int:
    """Extract length of command string from audit record.

    Checks params and result details for command field.
    Returns 0 if no command found or if data is masked.
    """
    command: str | None = None

    params = record.get("params", {})
    if isinstance(params, dict) and not _is_masked_value(params):
        cmd_value = params.get("command")
        if cmd_value is not None and not _is_masked_value(cmd_value):
            if isinstance(cmd_value, str):
                command = cmd_value

    if command is None:
        result = record.get("result", {})
        if isinstance(result, dict):
            details = result.get("details", {})
            if isinstance(details, dict) and not _is_masked_value(details):
                cmd_value = details.get("command")
                if cmd_value is not None and not _is_masked_value(cmd_value):
                    if isinstance(cmd_value, str):
                        command = cmd_value

    if command is None:
        return 0

    return len(command)


def _extract_decision_action(record: dict[str, Any]) -> str:
    """Extract decision action from audit record.

    Returns 'unknown' if decision is missing, masked, or unparseable.
    Handles both direct fields and nested result.decision structures.
    """
    action = record.get("decision_action")
    if action is not None and not _is_masked_value(action):
        if isinstance(action, str):
            return action.strip().lower() or "unknown"
        return "unknown"

    result = record.get("result", {})
    if isinstance(result, dict):
        details = result.get("details", {})
        if isinstance(details, dict):
            decision = details.get("decision", {})
            if isinstance(decision, dict):
                action = decision.get("action")
                if action is not None and not _is_masked_value(action):
                    if isinstance(action, str):
                        return action.strip().lower() or "unknown"

    return "unknown"


def _extract_risk_level(record: dict[str, Any]) -> str:
    """Extract risk level from audit record.

    Returns 'unknown' if risk level is missing, masked, or unparseable.
    Handles both direct fields and nested result.decision structures.
    """
    risk = record.get("decision_risk_level")
    if risk is not None and not _is_masked_value(risk):
        if isinstance(risk, str):
            return str(risk).strip().lower() or "unknown"
        return "unknown"

    result = record.get("result", {})
    if isinstance(result, dict):
        details = result.get("details", {})
        if isinstance(details, dict):
            decision = details.get("decision", {})
            if isinstance(decision, dict):
                risk = decision.get("risk_level")
                if risk is not None and not _is_masked_value(risk):
                    if isinstance(risk, str):
                        return str(risk).strip().lower() or "unknown"

    return "unknown"


def _is_masked_value(value: Any) -> bool:
    """Check if a value is masked/redacted.

    Masked values are typically dicts with 'redacted': True key.
    """
    if isinstance(value, dict):
        return value.get("redacted") is True
    return False


def _parse_timestamp(timestamp: str) -> datetime | None:
    """Parse ISO-8601 timestamp string.

    Tries multiple formats commonly used in audit logs.
    Returns None if parsing fails.
    """
    formats = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(timestamp, fmt)
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        pass

    return None


def extract_features(record: dict[str, Any]) -> AnomalyFeature:
    """Extract anomaly features from an audit record.

    This is the main public API for feature extraction.

    Args:
        record: Audit record dictionary.

    Returns:
        AnomalyFeature instance with extracted features.

    Raises:
        ValueError: If record is not a valid dictionary.
    """
    if not isinstance(record, dict):
        raise ValueError("record must be a dictionary")
    return AnomalyFeature.from_audit_record(record)


def extract_features_batch(records: list[dict[str, Any]]) -> list[AnomalyFeature]:
    """Extract features from multiple audit records.

    Args:
        records: List of audit record dictionaries.

    Returns:
        List of AnomalyFeature instances. Invalid records are skipped.
    """
    features: list[AnomalyFeature] = []
    for record in records:
        try:
            feature = extract_features(record)
            features.append(feature)
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
    return features


def parse_record_from_json(json_str: str) -> dict[str, Any] | None:
    """Parse audit record from JSON string.

    Args:
        json_str: JSON string containing audit record.

    Returns:
        Parsed dictionary or None if parsing fails.
    """
    try:
        result = json.loads(json_str)
        if isinstance(result, dict):
            return result
        return None
    except (json.JSONDecodeError, TypeError):
        return None


def parse_record_from_yaml(yaml_str: str) -> dict[str, Any] | None:
    """Parse audit record from YAML string.

    Args:
        yaml_str: YAML string containing audit record.

    Returns:
        Parsed dictionary or None if parsing fails or YAML is not available.
    """
    if not _YAML_AVAILABLE:
        return None
    try:
        result = yaml.safe_load(yaml_str)  # type: ignore[name-defined]
        if isinstance(result, dict):
            return result
        return None
    except (yaml.YAMLError, TypeError):  # type: ignore[name-defined]
        return None


# ---------------------------------------------------------------------------
# Rule-based anomaly scorer
# ---------------------------------------------------------------------------

# Tools that access the file system
_FILE_ACCESS_TOOLS: set[str] = {
    "read_file",
    "write_file",
    "copy_file",
    "move_file",
    "patch_file",
    "preview_patch",
    "undo_last_patch",
    "list_directory",
    "find_path",
    "grep",
}

# Path substrings that indicate sensitive files
_SENSITIVE_PATH_SUBSTRINGS: list[str] = [
    ".ssh/",
    "/etc/passwd",
    "/etc/shadow",
    ".env",
    ".git/config",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "credentials",
    ".aws/credentials",
    ".htpasswd",
    "/var/run/docker.sock",
    "authorized_keys",
    "known_hosts",
]

# Time window for burst detection (5 minutes)
_BURST_WINDOW_MINUTES: int = 5

# Thresholds
_HIGH_VOLUME_THRESHOLD: int = 10
_SENSITIVE_PATH_BURST_THRESHOLD: int = 3
_HIGH_RISK_SPIKE_THRESHOLD: int = 3

# Base scores for each anomaly type
_BASE_SCORES: dict[str, int] = {
    "new_tool_use": 20,
    "high_volume_file_access": 30,
    "sensitive_path_burst": 60,
    "unusual_hour": 15,
    "high_risk_spike": 40,
}

# Unusual hours range (start, end) — 1am to 5am
_UNUSUAL_HOUR_START: int = 1
_UNUSUAL_HOUR_END: int = 5

# Maximum possible score
_MAX_SCORE: int = 100


@dataclass
class AnomalyResult:
    """Result of anomaly scoring for a single record.

    Attributes:
        record_id: The audit record identifier.
        score: Anomaly score from 0 (normal) to 100 (critical).
        anomaly_types: List of anomaly type labels that fired.
        explanation: Human-readable explanation of the score.
    """

    record_id: str
    score: int
    anomaly_types: list[str] = field(default_factory=list)
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "score": self.score,
            "anomaly_types": self.anomaly_types,
            "explanation": self.explanation,
        }


def _parse_record_timestamp(record: dict[str, Any]) -> datetime | None:
    """Extract and parse timestamp from a raw audit record."""
    ts = record.get("timestamp")
    if ts is None or _is_masked_value(ts):
        return None
    if not isinstance(ts, str):
        return None
    return _parse_timestamp(ts)


def _collect_record_paths(record: dict[str, Any]) -> set[str]:
    """Collect all path strings referenced in a raw audit record."""
    path_keys = {"file", "path", "source", "destination", "target", "from_path", "to_path"}
    paths: set[str] = set()

    params = record.get("params", {})
    if isinstance(params, dict) and not _is_masked_value(params):
        for key in path_keys:
            value = params.get(key)
            if value is not None and not _is_masked_value(value):
                if isinstance(value, str) and value.strip():
                    paths.add(value.strip())
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, str) and item.strip():
                            paths.add(item.strip())
    return paths


def _is_sensitive_path(path: str) -> bool:
    """Check if a path matches any sensitive path pattern."""
    lower_path = path.lower()
    for substr in _SENSITIVE_PATH_SUBSTRINGS:
        if substr.lower() in lower_path:
            return True
    return False


def _collect_sensitive_paths(record: dict[str, Any]) -> list[str]:
    """Return all sensitive paths referenced in a record."""
    all_paths = _collect_record_paths(record)
    return [p for p in all_paths if _is_sensitive_path(p)]


def _is_file_access_tool(tool_name: str) -> bool:
    """Check if a tool name is a file-access tool."""
    return tool_name in _FILE_ACCESS_TOOLS


def _extract_tool_name_raw(record: dict[str, Any]) -> str:
    """Extract tool name from raw record, returning empty string if missing."""
    name = record.get("tool_name")
    if name is None or _is_masked_value(name):
        return ""
    if isinstance(name, str):
        return name.strip()
    return ""


def _extract_decision_risk_raw(record: dict[str, Any]) -> str:
    """Extract decision risk level from raw record."""
    risk = record.get("decision_risk_level")
    if risk is not None and not _is_masked_value(risk) and isinstance(risk, str):
        return str(risk).strip().lower()

    result = record.get("result", {})
    if isinstance(result, dict):
        details = result.get("details", {})
        if isinstance(details, dict):
            decision = details.get("decision", {})
            if isinstance(decision, dict):
                risk = decision.get("risk_level")
                if risk is not None and not _is_masked_value(risk) and isinstance(risk, str):
                    return str(risk).strip().lower()
    return "unknown"


def _records_in_window(
    records: list[dict[str, Any]],
    center_index: int,
    window: timedelta,
) -> list[int]:
    """Find record indices within a time window around center_index.

    Returns a list of indices (not including center_index itself)
    that fall within the window.
    """
    center_ts = _parse_record_timestamp(records[center_index])
    if center_ts is None:
        return []

    indices: list[int] = []
    for i, record in enumerate(records):
        if i == center_index:
            continue
        ts = _parse_record_timestamp(record)
        if ts is None:
            continue
        if abs(ts - center_ts) <= window:
            indices.append(i)
    return indices


def compute_anomaly_scores(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute rule-based anomaly scores for a list of audit records.

    Applies five deterministic rules to each record:

    - **new_tool_use**: A tool type not seen in any prior record within the session.
    - **high_volume_file_access**: ≥10 file-access tool calls within a
      5-minute sliding window.
    - **sensitive_path_burst**: ≥3 records referencing sensitive paths within a
      5-minute sliding window.
    - **unusual_hour**: Tool called between 01:00–05:59 local time.
    - **high_risk_spike**: ≥3 high/critical risk decisions within a
      5-minute sliding window.

    Scores are additive and capped at 100.

    Args:
        records: List of audit record dicts (as stored in session files).

    Returns:
        Dictionary with keys:
        - ``scores`` (list[dict]): Per-record anomaly scoring results.
        - ``anomaly_counts`` (dict[str, int]): Total number of records where
          each anomaly type fired.
        - ``overall_max_score`` (int): Highest score across all records.
    """
    if not records:
        return {
            "scores": [],
            "anomaly_counts": {},
            "overall_max_score": 0,
        }

    window = timedelta(minutes=_BURST_WINDOW_MINUTES)
    seen_tools: set[str] = set()
    anomaly_counts: CounterType[str] = CounterType()
    all_results: list[AnomalyResult] = []

    for idx, record in enumerate(records):
        anomaly_types: list[str] = []
        explanations: list[str] = []

        tool_name = _extract_tool_name_raw(record)
        record_id = str(record.get("record_id", ""))

        # ---- Rule 1: new_tool_use ----
        if tool_name and tool_name not in seen_tools:
            anomaly_types.append("new_tool_use")
            explanations.append(f"First use of tool '{tool_name}' in session")
            seen_tools.add(tool_name)
        if tool_name:
            seen_tools.add(tool_name)

        # ---- Rule 2: high_volume_file_access ----
        nearby_indices = _records_in_window(records, idx, window)
        nearby_file_access_count = sum(
            1 for i in nearby_indices if _is_file_access_tool(_extract_tool_name_raw(records[i]))
        )
        if _is_file_access_tool(tool_name):
            nearby_file_access_count += 1
        if nearby_file_access_count >= _HIGH_VOLUME_THRESHOLD:
            anomaly_types.append("high_volume_file_access")
            explanations.append(
                f"{nearby_file_access_count} file-access calls within "
                f"{_BURST_WINDOW_MINUTES} min window"
            )

        # ---- Rule 3: sensitive_path_burst ----
        nearby_sensitive_count = 0
        if _collect_sensitive_paths(record):
            nearby_sensitive_count += 1
        for i in nearby_indices:
            if _collect_sensitive_paths(records[i]):
                nearby_sensitive_count += 1
        if nearby_sensitive_count >= _SENSITIVE_PATH_BURST_THRESHOLD:
            anomaly_types.append("sensitive_path_burst")
            explanations.append(
                f"{nearby_sensitive_count} records with sensitive paths "
                f"within {_BURST_WINDOW_MINUTES} min window"
            )

        # ---- Rule 4: unusual_hour ----
        ts = _parse_record_timestamp(record)
        if ts is not None:
            hour = ts.hour
            if _UNUSUAL_HOUR_START <= hour <= _UNUSUAL_HOUR_END:
                anomaly_types.append("unusual_hour")
                explanations.append(f"Tool called at unusual hour {hour:02d}:00")

        # ---- Rule 5: high_risk_spike ----
        risk = _extract_decision_risk_raw(record)
        nearby_high_risk = 0
        if risk in {"high", "critical"}:
            nearby_high_risk += 1
        for i in nearby_indices:
            neighbor_risk = _extract_decision_risk_raw(records[i])
            if neighbor_risk in {"high", "critical"}:
                nearby_high_risk += 1
        if nearby_high_risk >= _HIGH_RISK_SPIKE_THRESHOLD:
            anomaly_types.append("high_risk_spike")
            explanations.append(
                f"{nearby_high_risk} high/critical risk decisions within "
                f"{_BURST_WINDOW_MINUTES} min window"
            )

        # Compute score
        score = 0
        for atype in anomaly_types:
            score += _BASE_SCORES.get(atype, 0)
        score = min(score, _MAX_SCORE)

        for atype in anomaly_types:
            anomaly_counts[atype] += 1

        explanation = "; ".join(explanations) if explanations else "No anomalies detected"

        all_results.append(
            AnomalyResult(
                record_id=record_id,
                score=score,
                anomaly_types=anomaly_types,
                explanation=explanation,
            )
        )

    overall_max = max((r.score for r in all_results), default=0)

    return {
        "scores": [r.to_dict() for r in all_results],
        "anomaly_counts": dict(anomaly_counts),
        "overall_max_score": overall_max,
    }


def classify_anomaly_level(score: int) -> str:
    """Classify an anomaly score into a severity level.

    Args:
        score: Anomaly score (0-100).

    Returns:
        One of ``"normal"``, ``"low"``, ``"medium"``, or ``"critical"``.
    """
    if score <= 0:
        return "normal"
    if score <= 25:
        return "low"
    if score <= 55:
        return "medium"
    return "critical"


def build_anomaly_summary(
    *,
    records: list[dict[str, Any]],
    session_id: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    """Build a high-level anomaly summary from audit records.

    This is the public entry point used by both the CLI ``anomaly scan``
    command and the MCP ``anomaly_summary`` tool.

    Args:
        records: Raw audit record dicts.
        session_id: Session identifier for the summary header.
        limit: Maximum number of records to process.

    Returns:
        Dictionary containing:

        - ``session_id``: The session id.
        - ``total_records_scanned``: How many records were processed.
        - ``anomaly_scores``: Per-record scoring results.
        - ``anomaly_counts``: Counts of each anomaly type that fired.
        - ``overall_max_score``: Highest score in the batch.
        - ``overall_level``: Classified severity level.
        - ``critical_records``: Records with score > 55 (critical level).
        - ``policy_decisions``: Policy decision metadata for critical records.
        - ``mvp_limits``: Note about what this MVP covers.
    """
    safe_limit = max(1, min(limit, 500))
    batch = records[:safe_limit]
    scored = compute_anomaly_scores(batch)
    overall_level = classify_anomaly_level(scored["overall_max_score"])

    critical_records: list[dict[str, Any]] = []
    policy_decisions: list[dict[str, Any]] = []

    for item in scored["scores"]:
        if item["score"] > 55:
            critical_records.append(item)
            decision_action = "unknown"
            decision_source = "unknown"
            decision_risk_level = "unknown"
            decision_reason = ""
            for record in batch:
                if record.get("record_id") == item["record_id"]:
                    decision_action = str(
                        record.get("decision_action") or "unknown"
                    )
                    decision_source = str(
                        record.get("decision_source") or "unknown"
                    )
                    decision_risk_level = str(
                        record.get("decision_risk_level") or "unknown"
                    )
                    decision_reason = str(
                        record.get("decision_reason") or ""
                    )
                    break
            policy_decisions.append(
                {
                    "record_id": item["record_id"],
                    "score": item["score"],
                    "level": "critical",
                    "anomaly_types": item["anomaly_types"],
                    "explanation": item["explanation"],
                    "decision_action": decision_action,
                    "decision_source": decision_source,
                    "decision_risk_level": decision_risk_level,
                    "decision_reason": decision_reason,
                    "recommended_action": (
                        "escalate"
                        if decision_action == "deny"
                        else "review"
                    ),
                }
            )

    return {
        "session_id": session_id,
        "total_records_scanned": len(batch),
        "anomaly_scores": scored["scores"],
        "anomaly_counts": scored["anomaly_counts"],
        "overall_max_score": scored["overall_max_score"],
        "overall_level": overall_level,
        "critical_count": len(critical_records),
        "critical_records": critical_records,
        "policy_decisions": policy_decisions,
        "mvp_limits": {
            "scope": "rule-based, no ML model",
            "rules": [
                "new_tool_use",
                "high_volume_file_access",
                "sensitive_path_burst",
                "unusual_hour",
                "high_risk_spike",
            ],
            "note": "This MVP uses deterministic heuristics only. "
            "Scores are additive and capped at 100.",
        },
    }
