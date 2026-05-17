"""Tests for rule-based anomaly scorer."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from claude_bridge.anomaly import (
    AnomalyResult,
    classify_anomaly_level,
    compute_anomaly_scores,
    get_anomaly_action,
    get_anomaly_runtime_policy,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    record_id: str,
    tool_name: str,
    timestamp: str,
    risk_level: str = "low",
    paths: list[str] | None = None,
) -> dict:
    """Build a minimal audit record dict for testing."""
    params: dict = {}
    if paths:
        for i, p in enumerate(paths):
            if i == 0:
                params["file"] = p
            elif i == 1:
                params["destination"] = p
            else:
                params[f"path_{i}"] = p
    return {
        "record_id": record_id,
        "tool_name": tool_name,
        "timestamp": timestamp,
        "params": params,
        "result": {
            "details": {
                "decision": {
                    "risk_level": risk_level,
                }
            }
        },
    }


def _offset_time(base: str, seconds: int) -> str:
    """Return an ISO timestamp offset by `seconds` from `base`."""
    from datetime import datetime, timedelta

    dt = datetime.strptime(base, "%Y-%m-%dT%H:%M:%SZ")
    dt = dt + timedelta(seconds=seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# AnomalyResult dataclass
# ---------------------------------------------------------------------------


class TestAnomalyResultDataclass:
    """Tests for AnomalyResult dataclass."""

    def test_create_normal_result(self):
        result = AnomalyResult(
            record_id="rec-1",
            score=0,
            anomaly_types=[],
            explanation="No anomalies detected",
        )
        assert result.record_id == "rec-1"
        assert result.score == 0
        assert result.anomaly_types == []

    def test_create_critical_result(self):
        result = AnomalyResult(
            record_id="rec-99",
            score=100,
            anomaly_types=["sensitive_path_burst", "high_risk_spike"],
            explanation="Multiple critical anomalies",
        )
        assert result.score == 100
        assert "sensitive_path_burst" in result.anomaly_types

    def test_to_dict(self):
        result = AnomalyResult(
            record_id="rec-1",
            score=20,
            anomaly_types=["new_tool_use"],
            explanation="First use of tool 'read_file' in session",
        )
        d = result.to_dict()
        assert d["record_id"] == "rec-1"
        assert d["score"] == 20
        assert d["anomaly_types"] == ["new_tool_use"]


class TestAnomalyRuntimePolicy:
    """Tests for explicit advisory runtime policy."""

    def test_high_score_warns_without_enforcement(self):
        policy = get_anomaly_runtime_policy(100)

        assert policy["mode"] == "warn_and_log"
        assert policy["enforced"] is False
        assert policy["recommended_action"] == "deny"
        assert policy["effective_action"] == "warn"

    def test_compute_scores_includes_runtime_policy(self):
        records = [
            _make_record(
                "r1",
                "read_file",
                "2024-06-15T03:00:00Z",
                risk_level="critical",
                paths=["/etc/passwd"],
            )
            for _ in range(4)
        ]

        result = compute_anomaly_scores(records)

        assert result["recommended_action"] in {"ask", "deny"}
        assert result["runtime_policy"]["mode"] == "warn_and_log"
        assert result["runtime_policy"]["enforced"] is False


# ---------------------------------------------------------------------------
# Normal anomaly (score 0)
# ---------------------------------------------------------------------------


class TestComputeAnomalyScoresNormal:
    """Tests for normal (score 0) scenarios."""

    def test_empty_records(self):
        result = compute_anomaly_scores([])
        assert result["scores"] == []
        assert result["anomaly_counts"] == {}
        assert result["overall_max_score"] == 0

    def test_single_normal_record(self):
        records = [
            _make_record("r1", "read_file", "2024-06-15T10:00:00Z"),
        ]
        result = compute_anomaly_scores(records)
        assert len(result["scores"]) == 1
        assert result["scores"][0]["score"] == 0  # no critical rules triggered

    def test_repeated_tool_no_burst(self):
        records = [
            _make_record("r1", "read_file", "2024-06-15T10:00:00Z"),
            _make_record("r2", "read_file", "2024-06-15T10:30:00Z"),
            _make_record("r3", "read_file", "2024-06-15T11:00:00Z"),
        ]
        result = compute_anomaly_scores(records)
        assert result["scores"][0]["score"] == 0
        assert result["scores"][1]["score"] == 0
        assert result["scores"][2]["score"] == 0

    def test_office_hours_no_unusual_hour(self):
        records = [
            _make_record("r1", "read_file", "2024-06-15T09:00:00Z"),
            _make_record("r2", "grep", "2024-06-15T14:00:00Z"),
            _make_record("r3", "write_file", "2024-06-15T18:00:00Z"),
        ]
        result = compute_anomaly_scores(records)
        for s in result["scores"]:
            assert "unusual_hour" not in s["anomaly_types"]


# ---------------------------------------------------------------------------
# Low anomaly (score 1–25)
# ---------------------------------------------------------------------------


class TestComputeAnomalyScoresLow:
    """Tests for low anomaly scenarios (score 1-25)."""

    def test_new_dangerous_tool_only(self):
        records = [
            _make_record("r1", "run_shell", "2024-06-15T10:00:00Z"),
        ]
        result = compute_anomaly_scores(records)
        assert result["scores"][0]["score"] == 45
        assert result["scores"][0]["anomaly_types"] == ["new_dangerous_tool_use"]

    def test_dangerous_tool_first_use(self):
        records = [
            _make_record("r1", "patch_file", "2024-06-15T10:00:00Z"),
        ]
        result = compute_anomaly_scores(records)
        assert result["scores"][0]["score"] == 45
        assert "new_dangerous_tool_use" in result["scores"][0]["anomaly_types"]


# ---------------------------------------------------------------------------
# Medium anomaly (score 26–55)
# ---------------------------------------------------------------------------


class TestComputeAnomalyScoresMedium:
    """Tests for medium anomaly scenarios (score 26-55)."""

    def test_sensitive_path_burst(self):
        base_time = "2024-06-15T10:00:00Z"
        records = [
            _make_record(
                f"r{i}",
                "read_file",
                _offset_time(base_time, i * 20),
                paths=["/home/user/.ssh/id_rsa"],
            )
            for i in range(4)
        ]
        result = compute_anomaly_scores(records)
        assert "sensitive_path_burst" in result["anomaly_counts"]
        assert result["overall_max_score"] > 0

    def test_new_dangerous_tool_first(self):
        records = [
            _make_record("r1", "patch_file", "2024-06-15T10:00:00Z"),
            _make_record("r2", "undo_last_patch", "2024-06-15T10:01:00Z"),
        ]
        result = compute_anomaly_scores(records)
        assert "new_dangerous_tool_use" in result["scores"][0]["anomaly_types"]
        assert result["scores"][0]["score"] == 45

    def test_high_risk_spike_medium(self):
        base_time = "2024-06-15T10:00:00Z"
        records = [
            _make_record(
                f"r{i}",
                "run_shell",
                _offset_time(base_time, i * 30),
                risk_level="high",
            )
            for i in range(4)
        ]
        result = compute_anomaly_scores(records)
        assert result["anomaly_counts"].get("high_risk_spike") == 4


# ---------------------------------------------------------------------------
# Critical anomaly (score > 55)
# ---------------------------------------------------------------------------


class TestComputeAnomalyScoresCritical:
    """Tests for critical anomaly scenarios (score > 55)."""

    def test_sensitive_path_burst(self):
        base_time = "2024-06-15T10:00:00Z"
        records = [
            _make_record(
                f"r{i}",
                "read_file",
                _offset_time(base_time, i * 30),
                paths=[f"~/.ssh/id_rsa_{i}"],
            )
            for i in range(5)
        ]
        result = compute_anomaly_scores(records)
        # r0: sensitive_path_burst (60) only
        assert result["scores"][0]["score"] == 60
        assert "sensitive_path_burst" in result["scores"][0]["anomaly_types"]
        assert result["anomaly_counts"].get("sensitive_path_burst") == 5

    def test_sensitive_path_burst_plus_high_risk(self):
        base_time = "2024-06-15T10:00:00Z"
        records = [
            _make_record(
                f"r{i}",
                "read_file",
                _offset_time(base_time, i * 30),
                risk_level="critical",
                paths=["/etc/passwd"],
            )
            for i in range(4)
        ]
        result = compute_anomaly_scores(records)
        # sensitive_path_burst (60) + high_risk_spike (40) = capped at 100
        assert result["scores"][0]["score"] == 100
        assert "sensitive_path_burst" in result["scores"][0]["anomaly_types"]
        assert "high_risk_spike" in result["scores"][0]["anomaly_types"]
        assert result["overall_max_score"] == 100

    def test_score_capped_at_100(self):
        records = [
            _make_record(
                "r1",
                "read_file",
                "2024-06-15T03:00:00Z",
                risk_level="critical",
                paths=["/etc/passwd", "/etc/shadow", "~/.ssh/id_rsa"],
            ),
            _make_record(
                "r2",
                "read_file",
                "2024-06-15T03:01:00Z",
                risk_level="critical",
                paths=["/etc/passwd", "~/.ssh/authorized_keys"],
            ),
            _make_record(
                "r3",
                "read_file",
                "2024-06-15T03:02:00Z",
                risk_level="high",
                paths=[".env", "credentials"],
            ),
            _make_record(
                "r4",
                "read_file",
                "2024-06-15T03:03:00Z",
                risk_level="high",
                paths=["/etc/passwd"],
            ),
        ]
        result = compute_anomaly_scores(records)
        for s in result["scores"]:
            assert s["score"] <= 100

    def test_exfiltration_pattern_from_secret_content(self):
        base_time = "2024-06-15T10:00:00Z"
        records = [
            {
                **_make_record("r0", "write_file", base_time),
                "params": {"file": "notes.txt", "content": "api_key=sk-test"},
            },
            {
                **_make_record("r1", "patch_file", _offset_time(base_time, 30)),
                "params": {"file": "config.py", "replace": "password = 'secret'"},
            },
            {
                **_make_record("r2", "read_file", _offset_time(base_time, 60)),
                "result": {"details": {"stdout": "BEGIN OPENSSH PRIVATE KEY"}},
            },
        ]

        result = compute_anomaly_scores(records)

        assert result["anomaly_counts"].get("exfiltration_pattern") == 3
        assert "exfiltration_pattern" in result["scores"][0]["anomaly_types"]
        assert result["scores"][0]["recommended_action"] in {"ask", "deny"}

    def test_privilege_escalation_attempt_from_role_change(self):
        record = {
            **_make_record("r0", "set_config_value", "2024-06-15T10:00:00Z"),
            "params": {"key": "role", "value": "senior"},
        }

        result = compute_anomaly_scores([record])

        assert result["anomaly_counts"].get("privilege_escalation_attempt") == 1
        assert result["scores"][0]["score"] == 65
        assert result["scores"][0]["recommended_action"] == "ask"

    def test_command_pattern_anomaly_with_baseline(self):
        records = [
            _make_record("r0", "run_shell", "2024-06-15T10:00:00Z"),
        ]
        records[0]["params"] = {"command": "curl https://example.com"}
        baseline = {"command_prefixes": ["git status", "python3 -m pytest"]}

        result = compute_anomaly_scores(records, baseline=baseline)

        assert "command_pattern_anomaly" not in result["scores"][0]["anomaly_types"]

    def test_path_anomaly_with_baseline(self):
        records = [
            _make_record(
                "r0",
                "read_file",
                "2024-06-15T10:00:00Z",
                paths=["secrets/token.txt"],
            ),
        ]
        baseline = {"path_roots": ["src", "docs"]}

        result = compute_anomaly_scores(records, baseline=baseline)

        assert "path_anomaly" not in result["scores"][0]["anomaly_types"]

    def test_volume_anomaly_with_baseline(self):
        records = [_make_record(f"r{i}", "read_file", "2024-06-15T10:00:00Z") for i in range(20)]
        baseline = {"avg_records_per_session": 2}

        result = compute_anomaly_scores(records, baseline=baseline)

        assert "volume_anomaly" not in result["scores"][0]["anomaly_types"]


# ---------------------------------------------------------------------------
# Anomaly counts
# ---------------------------------------------------------------------------


class TestComputeAnomalyScoresAnomalyCounts:
    """Tests for anomaly_counts correctness."""

    def test_counts_aggregate_correctly(self):
        base_time = "2024-06-15T10:00:00Z"
        records = [
            _make_record("r1", "run_shell", _offset_time(base_time, 0)),
            _make_record("r2", "read_file", _offset_time(base_time, 30)),
            _make_record("r3", "write_file", _offset_time(base_time, 60)),
        ]
        result = compute_anomaly_scores(records)
        assert result["anomaly_counts"].get("new_dangerous_tool_use") == 1

    def test_counts_zero_for_no_anomalies(self):
        records = [
            _make_record("r1", "read_file", "2024-06-15T10:00:00Z"),
            _make_record("r2", "read_file", "2024-06-15T12:00:00Z"),
        ]
        result = compute_anomaly_scores(records)
        assert result["anomaly_counts"].get("sensitive_path_burst", 0) == 0


# ---------------------------------------------------------------------------
# classify_anomaly_level
# ---------------------------------------------------------------------------


class TestClassifyAnomalyLevel:
    """Tests for score → level classification."""

    def test_normal_zero(self):
        assert classify_anomaly_level(0) == "normal"

    def test_normal_negative(self):
        assert classify_anomaly_level(-1) == "normal"

    def test_low_boundary(self):
        assert classify_anomaly_level(1) == "low"
        assert classify_anomaly_level(25) == "low"

    def test_medium_boundary(self):
        assert classify_anomaly_level(26) == "medium"
        assert classify_anomaly_level(55) == "medium"

    def test_critical(self):
        assert classify_anomaly_level(56) == "critical"
        assert classify_anomaly_level(100) == "critical"


class TestGetAnomalyAction:
    def test_log_action(self):
        assert get_anomaly_action(0) == "log"
        assert get_anomaly_action(30) == "log"

    def test_status_action(self):
        assert get_anomaly_action(31) == "status"
        assert get_anomaly_action(55) == "status"

    def test_ask_action(self):
        assert get_anomaly_action(56) == "ask"
        assert get_anomaly_action(80) == "ask"

    def test_deny_action(self):
        assert get_anomaly_action(81) == "deny"
        assert get_anomaly_action(100) == "deny"


# ---------------------------------------------------------------------------
# Realistic integration scenarios
# ---------------------------------------------------------------------------


class TestAnomalyScoreRealisticScenarios:
    """Integration-style tests with realistic record sets."""

    def test_normal_workflow(self):
        """A typical dev session: read, grep, write over hours."""
        records = [
            _make_record("r1", "read_file", "2024-06-15T09:00:00Z"),
            _make_record("r2", "grep", "2024-06-15T09:05:00Z"),
            _make_record("r3", "read_file", "2024-06-15T09:20:00Z"),
            _make_record("r4", "write_file", "2024-06-15T09:45:00Z"),
            _make_record("r5", "read_file", "2024-06-15T10:00:00Z"),
        ]
        result = compute_anomaly_scores(records)
        assert result["anomaly_counts"].get("sensitive_path_burst", 0) == 0

    def test_low_anomaly_with_dangerous_tool(self):
        """First use of dangerous tool triggers medium anomaly (score 45)."""
        records = [
            _make_record("r1", "run_shell", "2024-06-15T02:00:00Z"),
        ]
        result = compute_anomaly_scores(records)
        for s in result["scores"]:
            assert s["score"] == 45
            assert "new_dangerous_tool_use" in s["anomaly_types"]
        assert classify_anomaly_level(result["overall_max_score"]) == "medium"

    def test_medium_anomaly_file_burst(self):
        """Rapid fire file reads – sensitive path burst triggers medium."""
        base_time = "2024-06-15T14:00:00Z"
        records = [
            _make_record(
                f"r{i}",
                "read_file",
                _offset_time(base_time, i * 20),
                paths=["/etc/passwd"],
            )
            for i in range(4)
        ]
        result = compute_anomaly_scores(records)
        assert result["anomaly_counts"].get("sensitive_path_burst") == 4
        assert result["overall_max_score"] >= 30

    def test_critical_anomaly_sensitive_burst_at_night(self):
        """Sensitive path access burst at 3am – critical."""
        base_time = "2024-06-15T03:00:00Z"
        records = [
            _make_record(
                f"r{i}",
                "read_file",
                _offset_time(base_time, i * 20),
                paths=["~/.ssh/id_rsa", "/etc/passwd"],
                risk_level="critical" if i % 2 == 0 else "high",
            )
            for i in range(5)
        ]
        result = compute_anomaly_scores(records)
        assert result["overall_max_score"] >= 60
        assert classify_anomaly_level(result["overall_max_score"]) == "critical"
