"""Tests for AI council sessions."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json

from claude_bridge.ai_router import AIModelRouter
from claude_bridge.council import assign_council_agents, run_council_session


def test_assign_council_agents_bounds_count() -> None:
    agents = assign_council_agents("implement a feature", agent_count=99)

    assert len(agents) == 8
    assert agents[0].role == "architect"


def test_council_prioritizes_security_role_for_secret_tasks() -> None:
    agents = assign_council_agents("add provider API key routing security", agent_count=3)

    assert agents[0].role == "security_reviewer"


def test_run_council_session_returns_steps_json() -> None:
    router = AIModelRouter(enabled=False)

    result = run_council_session(
        task="add AI routing",
        target="src/",
        agent_count=3,
        rounds=1,
        router=router,
    )

    assert result["ok"] is True
    details = result["details"]
    assert details["schema_version"] == "ai_council_session.v1"
    assert len(details["agents"]) == 3
    assert details["debate"][0]["responses"][0]["route"]["profile"] == "local"
    steps = json.loads(details["steps_json"])
    assert steps[0]["action"].startswith("Inspect src/")
