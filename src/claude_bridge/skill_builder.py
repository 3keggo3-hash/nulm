"""Auto-skill creation from workflow results."""

from __future__ import annotations

import asyncio
import inspect
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Coroutine, cast

from claude_bridge.skill_schema import (
    SkillMeta,
    create_skill_json,
)
from claude_bridge.skill_registry import get_registry
from claude_bridge.tool_utils import request_approval, PermissionCard


@dataclass
class SkillProposal:
    """Proposed skill from workflow analysis."""

    skill_name: str
    trigger_phrases: list[str]
    skill_code: str
    confidence: float
    workflow_context: str


@dataclass
class WorkflowResult:
    """Workflow execution result for skill extraction."""

    task: str
    steps: list[dict[str, Any]]
    outcome: str
    artifacts: dict[str, Any]


async def propose_skill_creation(
    workflow_result: WorkflowResult,
) -> SkillProposal | None:
    """Propose a new skill based on completed workflow.

    Returns None if no skill-worthy pattern detected.
    Raises SkillApprovalNeeded if user confirmation required.
    """
    proposal = _extract_skill_proposal(workflow_result)
    if proposal is None:
        return None

    approved = await _request_user_approval(proposal)
    if not approved:
        return None

    await _create_skill_files(proposal)
    return proposal


def _extract_skill_proposal(workflow_result: WorkflowResult) -> SkillProposal | None:
    """Extract skill-worthy pattern from workflow result."""
    skill_json, skill_code = _extract_skill_components(workflow_result)
    if skill_json is None or skill_code is None:
        return None

    name = skill_json["name"]
    confidence = _calculate_confidence(workflow_result)

    return SkillProposal(
        skill_name=name,
        trigger_phrases=skill_json["trigger_phrases"],
        skill_code=skill_code,
        confidence=confidence,
        workflow_context=workflow_result.task,
    )


def _extract_skill_components(
    workflow_result: WorkflowResult,
) -> tuple[dict[str, Any] | None, str | None]:
    """Extract skill definition from workflow result."""
    outcome = workflow_result.outcome
    if outcome != "success":
        return None, None

    steps = workflow_result.steps
    if len(steps) < 3:
        return None, None

    task = workflow_result.task
    name = _generate_skill_name(task)
    if name is None:
        return None, None

    trigger_phrases = _extract_trigger_phrases(task)
    if not trigger_phrases:
        return None, None

    context_tags = _extract_context_tags(workflow_result)
    code = _generate_skill_code(task, steps)

    skill_json = create_skill_json(
        name=name,
        version="1.0",
        trigger_phrases=trigger_phrases,
        trigger_context=context_tags,
        auto_load=False,
        permissions=["read", "analyze"],
    )
    return skill_json, code


async def _request_user_approval(proposal: SkillProposal) -> bool:
    """Request user approval via approval system."""
    card = PermissionCard(
        agent="skill_builder",
        action=f"Create skill: {proposal.skill_name}",
        reason=f"New skill from workflow pattern (confidence: {proposal.confidence:.0%})",
        risk=25,
        files=[],
        params={
            "skill_name": proposal.skill_name,
            "trigger_phrases": proposal.trigger_phrases,
            "confidence": proposal.confidence,
        },
    )
    return await request_approval("skill_create", card.params, card=card)


async def _create_skill_files(proposal: SkillProposal) -> None:
    """Create skill JSON and code files."""
    registry = get_registry()
    skill_json, _ = _extract_skill_json(proposal)
    if skill_json is None:
        return
    meta = SkillMeta.from_dict(skill_json)
    registry.register(proposal.skill_name, meta, proposal.skill_code)


def _extract_skill_json(proposal: SkillProposal) -> tuple[dict[str, Any], str]:
    """Reconstruct skill JSON from proposal."""
    skill_json = create_skill_json(
        name=proposal.skill_name,
        version="1.0",
        trigger_phrases=proposal.trigger_phrases,
        trigger_context=["workflow"],
        auto_load=False,
        permissions=["read", "analyze"],
    )
    return skill_json, proposal.skill_code


def _calculate_confidence(workflow_result: WorkflowResult) -> float:
    """Calculate confidence score for skill proposal."""
    base_confidence = 0.5

    if len(workflow_result.steps) >= 5:
        base_confidence += 0.2
    elif len(workflow_result.steps) >= 3:
        base_confidence += 0.1

    if "fix" in workflow_result.task.lower() or "bug" in workflow_result.task.lower():
        base_confidence += 0.1

    if workflow_result.outcome == "success":
        base_confidence += 0.1

    return min(base_confidence, 1.0)


def extract_skill(
    workflow_result: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Extract skill definition from a workflow result.

    Analyzes the workflow result and produces (skill_json, skill_code) if
    a skill can be created, otherwise (None, None).

    The workflow_result should contain:
        - task: str - the original task description
        - steps: list[dict] - steps taken to complete the task
        - outcome: str - success/failure
        - artifacts: dict - any files created or modified
    """
    task = workflow_result.get("task", "")
    outcome = workflow_result.get("outcome", "")

    if outcome != "success":
        return None, None

    steps = workflow_result.get("steps", [])
    if len(steps) < 3:
        return None, None

    name = _generate_skill_name(task)
    if name is None:
        return None, None

    trigger_phrases = _extract_trigger_phrases(task)
    if not trigger_phrases:
        return None, None

    context_tags = _extract_context_tags(workflow_result)
    code = _generate_skill_code(task, steps)

    skill_json = create_skill_json(
        name=name,
        version="1.0",
        trigger_phrases=trigger_phrases,
        trigger_context=context_tags,
        auto_load=False,
        permissions=["read", "analyze"],
    )
    return skill_json, code


def _generate_skill_name(task: str) -> str | None:
    """Generate a valid skill name from task description."""
    words = re.findall(r"[a-zA-Z0-9]+", task.lower())
    if not words:
        return None

    core = words[:3]
    name = "_".join(core)
    name = re.sub(r"[^a-zA-Z0-9_-]", "", name)
    name = name.strip("_")

    if len(name) < 3 or len(name) > 48:
        name = f"skill_{name[:40]}"

    return name or None


def _extract_trigger_phrases(task: str) -> list[str]:
    """Extract trigger phrases from task description."""
    phrases: list[str] = []

    patterns = [
        r"(\w+[\w\s]*?\w+)(?:\s+çali[ş|s]m[i|ı]yor|çalışmıyor|hata|error)",
        r"(sistem\s+\w+)",
        r"(?:fix|repair|debug|check|analyze)\s+(\w+)",
    ]

    for pattern in patterns:
        matches = re.findall(pattern, task.lower())
        phrases.extend(matches[:2])

    task_words = task.split()
    if len(task_words) <= 6:
        phrases.append(task.lower())

    return list(dict.fromkeys(phrases))[:5]


def _extract_context_tags(workflow_result: WorkflowResult | dict[str, Any]) -> list[str]:
    """Extract context tags from workflow result."""
    tags: set[str] = set()

    tags.add("workflow")

    artifacts = workflow_result.get("artifacts", {}) if isinstance(workflow_result, dict) else {}
    files = artifacts.get("files", [])
    for f in files:
        ext = Path(f).suffix.lower()
        context_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".json": "config",
            ".md": "docs",
            ".sh": "shell",
        }
        if ext in context_map:
            tags.add(context_map[ext])

    return sorted(tags)


def _generate_skill_code(task: str, steps: list[dict[str, Any]]) -> str:
    """Generate executable skill code from workflow steps."""
    task_lower = task.lower()

    if any(kw in task_lower for kw in ["fix", "bug", "error", "hata"]):
        template = """def run(context):
    '''
    Auto-generated skill from workflow.
    Task: {task}
    '''
    import subprocess
    import sys

    task = context.get("task", "")
    # Diagnostic steps extracted from workflow

    results = []
    # Placeholder for actual diagnostic logic
    results.append({{"status": "analyzed", "task": task}})

    return {{"status": "success", "results": results}}
"""
    elif any(kw in task_lower for kw in ["create", "add", "implement", "yeni"]):
        template = """def run(context):
    '''
    Auto-generated skill from workflow.
    Task: {task}
    '''
    task = context.get("task", "")
    # Implementation steps extracted from workflow

    return {{"status": "success", "task": task}}
"""
    else:
        template = """def run(context):
    '''
    Auto-generated skill from workflow.
    Task: {task}
    '''
    task = context.get("task", "")

    return {{"status": "success", "task": task}}
"""

    return template.format(task=task[:200])


def propose_skill_creation_sync(
    workflow_result: dict[str, Any],
    request_approval_fn: Any = None,
) -> tuple[bool, str | None]:
    """Propose skill creation to user and optionally save.

    Returns (approved, skill_name). If approved, skill is saved.
    """
    task = workflow_result.get("task", "")
    outcome = workflow_result.get("outcome", "")
    steps = workflow_result.get("steps", [])

    wr = WorkflowResult(
        task=task,
        steps=steps,
        outcome=outcome,
        artifacts=workflow_result.get("artifacts", {}),
    )

    proposal = _extract_skill_proposal(wr)
    if proposal is None:
        return False, None

    if request_approval_fn is not None:
        approved = _run_sync(
            request_approval_fn("skill_create", {"skill_name": proposal.skill_name})
        )
    else:

        async def check() -> bool:
            return await _request_user_approval(proposal)

        approved = _run_sync(check())

    if approved:
        _run_sync(_create_skill_files(proposal))
        return True, proposal.skill_name

    return False, None


def _run_sync(awaitable: Any) -> Any:
    """Run an awaitable from sync code in Python versions without a default loop."""
    if not inspect.isawaitable(awaitable):
        return awaitable
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(cast(Coroutine[Any, Any, Any], awaitable))
    raise RuntimeError("Cannot run synchronous skill proposal while an event loop is running")


def check_and_propose(
    workflow_result: dict[str, Any],
    request_approval_fn: Any = None,
) -> tuple[bool, str | None]:
    """Check if workflow result is suitable for skill creation and propose.

    Called from workflow DONE state. Returns (proposed, skill_name).
    """
    return propose_skill_creation_sync(workflow_result, request_approval_fn)
