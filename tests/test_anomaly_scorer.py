"""Tests for rule-based anomaly scorer."""


from claude_bridge.anomaly import (
    AnomalyResult,
    classify_anomaly_level,
    compute_anomaly_scores,
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
        assert result["scores"][0]["score"] == 20  # new_tool_use only

    def test_repeated_tool_no_burst(self):
        records = [
            _make_record("r1", "read_file", "2024-06-15T10:00:00Z"),
            _make_record("r2", "read_file", "2024-06-15T10:30:00Z"),
            _make_record("r3", "read_file", "2024-06-15T11:00:00Z"),
        ]
        result = compute_anomaly_scores(records)
        assert result["scores"][0]["score"] == 20  # new_tool_use only
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

    def test_new_tool_use_only(self):
        records = [
            _make_record("r1", "read_file", "2024-06-15T10:00:00Z"),
            _make_record("r2", "grep", "2024-06-15T10:01:00Z"),
        ]
        result = compute_anomaly_scores(records)
        assert result["scores"][0]["score"] == 20
        assert result["scores"][0]["anomaly_types"] == ["new_tool_use"]
        assert result["scores"][1]["score"] == 20
        assert result["scores"][1]["anomaly_types"] == ["new_tool_use"]
        assert result["anomaly_counts"].get("new_tool_use") == 2

    def test_unusual_hour_only(self):
        records = [
            _make_record("r1", "read_file", "2024-06-15T03:00:00Z"),
            _make_record("r2", "read_file", "2024-06-15T03:30:00Z"),
        ]
        result = compute_anomaly_scores(records)
        # r1: new_tool_use (20) + unusual_hour (15) = 35 (medium)
        # r2: unusual_hour (15) only since read_file already seen
        assert result["scores"][1]["score"] == 15
        assert "unusual_hour" in result["scores"][1]["anomaly_types"]


# ---------------------------------------------------------------------------
# Medium anomaly (score 26–55)
# ---------------------------------------------------------------------------


class TestComputeAnomalyScoresMedium:
    """Tests for medium anomaly scenarios (score 26-55)."""

    def test_high_volume_file_access(self):
        base_time = "2024-06-15T10:00:00Z"
        records = [
            _make_record(f"r{i}", "read_file", _offset_time(base_time, i * 20)) for i in range(12)
        ]
        result = compute_anomaly_scores(records)
        # First record: new_tool_use (20) + high_volume (30) = 50
        assert result["scores"][0]["score"] == 50
        assert "high_volume_file_access" in result["scores"][0]["anomaly_types"]
        assert result["scores"][6]["score"] == 30
        assert result["anomaly_counts"].get("high_volume_file_access") == 12

    def test_unusual_hour_plus_new_tool(self):
        records = [
            _make_record("r1", "read_file", "2024-06-15T04:00:00Z"),
            _make_record("r2", "grep", "2024-06-15T04:30:00Z"),
        ]
        result = compute_anomaly_scores(records)
        # r1: new_tool_use (20) + unusual_hour (15) = 35
        assert result["scores"][0]["score"] == 35
        assert "new_tool_use" in result["scores"][0]["anomaly_types"]
        assert "unusual_hour" in result["scores"][0]["anomaly_types"]

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
        # r0: new_tool_use (20) + sensitive_path_burst (60) = 80
        assert result["scores"][0]["score"] == 80
        assert "sensitive_path_burst" in result["scores"][0]["anomaly_types"]
        assert result["anomaly_counts"].get("sensitive_path_burst") == 5

    def test_sensitive_path_burst_plus_high_risk(self):
        base_time = "2024-06-15T03:00:00Z"
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
        # r0 capped at 100
        assert result["scores"][0]["score"] == 100
        assert "sensitive_path_burst" in result["scores"][0]["anomaly_types"]
        assert "unusual_hour" in result["scores"][0]["anomaly_types"]
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


# ---------------------------------------------------------------------------
# Anomaly counts
# ---------------------------------------------------------------------------


class TestComputeAnomalyScoresAnomalyCounts:
    """Tests for anomaly_counts correctness."""

    def test_counts_aggregate_correctly(self):
        base_time = "2024-06-15T10:00:00Z"
        records = [
            _make_record("r1", "read_file", _offset_time(base_time, 0)),
            _make_record("r2", "grep", _offset_time(base_time, 30)),
            _make_record("r3", "write_file", _offset_time(base_time, 60)),
        ]
        result = compute_anomaly_scores(records)
        assert result["anomaly_counts"].get("new_tool_use") == 3

    def test_counts_zero_for_no_anomalies(self):
        records = [
            _make_record("r1", "read_file", "2024-06-15T10:00:00Z"),
            _make_record("r2", "read_file", "2024-06-15T12:00:00Z"),
        ]
        result = compute_anomaly_scores(records)
        assert result["anomaly_counts"].get("high_volume_file_access", 0) == 0
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
        assert result["anomaly_counts"].get("new_tool_use") == 3
        assert result["anomaly_counts"].get("high_volume_file_access", 0) == 0

    def test_low_anomaly_unusual_hour(self):
        """Working late: unusual hour but normal activity."""
        records = [
            _make_record("r1", "read_file", "2024-06-15T02:00:00Z"),
            _make_record("r2", "grep", "2024-06-15T02:15:00Z"),
            _make_record("r3", "write_file", "2024-06-15T02:30:00Z"),
        ]
        result = compute_anomaly_scores(records)
        for s in result["scores"]:
            assert s["score"] == 35  # new_tool_use + unusual_hour
            assert "unusual_hour" in s["anomaly_types"]
        assert classify_anomaly_level(result["overall_max_score"]) == "medium"

    def test_medium_anomaly_file_burst(self):
        """Rapid fire file reads – volume triggers medium."""
        base_time = "2024-06-15T14:00:00Z"
        records = [
            _make_record(f"r{i}", "read_file", _offset_time(base_time, i * 15)) for i in range(15)
        ]
        result = compute_anomaly_scores(records)
        assert result["anomaly_counts"].get("high_volume_file_access", 0) >= 10
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
            )
            for i in range(5)
        ]
        result = compute_anomaly_scores(records)
        assert result["overall_max_score"] >= 75
        assert classify_anomaly_level(result["overall_max_score"]) == "critical"
