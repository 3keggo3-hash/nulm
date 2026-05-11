"""Deterministic Agent Quality Layer advice for rough user goals."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

_SAFE_PROVIDER_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "tool_profile",
        "context_budget_profile",
        "intent_compaction_enabled",
        "ai_evaluator_timeout",
        "onboarding_enabled",
        "shell_timeout",
    }
)
_PROVIDER_TELEMETRY_SAMPLE_COUNT = 0
_PROVIDER_TELEMETRY_PARSE_FAILURES = 0
_PROVIDER_TELEMETRY_FALLBACK_COUNT = 0
_PROVIDER_TELEMETRY_LAST_DURATION_MS = 0.0


@dataclass
class AgentAdviceRequest:
    """Input for read-only agent quality advice."""

    goal: str
    target: str = ""
    recent_context: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    current_config: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConfigSuggestion:
    """Safe configuration suggestion produced by the advisor."""

    key: str
    value: str | bool | int
    reason: str
    risk: str = "low"
    requires_approval: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Serialize the suggestion to a JSON-compatible dictionary."""
        return {
            "key": self.key,
            "value": self.value,
            "reason": self.reason,
            "risk": self.risk,
            "requires_approval": self.requires_approval,
        }


@dataclass
class AgentAdviceResponse:
    """Structured advice for improving the next agent step."""

    schema_version: str = "agent_advice.v1"
    intent_summary: str = ""
    recommended_next_step: str = ""
    why_this_step: str = ""
    needed_context: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    validation: list[str] = field(default_factory=list)
    token_strategy: list[str] = field(default_factory=list)
    config_suggestions: list[ConfigSuggestion] = field(default_factory=list)
    should_ask_user: bool = False
    question: str = ""
    next_prompt: str = ""
    uncertainty_flag: bool = False
    ambiguity_triggers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the advice to a JSON-compatible dictionary."""
        return {
            "schema_version": self.schema_version,
            "intent_summary": self.intent_summary,
            "recommended_next_step": self.recommended_next_step,
            "why_this_step": self.why_this_step,
            "needed_context": list(self.needed_context),
            "risks": list(self.risks),
            "validation": list(self.validation),
            "token_strategy": list(self.token_strategy),
            "config_suggestions": [item.to_dict() for item in self.config_suggestions],
            "should_ask_user": self.should_ask_user,
            "question": self.question,
            "next_prompt": self.next_prompt,
            "uncertainty_flag": self.uncertainty_flag,
            "ambiguity_triggers": list(self.ambiguity_triggers),
        }


@dataclass
class ProviderAdviceParseMeta:
    """Metadata for provider-backed advice parsing."""

    ok: bool
    reason: str
    fallback_used: bool
    schema_version: str = ""
    duration_ms: float = 0.0
    unsafe_config_keys: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize parser metadata to a JSON-compatible dictionary."""
        return {
            "ok": self.ok,
            "reason": self.reason,
            "fallback_used": self.fallback_used,
            "schema_version": self.schema_version,
            "duration_ms": self.duration_ms,
            "unsafe_config_keys": list(self.unsafe_config_keys),
        }


@dataclass
class ProviderAdviceParseResult:
    """Parsed provider advice plus fail-safe metadata."""

    advice: AgentAdviceResponse
    metadata: ProviderAdviceParseMeta

    def to_dict(self) -> dict[str, Any]:
        """Serialize the parse result to a JSON-compatible dictionary."""
        return {
            "advice": self.advice.to_dict(),
            "metadata": self.metadata.to_dict(),
        }


@dataclass
class ImprovedRequestResponse:
    """Structured rewrite of a rough user request into an execution-ready task."""

    schema_version: str = "improved_request.v1"
    clarified_goal: str = ""
    assumptions: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    acceptance_criteria: list[str] = field(default_factory=list)
    suggested_first_slice: str = ""
    improved_prompt: str = ""
    should_ask_user: bool = False
    question: str = ""
    uncertainty_flag: bool = False
    ambiguity_triggers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the improved request to a JSON-compatible dictionary."""
        return {
            "schema_version": self.schema_version,
            "clarified_goal": self.clarified_goal,
            "assumptions": list(self.assumptions),
            "constraints": list(self.constraints),
            "acceptance_criteria": list(self.acceptance_criteria),
            "suggested_first_slice": self.suggested_first_slice,
            "improved_prompt": self.improved_prompt,
            "should_ask_user": self.should_ask_user,
            "question": self.question,
            "uncertainty_flag": self.uncertainty_flag,
            "ambiguity_triggers": list(self.ambiguity_triggers),
        }


@dataclass
class PlanQualityReviewRequest:
    """Input for read-only critique of a proposed implementation plan."""

    plan: str
    goal: str = ""
    target: str = ""
    recent_context: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)


@dataclass
class PlanQualityReviewResponse:
    """Structured quality critique for an implementation plan."""

    schema_version: str = "plan_quality_review.v1"
    verdict: str = "revise"
    summary: str = ""
    strengths: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)
    missing_context: list[str] = field(default_factory=list)
    missing_tests: list[str] = field(default_factory=list)
    scope_warnings: list[str] = field(default_factory=list)
    security_warnings: list[str] = field(default_factory=list)
    token_warnings: list[str] = field(default_factory=list)
    recommended_changes: list[str] = field(default_factory=list)
    safer_plan: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the review to a JSON-compatible dictionary."""
        return {
            "schema_version": self.schema_version,
            "verdict": self.verdict,
            "summary": self.summary,
            "strengths": list(self.strengths),
            "concerns": list(self.concerns),
            "missing_context": list(self.missing_context),
            "missing_tests": list(self.missing_tests),
            "scope_warnings": list(self.scope_warnings),
            "security_warnings": list(self.security_warnings),
            "token_warnings": list(self.token_warnings),
            "recommended_changes": list(self.recommended_changes),
            "safer_plan": list(self.safer_plan),
        }


@dataclass
class ResultQualityReviewRequest:
    """Input for read-only review of completed work quality."""

    goal: str
    result_summary: str
    changed_files: list[str] = field(default_factory=list)
    validation: dict[str, Any] = field(default_factory=dict)
    recent_context: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    self_critique: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResultQualityReviewResponse:
    """Structured review of completed work against a quality bar."""

    schema_version: str = "result_quality_review.v1"
    verdict: str = "needs_followup"
    evidence_level: str = "missing"
    summary: str = ""
    goal_alignment: list[str] = field(default_factory=list)
    scope_drift: list[str] = field(default_factory=list)
    validation_gaps: list[str] = field(default_factory=list)
    docs_drift_risks: list[str] = field(default_factory=list)
    security_config_risks: list[str] = field(default_factory=list)
    token_context_waste: list[str] = field(default_factory=list)
    self_critique_findings: list[str] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    next_small_fixes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the result review to a JSON-compatible dictionary."""
        return {
            "schema_version": self.schema_version,
            "verdict": self.verdict,
            "evidence_level": self.evidence_level,
            "summary": self.summary,
            "goal_alignment": list(self.goal_alignment),
            "scope_drift": list(self.scope_drift),
            "validation_gaps": list(self.validation_gaps),
            "docs_drift_risks": list(self.docs_drift_risks),
            "security_config_risks": list(self.security_config_risks),
            "token_context_waste": list(self.token_context_waste),
            "self_critique_findings": list(self.self_critique_findings),
            "strengths": list(self.strengths),
            "next_small_fixes": list(self.next_small_fixes),
        }


def parse_optional_json_object(raw: str | None, *, field_name: str) -> dict[str, Any]:
    """Parse an optional JSON object and raise a clear ValueError on invalid input."""
    if raw is None or not raw.strip():
        return {}
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} must be a JSON object") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    return parsed


def parse_provider_agent_advice(
    raw: str,
    *,
    fallback_request: AgentAdviceRequest | None = None,
) -> ProviderAdviceParseResult:
    """Parse provider-backed Agent Quality advice with deterministic fail-safe fallback."""
    started_at = time.perf_counter()
    request = fallback_request or AgentAdviceRequest(goal="Review provider advice")
    schema_version = ""
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError:
        return _provider_parse_fallback(
            request,
            started_at=started_at,
            reason="invalid_json",
            schema_version=schema_version,
        )

    if not isinstance(parsed, dict):
        return _provider_parse_fallback(
            request,
            started_at=started_at,
            reason="invalid_payload",
            schema_version=schema_version,
        )

    schema_version = str(parsed.get("schema_version", ""))
    if schema_version != "agent_advice.v1":
        return _provider_parse_fallback(
            request,
            started_at=started_at,
            reason="wrong_schema",
            schema_version=schema_version,
        )

    try:
        advice, unsafe_keys = _provider_advice_from_dict(parsed)
    except (TypeError, ValueError):
        return _provider_parse_fallback(
            request,
            started_at=started_at,
            reason="invalid_schema",
            schema_version=schema_version,
        )

    reason = "unsafe_config_suggestions_filtered" if unsafe_keys else "ok"
    duration_ms = _duration_ms(started_at)
    _record_provider_parse(ok=True, fallback_used=False, duration_ms=duration_ms)
    return ProviderAdviceParseResult(
        advice=advice,
        metadata=ProviderAdviceParseMeta(
            ok=True,
            reason=reason,
            fallback_used=False,
            schema_version=schema_version,
            duration_ms=duration_ms,
            unsafe_config_keys=unsafe_keys,
        ),
    )


def agent_quality_telemetry_summary() -> dict[str, Any]:
    """Return in-memory Agent Quality parser telemetry."""
    return {
        "sample_count": _PROVIDER_TELEMETRY_SAMPLE_COUNT,
        "parse_failures": _PROVIDER_TELEMETRY_PARSE_FAILURES,
        "fallback_count": _PROVIDER_TELEMETRY_FALLBACK_COUNT,
        "last_duration_ms": _PROVIDER_TELEMETRY_LAST_DURATION_MS,
    }


def reset_agent_quality_telemetry() -> None:
    """Reset parser telemetry for focused tests."""
    global _PROVIDER_TELEMETRY_FALLBACK_COUNT
    global _PROVIDER_TELEMETRY_LAST_DURATION_MS
    global _PROVIDER_TELEMETRY_PARSE_FAILURES
    global _PROVIDER_TELEMETRY_SAMPLE_COUNT

    _PROVIDER_TELEMETRY_SAMPLE_COUNT = 0
    _PROVIDER_TELEMETRY_PARSE_FAILURES = 0
    _PROVIDER_TELEMETRY_FALLBACK_COUNT = 0
    _PROVIDER_TELEMETRY_LAST_DURATION_MS = 0.0


def advise_next_step(request: AgentAdviceRequest) -> AgentAdviceResponse:
    """Return deterministic next-step advice for a rough user goal."""
    goal = _compact_text(request.goal)
    target = _compact_text(request.target)
    lowered = f"{goal} {target}".lower()

    if not goal:
        return AgentAdviceResponse(
            intent_summary="No clear user goal was provided.",
            recommended_next_step="Ask the user for the desired outcome before reading files.",
            why_this_step="A missing goal would make context selection and validation arbitrary.",
            should_ask_user=True,
            question="What outcome should Claude Bridge help you achieve?",
            next_prompt=(
                "State the product or code outcome you want, plus any important constraints."
            ),
        )

    advice = AgentAdviceResponse(
        intent_summary=_intent_summary(goal, target),
        recommended_next_step="Create a scoped first slice before editing files.",
        why_this_step=(
            "A small first slice keeps the work reviewable and avoids broad context reads."
        ),
        needed_context=_base_context(target),
        risks=[
            "The request may be broader than one safe implementation slice.",
            "Validation can be missed if acceptance criteria are not stated up front.",
        ],
        validation=["Run the smallest focused tests for touched behavior."],
        token_strategy=[
            "Use rg or relevance search before opening many files.",
            "Read narrow file ranges instead of whole large modules.",
        ],
        next_prompt=_next_prompt(goal, target),
    )

    _apply_goal_patterns(advice, lowered)
    _apply_context_inputs(advice, request.recent_context, request.constraints)
    _apply_config_suggestions(advice, lowered, request.current_config)
    _apply_ambiguity_triggers(advice, goal, target, request.recent_context, request.constraints)
    _dedupe_response(advice)
    return advice


def improve_request(
    goal: str,
    *,
    target: str = "",
    constraints: dict[str, Any] | None = None,
) -> ImprovedRequestResponse:
    """Convert a rough user request into a scoped task prompt."""
    compact_goal = _compact_text(goal)
    compact_target = _compact_text(target)
    lowered = f"{compact_goal} {compact_target}".lower()
    constraint_values = _constraint_texts(constraints or {})

    if not compact_goal:
        return ImprovedRequestResponse(
            clarified_goal="No clear user goal was provided.",
            should_ask_user=True,
            question="What outcome should Claude Bridge help you achieve?",
            improved_prompt=(
                "State the desired outcome, the target project area, and any constraints."
            ),
        )

    response = ImprovedRequestResponse(
        clarified_goal=_intent_summary(compact_goal, compact_target),
        assumptions=[
            "Prefer the smallest useful implementation slice.",
            "Preserve existing module boundaries and project style.",
        ],
        constraints=[
            "Do not weaken shell, path, approval, or secret-handling safeguards.",
            "Avoid unrelated refactors.",
            *constraint_values,
        ],
        acceptance_criteria=[
            "Relevant files are identified before editing.",
            "Changes are limited to the stated goal.",
            "Focused validation is run or explicitly recommended.",
        ],
        suggested_first_slice="Inspect the target and draft a narrow plan before editing.",
        improved_prompt=_next_prompt(compact_goal, compact_target),
    )

    if _contains_any(lowered, {"quality", "professional", "clean", "refactor", "polish"}):
        response.acceptance_criteria.extend(
            [
                "The patch improves one named quality dimension.",
                "Behavior remains covered by existing or added focused tests.",
            ]
        )
        response.suggested_first_slice = "Choose one concrete quality issue and fix it end to end."

    if _contains_any(lowered, {"bug", "fix", "failing", "failure", "test pass"}):
        response.assumptions.append("A failing test, traceback, or reproduction may exist.")
        response.acceptance_criteria.append(
            "The failure is reproduced or inspected before the fix."
        )
        response.suggested_first_slice = "Find the reproduction or failing test before editing."

    if _contains_any(lowered, {"public", "publish", "release", "pypi", "alpha"}):
        response.acceptance_criteria.extend(
            [
                "Public docs avoid overclaiming planned features.",
                "Release validation commands are identified.",
            ]
        )
        response.suggested_first_slice = "Run a release-readiness doc and metadata pass first."

    if _contains_any(lowered, {"token", "context", "cost", "cheap", "budget"}):
        response.acceptance_criteria.append("The plan names a minimal context strategy.")
        response.suggested_first_slice = "Reduce context/tool surface before implementation work."

    _apply_request_ambiguity_triggers(response, compact_goal, compact_target, constraints)
    _dedupe_improved_request(response)
    return response


def plan_quality_review(request: PlanQualityReviewRequest) -> PlanQualityReviewResponse:
    """Critique an implementation plan before execution."""
    plan = _compact_text(request.plan)
    goal = _compact_text(request.goal)
    target = _compact_text(request.target)
    lowered = f"{plan} {goal} {target}".lower()

    if not plan:
        return PlanQualityReviewResponse(
            verdict="revise",
            summary="No implementation plan was provided.",
            concerns=["A missing plan cannot be checked for scope, context, or validation."],
            recommended_changes=["Write a short first-slice plan before editing files."],
            safer_plan=[
                "Clarify the goal.",
                "Identify the smallest relevant files.",
                "Name focused validation.",
            ],
        )

    review = PlanQualityReviewResponse(
        verdict="proceed_with_caution",
        summary="The plan is reviewable but should stay narrow and validated.",
        strengths=["The plan can be assessed before execution."],
        missing_context=[
            "Relevant source files near the target.",
            "Existing tests for touched behavior.",
        ],
        missing_tests=["Focused validation for changed behavior."],
        recommended_changes=[
            "Name the first implementation slice explicitly.",
            "List the focused validation command before editing.",
        ],
        safer_plan=[
            "Inspect the target and nearest tests.",
            "Apply the smallest patch that satisfies the goal.",
            "Run focused validation and review remaining risks.",
        ],
    )

    if target:
        review.missing_context.insert(0, f"Requested target: {target}.")

    if _contains_any(lowered, {"all files", "entire codebase", "everything", "whole project"}):
        review.verdict = "revise"
        review.scope_warnings.append("The plan appears broader than one safe implementation slice.")
        review.recommended_changes.append(
            "Split the work into one target area and one validation path."
        )

    if _contains_any(lowered, {"refactor", "rewrite", "restructure", "move modules"}):
        review.scope_warnings.append(
            "Refactor-heavy work should name module boundaries and rollback risk."
        )
        review.recommended_changes.append("Separate behavior changes from structural cleanup.")

    if not _contains_any(lowered, {"test", "pytest", "ruff", "mypy", "validation", "check"}):
        review.verdict = "revise"
        review.concerns.append("The plan does not name validation.")
        review.missing_tests.append("At least one relevant test, lint, or type-check command.")

    if _contains_any(lowered, {"rm -r", "rm -rf", "sudo", "curl |", "wget |", "auto_approve"}):
        review.verdict = "revise"
        review.security_warnings.append("The plan mentions risky shell or approval behavior.")
        review.recommended_changes.append(
            "Use guarded tools and keep destructive actions explicit."
        )

    if _contains_any(lowered, {"read all", "open all", "dump", "full logs", "entire log"}):
        review.token_warnings.append("The context plan may waste tokens with broad reads.")
        review.recommended_changes.append("Use rg, relevance search, and narrow file ranges first.")

    if request.constraints:
        review.strengths.append("User constraints are available for the review.")
    if request.recent_context.get("dirty_worktree"):
        review.concerns.append("Dirty worktree context should be separated from this plan.")

    _dedupe_plan_review(review)
    return review


def review_result_quality(
    request: ResultQualityReviewRequest,
) -> ResultQualityReviewResponse:
    """Review completed work for product-quality risks using local heuristics."""
    goal = _compact_text(request.goal)
    result_summary = _compact_text(request.result_summary)
    changed_files = [_compact_text(path) for path in request.changed_files if _compact_text(path)]
    changed_text = " ".join(changed_files).lower()
    validation_text = _dict_text(request.validation)
    context_text = _dict_text(request.recent_context)
    constraint_text = _dict_text(request.constraints)
    lowered = " ".join(
        item for item in [goal, result_summary, changed_text, validation_text, context_text] if item
    ).lower()

    if not goal or not result_summary:
        return ResultQualityReviewResponse(
            verdict="needs_clarification",
            summary="The review needs both the original goal and a result summary.",
            goal_alignment=["Provide the intended outcome and what changed."],
            validation_gaps=["Validation cannot be assessed without a completed-work summary."],
            next_small_fixes=[
                "Call review_result_quality again with goal and result_summary filled in."
            ],
        )

    review = ResultQualityReviewResponse(
        verdict="pass_with_notes",
        evidence_level="missing",
        summary=(
            "The result appears reviewable; validation is based on reported evidence, not an "
            "independent rerun."
        ),
        goal_alignment=["Result summary is present and can be compared with the stated goal."],
        strengths=["The work has an explicit goal and completion summary."],
        next_small_fixes=["Address the highest-risk remaining gap before broad follow-up work."],
    )

    if changed_files:
        review.strengths.append("Changed files were supplied for review.")
    else:
        review.validation_gaps.append(
            "Changed files were not supplied, so scope is hard to verify."
        )
        review.next_small_fixes.append("List the changed files in a compact summary.")

    if _has_validation_evidence(request.validation, validation_text):
        review.evidence_level = "reported"
        review.strengths.append("Validation evidence is mentioned.")
    else:
        review.verdict = "needs_followup"
        review.validation_gaps.append("No focused validation evidence was provided.")
        review.next_small_fixes.append("Run or name the smallest relevant validation command.")

    if request.validation.get("failed") or _contains_any(validation_text, {"failed", "error"}):
        review.verdict = "needs_followup"
        review.validation_gaps.append("Validation appears to have failed or reported errors.")
        review.next_small_fixes.append("Fix the failing validation before expanding scope.")

    _review_scope(goal, result_summary, changed_files, review)
    _review_docs_drift(goal, changed_text, review)
    _review_security_config(lowered, review)
    _review_token_context(request.recent_context, context_text, review)
    _review_self_critique(request.self_critique, review)

    if constraint_text and _contains_any(constraint_text, {"read-only", "no mutation"}):
        review.strengths.append("Read-only or no-mutation constraints were visible to the review.")

    _dedupe_result_review(review)
    return review


def suggest_bridge_config(
    goal: str,
    *,
    current_config: dict[str, Any],
) -> dict[str, Any]:
    """Suggest safe Bridge config changes for a user goal."""
    advice = advise_next_step(AgentAdviceRequest(goal=goal, current_config=current_config))
    suggestions = [item.to_dict() for item in advice.config_suggestions]
    lowered = _compact_text(goal).lower()
    tool_profile = str(current_config.get("tool_profile", "standard"))

    if _contains_any(lowered, {"token", "context", "cost", "cheap", "budget"}):
        if tool_profile not in {"essential", "standard"}:
            suggestions.append(
                ConfigSuggestion(
                    key="tool_profile",
                    value="essential",
                    reason="Token/cost-focused work benefits from the smallest useful tool set.",
                ).to_dict()
            )
        suggestions.append(
            ConfigSuggestion(
                key="context_budget_profile",
                value="low-cost",
                reason="Low-cost context budget reduces default context expansion.",
            ).to_dict()
        )

    if _contains_any(lowered, {"quality", "plan", "prompt", "professional"}):
        suggestions.append(
            ConfigSuggestion(
                key="intent_compaction_enabled",
                value=True,
                reason="Compaction helps turn repeated rough requests into smaller intent objects.",
            ).to_dict()
        )

    return {
        "schema_version": "bridge_config_suggestions.v1",
        "goal": _compact_text(goal),
        "suggestions": _dedupe_config_dicts(suggestions),
        "safe_keys": [
            "tool_profile",
            "context_budget_profile",
            "intent_compaction_enabled",
            "ai_evaluator_timeout",
            "onboarding_enabled",
            "shell_timeout",
        ],
        "restricted_keys": [
            "allowed_roots",
            "project_dir",
            "approval_preset",
            "auto_approve",
            "client_managed_approval",
            "ai_evaluator_enabled",
            "ai_evaluator_provider",
            "ai_evaluator_api_key",
            "ai_evaluator_model",
            "ai_evaluator_fallback_action",
            "role",
            "user",
        ],
        "notes": [
            "Suggestions are advisory until apply_bridge_config_change is called.",
            "Secrets and safety-weakening settings are not chat-mutable.",
        ],
    }


def _provider_parse_fallback(
    request: AgentAdviceRequest,
    *,
    started_at: float,
    reason: str,
    schema_version: str,
) -> ProviderAdviceParseResult:
    advice = advise_next_step(request)
    duration_ms = _duration_ms(started_at)
    _record_provider_parse(ok=False, fallback_used=True, duration_ms=duration_ms)
    return ProviderAdviceParseResult(
        advice=advice,
        metadata=ProviderAdviceParseMeta(
            ok=False,
            reason=reason,
            fallback_used=True,
            schema_version=schema_version,
            duration_ms=duration_ms,
        ),
    )


def _provider_advice_from_dict(payload: dict[str, Any]) -> tuple[AgentAdviceResponse, list[str]]:
    unsafe_config_keys: list[str] = []
    should_ask_user = payload.get("should_ask_user", False)
    if not isinstance(should_ask_user, bool):
        raise ValueError("should_ask_user must be a boolean")

    advice = AgentAdviceResponse(
        schema_version="agent_advice.v1",
        intent_summary=_string_field(payload, "intent_summary"),
        recommended_next_step=_string_field(payload, "recommended_next_step"),
        why_this_step=_string_field(payload, "why_this_step"),
        needed_context=_string_list_field(payload, "needed_context"),
        risks=_string_list_field(payload, "risks"),
        validation=_string_list_field(payload, "validation"),
        token_strategy=_string_list_field(payload, "token_strategy"),
        config_suggestions=_provider_config_suggestions(payload, unsafe_config_keys),
        should_ask_user=should_ask_user,
        question=_string_field(payload, "question"),
        next_prompt=_string_field(payload, "next_prompt"),
    )
    if not advice.intent_summary or not advice.recommended_next_step:
        raise ValueError("provider advice is missing required summary or next step")
    _dedupe_response(advice)
    return advice, unsafe_config_keys


def _provider_config_suggestions(
    payload: dict[str, Any],
    unsafe_config_keys: list[str],
) -> list[ConfigSuggestion]:
    raw_items = payload.get("config_suggestions", [])
    if raw_items is None:
        return []
    if not isinstance(raw_items, list):
        raise ValueError("config_suggestions must be a list")

    suggestions: list[ConfigSuggestion] = []
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            raise ValueError("config_suggestions items must be objects")
        suggestion = _provider_config_suggestion(raw_item, unsafe_config_keys)
        if suggestion is not None:
            suggestions.append(suggestion)
    return suggestions


def _provider_config_suggestion(
    raw_item: dict[str, Any],
    unsafe_config_keys: list[str],
) -> ConfigSuggestion | None:
    key = _compact_text(str(raw_item.get("key", "")))
    if not key or key not in _SAFE_PROVIDER_CONFIG_KEYS:
        unsafe_config_keys.append(key or "<missing>")
        return None

    value = raw_item.get("value")
    if not isinstance(value, (str, bool, int)):
        unsafe_config_keys.append(key)
        return None

    reason = _string_field(raw_item, "reason") or "Provider suggested a safe config change."
    risk = _string_field(raw_item, "risk") or "low"
    requires_approval = raw_item.get("requires_approval", True)
    if not isinstance(requires_approval, bool):
        raise ValueError("requires_approval must be a boolean")

    return ConfigSuggestion(
        key=key,
        value=value,
        reason=reason,
        risk=risk,
        requires_approval=requires_approval,
    )


def _record_provider_parse(
    *,
    ok: bool,
    fallback_used: bool,
    duration_ms: float,
) -> None:
    global _PROVIDER_TELEMETRY_FALLBACK_COUNT
    global _PROVIDER_TELEMETRY_LAST_DURATION_MS
    global _PROVIDER_TELEMETRY_PARSE_FAILURES
    global _PROVIDER_TELEMETRY_SAMPLE_COUNT

    _PROVIDER_TELEMETRY_SAMPLE_COUNT += 1
    if not ok:
        _PROVIDER_TELEMETRY_PARSE_FAILURES += 1
    if fallback_used:
        _PROVIDER_TELEMETRY_FALLBACK_COUNT += 1
    _PROVIDER_TELEMETRY_LAST_DURATION_MS = duration_ms


def _duration_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 3)


def _string_field(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return _compact_text(value)


def _string_list_field(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{key} items must be strings")
        compacted = _compact_text(item)
        if compacted:
            result.append(compacted)
    return result


def _compact_text(value: str) -> str:
    return " ".join(str(value).strip().split())


def _intent_summary(goal: str, target: str) -> str:
    if target:
        return f"Turn '{goal}' into a scoped, validated change for {target}."
    return f"Turn '{goal}' into a scoped, validated change."


def _base_context(target: str) -> list[str]:
    context = [
        "Project docs that define current behavior and constraints.",
        "The smallest relevant source files for the requested change.",
        "Existing tests around the touched behavior.",
    ]
    if target:
        context.insert(0, f"Inspect the requested target first: {target}.")
    return context


def _next_prompt(goal: str, target: str) -> str:
    if target:
        return (
            f"Turn this goal into the smallest safe implementation slice for {target}: {goal}. "
            "List assumptions, needed files, validation, and stop before broad refactors."
        )
    return (
        f"Turn this goal into the smallest safe implementation slice: {goal}. "
        "List assumptions, needed files, validation, and stop before broad refactors."
    )


def _apply_goal_patterns(advice: AgentAdviceResponse, lowered: str) -> None:
    if _contains_any(lowered, {"public", "publish", "release", "pypi", "alpha"}):
        advice.recommended_next_step = "Run a release-readiness slice before publishing."
        advice.needed_context.extend(
            [
                "README.md",
                "pyproject.toml",
                "docs/publishing-checklist.md",
                "docs/product-vision.md",
            ]
        )
        advice.validation.extend(
            ["pytest", "ruff check .", "mypy src", "python -m build", "twine check dist/*"]
        )
        advice.risks.append("Public docs may overclaim planned Agent Quality Layer behavior.")

    if _contains_any(lowered, {"bug", "fix", "failing", "failure", "test pass"}):
        advice.recommended_next_step = "Reproduce or inspect the failing behavior first."
        advice.needed_context.extend(
            [
                "The failing test, traceback, or reproduction steps.",
                "The narrow source path most likely responsible for the failure.",
            ]
        )
        advice.validation.append("Run the focused failing test before and after the fix.")
        advice.risks.append("Changing code before reproducing the failure may hide the real cause.")

    if _contains_any(lowered, {"quality", "professional", "clean", "refactor", "polish"}):
        advice.recommended_next_step = "Define the quality bar and choose one narrow improvement."
        advice.needed_context.extend(
            [
                "Existing style and module-boundary examples near the target.",
                "Tests or docs that show intended user-facing behavior.",
            ]
        )
        advice.validation.append("Run a result quality review after the patch.")
        advice.risks.append("A broad quality request can turn into unrelated refactoring.")

    if _contains_any(lowered, {"token", "context", "cost", "cheap", "budget"}):
        advice.recommended_next_step = "Optimize context strategy before doing implementation work."
        advice.token_strategy.extend(
            [
                "Prefer essential or standard tool profile for narrow sessions.",
                "Use find_relevant_files before read_multiple_files.",
                "Summarize long command output instead of feeding full logs back into chat.",
            ]
        )
        advice.validation.append("Check session usage insights after the task.")

    if _contains_any(lowered, {"config", "setting", "settings", "ayar", "ayarlar"}):
        advice.needed_context.append("Current bridge_status and get_config output.")
        advice.risks.append("Config changes must not set secrets or weaken safety defaults.")


def _apply_context_inputs(
    advice: AgentAdviceResponse,
    recent_context: dict[str, Any],
    constraints: dict[str, Any],
) -> None:
    if constraints:
        advice.needed_context.append("User-provided constraints from constraints_json.")
    if recent_context.get("validation_failed"):
        advice.recommended_next_step = "Inspect the validation failure before making new changes."
        advice.needed_context.append("Recent validation failure output.")
        advice.validation.append("Re-run the previously failing validation command.")
    if recent_context.get("dirty_worktree"):
        advice.risks.append("Dirty worktree detected; avoid mixing unrelated changes.")


def _apply_config_suggestions(
    advice: AgentAdviceResponse,
    lowered: str,
    current_config: dict[str, Any],
) -> None:
    tool_profile = str(current_config.get("tool_profile", "standard"))
    budget_profile = str(current_config.get("context_budget_profile", "balanced"))

    if _contains_any(
        lowered,
        {"docs", "readme", "documentation", "token", "context", "public", "publish", "release"},
    ):
        if tool_profile == "full":
            advice.config_suggestions.append(
                ConfigSuggestion(
                    key="tool_profile",
                    value="standard",
                    reason=(
                        "The goal looks narrow enough that the full tool surface may add token "
                        "overhead without improving quality."
                    ),
                )
            )
        if budget_profile == "deep":
            advice.config_suggestions.append(
                ConfigSuggestion(
                    key="context_budget_profile",
                    value="balanced",
                    reason="A balanced context budget is safer for routine focused work.",
                )
            )

    if _contains_any(lowered, {"token", "cost", "cheap"}):
        advice.config_suggestions.append(
            ConfigSuggestion(
                key="intent_compaction_enabled",
                value=True,
                reason="Intent compaction can reduce repeated prompt/context overhead.",
            )
        )


def _dedupe_response(advice: AgentAdviceResponse) -> None:
    advice.needed_context = _dedupe(advice.needed_context)
    advice.risks = _dedupe(advice.risks)
    advice.validation = _dedupe(advice.validation)
    advice.token_strategy = _dedupe(advice.token_strategy)

    seen_config: set[tuple[str, str]] = set()
    deduped_config: list[ConfigSuggestion] = []
    for suggestion in advice.config_suggestions:
        key = (suggestion.key, str(suggestion.value))
        if key in seen_config:
            continue
        seen_config.add(key)
        deduped_config.append(suggestion)
    advice.config_suggestions = deduped_config


def _dedupe_improved_request(response: ImprovedRequestResponse) -> None:
    response.assumptions = _dedupe(response.assumptions)
    response.constraints = _dedupe(response.constraints)
    response.acceptance_criteria = _dedupe(response.acceptance_criteria)


def _dedupe_plan_review(review: PlanQualityReviewResponse) -> None:
    review.strengths = _dedupe(review.strengths)
    review.concerns = _dedupe(review.concerns)
    review.missing_context = _dedupe(review.missing_context)
    review.missing_tests = _dedupe(review.missing_tests)
    review.scope_warnings = _dedupe(review.scope_warnings)
    review.security_warnings = _dedupe(review.security_warnings)
    review.token_warnings = _dedupe(review.token_warnings)
    review.recommended_changes = _dedupe(review.recommended_changes)
    review.safer_plan = _dedupe(review.safer_plan)


def _dedupe_result_review(review: ResultQualityReviewResponse) -> None:
    review.goal_alignment = _dedupe(review.goal_alignment)
    review.scope_drift = _dedupe(review.scope_drift)
    review.validation_gaps = _dedupe(review.validation_gaps)
    review.docs_drift_risks = _dedupe(review.docs_drift_risks)
    review.security_config_risks = _dedupe(review.security_config_risks)
    review.token_context_waste = _dedupe(review.token_context_waste)
    review.self_critique_findings = _dedupe(review.self_critique_findings)
    review.strengths = _dedupe(review.strengths)
    review.next_small_fixes = _dedupe(review.next_small_fixes)


def _review_scope(
    goal: str,
    result_summary: str,
    changed_files: list[str],
    review: ResultQualityReviewResponse,
) -> None:
    lowered = f"{goal} {result_summary}".lower()
    if _contains_any(lowered, {"only", "just", "small", "narrow"}) and len(changed_files) > 6:
        review.verdict = "needs_followup"
        review.scope_drift.append("A narrow goal touched many files.")
        review.next_small_fixes.append("Confirm every touched file is required for the goal.")
    if _contains_any(lowered, {"refactor", "rewrite", "cleanup"}) and len(changed_files) > 4:
        review.scope_drift.append("Broad structural work may be mixed with behavior changes.")
        review.next_small_fixes.append("Separate behavior changes from cleanup in the summary.")
    if _contains_any(lowered, {"unrelated", "while there", "also changed", "drive-by"}):
        review.verdict = "needs_followup"
        review.scope_drift.append("The summary suggests unrelated changes may have been included.")


def _review_docs_drift(
    goal: str,
    changed_text: str,
    review: ResultQualityReviewResponse,
) -> None:
    goal_lowered = goal.lower()
    docs_changed = "docs/" in changed_text or "readme" in changed_text
    if _contains_any(goal_lowered, {"mcp tool", "api", "config", "public", "roadmap"}):
        if docs_changed:
            review.strengths.append("Documentation or roadmap files were included.")
        else:
            review.docs_drift_risks.append("User-facing behavior changed without docs evidence.")
            review.next_small_fixes.append("Update or explicitly defer relevant docs.")
    if _contains_any(changed_text, {"readme", "docs/", "roadmap"}):
        review.goal_alignment.append("Docs changes are visible in the changed-file list.")


def _review_security_config(lowered: str, review: ResultQualityReviewResponse) -> None:
    risky_terms = {
        "api key",
        "secret",
        "token",
        "allowed_roots",
        "auto_approve",
        "sudo",
        "rm -rf",
        "curl |",
        "wget |",
    }
    if _contains_any(lowered, risky_terms):
        review.verdict = "needs_followup"
        review.security_config_risks.append(
            "The result mentions sensitive config, shell, or secret-adjacent behavior."
        )
        review.next_small_fixes.append(
            "Verify the change did not weaken hard denies, path bounds, or secret handling."
        )


def _review_token_context(
    recent_context: dict[str, Any],
    context_text: str,
    review: ResultQualityReviewResponse,
) -> None:
    if recent_context.get("broad_reads") or recent_context.get("large_context"):
        review.token_context_waste.append("Recent context indicates broad or large reads.")
        review.next_small_fixes.append("Use relevance search and narrow file ranges next time.")
    if _contains_any(context_text, {"read all", "entire codebase", "full logs", "dumped"}):
        review.token_context_waste.append("Context notes suggest avoidable broad context usage.")
    estimated_tokens = recent_context.get("estimated_tokens")
    if isinstance(estimated_tokens, int) and estimated_tokens > 12000:
        review.token_context_waste.append("Estimated context use is high for a focused review.")


def _review_self_critique(
    self_critique: dict[str, Any],
    review: ResultQualityReviewResponse,
) -> None:
    if not self_critique:
        review.next_small_fixes.append(
            "Optionally run self_critique on changed code for deterministic code-quality signals."
        )
        return

    if self_critique.get("ok") is False:
        message = _compact_text(str(self_critique.get("message", "self_critique warning")))
        review.self_critique_findings.append(f"self_critique warning: {message}")
        review.next_small_fixes.append("Resolve or explain deterministic self_critique warnings.")
        if review.verdict == "pass_with_notes":
            review.verdict = "needs_followup"
        return

    details = self_critique.get("details", {})
    if not isinstance(details, dict):
        review.self_critique_findings.append("self_critique payload did not include details.")
        return

    summary = details.get("summary", {})
    if not isinstance(summary, dict):
        review.self_critique_findings.append("self_critique details did not include a summary.")
        return

    total_issues = _int_field(summary, "total_issues")
    if total_issues <= 0:
        review.strengths.append("Deterministic self_critique reported no issues.")
        return

    review.self_critique_findings.append(
        f"Deterministic self_critique reported {total_issues} issue(s)."
    )
    by_severity = summary.get("by_severity", {})
    if isinstance(by_severity, dict):
        severe = sum(_coerce_int(by_severity.get(key, 0)) for key in ("critical", "high"))
        if severe > 0:
            review.verdict = "needs_followup"
            review.self_critique_findings.append(
                f"self_critique includes {severe} high-severity issue(s)."
            )
    review.next_small_fixes.append("Review self_critique findings before broad follow-up work.")


def _has_validation_evidence(validation: dict[str, Any], validation_text: str) -> bool:
    if _contains_any(
        validation_text,
        {"test", "pytest", "ruff", "mypy", "black --check", "validation"},
    ):
        return True

    for value in validation.values():
        if isinstance(value, list) and value:
            text = " ".join(str(item) for item in value).lower()
            if _contains_any(text, {"test", "pytest", "ruff", "mypy", "black"}):
                return True
    return False


def _dedupe_config_dicts(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for item in values:
        key = (str(item.get("key", "")), str(item.get("value", "")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _constraint_texts(constraints: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for key, value in constraints.items():
        if isinstance(value, (str, int, float, bool)):
            texts.append(f"{key}: {value}")
        elif value is not None:
            texts.append(f"{key}: provided")
    return texts


def _dict_text(values: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in values.items():
        if isinstance(value, (str, int, float, bool)):
            parts.append(f"{key}: {value}")
        elif isinstance(value, list):
            parts.append(f"{key}: {len(value)} items")
        elif value is not None:
            parts.append(f"{key}: provided")
    return " ".join(parts)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _contains_any(text: str, needles: set[str]) -> bool:
    return any(needle in text for needle in needles)


def _int_field(data: dict[str, Any], key: str) -> int:
    return _coerce_int(data.get(key, 0))


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _apply_ambiguity_triggers(
    advice: AgentAdviceResponse,
    goal: str,
    target: str,
    recent_context: dict[str, Any],
    constraints: dict[str, Any],
) -> None:
    triggers: list[str] = []
    goal_lower = goal.lower()
    target_lower = target.lower()

    competing_goals = ["and", "but also", "simultaneously", "both"]
    if any(cg in goal_lower for cg in competing_goals):
        triggers.append("competing_goals")
    if any(cg in target_lower for cg in competing_goals):
        triggers.append("competing_goals")

    conflicting_terms = ["but not", "avoid", "never", "must not", "don't"]
    if any(ct in goal_lower for ct in conflicting_terms):
        triggers.append("conflicting_constraints")

    validation_terms = {"verify", "check", "test", "validate", "ensure"}
    missing_validation = not any(vt in goal_lower for vt in validation_terms)
    context_has_validation = recent_context.get("validation_failed") or recent_context.get("validation_passed")
    if missing_validation and not context_has_validation:
        triggers.append("missing_validation_evidence")

    if len(target) > 80:
        triggers.append("broad_target")

    if triggers:
        advice.uncertainty_flag = True
        advice.ambiguity_triggers = triggers
        advice.should_ask_user = True
        advice.question = (
            "Multiple paths or ambiguous constraints detected. "
            "Which direction should take priority: " + ", ".join(triggers) + "?"
        )


def _apply_request_ambiguity_triggers(
    response: ImprovedRequestResponse,
    goal: str,
    target: str,
    constraints: dict[str, Any] | None,
) -> None:
    triggers: list[str] = []
    goal_lower = goal.lower()
    target_lower = target.lower()

    competing_goals = ["and", "but also", "simultaneously", "both"]
    if any(cg in goal_lower for cg in competing_goals):
        triggers.append("competing_goals")
    if any(cg in target_lower for cg in competing_goals):
        triggers.append("competing_goals")

    conflicting_terms = ["but not", "avoid", "never", "must not", "don't"]
    if any(ct in goal_lower for ct in conflicting_terms):
        triggers.append("conflicting_constraints")

    validation_terms = {"verify", "check", "test", "validate", "ensure"}
    missing_validation = not any(vt in goal_lower for vt in validation_terms)
    if missing_validation:
        triggers.append("missing_validation_evidence")

    if len(target) > 80:
        triggers.append("broad_target")

    if constraints:
        constraint_keys = list(constraints.keys()) if constraints else []
        if len(constraint_keys) > 4:
            triggers.append("multiple_constraints")

    if triggers:
        response.uncertainty_flag = True
        response.ambiguity_triggers = triggers
        response.should_ask_user = True
        response.question = (
            "Ambiguous or competing goals detected. "
            "Clarify priorities: " + ", ".join(triggers) + "?"
        )
