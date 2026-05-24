"""Tests for AgentRunRecord dataclass and run record lifecycle."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


import time

import pytest

from claude_bridge.agents.result import AgentResult
from claude_bridge.agents.run_record import (
    compact_run_summary,
    finish_agent_run,
    start_agent_run,
)


def test_start_agent_run_creates_record():
    record = start_agent_run(task_id="test_task", agent_name="test_agent", task_kind="test")
    assert record.run_id is not None
    assert record.task_id == "test_task"
    assert record.agent_name == "test_agent"
    assert record.task_kind == "test"
    assert record.started_at is not None
    assert record.status == "running"
    assert record.ended_at is None
    assert record.duration_ms is None


def test_finish_agent_run_success():
    record = start_agent_run(task_id="t", agent_name="a", task_kind="k")
    result = AgentResult.success(findings=["found it"], agent_name="a")
    finish_agent_run(record, result)
    assert record.status == "success"
    assert record.ended_at is not None
    assert record.duration_ms is not None
    assert record.duration_ms >= 0


def test_finish_agent_run_failure():
    record = start_agent_run(task_id="t", agent_name="a", task_kind="k")
    result = AgentResult.failure(error="something went wrong", agent_name="a")
    finish_agent_run(record, result)
    assert record.status == "failure"
    assert record.error_class == "AgentFailure"
    assert record.error_message == "something went wrong"


def test_finish_agent_run_with_exception_class():
    record = start_agent_run(task_id="t", agent_name="a", task_kind="k")
    result = AgentResult.success(agent_name="a")
    finish_agent_run(record, result, error_class="RuntimeError", error_message="boom")
    assert record.error_class == "RuntimeError"
    assert record.error_message == "boom"


def test_agent_run_record_to_dict():
    record = start_agent_run(task_id="t", agent_name="a", task_kind="k")
    record.finish(ended_at=time.time(), status="success")
    d = record.to_dict()
    assert d["run_id"] == record.run_id
    assert d["task_id"] == "t"
    assert d["agent_name"] == "a"
    assert d["task_kind"] == "k"
    assert d["status"] == "success"
    assert "tool_calls" in d


def test_compact_run_summary_empty():
    summary = compact_run_summary([])
    assert summary["run_count"] == 0
    assert summary["status_counts"] == {}
    assert summary["total_duration_ms"] == 0.0
    assert summary["failures"] == []


def test_compact_run_summary_multiple_records():
    record1 = start_agent_run(task_id="t1", agent_name="a", task_kind="k")
    record1.finish(ended_at=time.time(), status="success")
    record2 = start_agent_run(task_id="t2", agent_name="b", task_kind="k")
    record2.finish(ended_at=time.time(), status="failure", error_class="Boom", error_message="boom")
    summary = compact_run_summary([record1, record2])
    assert summary["run_count"] == 2
    assert summary["status_counts"]["success"] == 1
    assert summary["status_counts"]["failure"] == 1
    assert len(summary["failures"]) == 1
    assert summary["failures"][0]["task_id"] == "t2"


def test_record_tool_calls_accumulated():
    record = start_agent_run(task_id="t", agent_name="a", task_kind="k")
    record.tool_calls.append(
        {"tool": "git_status", "params": {}, "status": "success", "timestamp": time.time()}
    )
    record.tool_calls.append(
        {"tool": "git_log", "params": {"limit": 5}, "status": "success", "timestamp": time.time()}
    )
    assert len(record.tool_calls) == 2
    assert record.tool_calls[0]["tool"] == "git_status"
    assert record.tool_calls[1]["params"]["limit"] == 5


def test_record_error_class_and_message():
    record = start_agent_run(task_id="t", agent_name="a", task_kind="k")
    record.error_class = "PermissionDenied"
    record.error_message = "Permission denied: git tool not allowed"
    assert record.error_class == "PermissionDenied"
    assert "Permission denied" in record.error_message


def test_record_duration_ms_derived():
    record = start_agent_run(task_id="t", agent_name="a", task_kind="k")
    started = record.started_at
    ended = started + 1.5
    record.finish(ended_at=ended, status="success")
    assert record.duration_ms == pytest.approx(1500.0, rel=1)


def test_record_context_manifest_id():
    record = start_agent_run(task_id="t", agent_name="a", task_kind="k")
    record.context_manifest_id = "manifest_abc123"
    assert record.context_manifest_id == "manifest_abc123"


def test_record_artifact_ids():
    record = start_agent_run(task_id="t", agent_name="a", task_kind="k")
    record.artifact_ids = ["artifact_1", "artifact_2"]
    assert len(record.artifact_ids) == 2
