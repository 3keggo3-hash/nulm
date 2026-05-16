
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT

"""Replay engine for Claude Bridge audit records (Package 3D).

Re-evaluates past tool calls against the *current* rule set so that
policy changes can be tested retroactively without re-executing the
original tools.

Key behaviours:
* Masked / redacted params never cause a crash; conditions that depend
  on missing data simply fail to match (deterministic no-match).
* A replay does **not** re-execute the tool, access the filesystem, or
  call an AI evaluator — it only replays the *policy-decision* layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path
from typing import Any, Dict, Sequence

from claude_bridge.audit import (
    _extract_decision_from_record,
    find_audit_record,
    _plain_string,
    _record_params,
    _record_result,
)
from claude_bridge.guard_policy import (
    DecisionAction,
    DecisionSource,
    GuardRule,
    PolicyDecision,
    RiskLevel,
    ToolRequestContext,
    load_rules,
    validate_guard_policy_file,
)
from claude_bridge.rules_engine import evaluate_policy_chain

# ---------------------------------------------------------------------------
# Replay result model
# ---------------------------------------------------------------------------

_MASKED_VALUE_MARKER_KEYS = {"redacted", "truncated", "sha256", "preview"}


def _value_looks_masked(value: Any) -> bool:
    """Heuristic: return True when a value is a redaction/truncation dict.

    Only used for reporting — never for access-control decisions.
    """
    if not isinstance(value, dict):
        return False
    return bool(set(value.keys()) & _MASKED_VALUE_MARKER_KEYS)


def _collect_masked_fields(params: dict[str, Any]) -> list[str]:
    """Return the names of params whose values appear masked/redacted."""
    masked: list[str] = []
    for key, val in params.items():
        if _value_looks_masked(val):
            masked.append(key)
    return masked


@dataclass
class ReplayResult:
    """The outcome of a single audit record replay."""

    original_decision: PolicyDecision | None
    replayed_decision: PolicyDecision
    changed: bool
    change_reason: str
    metadata: Dict[str, Any] = dc_field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        return {
            "original_decision": (
                self.original_decision.to_dict() if self.original_decision is not None else None
            ),
            "replayed_decision": self.replayed_decision.to_dict(),
            "changed": self.changed,
            "change_reason": self.change_reason,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Context building
# ---------------------------------------------------------------------------


def build_replay_context(
    record: dict[str, Any],
    *,
    project_dir: str | None = None,
    allowed_roots: list[str] | None = None,
) -> tuple[ToolRequestContext, PolicyDecision | None]:
    """Build a replay-ready context from an audit record.

    Args:
        record: A single audit record (from a JSONL session file).
        project_dir: Optional workspace directory override.
        allowed_roots: Optional allowed-roots override.

    Returns:
        A ``(ToolRequestContext, original_decision_or_None)`` tuple.
        The params in the context are the *summarized / redacted* params
        as stored in the audit record.
    """
    tool_name = str(record.get("tool_name", "unknown"))
    params = _record_params(record)
    # Try to recover project_dir from result details or params
    resolved_project_dir = project_dir
    if resolved_project_dir is None:
        result = _record_result(record)
        details = result.get("details", {})
        if isinstance(details, dict):
            resolved_project_dir = _plain_string(details.get("project_dir"))
    if resolved_project_dir is None:
        resolved_project_dir = _plain_string(params.get("project_dir"))
    resolved_allowed_roots = allowed_roots or []
    ctx = ToolRequestContext(
        tool_name=tool_name,
        params=dict(params),
        project_dir=resolved_project_dir,
        allowed_roots=list(resolved_allowed_roots),
    )
    original = _build_original_decision(record)
    return ctx, original


def _build_original_decision(record: dict[str, Any]) -> PolicyDecision | None:
    """Reconstruct the original PolicyDecision from audit record fields."""
    extracted = _extract_decision_from_record(record)
    if extracted is None:
        return None
    action_raw = extracted.get("action")
    source_raw = extracted.get("source")
    risk_raw = extracted.get("risk_level")
    try:
        action = DecisionAction(str(action_raw)) if action_raw else DecisionAction.DENY
    except ValueError:
        action = DecisionAction.DENY
    try:
        source = DecisionSource(str(source_raw)) if source_raw else DecisionSource.DEFAULT
    except ValueError:
        source = DecisionSource.DEFAULT
    try:
        risk_level = RiskLevel(str(risk_raw)) if risk_raw else RiskLevel.LOW
    except ValueError:
        risk_level = RiskLevel.LOW
    return PolicyDecision(
        action=action,
        source=source,
        risk_level=risk_level,
        reason=str(extracted.get("reason", "")),
        risk_reasons=[str(r) for r in extracted.get("risk_reasons", [])],
        metadata=dict(extracted.get("metadata", {})),
    )


# ---------------------------------------------------------------------------
# Replay evaluation
# ---------------------------------------------------------------------------


def replay_decision(
    record: dict[str, Any],
    *,
    rules: Sequence[GuardRule] | None = None,
    builtin_deny: PolicyDecision | None = None,
    default_decision: PolicyDecision | None = None,
    project_dir: str | None = None,
    allowed_roots: list[str] | None = None,
) -> ReplayResult:
    """Re-evaluate a single audit record against the current policy.

    The function builds a :class:`ToolRequestContext` from the audit
    record and runs it through :func:`evaluate_policy_chain`.  Masked or
    missing param data is handled safely: conditions that need the real
    value fail to match (fail-closed), which is the same deterministic
    behaviour the rules engine already applies.

    Args:
        record: The audit record to replay.
        rules: Current guard rules.  When ``None``, the replay only
            considers the builtin-deny and default layers.
        builtin_deny: Pre-computed builtin deny decision (optional).
        default_decision: Fallback decision (optional).
        project_dir: Override workspace directory.
        allowed_roots: Override allowed roots.

    Returns:
        A :class:`ReplayResult` comparing original and replayed decisions.
    """
    ctx, original = build_replay_context(
        record,
        project_dir=project_dir,
        allowed_roots=allowed_roots,
    )

    masked_param_names = _collect_masked_fields(ctx.params)
    replay_meta: dict[str, Any] = {
        "tool_name": ctx.tool_name,
        "has_masked_params": bool(masked_param_names),
    }
    if masked_param_names:
        replay_meta["masked_param_names"] = masked_param_names

    replayed = evaluate_policy_chain(
        ctx,
        builtin_deny=builtin_deny,
        user_rules=list(rules) if rules else None,
        default_decision=default_decision,
    )

    changed, change_reason = _compare_decisions(original, replayed)

    if masked_param_names and not changed:
        replay_meta["masking_note"] = (
            "One or more params are masked; rule conditions that depend on "
            "those values will not match.  A false-negative match is "
            "possible (the rule engine never fail-opens)."
        )

    return ReplayResult(
        original_decision=original,
        replayed_decision=replayed,
        changed=changed,
        change_reason=change_reason,
        metadata=replay_meta,
    )


def _compare_decisions(
    original: PolicyDecision | None,
    replayed: PolicyDecision,
) -> tuple[bool, str]:
    """Compare original and replayed decisions.

    Returns:
        ``(changed, reason)`` tuple.
    """
    if original is None:
        return True, "no original decision available for comparison"
    if original.action != replayed.action:
        return True, (f"action changed: {original.action.value} → {replayed.action.value}")
    if original.source != replayed.source:
        return True, (f"source changed: {original.source.value} → {replayed.source.value}")
    if original.risk_level != replayed.risk_level:
        return True, (
            f"risk_level changed: {original.risk_level.value} → {replayed.risk_level.value}"
        )
    return False, ""


# ---------------------------------------------------------------------------
# Batch replay helpers
# ---------------------------------------------------------------------------


def replay_session(
    records: list[dict[str, Any]],
    *,
    rules: Sequence[GuardRule] | None = None,
    builtin_deny: PolicyDecision | None = None,
    default_decision: PolicyDecision | None = None,
    project_dir: str | None = None,
    allowed_roots: list[str] | None = None,
    limit: int | None = None,
) -> list[ReplayResult]:
    """Replay every record in a session, optionally limited.

    Args:
        records: All audit records from a session.
        rules: Current guard rules.
        builtin_deny: Pre-computed builtin deny decision.
        default_decision: Fallback decision.
        project_dir: Override workspace directory.
        allowed_roots: Override allowed roots.
        limit: Maximum number of records to replay (most recent first).

    Returns:
        A list of :class:`ReplayResult` objects, one per replayed record.
    """
    if limit is not None:
        subset = list(reversed(records[-limit:])) if limit > 0 else []
    else:
        subset = list(reversed(records))
    results: list[ReplayResult] = []
    for record in subset:
        result = replay_decision(
            record,
            rules=rules,
            builtin_deny=builtin_deny,
            default_decision=default_decision,
            project_dir=project_dir,
            allowed_roots=allowed_roots,
        )
        results.append(result)
    return results


def replay_summary(results: list[ReplayResult]) -> dict[str, Any]:
    """Produce a high-level summary of replay results."""
    total = len(results)
    changed_count = sum(1 for r in results if r.changed)
    action_transitions: dict[str, int] = {}
    for r in results:
        if not r.changed or r.original_decision is None:
            continue
        key = f"{r.original_decision.action.value}→{r.replayed_decision.action.value}"
        action_transitions[key] = action_transitions.get(key, 0) + 1
    masked_affected = sum(1 for r in results if r.metadata.get("has_masked_params"))
    return {
        "total_replayed": total,
        "changed_count": changed_count,
        "unchanged_count": total - changed_count,
        "action_transitions": action_transitions,
        "records_with_masked_params": masked_affected,
        "masking_aware": (
            "Conditions that depend on masked/redacted values will not "
            "match (fail-closed).  Always review changed decisions manually."
            if masked_affected > 0
            else None
        ),
    }


def replay_with_justification(
    record: dict[str, Any],
    *,
    justification: str,
    rules: Sequence[GuardRule] | None = None,
    builtin_deny: PolicyDecision | None = None,
    default_decision: PolicyDecision | None = None,
    project_dir: str | None = None,
    allowed_roots: list[str] | None = None,
) -> ReplayResult:
    """Re-evaluate an audit record with an appeal justification.

    The justification is embedded into the replay metadata so that
    downstream systems (audit log, admin review) can trace why the
    replay was triggered and what context the user provided.

    When no AI evaluator is available the replay is purely deterministic.
    If the original decision was ``deny`` and the replay still produces
    ``deny``, the result is marked as ``ask`` (requires human review)
    with the justification attached.

    Args:
        record: The audit record to replay.
        justification: User-provided reason for the appeal.
        rules: Current guard rules.
        builtin_deny: Pre-computed builtin deny decision.
        default_decision: Fallback decision.
        project_dir: Override workspace directory.
        allowed_roots: Override allowed roots.

    Returns:
        A :class:`ReplayResult` with justification metadata attached.
    """
    ctx, original = build_replay_context(
        record,
        project_dir=project_dir,
        allowed_roots=allowed_roots,
    )

    masked_param_names = _collect_masked_fields(ctx.params)
    replay_meta: dict[str, Any] = {
        "tool_name": ctx.tool_name,
        "has_masked_params": bool(masked_param_names),
        "appeal_justification": justification,
        "appeal_replay": True,
    }
    if masked_param_names:
        replay_meta["masked_param_names"] = masked_param_names

    replayed = evaluate_policy_chain(
        ctx,
        builtin_deny=builtin_deny,
        user_rules=list(rules) if rules else None,
        default_decision=default_decision,
    )

    changed, change_reason = _compare_decisions(original, replayed)

    if masked_param_names and not changed:
        replay_meta["masking_note"] = (
            "One or more params are masked; rule conditions that depend on "
            "those values will not match.  A false-negative match is "
            "possible (the rule engine never fail-opens)."
        )

    if original is not None and original.action == DecisionAction.DENY:
        if replayed.action == DecisionAction.DENY and not changed:
            replay_meta["requires_human_review"] = True
            replay_meta["review_reason"] = (
                "Original decision was deny; deterministic replay also "
                "produces deny. Human review required with justification."
            )

    return ReplayResult(
        original_decision=original,
        replayed_decision=replayed,
        changed=changed,
        change_reason=change_reason,
        metadata=replay_meta,
    )


def replay_record_id(
    record_id: str,
    *,
    policy_path: Path | None = None,
) -> dict[str, Any] | None:
    """Replay a single audit record by id.

    This is the CLI-facing convenience wrapper.  It does not execute the
    original tool; it only reloads the requested audit record and evaluates
    its stored context against the current or explicitly provided policy.
    """
    record = find_audit_record(record_id)
    if record is None:
        return None

    if policy_path is not None:
        policy = validate_guard_policy_file(policy_path.resolve())
        rules = policy.rules
        validation_errors = list(policy.errors)
    else:
        rule_set = load_rules()
        rules = rule_set.rules
        validation_errors = []

    result = replay_decision(record, rules=rules)
    payload = result.to_dict()
    payload["record_id"] = record_id
    payload["tool_name"] = record.get("tool_name", "unknown")
    limitations = [
        "Replay only re-evaluates deterministic policy/rule decisions.",
        "Replay does not execute tools, shell commands, approval prompts, AI evaluators, "
        "filesystem snapshots, or side effects.",
    ]
    if validation_errors:
        limitations.append("Policy validation errors were present during replay.")
        payload["policy_validation_errors"] = validation_errors
    if result.metadata.get("has_masked_params"):
        limitations.append(
            "Masked/redacted params may cause value-dependent rule conditions not to match."
        )
    payload["limitations"] = limitations
    return payload
