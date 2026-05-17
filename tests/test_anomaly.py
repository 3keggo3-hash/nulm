"""Tests for anomaly feature extraction and rule-based scoring."""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


import pytest

from claude_bridge.anomaly import (
    AnomalyFeature,
    build_anomaly_summary,
    classify_anomaly_level,
    compute_anomaly_scores,
    extract_features,
    extract_features_batch,
    parse_record_from_json,
    parse_record_from_yaml,
)

try:
    import yaml

    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False
    yaml = None


class TestAnomalyFeatureDataclass:
    """Tests for AnomalyFeature dataclass."""

    def test_create_anomaly_feature(self):
        feature = AnomalyFeature(
            tool_name="read_file",
            hour=14,
            path_count=1,
            command_length=0,
            decision_action="allow",
            risk_level="low",
            record_id="abc123",
            timestamp="2024-01-15T14:30:00Z",
        )
        assert feature.tool_name == "read_file"
        assert feature.hour == 14
        assert feature.path_count == 1
        assert feature.command_length == 0
        assert feature.decision_action == "allow"
        assert feature.risk_level == "low"
        assert feature.record_id == "abc123"
        assert feature.timestamp == "2024-01-15T14:30:00Z"

    def test_to_dict(self):
        feature = AnomalyFeature(
            tool_name="run_shell",
            hour=10,
            path_count=0,
            command_length=25,
            decision_action="deny",
            risk_level="high",
        )
        result = feature.to_dict()
        assert result["tool_name"] == "run_shell"
        assert result["hour"] == 10
        assert result["path_count"] == 0
        assert result["command_length"] == 25
        assert result["decision_action"] == "deny"
        assert result["risk_level"] == "high"


class TestExtractToolName:
    """Tests for tool name extraction."""

    def test_extract_tool_name_normal(self):
        record = {"tool_name": "read_file"}
        feature = extract_features(record)
        assert feature.tool_name == "read_file"

    def test_extract_tool_name_missing(self):
        record: dict = {}
        feature = extract_features(record)
        assert feature.tool_name == "unknown"

    def test_extract_tool_name_masked(self):
        record = {"tool_name": {"redacted": True, "reason": "sensitive"}}
        feature = extract_features(record)
        assert feature.tool_name == "unknown"

    def test_extract_tool_name_empty_string(self):
        record = {"tool_name": ""}
        feature = extract_features(record)
        assert feature.tool_name == "unknown"

    def test_extract_tool_name_whitespace(self):
        record = {"tool_name": "   "}
        feature = extract_features(record)
        assert feature.tool_name == "unknown"


class TestExtractHour:
    """Tests for hour extraction from timestamp."""

    def test_extract_hour_normal(self):
        record = {"timestamp": "2024-01-15T14:30:00Z"}
        feature = extract_features(record)
        assert feature.hour == 14

    def test_extract_hour_midnight(self):
        record = {"timestamp": "2024-01-15T00:00:00Z"}
        feature = extract_features(record)
        assert feature.hour == 0

    def test_extract_hour_night(self):
        record = {"timestamp": "2024-01-15T23:59:59Z"}
        feature = extract_features(record)
        assert feature.hour == 23

    def test_extract_hour_missing_timestamp(self):
        record: dict = {}
        feature = extract_features(record)
        assert feature.hour == -1

    def test_extract_hour_masked_timestamp(self):
        record = {"timestamp": {"redacted": True}}
        feature = extract_features(record)
        assert feature.hour == -1

    def test_extract_hour_invalid_format(self):
        record = {"timestamp": "not-a-timestamp"}
        feature = extract_features(record)
        assert feature.hour == -1

    def test_extract_hour_with_milliseconds(self):
        record = {"timestamp": "2024-01-15T10:30:45.123Z"}
        feature = extract_features(record)
        assert feature.hour == 10


class TestExtractPathCount:
    """Tests for path count extraction."""

    def test_extract_path_count_single_file(self):
        record = {"params": {"file": "/path/to/file.txt"}}
        feature = extract_features(record)
        assert feature.path_count == 1

    def test_extract_path_count_multiple_paths(self):
        record = {
            "params": {
                "source": "/src/file.py",
                "destination": "/dst/file.py",
            }
        }
        feature = extract_features(record)
        assert feature.path_count == 2

    def test_extract_path_count_duplicate_paths(self):
        record = {
            "params": {
                "file": "/same/path.txt",
                "path": "/same/path.txt",
            }
        }
        feature = extract_features(record)
        assert feature.path_count == 1

    def test_extract_path_count_no_paths(self):
        record = {"params": {"command": "echo hello"}}
        feature = extract_features(record)
        assert feature.path_count == 0

    def test_extract_path_count_masked_params(self):
        record = {"params": {"redacted": True}}
        feature = extract_features(record)
        assert feature.path_count == 0

    def test_extract_path_count_masked_path_value(self):
        record = {"params": {"file": {"redacted": True, "reason": "sensitive"}}}
        feature = extract_features(record)
        assert feature.path_count == 0

    def test_extract_path_count_from_result_details(self):
        record = {"result": {"details": {"path": "/output/file.txt"}}}
        feature = extract_features(record)
        assert feature.path_count == 1

    def test_extract_path_count_empty_string_path(self):
        record = {"params": {"file": ""}}
        feature = extract_features(record)
        assert feature.path_count == 0


class TestExtractCommandLength:
    """Tests for command length extraction."""

    def test_extract_command_length_normal(self):
        record = {"params": {"command": "git status"}}
        feature = extract_features(record)
        assert feature.command_length == 10

    def test_extract_command_length_empty(self):
        record = {"params": {"command": ""}}
        feature = extract_features(record)
        assert feature.command_length == 0

    def test_extract_command_length_missing(self):
        record: dict = {"params": {}}
        feature = extract_features(record)
        assert feature.command_length == 0

    def test_extract_command_length_masked(self):
        record = {"params": {"command": {"redacted": True}}}
        feature = extract_features(record)
        assert feature.command_length == 0

    def test_extract_command_length_from_result_details(self):
        record = {"result": {"details": {"command": "pytest tests/"}}}
        feature = extract_features(record)
        assert feature.command_length == 13

    def test_extract_command_length_params_take_priority(self):
        record = {
            "params": {"command": "short"},
            "result": {"details": {"command": "much longer command"}},
        }
        feature = extract_features(record)
        assert feature.command_length == 5


class TestExtractDecisionAction:
    """Tests for decision action extraction."""

    def test_extract_decision_action_allow(self):
        record = {"decision_action": "allow"}
        feature = extract_features(record)
        assert feature.decision_action == "allow"

    def test_extract_decision_action_deny(self):
        record = {"decision_action": "deny"}
        feature = extract_features(record)
        assert feature.decision_action == "deny"

    def test_extract_decision_action_ask(self):
        record = {"decision_action": "ask"}
        feature = extract_features(record)
        assert feature.decision_action == "ask"

    def test_extract_decision_action_case_insensitive(self):
        record = {"decision_action": "ALLOW"}
        feature = extract_features(record)
        assert feature.decision_action == "allow"

    def test_extract_decision_action_missing(self):
        record: dict = {}
        feature = extract_features(record)
        assert feature.decision_action == "unknown"

    def test_extract_decision_action_masked(self):
        record = {"decision_action": {"redacted": True}}
        feature = extract_features(record)
        assert feature.decision_action == "unknown"

    def test_extract_decision_action_from_result_details(self):
        record = {"result": {"details": {"decision": {"action": "deny"}}}}
        feature = extract_features(record)
        assert feature.decision_action == "deny"

    def test_extract_decision_action_direct_takes_priority(self):
        record = {
            "decision_action": "allow",
            "result": {"details": {"decision": {"action": "deny"}}},
        }
        feature = extract_features(record)
        assert feature.decision_action == "allow"


class TestExtractRiskLevel:
    """Tests for risk level extraction."""

    def test_extract_risk_level_low(self):
        record = {"decision_risk_level": "low"}
        feature = extract_features(record)
        assert feature.risk_level == "low"

    def test_extract_risk_level_medium(self):
        record = {"decision_risk_level": "medium"}
        feature = extract_features(record)
        assert feature.risk_level == "medium"

    def test_extract_risk_level_high(self):
        record = {"decision_risk_level": "high"}
        feature = extract_features(record)
        assert feature.risk_level == "high"

    def test_extract_risk_level_critical(self):
        record = {"decision_risk_level": "critical"}
        feature = extract_features(record)
        assert feature.risk_level == "critical"

    def test_extract_risk_level_case_insensitive(self):
        record = {"decision_risk_level": "HIGH"}
        feature = extract_features(record)
        assert feature.risk_level == "high"

    def test_extract_risk_level_missing(self):
        record: dict = {}
        feature = extract_features(record)
        assert feature.risk_level == "unknown"

    def test_extract_risk_level_masked(self):
        record = {"decision_risk_level": {"redacted": True}}
        feature = extract_features(record)
        assert feature.risk_level == "unknown"

    def test_extract_risk_level_from_result_details(self):
        record = {"result": {"details": {"decision": {"risk_level": "high"}}}}
        feature = extract_features(record)
        assert feature.risk_level == "high"

    def test_extract_risk_level_direct_takes_priority(self):
        record = {
            "decision_risk_level": "low",
            "result": {"details": {"decision": {"risk_level": "high"}}},
        }
        feature = extract_features(record)
        assert feature.risk_level == "low"


class TestExtractFeaturesIntegration:
    """Integration tests for full feature extraction."""

    def test_extract_features_complete_record(self):
        record = {
            "record_id": "test-123",
            "timestamp": "2024-01-15T14:30:00Z",
            "tool_name": "run_shell",
            "params": {"command": "git push origin main"},
            "decision_action": "allow",
            "decision_risk_level": "low",
        }
        feature = extract_features(record)
        assert feature.tool_name == "run_shell"
        assert feature.hour == 14
        assert feature.path_count == 0
        assert feature.command_length == 20
        assert feature.decision_action == "allow"
        assert feature.risk_level == "low"
        assert feature.record_id == "test-123"

    def test_extract_features_with_paths(self):
        record = {
            "record_id": "test-456",
            "timestamp": "2024-01-15T09:00:00Z",
            "tool_name": "copy_file",
            "params": {
                "source": "/src/config.py",
                "destination": "/dst/config.py",
            },
            "decision_action": "ask",
            "decision_risk_level": "medium",
        }
        feature = extract_features(record)
        assert feature.tool_name == "copy_file"
        assert feature.hour == 9
        assert feature.path_count == 2
        assert feature.command_length == 0
        assert feature.decision_action == "ask"
        assert feature.risk_level == "medium"

    def test_extract_features_all_masked(self):
        record = {
            "record_id": "test-789",
            "timestamp": {"redacted": True},
            "tool_name": {"redacted": True},
            "params": {"redacted": True},
            "decision_action": {"redacted": True},
            "decision_risk_level": {"redacted": True},
        }
        feature = extract_features(record)
        assert feature.tool_name == "unknown"
        assert feature.hour == -1
        assert feature.path_count == 0
        assert feature.command_length == 0
        assert feature.decision_action == "unknown"
        assert feature.risk_level == "unknown"

    def test_extract_features_empty_record(self):
        record: dict = {}
        feature = extract_features(record)
        assert feature.tool_name == "unknown"
        assert feature.hour == -1
        assert feature.path_count == 0
        assert feature.command_length == 0
        assert feature.decision_action == "unknown"
        assert feature.risk_level == "unknown"


class TestExtractFeaturesBatch:
    """Tests for batch feature extraction."""

    def test_extract_features_batch_multiple_records(self):
        records = [
            {"tool_name": "read_file", "timestamp": "2024-01-15T10:00:00Z"},
            {"tool_name": "write_file", "timestamp": "2024-01-15T11:00:00Z"},
            {"tool_name": "run_shell", "timestamp": "2024-01-15T12:00:00Z"},
        ]
        features = extract_features_batch(records)
        assert len(features) == 3
        assert features[0].tool_name == "read_file"
        assert features[1].tool_name == "write_file"
        assert features[2].tool_name == "run_shell"

    def test_extract_features_batch_skips_invalid(self):
        records = [
            {"tool_name": "read_file"},
            "not a dict",
            {"tool_name": "write_file"},
            None,
            123,
        ]
        features = extract_features_batch(records)
        assert len(features) == 2

    def test_extract_features_batch_empty_list(self):
        features = extract_features_batch([])
        assert len(features) == 0


class TestParseRecordFromJson:
    """Tests for JSON parsing."""

    def test_parse_record_from_json_valid(self):
        json_str = '{"tool_name": "read_file", "params": {"file": "test.txt"}}'
        result = parse_record_from_json(json_str)
        assert result is not None
        assert result["tool_name"] == "read_file"
        assert result["params"]["file"] == "test.txt"

    def test_parse_record_from_json_invalid(self):
        json_str = "not valid json"
        result = parse_record_from_json(json_str)
        assert result is None

    def test_parse_record_from_json_not_dict(self):
        json_str = '["array", "not", "dict"]'
        result = parse_record_from_json(json_str)
        assert result is None

    def test_parse_record_from_json_empty(self):
        result = parse_record_from_json("")
        assert result is None


class TestParseRecordFromYaml:
    """Tests for YAML parsing."""

    @pytest.mark.skipif(not _YAML_AVAILABLE, reason="PyYAML not installed")
    def test_parse_record_from_yaml_valid(self):
        yaml_str = """
tool_name: read_file
params:
  file: test.txt
"""
        result = parse_record_from_yaml(yaml_str)
        assert result is not None
        assert result["tool_name"] == "read_file"
        assert result["params"]["file"] == "test.txt"

    @pytest.mark.skipif(not _YAML_AVAILABLE, reason="PyYAML not installed")
    def test_parse_record_from_yaml_invalid(self):
        yaml_str = "invalid: yaml: : :"
        result = parse_record_from_yaml(yaml_str)
        assert result is None

    @pytest.mark.skipif(not _YAML_AVAILABLE, reason="PyYAML not installed")
    def test_parse_record_from_yaml_not_dict(self):
        yaml_str = "- item1\n- item2\n"
        result = parse_record_from_yaml(yaml_str)
        assert result is None

    @pytest.mark.skipif(not _YAML_AVAILABLE, reason="PyYAML not installed")
    def test_parse_record_from_yaml_empty(self):
        result = parse_record_from_yaml("")
        assert result is None

    def test_parse_record_from_yaml_not_available(self):
        if not _YAML_AVAILABLE:
            result = parse_record_from_yaml("tool_name: test")
            assert result is None


class TestFeatureExtractionExceptionHandling:
    """Tests for exception handling during feature extraction."""

    def test_extract_features_non_dict_record(self):
        with pytest.raises(ValueError, match="record must be a dictionary"):
            extract_features("not a dict")  # type: ignore

    def test_extract_features_none_record(self):
        with pytest.raises(ValueError, match="record must be a dictionary"):
            extract_features(None)  # type: ignore

    def test_extract_features_list_record(self):
        with pytest.raises(ValueError, match="record must be a dictionary"):
            extract_features([1, 2, 3])  # type: ignore


class TestTimestampParsingEdgeCases:
    """Tests for various timestamp formats."""

    def test_timestamp_iso_with_timezone(self):
        record = {"timestamp": "2024-01-15T10:30:00+00:00"}
        feature = extract_features(record)
        assert feature.hour == 10

    def test_timestamp_space_separated(self):
        record = {"timestamp": "2024-01-15 14:00:00"}
        feature = extract_features(record)
        assert feature.hour == 14

    def test_timestamp_without_timezone(self):
        record = {"timestamp": "2024-01-15T08:30:00"}
        feature = extract_features(record)
        assert feature.hour == 8


class TestClassifyAnomalyLevel:
    def test_normal(self):
        assert classify_anomaly_level(0) == "normal"

    def test_low(self):
        assert classify_anomaly_level(1) == "low"
        assert classify_anomaly_level(25) == "low"

    def test_medium(self):
        assert classify_anomaly_level(26) == "medium"
        assert classify_anomaly_level(55) == "medium"

    def test_critical(self):
        assert classify_anomaly_level(56) == "critical"
        assert classify_anomaly_level(100) == "critical"


class TestComputeAnomalyScores:
    def test_empty_records(self):
        result = compute_anomaly_scores([])
        assert result["scores"] == []
        assert result["anomaly_counts"] == {}
        assert result["overall_max_score"] == 0

    def test_single_record_no_anomalies(self):
        records = [
            {
                "record_id": "r1",
                "timestamp": "2024-01-15T14:00:00Z",
                "tool_name": "read_file",
                "decision_action": "allow",
                "decision_risk_level": "low",
            }
        ]
        result = compute_anomaly_scores(records)
        assert len(result["scores"]) == 1
        assert result["scores"][0]["score"] >= 0
        assert result["overall_max_score"] >= 0

    def test_new_dangerous_tool_detected(self):
        records = [
            {
                "record_id": "r1",
                "timestamp": "2024-01-15T14:00:00Z",
                "tool_name": "run_shell",
                "decision_action": "allow",
                "decision_risk_level": "high",
            },
        ]
        result = compute_anomaly_scores(records)
        types_seen: set[str] = set()
        for s in result["scores"]:
            types_seen.update(s["anomaly_types"])
        assert "new_dangerous_tool_use" in types_seen

    def test_sensitive_path_burst(self):
        base_ts = "2024-01-15T14:00:00Z"
        records = []
        for i in range(4):
            records.append(
                {
                    "record_id": f"sp{i}",
                    "timestamp": base_ts,
                    "tool_name": "read_file",
                    "params": {"file": "/home/user/.ssh/id_rsa"},
                    "decision_action": "allow",
                    "decision_risk_level": "low",
                }
            )
        result = compute_anomaly_scores(records)
        types_seen: set[str] = set()
        for s in result["scores"]:
            types_seen.update(s["anomaly_types"])
        assert "sensitive_path_burst" in types_seen
        assert result["overall_max_score"] > 0

    def test_score_capped_at_100(self):
        records = [
            {
                "record_id": f"c{i}",
                "timestamp": "2024-01-15T03:00:00Z",
                "tool_name": f"tool_{i}",
                "params": {"file": "/home/user/.ssh/id_rsa"},
                "decision_action": "deny",
                "decision_risk_level": "critical",
            }
            for i in range(20)
        ]
        result = compute_anomaly_scores(records)
        for s in result["scores"]:
            assert s["score"] <= 100


class TestBuildAnomalySummary:
    def test_empty_records(self):
        summary = build_anomaly_summary(records=[], session_id="test-session", limit=50)
        assert summary["session_id"] == "test-session"
        assert summary["total_records_scanned"] == 0
        assert summary["anomaly_scores"] == []
        assert summary["critical_count"] == 0
        assert summary["overall_level"] == "normal"
        assert summary["recommended_action"] == "log"
        assert summary["runtime_policy"]["mode"] == "warn_and_log"
        assert summary["runtime_policy"]["enforced"] is False
        assert summary["baseline"]["enabled"] is False
        assert summary["policy_decisions"] == []

    def test_summary_includes_mvp_limits(self):
        summary = build_anomaly_summary(records=[], session_id="test", limit=10)
        assert "mvp_limits" in summary
        assert summary["mvp_limits"]["scope"] == "critical security anomalies only, no ML model"
        assert len(summary["mvp_limits"]["rules"]) == 6
        assert "exfiltration_pattern" in summary["mvp_limits"]["rules"]
        assert "privilege_escalation_attempt" in summary["mvp_limits"]["rules"]
        assert "new_dangerous_tool_use" in summary["mvp_limits"]["rules"]
        assert "sensitive_path_burst" in summary["mvp_limits"]["rules"]
        assert "high_risk_spike" in summary["mvp_limits"]["rules"]
        assert "suspicious_file_type" in summary["mvp_limits"]["rules"]

    def test_critical_record_includes_policy_metadata(self):
        records = [
            {
                "record_id": "crit-1",
                "timestamp": "2024-01-15T03:00:00Z",
                "tool_name": "read_file",
                "params": {"file": "/home/user/.ssh/id_rsa"},
                "decision_action": "deny",
                "decision_source": "rule",
                "decision_risk_level": "high",
                "decision_reason": "sensitive path access blocked",
            },
            {
                "record_id": "crit-2",
                "timestamp": "2024-01-15T03:01:00Z",
                "tool_name": "read_file",
                "params": {"file": "/home/user/.ssh/authorized_keys"},
                "decision_action": "deny",
                "decision_source": "rule",
                "decision_risk_level": "high",
                "decision_reason": "sensitive path access blocked",
            },
            {
                "record_id": "crit-3",
                "timestamp": "2024-01-15T03:02:00Z",
                "tool_name": "read_file",
                "params": {"file": "/etc/passwd"},
                "decision_action": "deny",
                "decision_source": "builtin_guard",
                "decision_risk_level": "critical",
                "decision_reason": "system file access blocked",
            },
        ]
        summary = build_anomaly_summary(records=records, session_id="sess-1", limit=50)
        assert summary["critical_count"] > 0
        assert len(summary["policy_decisions"]) > 0
        pd = summary["policy_decisions"][0]
        assert pd["level"] == "critical"
        assert pd["decision_action"] in ("deny", "unknown")
        assert "recommended_action" in pd
        assert pd["recommended_action"] in ("escalate", "review")

    def test_limit_is_respected(self):
        records = [
            {
                "record_id": f"r{i}",
                "timestamp": "2024-01-15T14:00:00Z",
                "tool_name": "read_file",
                "decision_action": "allow",
                "decision_risk_level": "low",
            }
            for i in range(100)
        ]
        summary = build_anomaly_summary(records=records, session_id="sess", limit=10)
        assert summary["total_records_scanned"] == 10

    def test_normal_records_no_critical(self):
        records = [
            {
                "record_id": f"n{i}",
                "timestamp": "2024-01-15T14:00:00Z",
                "tool_name": "read_file",
                "params": {"file": "/project/normal.txt"},
                "decision_action": "allow",
                "decision_risk_level": "low",
            }
            for i in range(5)
        ]
        summary = build_anomaly_summary(records=records, session_id="sess", limit=50)
        assert summary["critical_count"] == 0
        assert summary["policy_decisions"] == []
        assert summary["overall_level"] in ("normal", "low", "medium")
