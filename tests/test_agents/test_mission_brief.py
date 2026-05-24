"""Tests for deterministic mission brief construction."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

import asyncio
from typing import Any

from claude_bridge.agents.base import BaseAgent
from claude_bridge.agents.context_manifest import build_context_manifest
from claude_bridge.agents.contracts import TaskPermissions, TaskSpec
from claude_bridge.agents.dispatcher import TaskDispatcher
from claude_bridge.agents.mission_brief import ContextCurator, MissionBrief
from claude_bridge.agents.result import AgentResult, AgentStatus


class BriefInspectAgent(BaseAgent):
    async def execute(self, task: str, context: dict[str, Any]) -> AgentResult:
        brief = context["mission_brief"]
        assert isinstance(brief, MissionBrief)
        assert context["mission_brief_id"] == brief.brief_id
        return AgentResult.success(
            findings=[brief.objective],
            artifacts={"brief_id": brief.brief_id},
            agent_name=self.name,
        )


def test_context_curator_filters_irrelevant_manifest_context(tmp_path) -> None:
    auth_file = tmp_path / "auth_login.py"
    notes_file = tmp_path / "billing_notes.md"
    auth_file.write_text("def login():\n    return True\n", encoding="utf-8")
    notes_file.write_text("billing notes\n", encoding="utf-8")
    task = TaskSpec(
        task_id="brief_filter",
        kind="research",
        goal="inspect auth login behavior",
        agent_name="research_agent",
        question="What does auth login do?",
        acceptance_criteria=("cite auth behavior",),
        expected_artifacts=("findings",),
    )
    manifest = build_context_manifest(
        task=task,
        run_id="run_1",
        session_id="session_1",
        context={"selected_files": [str(auth_file), str(notes_file)]},
    )

    brief = ContextCurator().curate(task, manifest)

    assert brief.context_manifest_id == manifest.manifest_id
    assert brief.objective == task.goal
    assert brief.question == task.question
    assert brief.allowed_scope == (str(auth_file),)
    assert str(notes_file) not in brief.allowed_scope
    assert task.read_set == ()
    assert task.write_set == ()
    assert task.permissions == TaskPermissions()


def test_context_curator_keeps_task_read_set_unchanged(tmp_path) -> None:
    target = tmp_path / "target.py"
    extra = tmp_path / "extra.py"
    target.write_text("target = True\n", encoding="utf-8")
    extra.write_text("extra = True\n", encoding="utf-8")
    task = TaskSpec(
        task_id="read_set",
        kind="research",
        goal="inspect target",
        agent_name="research_agent",
        read_set=(str(target),),
    )
    manifest = build_context_manifest(
        task=task,
        run_id="run_1",
        session_id="session_1",
        context={"selected_files": [str(target), str(extra)]},
    )

    brief = ContextCurator().curate(task, manifest)

    assert brief.allowed_scope == (str(target),)
    assert task.read_set == (str(target),)


def test_context_curator_ignores_parent_directory_token_matches(tmp_path) -> None:
    auth_dir = tmp_path / "auth"
    auth_dir.mkdir()
    unrelated = auth_dir / "billing_notes.md"
    unrelated.write_text("billing notes\n", encoding="utf-8")
    task = TaskSpec(
        task_id="basename_filter",
        kind="research",
        goal="inspect auth login behavior",
        agent_name="research_agent",
    )
    manifest = build_context_manifest(
        task=task,
        run_id="run_1",
        session_id="session_1",
        context={"selected_files": [str(unrelated)]},
    )

    brief = ContextCurator().curate(task, manifest)

    assert brief.allowed_scope == (str(unrelated),)
    assert (
        brief.omitted_context_reason
        == "no deterministic relevance signal; kept manifest-selected context"
    )


def test_dispatcher_includes_mission_brief_and_run_record_id() -> None:
    dispatcher = TaskDispatcher()
    agent = BriefInspectAgent("research_agent")
    task = TaskSpec(
        task_id="dispatch_brief",
        kind="research",
        goal="inspect dispatcher brief",
        agent_name="research_agent",
    )

    results = asyncio.run(dispatcher.distribute([task], [agent]))
    record = dispatcher.run_records[0]

    assert results[0].status == AgentStatus.SUCCESS
    assert record.context_manifest_id
    assert record.mission_brief_id
    assert results[0].artifacts["brief_id"] == record.mission_brief_id
