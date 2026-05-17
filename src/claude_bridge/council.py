"""AI council session planning and consensus synthesis."""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from claude_bridge.ai_router import AIModelResponse, AIModelRouter

_MIN_AGENTS = 2
_MAX_AGENTS = 8
_MIN_ROUNDS = 1
_MAX_ROUNDS = 3


@dataclass(frozen=True)
class CouncilAgent:
    """Role assigned to a council participant."""

    name: str
    role: str
    expertise: str
    profile: str = "auto"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "expertise": self.expertise,
            "profile": self.profile,
        }


_ROLE_POOL: tuple[tuple[str, str], ...] = (
    ("architect", "architecture, module boundaries, and integration risk"),
    ("implementer", "minimal implementation path and code ownership"),
    ("test_strategist", "regression tests, validation commands, and failure modes"),
    ("security_reviewer", "secrets, path boundaries, approvals, and unsafe execution"),
    ("maintainer", "scope control, docs impact, and long-term maintainability"),
    ("performance_reviewer", "latency, parallelism, caching, and cost"),
    ("product_reviewer", "user workflow, defaults, and ergonomics"),
    ("docs_reviewer", "configuration docs, examples, and migration notes"),
)


def assign_council_agents(
    task: str, *, agent_count: int, profile: str = "auto"
) -> list[CouncilAgent]:
    """Assign deterministic council roles for a task."""
    count = _clamp(agent_count, _MIN_AGENTS, _MAX_AGENTS)
    task_lower = task.lower()
    roles = list(_ROLE_POOL)
    if any(word in task_lower for word in ("security", "secret", "approval", "shell")):
        roles.insert(0, roles.pop(3))
    if any(word in task_lower for word in ("test", "validation", "pytest", "ci")):
        roles.insert(0, roles.pop(2))
    return [
        CouncilAgent(
            name=f"{role}_agent",
            role=role,
            expertise=expertise,
            profile=profile,
        )
        for role, expertise in roles[:count]
    ]


def run_council_session(
    *,
    task: str,
    target: str = ".",
    agent_count: int = 5,
    rounds: int = 2,
    model_profile: str = "auto",
    language: str = "Turkish",
    router: AIModelRouter,
) -> dict[str, Any]:
    """Run a bounded read-only council and return a consensus implementation plan."""
    if not task.strip():
        return {"ok": False, "message": "task must not be empty", "code": "invalid_task"}

    resolved_rounds = _clamp(rounds, _MIN_ROUNDS, _MAX_ROUNDS)
    agents = assign_council_agents(task, agent_count=agent_count, profile=model_profile)
    first_round = [
        _ask_agent(
            router,
            agent,
            task=task,
            target=target,
            language=language,
            round_index=1,
            prior_findings=[],
        )
        for agent in agents
    ]
    debate_rounds: list[dict[str, Any]] = [{"round": 1, "responses": first_round}]
    prior_findings = [item["text"] for item in first_round if item.get("text")]
    for round_index in range(2, resolved_rounds + 1):
        responses = [
            _ask_agent(
                router,
                agent,
                task=task,
                target=target,
                language=language,
                round_index=round_index,
                prior_findings=prior_findings,
            )
            for agent in agents
        ]
        debate_rounds.append({"round": round_index, "responses": responses})
        prior_findings.extend(item["text"] for item in responses if item.get("text"))

    consensus = _synthesize_consensus(
        router,
        task=task,
        target=target,
        language=language,
        agents=agents,
        findings=prior_findings,
        model_profile=model_profile,
    )
    steps = _plan_steps(task, target)
    return {
        "ok": True,
        "message": "Council session completed",
        "details": {
            "schema_version": "ai_council_session.v1",
            "task": task,
            "target": target,
            "agent_count": len(agents),
            "rounds": resolved_rounds,
            "agents": [agent.to_dict() for agent in agents],
            "debate": debate_rounds,
            "consensus": consensus["text"],
            "consensus_route": consensus["route"],
            "dissent": _extract_dissent(prior_findings),
            "risks": _risk_list(task),
            "validation_plan": _validation_plan(target),
            "steps": steps,
            "steps_json": json.dumps(steps),
            "execution_boundary": (
                "This council is read-only. Apply steps through create_plan/execute_step "
                "or existing approval-gated tools."
            ),
        },
    }


def _ask_agent(
    router: AIModelRouter,
    agent: CouncilAgent,
    *,
    task: str,
    target: str,
    language: str,
    round_index: int,
    prior_findings: list[str],
) -> dict[str, Any]:
    prior = "\n".join(f"- {item[:300]}" for item in prior_findings[-6:])
    prompt = (
        f"Council task: {task}\n"
        f"Target: {target}\n"
        f"Role: {agent.role}\n"
        f"Expertise: {agent.expertise}\n"
        f"Round: {round_index}\n"
        f"Prior findings:\n{prior or '- none'}\n"
        f"Respond in {language}. Give concise findings, risks, and concrete next steps."
    )
    response = router.generate_text(
        prompt,
        task=task,
        context={"role": agent.role, "target": target},
        profile_name=agent.profile,
        max_tokens=500,
    )
    return _response_payload(agent, response)


def _synthesize_consensus(
    router: AIModelRouter,
    *,
    task: str,
    target: str,
    language: str,
    agents: list[CouncilAgent],
    findings: list[str],
    model_profile: str,
) -> dict[str, Any]:
    findings_text = "\n".join(f"- {item[:400]}" for item in findings[-12:])
    roles = ", ".join(agent.role for agent in agents)
    prompt = (
        f"Synthesize consensus for this AI council.\nTask: {task}\nTarget: {target}\n"
        f"Roles: {roles}\nFindings:\n{findings_text}\n"
        f"Respond in {language}. Return the agreed plan, dissent, risks, and validation."
    )
    response = router.generate_text(
        prompt,
        task=task,
        context={"role": "chair", "target": target, "task_type": "council_consensus"},
        profile_name=model_profile,
        max_tokens=800,
    )
    if not response.text.strip():
        text = _fallback_consensus(task, target)
    else:
        text = response.text.strip()
    return {"text": text, "route": response.decision.to_dict()}


def _response_payload(agent: CouncilAgent, response: AIModelResponse) -> dict[str, Any]:
    return {
        "agent": agent.to_dict(),
        "ok": response.ok,
        "text": response.text,
        "route": response.decision.to_dict(),
        "duration_ms": round(response.duration_ms, 3),
        "error": response.error,
    }


def _plan_steps(task: str, target: str) -> list[dict[str, Any]]:
    return [
        {
            "action": f"Inspect {target} and identify the smallest affected areas for: {task}",
            "files_affected": [target],
            "risk_score": 10,
            "rollback_plan": "No changes made in inspection step.",
        },
        {
            "action": "Implement the agreed minimal slice behind existing policy and approvals.",
            "files_affected": [target],
            "risk_score": 35,
            "rollback_plan": "Revert the focused implementation changes via git.",
        },
        {
            "action": "Run focused validation and summarize council decision, changes, and risks.",
            "files_affected": [],
            "risk_score": 15,
            "rollback_plan": "Fix validation failures or revert the implementation slice.",
        },
    ]


def _risk_list(task: str) -> list[str]:
    risks = ["Council output is advisory until implemented through approval-gated tools."]
    task_lower = task.lower()
    if any(word in task_lower for word in ("key", "secret", "provider", "api")):
        risks.append("Keep provider secrets in environment variables and redact config output.")
    if any(word in task_lower for word in ("shell", "execute", "auto")):
        risks.append("Do not bypass shell safety, destructive command blocks, or approval gates.")
    return risks


def _validation_plan(target: str) -> list[str]:
    commands = ["pytest"]
    if target not in {".", ""}:
        commands.insert(0, f"pytest {target}")
    commands.extend(["ruff check .", "mypy src"])
    return commands


def _extract_dissent(findings: list[str]) -> list[str]:
    dissent: list[str] = []
    for finding in findings:
        lowered = finding.lower()
        if any(word in lowered for word in ("risk", "concern", "dissent", "caution")):
            dissent.append(finding[:300])
    return dissent[:5]


def _fallback_consensus(task: str, target: str) -> str:
    return (
        f"Consensus for {task}: inspect {target}, keep the implementation small, preserve "
        "existing security and approval boundaries, then validate with focused tests."
    )


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))
