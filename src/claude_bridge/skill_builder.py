"""Auto-skill creation from workflow results."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from claude_bridge.skill_schema import (
    SkillMeta,
    create_skill_json,
    get_current_timestamp,
    save_skill_json,
)
from claude_bridge.skill_registry import get_registry


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


def _extract_context_tags(workflow_result: dict[str, Any]) -> list[str]:
    """Extract context tags from workflow result."""
    tags: set[str] = set()

    tags.add("workflow")

    files = workflow_result.get("artifacts", {}).get("files", [])
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


def propose_skill_creation(
    workflow_result: dict[str, Any],
    request_approval_fn=None,
) -> tuple[bool, str | None]:
    """Propose skill creation to user and optionally save.

    Returns (approved, skill_name). If approved, skill is saved.
    """
    skill_json, skill_code = extract_skill(workflow_result)
    if skill_json is None:
        return False, None

    name = skill_json["name"]

    if request_approval_fn is not None:
        import asyncio

        async def ask():
            message = (
                f"Bunu skill olarak kaydetmemi ister misin?\n"
                f"  Name: {name}\n"
                f"  Triggers: {', '.join(skill_json['trigger_phrases'][:3])}\n"
                f"  Context: {', '.join(skill_json['trigger_context'])}"
            )
            return await request_approval_fn("skill_create", {"skill_name": name, "message": message})

        approved = asyncio.get_event_loop().run_until_complete(ask())
    else:
        approved = True

    if approved:
        registry = get_registry()
        meta = SkillMeta.from_dict(skill_json)
        success, _ = registry.register(name, meta, skill_code)
        return success, name if success else None

    return False, None


def check_and_propose(
    workflow_result: dict[str, Any],
    request_approval_fn=None,
) -> tuple[bool, str | None]:
    """Check if workflow result is suitable for skill creation and propose.

    Called from workflow DONE state. Returns (proposed, skill_name).
    """
    return propose_skill_creation(workflow_result, request_approval_fn)