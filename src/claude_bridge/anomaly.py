"""Anomaly feature extraction and rule-based scoring from audit records."""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


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
# Critical-only anomaly detection
# ---------------------------------------------------------------------------

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

_PRIVILEGED_TOOLS: set[str] = {
    "set_config_value",
    "run_shell",
    "start_process",
    "sudo",
}

_DANGEROUS_TOOLS: set[str] = {
    "run_shell",
    "start_process",
    "patch_file",
    "undo_last_patch",
}

_SUSPICIOUS_FILE_EXTENSIONS: tuple[str, ...] = (
    ".pem",
    ".p12",
    ".pfx",
    ".crt",
    ".cer",
    ".key",
    ".jks",
    ".keystore",
    ".pkcs12",
)

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
    ".p12",
    ".pfx",
    ".pem",
    ".crt",
    ".cer",
    ".key",
    ".jks",
    ".keystore",
]

_SENSITIVE_CONTENT_MARKERS: tuple[str, ...] = (
    "api_key",
    "apikey",
    "access_token",
    "auth_token",
    "secret",
    "password",
    "private key",
    "begin rsa private key",
    "begin openssh private key",
)

# Critical-only rules: only detect genuine security concerns
# Removed noise-generating rules like unusual_hour, rapid_tool_switch, volume_anomaly

_PRIVILEGE_CONFIG_KEYS: set[str] = {
    "role",
    "user",
    "auto_approve",
    "client_managed_approval",
    "approval_preset",
}

_BURST_WINDOW_MINUTES: int = 5
_SENSITIVE_PATH_BURST_THRESHOLD: int = 3
_HIGH_RISK_SPIKE_THRESHOLD: int = 3
_EXFILTRATION_PATTERN_THRESHOLD: int = 3
_SUSPICIOUS_FILE_TYPE_THRESHOLD: int = 2

_BASE_SCORES: dict[str, int] = {
    "sensitive_path_burst": 60,
    "exfiltration_pattern": 70,
    "privilege_escalation_attempt": 65,
    "new_dangerous_tool_use": 45,
    "high_risk_spike": 40,
    "suspicious_file_type": 40,
}

_MAX_SCORE: int = 100
_RUNTIME_POLICY_MODE = "warn_and_log"


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
            "recommended_action": get_anomaly_action(self.score),
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


def _record_has_sensitive_content_marker(record: dict[str, Any]) -> bool:
    """Return True when params/details suggest secret material content."""
    candidates: list[str] = []
    params = record.get("params", {})
    if isinstance(params, dict) and not _is_masked_value(params):
        for key in ("content", "search", "replace", "text", "value"):
            value = params.get(key)
            if isinstance(value, str):
                candidates.append(value)

    result = record.get("result", {})
    if isinstance(result, dict):
        details = result.get("details", {})
        if isinstance(details, dict) and not _is_masked_value(details):
            for key in ("content_preview", "preview", "stdout", "stderr"):
                value = details.get(key)
                if isinstance(value, str):
                    candidates.append(value)

    return any(
        marker in candidate.lower()
        for candidate in candidates
        for marker in _SENSITIVE_CONTENT_MARKERS
    )


def _is_exfiltration_candidate(record: dict[str, Any]) -> bool:
    """Detect records that expose secret-like content, not just sensitive paths."""
    return _record_has_sensitive_content_marker(record)


def _is_privilege_escalation_attempt(record: dict[str, Any]) -> bool:
    """Detect role/config changes that could elevate execution privileges."""
    tool_name = _extract_tool_name_raw(record)
    params = record.get("params", {})
    if not isinstance(params, dict) or _is_masked_value(params):
        return False

    if tool_name == "set_config_value":
        key = params.get("key")
        if isinstance(key, str) and key in _PRIVILEGE_CONFIG_KEYS:
            return True

    command = params.get("command")
    if isinstance(command, str):
        lowered = command.lower()
        return any(
            token in lowered
            for token in (
                "sudo ",
                "su ",
                "chmod 777",
                "chown ",
                "set_config_value role",
            )
        )
    return False


def _command_prefix(command: str) -> str:
    parts = command.strip().split()
    if not parts:
        return ""
    if len(parts) >= 2 and parts[0] in {"python", "python3"} and parts[1] == "-m":
        return " ".join(parts[:3])
    if len(parts) >= 2 and parts[0] in {"npm", "pnpm", "yarn", "git"}:
        return " ".join(parts[:2])
    return parts[0]


def _record_command_prefix(record: dict[str, Any]) -> str:
    if _extract_tool_name_raw(record) not in {"run_shell", "start_process"}:
        return ""
    params = record.get("params", {})
    if not isinstance(params, dict) or _is_masked_value(params):
        return ""
    command = params.get("command")
    return _command_prefix(command) if isinstance(command, str) else ""


def _path_root(path: str) -> str:
    normalized = path.replace("\\", "/").strip()
    if not normalized:
        return ""
    if normalized.startswith("/"):
        parts = [part for part in normalized.split("/") if part]
        return f"/{parts[0]}" if parts else "/"
    return normalized.split("/", 1)[0]


def _record_path_roots(record: dict[str, Any]) -> set[str]:
    return {root for root in (_path_root(path) for path in _collect_record_paths(record)) if root}


def _is_dangerous_tool(tool_name: str) -> bool:
    """Check if a tool name is considered dangerous."""
    return tool_name in _DANGEROUS_TOOLS


def _has_suspicious_file_extension(path: str) -> bool:
    """Check if a path has a suspicious certificate/key file extension."""
    lower_path = path.lower()
    return lower_path.endswith(_SUSPICIOUS_FILE_EXTENSIONS)


def _extract_command(record: dict[str, Any]) -> str:
    """Extract command string from record params or result details."""
    params = record.get("params", {})
    if isinstance(params, dict) and not _is_masked_value(params):
        cmd = params.get("command")
        if isinstance(cmd, str) and cmd.strip():
            return cmd.strip()
    result = record.get("result", {})
    if isinstance(result, dict):
        details = result.get("details", {})
        if isinstance(details, dict) and not _is_masked_value(details):
            cmd = details.get("command")
            if isinstance(cmd, str) and cmd.strip():
                return cmd.strip()
    return ""


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
    *,
    baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute critical-only anomaly scores for audit records.

    Only detects genuine security concerns:
    - **sensitive_path_burst**: ≥3 records referencing sensitive paths within
      a 5-minute sliding window.
    - **exfiltration_pattern**: Records touching sensitive content.
    - **privilege_escalation_attempt**: Config/role changes or suspicious commands.
    - **new_dangerous_tool_use**: First use of dangerous tool in session.
    - **high_risk_spike**: ≥3 high/critical risk decisions within a
      5-minute sliding window.
    - **suspicious_file_type**: Access to certificate/key files.

    Removed noise-generating rules: unusual_hour, rapid_tool_switch,
    volume_anomaly, new_tool_use, high_volume_file_access, etc.
    """
    if not records:
        return {
            "scores": [],
            "anomaly_counts": {},
            "overall_max_score": 0,
            "recommended_action": get_anomaly_action(0),
            "runtime_policy": get_anomaly_runtime_policy(0),
        }

    window = timedelta(minutes=_BURST_WINDOW_MINUTES)
    anomaly_counts: CounterType[str] = CounterType()
    all_results: list[AnomalyResult] = []

    for idx, record in enumerate(records):
        anomaly_types: list[str] = []
        explanations: list[str] = []

        tool_name = _extract_tool_name_raw(record)
        record_id = str(record.get("record_id", ""))
        nearby_indices = _records_in_window(records, idx, window)

        # ---- sensitive_path_burst ----
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

        # ---- exfiltration_pattern ----
        nearby_exfiltration_count = 1 if _is_exfiltration_candidate(record) else 0
        for i in nearby_indices:
            if _is_exfiltration_candidate(records[i]):
                nearby_exfiltration_count += 1
        if nearby_exfiltration_count >= _EXFILTRATION_PATTERN_THRESHOLD:
            anomaly_types.append("exfiltration_pattern")
            explanations.append(
                f"{nearby_exfiltration_count} records touching sensitive "
                f"content within {_BURST_WINDOW_MINUTES} min window"
            )

        # ---- privilege_escalation_attempt ----
        if _is_privilege_escalation_attempt(record):
            anomaly_types.append("privilege_escalation_attempt")
            explanations.append("Record attempts to alter role, approval, or privilege settings")

        # ---- new_dangerous_tool_use ----
        if tool_name and _is_dangerous_tool(tool_name):
            anomaly_types.append("new_dangerous_tool_use")
            explanations.append(f"First use of dangerous tool '{tool_name}'")

        # ---- high_risk_spike ----
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

        # ---- suspicious_file_type ----
        all_paths = _collect_record_paths(record)
        suspicious_ext_count = sum(1 for p in all_paths if _has_suspicious_file_extension(p))
        if suspicious_ext_count >= _SUSPICIOUS_FILE_TYPE_THRESHOLD:
            anomaly_types.append("suspicious_file_type")
            explanations.append(
                f"Access to {suspicious_ext_count} certificate/key files "
                f"(.pem, .p12, .crt, .key, etc.)"
            )

        score = 0
        for atype in anomaly_types:
            score += _BASE_SCORES.get(atype, 0)
        score = min(score, _MAX_SCORE)

        for atype in anomaly_types:
            anomaly_counts[atype] += 1

        explanation = "; ".join(explanations) if explanations else "No critical anomalies detected"

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
        "recommended_action": get_anomaly_action(overall_max),
        "runtime_policy": get_anomaly_runtime_policy(overall_max),
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


def get_anomaly_action(score: int) -> str:
    """Map an anomaly score to the recommended runtime action."""
    if score <= 30:
        return "log"
    if score <= 55:
        return "status"
    if score <= 80:
        return "ask"
    return "deny"


def get_anomaly_runtime_policy(score: int) -> dict[str, Any]:
    """Return the explicit runtime policy for anomaly results.

    v0.1 keeps anomaly detection advisory: high scores are surfaced as warning
    metadata and audit detail, but they do not deny or approve tool calls.
    """
    recommended_action = get_anomaly_action(score)
    return {
        "mode": _RUNTIME_POLICY_MODE,
        "enforced": False,
        "recommended_action": recommended_action,
        "effective_action": "warn" if recommended_action in {"ask", "deny"} else "log",
        "note": (
            "Anomaly scoring is advisory in this release. High scores should be "
            "reviewed, but they do not change guard-policy decisions."
        ),
    }


def build_anomaly_summary(
    *,
    records: list[dict[str, Any]],
    session_id: str = "",
    limit: int = 50,
    baseline: dict[str, Any] | None = None,
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
    scored = compute_anomaly_scores(batch, baseline=baseline)
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
                    decision_action = str(record.get("decision_action") or "unknown")
                    decision_source = str(record.get("decision_source") or "unknown")
                    decision_risk_level = str(record.get("decision_risk_level") or "unknown")
                    decision_reason = str(record.get("decision_reason") or "")
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
                    "recommended_action": ("escalate" if decision_action == "deny" else "review"),
                }
            )

    return {
        "session_id": session_id,
        "total_records_scanned": len(batch),
        "anomaly_scores": scored["scores"],
        "anomaly_counts": scored["anomaly_counts"],
        "overall_max_score": scored["overall_max_score"],
        "overall_level": overall_level,
        "recommended_action": scored["recommended_action"],
        "runtime_policy": scored["runtime_policy"],
        "baseline": {
            "enabled": isinstance(baseline, dict),
            "session_count": baseline.get("session_count") if isinstance(baseline, dict) else None,
            "record_count": baseline.get("record_count") if isinstance(baseline, dict) else None,
            "updated_at": baseline.get("updated_at") if isinstance(baseline, dict) else None,
        },
        "critical_count": len(critical_records),
        "critical_records": critical_records,
        "policy_decisions": policy_decisions,
        "mvp_limits": {
            "scope": "critical security anomalies only, no ML model",
            "rules": [
                "sensitive_path_burst",
                "exfiltration_pattern",
                "privilege_escalation_attempt",
                "new_dangerous_tool_use",
                "high_risk_spike",
                "suspicious_file_type",
            ],
            "note": "Heuristics only, scores are additive, capped at 100, advisory.",
        },
    }
