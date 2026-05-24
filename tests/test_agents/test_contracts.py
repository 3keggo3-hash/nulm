"""Tests for agent contracts (TaskSpec, TaskBudget, TaskPermissions, coerce_task_spec)."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


import pytest

from claude_bridge.agents.contracts import (
    TaskBudget,
    TaskPermissions,
    TaskSpec,
    coerce_task_spec,
)


class TestTaskSpecValidation:
    def test_task_spec_from_minimal_dict(self):
        spec = TaskSpec.from_legacy_dict(
            {"id": "t1", "task": "do stuff", "agent_name": "git_agent"}
        )
        assert spec.task_id == "t1"
        assert spec.goal == "do stuff"
        assert spec.agent_name == "git_agent"
        assert spec.kind == "git"

    def test_task_spec_from_full_dict(self):
        spec = TaskSpec.from_legacy_dict(
            {
                "task_id": "full_task",
                "task": "full goal",
                "agent_name": "research_agent",
                "kind": "research",
                "question": "What should be checked?",
                "read_set": ["src", "tests"],
                "write_set": ["docs"],
                "budget": {"max_tool_calls": 10, "timeout_seconds": 120},
                "permissions": {"allowed_tools": ["search"], "allow_mutation": False},
                "acceptance_criteria": ["answer the question"],
                "escalation_policy": "ask_user",
                "allowed_failure_classes": ["context_insufficiency"],
                "expected_evidence": ["file citation"],
                "expected_artifacts": ["findings"],
                "priority": 1,
            }
        )
        assert spec.task_id == "full_task"
        assert spec.kind == "research"
        assert spec.goal == "full goal"
        assert spec.read_set == ("src", "tests")
        assert spec.write_set == ("docs",)
        assert spec.budget.max_tool_calls == 10
        assert spec.permissions.allowed_tools == frozenset({"search"})
        assert spec.question == "What should be checked?"
        assert spec.acceptance_criteria == ("answer the question",)
        assert spec.escalation_policy == "ask_user"
        assert spec.allowed_failure_classes == ("context_insufficiency",)
        assert spec.expected_evidence == ("file citation",)
        assert spec.priority == 1

    def test_task_spec_coerce_passthrough(self):
        spec = TaskSpec(task_id="x", kind="y", goal="z", agent_name="a")
        result = coerce_task_spec(spec)
        assert result is spec

    def test_task_spec_empty_task_id_raises(self):
        with pytest.raises(ValueError, match="task_id is required"):
            TaskSpec(task_id="", kind="general", goal="x", agent_name="a")

    def test_task_spec_empty_goal_raises(self):
        with pytest.raises(ValueError, match="goal is required"):
            TaskSpec(task_id="x", kind="general", goal="", agent_name="a")

    def test_task_spec_empty_agent_name_raises(self):
        with pytest.raises(ValueError, match="agent_name is required"):
            TaskSpec(task_id="x", kind="general", goal="y", agent_name="")

    def test_task_spec_priority_out_of_range_raises(self):
        with pytest.raises(ValueError, match="priority must be"):
            TaskSpec(task_id="x", kind="general", goal="y", agent_name="a", priority=0)
        with pytest.raises(ValueError, match="priority must be"):
            TaskSpec(task_id="x", kind="general", goal="y", agent_name="a", priority=4)

    def test_task_spec_valid_priority_bounds(self):
        for p in [1, 2, 3]:
            spec = TaskSpec(task_id="x", kind="general", goal="y", agent_name="a", priority=p)
            assert spec.priority == p


class TestTaskBudgetValidation:
    def test_task_budget_from_raw_nulls(self):
        budget = TaskBudget.from_raw(None)
        assert budget.max_tool_calls is None
        assert budget.timeout_seconds is None

    def test_task_budget_from_raw_partial(self):
        budget = TaskBudget.from_raw({"max_tool_calls": 5})
        assert budget.max_tool_calls == 5
        assert budget.timeout_seconds is None

    def test_task_budget_negative_max_tool_calls_raises(self):
        with pytest.raises(ValueError, match="max_tool_calls must be positive"):
            TaskBudget(max_tool_calls=-1)

    def test_task_budget_zero_timeout_raises(self):
        with pytest.raises(ValueError, match="timeout_seconds must be positive"):
            TaskBudget(timeout_seconds=0)

    def test_task_budget_invalid_int_coersion_fallback(self):
        budget = TaskBudget.from_raw({"max_tool_calls": "many", "timeout_seconds": "lots"})
        assert budget.max_tool_calls is None
        assert budget.timeout_seconds is None


class TestTaskPermissionsValidation:
    def test_task_permissions_mutation_without_tools_raises(self):
        with pytest.raises(ValueError, match="allowed_tools required when allow_mutation"):
            TaskPermissions(allow_mutation=True)

    def test_task_permissions_mutation_with_tools_ok(self):
        perms = TaskPermissions(allow_mutation=True, allowed_tools=frozenset({"shell"}))
        assert perms.allow_mutation is True
        assert perms.allowed_tools == frozenset({"shell"})

    def test_task_permissions_from_raw_parses_string_bools_safely(self):
        perms = TaskPermissions.from_raw(
            {
                "allowed_tools": ["shell"],
                "allow_mutation": "false",
                "allow_network": "yes",
            }
        )

        assert perms.allow_mutation is False
        assert perms.allow_network is True


class TestCoerceTaskSpecEdgeCases:
    def test_coerce_task_spec_with_dict_and_spec_mixed(self):
        spec = TaskSpec(
            task_id="typed", kind="research", goal="typed goal", agent_name="research_agent"
        )
        dict_spec = {"id": "dict", "task": "dict task", "agent_name": "git_agent"}
        result1 = coerce_task_spec(spec)
        result2 = coerce_task_spec(dict_spec)
        assert result1 is spec
        assert result2.task_id == "dict"

    def test_from_legacy_dict_kind_inference(self):
        spec = TaskSpec.from_legacy_dict({"id": "t", "task": "x", "agent_name": "debug_agent"})
        assert spec.kind == "debug"

    def test_legacy_adapter_id_fallback(self):
        spec1 = TaskSpec.from_legacy_dict({"id": "t1", "task": "x", "agent_name": "a"})
        spec2 = TaskSpec.from_legacy_dict({"task_id": "t1", "task": "x", "agent_name": "a"})
        assert spec1.task_id == spec2.task_id == "t1"

    def test_coerce_task_spec_none_input_returns_invalid(self):
        result = coerce_task_spec(None)
        assert result.task_id == "_invalid"
        assert result.agent_name == "_invalid"

    def test_coerce_task_spec_non_dict_returns_invalid(self):
        result = coerce_task_spec("not a dict")
        assert result.task_id == "_invalid"

    def test_coerce_task_spec_empty_dict_returns_invalid(self):
        result = coerce_task_spec({})
        assert result.task_id == "_invalid"

    def test_coerce_task_spec_string_priority_invalid_falls_back(self):
        result = coerce_task_spec({"id": "t", "task": "x", "agent_name": "a", "priority": "high"})
        assert result.priority == 2

    def test_coerce_task_spec_none_value_in_dict(self):
        result = coerce_task_spec({"id": "t", "task": None, "agent_name": "a"})
        assert result.task_id == "_invalid"

    def test_to_legacy_context_roundtrip(self):
        spec = TaskSpec(
            task_id="round_trip",
            kind="research",
            goal="test goal",
            agent_name="research_agent",
            question="What is the test goal?",
            acceptance_criteria=("criteria",),
            escalation_policy="ask_user",
            allowed_failure_classes=("validation_failure",),
            expected_evidence=("test output",),
            priority=1,
        )
        ctx = spec.to_legacy_context()
        assert ctx["id"] == "round_trip"
        assert ctx["task"] == "test goal"
        assert ctx["agent_name"] == "research_agent"
        assert ctx["kind"] == "research"
        assert ctx["question"] == "What is the test goal?"
        assert ctx["acceptance_criteria"] == ["criteria"]
        assert ctx["escalation_policy"] == "ask_user"
        assert ctx["allowed_failure_classes"] == ["validation_failure"]
        assert ctx["expected_evidence"] == ["test output"]
        assert ctx["priority"] == 1

    def test_behavioral_fields_round_trip_from_legacy_context(self):
        source = TaskSpec(
            task_id="behavior",
            kind="review",
            goal="review behavior",
            agent_name="review_agent",
            question="What changed?",
            acceptance_criteria=("explain risks",),
            escalation_policy="block on schema failure",
            allowed_failure_classes=("schema_failure",),
            expected_evidence=("diff citation",),
        )

        loaded = TaskSpec.from_legacy_dict(source.to_legacy_context())

        assert loaded.question == source.question
        assert loaded.acceptance_criteria == source.acceptance_criteria
        assert loaded.escalation_policy == source.escalation_policy
        assert loaded.allowed_failure_classes == source.allowed_failure_classes
        assert loaded.expected_evidence == source.expected_evidence

    def test_invalid_behavioral_fields_coerce_safely(self):
        spec = TaskSpec.from_legacy_dict(
            {
                "id": "safe",
                "task": "safe coercion",
                "agent_name": "research_agent",
                "question": {"bad": "shape"},
                "acceptance_criteria": "not a list",
                "escalation_policy": ["not", "a", "string"],
                "allowed_failure_classes": {"schema_failure": True},
                "expected_evidence": 42,
            }
        )

        assert spec.question == ""
        assert spec.acceptance_criteria == ()
        assert spec.escalation_policy == ""
        assert spec.allowed_failure_classes == ()
        assert spec.expected_evidence == ()
