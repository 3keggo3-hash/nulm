"""Deterministic mission brief construction for subagent runs."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from claude_bridge.agents.contracts import ContextManifest, TaskSpec


@dataclass(frozen=True)
class MissionBrief:
    """Compact auditable context package for one subagent task."""

    brief_id: str
    task_id: str
    agent_name: str
    context_manifest_id: str
    objective: str
    question: str
    must_know: tuple[str, ...]
    allowed_scope: tuple[str, ...]
    non_goals: tuple[str, ...]
    expected_artifacts: tuple[str, ...]
    escalation_triggers: tuple[str, ...]
    confidence_floor: float | None
    token_estimate: int
    source_reason: str
    omitted_context_reason: str

    def to_dict(self) -> dict[str, Any]:
        """Return a stable JSON-compatible representation."""
        return {
            "brief_id": self.brief_id,
            "task_id": self.task_id,
            "agent_name": self.agent_name,
            "context_manifest_id": self.context_manifest_id,
            "objective": self.objective,
            "question": self.question,
            "must_know": list(self.must_know),
            "allowed_scope": list(self.allowed_scope),
            "non_goals": list(self.non_goals),
            "expected_artifacts": list(self.expected_artifacts),
            "escalation_triggers": list(self.escalation_triggers),
            "confidence_floor": self.confidence_floor,
            "token_estimate": self.token_estimate,
            "source_reason": self.source_reason,
            "omitted_context_reason": self.omitted_context_reason,
        }


class ContextCurator:
    """Build mission briefs without replanning, routing, or changing permissions."""

    def curate(self, task: TaskSpec, manifest: ContextManifest) -> MissionBrief:
        """Create a deterministic brief from an immutable task and manifest."""
        objective = task.goal
        question = task.question or task.goal
        allowed_scope, omitted_reason = _allowed_scope(task, manifest)
        must_know = _must_know(task, manifest)
        escalation_triggers = _escalation_triggers(task)
        expected_artifacts = task.expected_artifacts or task.expected_evidence
        token_estimate = _estimate_tokens(
            (
                objective,
                question,
                *must_know,
                *allowed_scope,
                *expected_artifacts,
                *escalation_triggers,
            )
        )
        brief_id = _brief_id(
            task_id=task.task_id,
            agent_name=task.agent_name,
            context_manifest_id=manifest.manifest_id,
            objective=objective,
            question=question,
            allowed_scope=allowed_scope,
            expected_artifacts=expected_artifacts,
        )
        return MissionBrief(
            brief_id=brief_id,
            task_id=task.task_id,
            agent_name=task.agent_name,
            context_manifest_id=manifest.manifest_id,
            objective=objective,
            question=question,
            must_know=must_know,
            allowed_scope=allowed_scope,
            non_goals=("Do not alter the task goal, permissions, dependencies, or file sets.",),
            expected_artifacts=expected_artifacts,
            escalation_triggers=escalation_triggers,
            confidence_floor=None,
            token_estimate=token_estimate,
            source_reason=manifest.source_reason,
            omitted_context_reason=omitted_reason,
        )


def _allowed_scope(task: TaskSpec, manifest: ContextManifest) -> tuple[tuple[str, ...], str]:
    selected = tuple(dict.fromkeys(path for path in manifest.selected_files if path))
    if not selected:
        return (), "no selected context"
    if task.read_set:
        allowed = tuple(path for path in selected if path in set(task.read_set))
        if allowed:
            reason = "kept task read_set entries from manifest"
            omitted = len(selected) - len(allowed)
            if omitted > 0:
                reason = f"{reason}; omitted {omitted} non-read_set file(s)"
            return allowed, reason
    tokens = _task_tokens(task)
    matching = tuple(path for path in selected if _path_matches_tokens(path, tokens))
    if matching:
        omitted = len(selected) - len(matching)
        reason = "omitted context with no objective/question token match"
        return matching, reason if omitted > 0 else "all selected context matched task tokens"
    return selected, "no deterministic relevance signal; kept manifest-selected context"


def _must_know(task: TaskSpec, manifest: ContextManifest) -> tuple[str, ...]:
    values = [manifest.summary_text]
    values.extend(task.acceptance_criteria)
    values.extend(task.expected_evidence)
    return tuple(dict.fromkeys(value for value in values if value))


def _escalation_triggers(task: TaskSpec) -> tuple[str, ...]:
    triggers = []
    if task.escalation_policy:
        triggers.append(task.escalation_policy)
    triggers.extend(task.allowed_failure_classes)
    return tuple(dict.fromkeys(triggers))


def _task_tokens(task: TaskSpec) -> frozenset[str]:
    raw = f"{task.goal} {task.question} {' '.join(task.acceptance_criteria)}"
    tokens = {token for token in _split_identifier(raw) if len(token) >= 3}
    return frozenset(tokens)


def _path_matches_tokens(path_value: str, tokens: frozenset[str]) -> bool:
    if not tokens:
        return False
    path = Path(path_value)
    parts = [path.name, path.stem]
    path_tokens = {token for part in parts for token in _split_identifier(part)}
    return bool(path_tokens & tokens)


def _split_identifier(value: str) -> tuple[str, ...]:
    normalized = "".join(char.lower() if char.isalnum() else " " for char in value)
    return tuple(part for part in normalized.split() if part)


def _estimate_tokens(values: tuple[str, ...]) -> int:
    text = "\n".join(values)
    if not text.strip():
        return 0
    try:
        from claude_bridge.smart import estimate_token_count

        return estimate_token_count(text)
    except Exception:
        return max(1, (len(text) + 3) // 4)


def _brief_id(
    *,
    task_id: str,
    agent_name: str,
    context_manifest_id: str,
    objective: str,
    question: str,
    allowed_scope: tuple[str, ...],
    expected_artifacts: tuple[str, ...],
) -> str:
    raw = json.dumps(
        {
            "task_id": task_id,
            "agent_name": agent_name,
            "context_manifest_id": context_manifest_id,
            "objective": objective,
            "question": question,
            "allowed_scope": list(allowed_scope),
            "expected_artifacts": list(expected_artifacts),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "brief_" + sha256(raw.encode("utf-8")).hexdigest()[:16]
