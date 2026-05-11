import json

import pytest

from claude_bridge.agent_advisor import (
    AgentAdviceRequest,
    PlanQualityReviewRequest,
    ResultQualityReviewRequest,
    agent_quality_telemetry_summary,
    advise_next_step,
    improve_request,
    parse_optional_json_object,
    parse_provider_agent_advice,
    plan_quality_review,
    reset_agent_quality_telemetry,
    review_result_quality,
    suggest_bridge_config,
)


def test_advise_next_step_public_readiness_goal_includes_release_gate():
    advice = advise_next_step(
        AgentAdviceRequest(
            goal="Make this project public ready",
            target=".",
            current_config={"tool_profile": "full", "context_budget_profile": "balanced"},
        )
    )

    payload = advice.to_dict()
    assert payload["schema_version"] == "agent_advice.v1"
    assert "release-readiness" in payload["recommended_next_step"]
    assert "README.md" in payload["needed_context"]
    assert "pytest" in payload["validation"]
    assert any(item["key"] == "tool_profile" for item in payload["config_suggestions"])


def test_advise_next_step_empty_goal_asks_for_clarification():
    advice = advise_next_step(AgentAdviceRequest(goal=""))

    assert advice.should_ask_user is True
    assert "What outcome" in advice.question
    assert "Ask the user" in advice.recommended_next_step


def test_advise_next_step_token_goal_suggests_compaction():
    advice = advise_next_step(
        AgentAdviceRequest(
            goal="Token usage is too high, optimize cost",
            current_config={"tool_profile": "standard", "context_budget_profile": "balanced"},
        )
    )

    suggestions = [item.to_dict() for item in advice.config_suggestions]
    assert any(
        item["key"] == "intent_compaction_enabled" and item["value"] is True for item in suggestions
    )
    assert any("find_relevant_files" in item for item in advice.token_strategy)


def test_parse_optional_json_object_rejects_array():
    with pytest.raises(ValueError, match="constraints_json must be a JSON object"):
        parse_optional_json_object("[]", field_name="constraints_json")


def test_improve_request_turns_rough_quality_goal_into_scoped_prompt():
    improved = improve_request("Make this code professional", target="src/claude_bridge/server.py")

    payload = improved.to_dict()
    assert payload["schema_version"] == "improved_request.v1"
    assert payload["should_ask_user"] is False
    assert "smallest safe implementation slice" in payload["improved_prompt"]
    assert any("quality" in item for item in payload["acceptance_criteria"])


def test_plan_quality_review_flags_broad_plan_without_validation():
    review = plan_quality_review(
        PlanQualityReviewRequest(
            goal="Improve project quality",
            plan="Read the entire codebase and refactor everything.",
        )
    )

    payload = review.to_dict()
    assert payload["schema_version"] == "plan_quality_review.v1"
    assert payload["verdict"] == "revise"
    assert payload["scope_warnings"]
    assert payload["missing_tests"]


def test_suggest_bridge_config_for_token_goal_returns_safe_suggestions():
    payload = suggest_bridge_config(
        "Token usage is too high, reduce cost",
        current_config={"tool_profile": "full", "context_budget_profile": "balanced"},
    )

    assert payload["schema_version"] == "bridge_config_suggestions.v1"
    assert "ai_evaluator_api_key" in payload["restricted_keys"]
    assert any(item["key"] == "tool_profile" for item in payload["suggestions"])
    assert any(item["key"] == "context_budget_profile" for item in payload["suggestions"])


def test_review_result_quality_flags_missing_validation_and_docs_drift():
    review = review_result_quality(
        ResultQualityReviewRequest(
            goal="Add review_result_quality MCP tool",
            result_summary="Added the tool wrapper and advisor logic.",
            changed_files=[
                "src/claude_bridge/agent_advisor.py",
                "src/claude_bridge/meta_tool_server.py",
            ],
        )
    )

    payload = review.to_dict()
    assert payload["schema_version"] == "result_quality_review.v1"
    assert payload["verdict"] == "needs_followup"
    assert payload["validation_gaps"]
    assert payload["docs_drift_risks"]


def test_review_result_quality_ignores_validation_words_outside_validation_evidence():
    review = review_result_quality(
        ResultQualityReviewRequest(
            goal="Add test runner validation helper",
            result_summary="Added test runner code but did not run checks.",
            changed_files=[
                "src/claude_bridge/agent_advisor.py",
                "docs/roadmap.md",
            ],
        )
    )

    payload = review.to_dict()
    assert payload["verdict"] == "needs_followup"
    assert payload["evidence_level"] == "missing"
    assert "Validation evidence is mentioned." not in payload["strengths"]


def test_review_result_quality_passes_with_validation_and_roadmap_update():
    review = review_result_quality(
        ResultQualityReviewRequest(
            goal="Add review_result_quality MCP tool",
            result_summary="Added deterministic review and ran pytest.",
            changed_files=[
                "src/claude_bridge/agent_advisor.py",
                "src/claude_bridge/meta_tool_server.py",
                "docs/roadmap.md",
            ],
            validation={"commands": ["pytest tests/test_agent_advisor.py"]},
        )
    )

    payload = review.to_dict()
    assert payload["verdict"] == "pass_with_notes"
    assert payload["evidence_level"] == "reported"
    assert any("Validation evidence" in item for item in payload["strengths"])


def test_review_result_quality_combines_self_critique_summary():
    review = review_result_quality(
        ResultQualityReviewRequest(
            goal="Improve code quality",
            result_summary="Refined implementation and ran pytest.",
            changed_files=["src/claude_bridge/agent_advisor.py"],
            validation={"commands": ["pytest tests/test_agent_advisor.py"]},
            self_critique={
                "ok": True,
                "details": {
                    "summary": {
                        "total_issues": 2,
                        "by_severity": {"high": 1, "medium": 1},
                    }
                },
            },
        )
    )

    payload = review.to_dict()
    assert payload["verdict"] == "needs_followup"
    assert any("self_critique" in item for item in payload["self_critique_findings"])


def test_parse_provider_agent_advice_accepts_valid_v1_json():
    reset_agent_quality_telemetry()
    result = parse_provider_agent_advice(
        json.dumps(
            {
                "schema_version": "agent_advice.v1",
                "intent_summary": "Ship a narrow quality pass.",
                "recommended_next_step": "Inspect the smallest relevant files.",
                "why_this_step": "It limits context and scope.",
                "needed_context": ["README.md"],
                "risks": ["Docs may drift."],
                "validation": ["pytest"],
                "token_strategy": ["Use rg before broad reads."],
                "config_suggestions": [
                    {
                        "key": "tool_profile",
                        "value": "standard",
                        "reason": "Use the normal tool surface.",
                    }
                ],
                "unknown_field": "ignored",
            }
        )
    )

    payload = result.to_dict()
    assert payload["metadata"]["ok"] is True
    assert payload["metadata"]["fallback_used"] is False
    assert payload["advice"]["recommended_next_step"] == "Inspect the smallest relevant files."
    assert payload["advice"]["config_suggestions"][0]["key"] == "tool_profile"
    assert agent_quality_telemetry_summary()["sample_count"] == 1


def test_parse_provider_agent_advice_malformed_json_falls_back_and_updates_telemetry():
    reset_agent_quality_telemetry()
    result = parse_provider_agent_advice(
        "{not json",
        fallback_request=AgentAdviceRequest(goal="Make this project public ready", target="."),
    )

    assert result.metadata.ok is False
    assert result.metadata.reason == "invalid_json"
    assert result.metadata.fallback_used is True
    assert "release-readiness" in result.advice.recommended_next_step
    telemetry = agent_quality_telemetry_summary()
    assert telemetry["sample_count"] == 1
    assert telemetry["parse_failures"] == 1
    assert telemetry["fallback_count"] == 1
    assert telemetry["last_duration_ms"] >= 0


def test_parse_provider_agent_advice_wrong_schema_falls_back():
    reset_agent_quality_telemetry()
    result = parse_provider_agent_advice(
        json.dumps(
            {
                "schema_version": "agent_advice.v2",
                "intent_summary": "Unsupported schema.",
                "recommended_next_step": "Do something.",
            }
        ),
        fallback_request=AgentAdviceRequest(goal="Fix a bug"),
    )

    assert result.metadata.ok is False
    assert result.metadata.reason == "wrong_schema"
    assert result.metadata.schema_version == "agent_advice.v2"
    assert result.metadata.fallback_used is True
    assert "Reproduce" in result.advice.recommended_next_step


def test_parse_provider_agent_advice_filters_unsafe_config_suggestion_key():
    reset_agent_quality_telemetry()
    result = parse_provider_agent_advice(
        json.dumps(
            {
                "schema_version": "agent_advice.v1",
                "intent_summary": "Reduce token usage.",
                "recommended_next_step": "Use a narrower context strategy.",
                "config_suggestions": [
                    {
                        "key": "auto_approve",
                        "value": True,
                        "reason": "This should never be accepted from provider output.",
                    },
                    {
                        "key": "intent_compaction_enabled",
                        "value": True,
                        "reason": "Compact repeated intent.",
                    },
                ],
            }
        )
    )

    suggestions = [item.to_dict() for item in result.advice.config_suggestions]
    assert result.metadata.ok is True
    assert result.metadata.reason == "unsafe_config_suggestions_filtered"
    assert result.metadata.unsafe_config_keys == ["auto_approve"]
    assert not any(item["key"] == "auto_approve" for item in suggestions)
    assert any(item["key"] == "intent_compaction_enabled" for item in suggestions)
