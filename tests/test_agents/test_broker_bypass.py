"""Tests for AgentToolBroker bypass prevention."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


import pytest

from claude_bridge.agents.broker import AgentToolBroker
from claude_bridge.agents.contracts import TaskPermissions
from claude_bridge.agents.run_record import start_agent_run


def make_record():
    return start_agent_run(task_id="test_task", agent_name="test_agent", task_kind="test")


class TestBrokerUnsupportedToolDenied:
    def test_unsupported_tool_git_not_in_broker_supported(self):
        broker = AgentToolBroker(TaskPermissions())
        record = make_record()
        assert broker.validate(record, "shell") is False
        assert broker.validate(record, "network") is False
        assert broker.validate(record, "unknown_tool") is False

    def test_unsupported_tool_returns_failure(self):
        broker = AgentToolBroker(TaskPermissions())
        record = make_record()
        result = broker.git_status(record)
        assert result.status.value == "failure"
        assert "Permission denied" in result.error


class TestBrokerTaskPermissionsEnforcement:
    def test_allowed_tools_restricts_git(self):
        perms = TaskPermissions(allowed_tools=frozenset({"file_read"}))
        broker = AgentToolBroker(perms)
        record = make_record()
        assert broker.validate(record, "git") is False

    def test_allowed_tools_allows_file_read(self):
        perms = TaskPermissions(allowed_tools=frozenset({"git", "file_read"}))
        broker = AgentToolBroker(perms)
        record = make_record()
        assert broker.validate(record, "git") is True
        assert broker.validate(record, "file_read") is True

    def test_empty_allowed_tools_denies_git(self):
        perms = TaskPermissions(allowed_tools=frozenset())
        broker = AgentToolBroker(perms)
        record = make_record()
        assert broker.validate(record, "git") is False


class TestBrokerToolCallsAttached:
    def test_git_status_tool_call_recorded(self):
        broker = AgentToolBroker(TaskPermissions(allowed_tools=frozenset({"git"})))
        record = make_record()
        broker.git_status(record)
        assert len(record.tool_calls) == 1
        assert record.tool_calls[0]["tool"] == "git_status"
        assert record.tool_calls[0]["status"] == "success"

    def test_git_log_tool_call_recorded(self):
        broker = AgentToolBroker(TaskPermissions(allowed_tools=frozenset({"git"})))
        record = make_record()
        broker.git_log(record, limit=5)
        assert len(record.tool_calls) == 1
        assert record.tool_calls[0]["tool"] == "git_log"
        assert record.tool_calls[0]["params"]["limit"] == 5

    def test_denied_tool_call_recorded_with_denied_status(self):
        broker = AgentToolBroker(TaskPermissions())
        record = make_record()
        broker.git_status(record)
        assert len(record.tool_calls) == 1
        assert record.tool_calls[0]["status"] == "denied"
        assert record.error_class == "PermissionDenied"

    def test_multiple_tool_calls_accumulated(self):
        broker = AgentToolBroker(TaskPermissions(allowed_tools=frozenset({"git"})))
        record = make_record()
        broker.git_status(record)
        broker.git_log(record, limit=3)
        assert len(record.tool_calls) == 2


class TestBrokerBypassVectors:
    def test_broker_rejects_tool_not_in_supported_set(self):
        broker = AgentToolBroker(TaskPermissions(allowed_tools=frozenset({"git"})))
        record = make_record()
        assert broker.validate(record, "sudo") is False
        assert broker.validate(record, "rm") is False
        assert broker.validate(record, "curl") is False

    def test_broker_does_not_expose_subprocess_direct_access(self):
        broker = AgentToolBroker(TaskPermissions(allowed_tools=frozenset({"git"})))
        assert not hasattr(broker, "_run_subprocess")

    def test_broker_allow_mutation_without_allowed_tools_raises_on_init(self):
        with pytest.raises(ValueError, match="allowed_tools required when allow_mutation"):
            TaskPermissions(allow_mutation=True)


class TestBrokerValidationTimestamp:
    def test_tool_call_has_timestamp(self):
        broker = AgentToolBroker(TaskPermissions(allowed_tools=frozenset({"git"})))
        record = make_record()
        broker.git_status(record)
        assert "timestamp" in record.tool_calls[0]
        assert isinstance(record.tool_calls[0]["timestamp"], float)


class TestBrokerFailClosed:
    def test_empty_permissions_fails_closed(self):
        broker = AgentToolBroker(TaskPermissions())
        record = make_record()
        result = broker.git_status(record)
        assert result.status.value == "failure"

    def test_mutation_without_tools_raises_at_init(self):
        with pytest.raises(ValueError):
            TaskPermissions(allow_mutation=True)