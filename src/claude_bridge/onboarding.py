"""Lightweight first-run onboarding hints for Claude Bridge."""

from __future__ import annotations

import json
import threading
from typing import Any

_ONBOARDING_LOCK = threading.RLock()
_ONBOARDING_STATE = {
    "tool_calls": 0,
    "messages_shown": 0,
}
_ONBOARDING_TRIGGER_CALLS = {1, 3, 6}
_ONBOARDING_MAX_TOOL_CALLS = 10
_ONBOARDING_MAX_MESSAGES = 3
_IGNORED_TOOLS = {"get_recent_tool_calls", "get_config", "set_config_value"}


def reset_onboarding_state() -> None:
    with _ONBOARDING_LOCK:
        _ONBOARDING_STATE["tool_calls"] = 0
        _ONBOARDING_STATE["messages_shown"] = 0


def _tips_for_call(call_number: int) -> dict[str, Any]:
    if call_number <= 1:
        return {
            "title": "Start With Structure",
            "message": "Use list_directory or workspace_status first when you need to orient yourself before reading files.",
            "quick_command": "claude-bridge doctor --project-dir .",
            "suggested_tools": ["list_directory", "workspace_status"],
        }
    if call_number <= 3:
        return {
            "title": "Narrow Context Early",
            "message": "Use find_relevant_files or read_multiple_files to compare a few strong candidates instead of reading many files one by one.",
            "suggested_tools": ["find_relevant_files", "read_multiple_files"],
        }
    return {
        "title": "Edit In Small Steps",
        "message": "Preview risky edits, prefer patch_file for existing files, and run validation commands before concluding the task is done.",
        "quick_command": "ruff check . && black --check .",
        "suggested_tools": ["preview_patch", "patch_file", "suggest_validation_commands"],
    }


def apply_onboarding(tool_name: str, result: str, *, enabled: bool) -> str:
    with _ONBOARDING_LOCK:
        _ONBOARDING_STATE["tool_calls"] += 1
        call_number = int(_ONBOARDING_STATE["tool_calls"])
        messages_shown = int(_ONBOARDING_STATE["messages_shown"])

        should_attach = (
            enabled
            and tool_name not in _IGNORED_TOOLS
            and call_number in _ONBOARDING_TRIGGER_CALLS
            and call_number <= _ONBOARDING_MAX_TOOL_CALLS
            and messages_shown < _ONBOARDING_MAX_MESSAGES
        )
        if should_attach:
            _ONBOARDING_STATE["messages_shown"] += 1

    if not should_attach:
        return result

    try:
        payload = json.loads(result)
    except json.JSONDecodeError:
        return result
    if not isinstance(payload, dict):
        return result

    details = payload.get("details")
    if not isinstance(details, dict):
        details = {}
        payload["details"] = details

    hint = _tips_for_call(call_number)
    hint["tool_calls_seen"] = call_number
    hint["remaining_before_auto_hide"] = max(0, _ONBOARDING_MAX_TOOL_CALLS - call_number)
    hint["dismiss_hint"] = (
        'Disable later with set_config_value(key="onboarding_enabled", value=false).'
    )
    details["onboarding"] = hint
    return json.dumps(payload, ensure_ascii=False)
