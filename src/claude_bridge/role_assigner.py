"""Role assignment system for agents and skills.

Provides automatic role assignment based on context keywords and
performance metrics to determine appropriate roles and approval requirements.
"""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ROLE_DEFINITIONS = {
    "architect": {
        "keywords": ["design", "plan", "structure", "architect", "architecture", "blueprint"],
        "risk": "low",
    },
    "implementer": {
        "keywords": ["write", "create", "build", "implement", "develop", "add", "new"],
        "risk": "medium",
    },
    "test_strategist": {
        "keywords": ["test", "verify", "validate", "coverage", "pytest", "testing", "quality"],
        "risk": "low",
    },
    "security_reviewer": {
        "keywords": [
            "security",
            "vulnerability",
            "auth",
            "permission",
            "secret",
            "password",
            "token",
        ],
        "risk": "low",
    },
    "executor": {
        "keywords": ["run", "execute", "terminal", "script", "shell", "bash", "sudo", "deploy"],
        "risk": "high",
    },
    "docs_reviewer": {
        "keywords": ["readme", "document", "comment", "explain", "readme", "docs", "documentation"],
        "risk": "low",
    },
    "refactor_agent": {
        "keywords": ["refactor", "clean", "optimize", "improve", "restructure", "cleanup"],
        "risk": "medium",
    },
    "observer": {
        "keywords": [],
        "risk": "low",
    },
}


@dataclass(frozen=True)
class RoleAssignment:
    role: str
    confidence: float
    reason: str
    requires_approval: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "requires_approval": self.requires_approval,
        }


def _score_keyword_match(context: str, keywords: list[str]) -> float:
    context_lower = context.lower()
    matched = sum(1 for kw in keywords if kw.lower() in context_lower)
    if not keywords:
        return 0.0
    return matched / len(keywords)


def _calculate_approval_required(role: str) -> bool:
    role_def = ROLE_DEFINITIONS.get(role, {})
    return role_def.get("risk", "low") == "high"


class RoleAssigner:
    def __init__(self, role_definitions: dict[str, dict[str, Any]] | None = None) -> None:
        self._role_definitions = role_definitions or ROLE_DEFINITIONS

    def assign_role(
        self, entity_name: str, context: str, metrics: dict[str, Any]
    ) -> RoleAssignment:
        scores: list[tuple[float, str]] = []

        for role, definition in self._role_definitions.items():
            raw_keywords = definition.get("keywords", [])
            keywords = [str(keyword) for keyword in raw_keywords] if raw_keywords else []
            keyword_score = _score_keyword_match(context, keywords)
            scores.append((keyword_score, role))

        scores.sort(reverse=True)

        best_score, best_role = scores[0] if scores else (0.0, "observer")

        hit_count = metrics.get("hit_count", 0)
        acceptance_rate = metrics.get("acceptance_rate", 0.0)

        if hit_count > 0 and best_score > 0:
            boost = min(acceptance_rate * 0.2, 0.3)
            best_score = min(best_score + boost, 1.0)

        confidence = best_score if best_score > 0 else 0.5

        if best_role == "observer":
            confidence = 0.3

        requires_approval = _calculate_approval_required(best_role)

        if acceptance_rate > 0.85 and hit_count >= 5:
            confidence = max(confidence, 0.9)

        matched_keywords = [
            kw
            for kw in [
                str(keyword)
                for keyword in self._role_definitions.get(best_role, {}).get("keywords", [])
            ]
            if kw.lower() in context.lower()
        ]
        reason = (
            f"matched: {', '.join(matched_keywords) if matched_keywords else 'default fallback'}"
        )

        return RoleAssignment(
            role=best_role,
            confidence=confidence,
            reason=reason,
            requires_approval=requires_approval,
        )

    def assign_bulk(
        self,
        entities: list[dict[str, Any]],
        context: str,
    ) -> list[RoleAssignment]:
        return [
            self.assign_role(
                entity_name=entity.get("name", ""),
                context=context,
                metrics=entity.get("metrics", {}),
            )
            for entity in entities
        ]


def assign_council_agents(
    task: str, *, agent_count: int, profile: str = "auto"
) -> list[dict[str, str]]:
    """Legacy wrapper for backward compatibility with council.py."""
    from claude_bridge.council import assign_council_agents as _original_assign

    agents = _original_assign(task, agent_count=agent_count, profile=profile)
    return [agent.to_dict() for agent in agents]
