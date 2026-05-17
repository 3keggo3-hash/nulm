"""Skills package for Claude Bridge skill system.

Skill directory: .claude-bridge/skills/
Format: skill_name.v1.json (metadata) + skill_name.py (code)
"""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

from claude_bridge.skill_executor import SkillExecutor, SkillResult, get_executor
from claude_bridge.skill_registry import LoadedSkill, SkillRegistry, get_registry
from claude_bridge.skill_schema import (
    SkillConfig,
    SkillMeta,
    create_skill_json,
    get_current_timestamp,
    load_skill_json,
    save_skill_json,
    validate_skill_json,
)

__all__ = [
    "SkillMeta",
    "SkillConfig",
    "SkillRegistry",
    "LoadedSkill",
    "SkillExecutor",
    "SkillResult",
    "get_registry",
    "get_executor",
    "validate_skill_json",
    "load_skill_json",
    "save_skill_json",
    "create_skill_json",
    "get_current_timestamp",
]
