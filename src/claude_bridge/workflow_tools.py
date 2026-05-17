"""Backward-compatible re-export wrapper for workflow sub-modules."""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

from claude_bridge.workflow_agent_loop import (
    build_agent_loop_execution_plan,
    build_agent_loop_session_summary,
    compact_agent_loop_result,
    compact_agent_loop_session_results,
    run_agent_loop_session,
    run_agent_loop_step,
)
from claude_bridge.workflow_cache import (
    _CONTEXT_PACK_CACHE,
    _WORKFLOW_PLAN_CACHE,
)
from claude_bridge.workflow_context import build_context_pack
from claude_bridge.workflow_project import (
    build_validation_suggestions,
    detect_project_type,
    suggest_validation_commands,
    supplemental_review_targets,
)
from claude_bridge.workflow_runner import (
    build_prompt_catalog_payload,
    run_workflow,
)

__all__ = [
    "_CONTEXT_PACK_CACHE",
    "_WORKFLOW_PLAN_CACHE",
    "build_agent_loop_execution_plan",
    "build_agent_loop_session_summary",
    "build_context_pack",
    "build_prompt_catalog_payload",
    "build_validation_suggestions",
    "compact_agent_loop_result",
    "compact_agent_loop_session_results",
    "detect_project_type",
    "run_agent_loop_session",
    "run_agent_loop_step",
    "run_workflow",
    "suggest_validation_commands",
    "supplemental_review_targets",
]
