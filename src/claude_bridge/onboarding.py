"""Lightweight first-run onboarding hints for Claude Bridge.

Only shown once per session on the FIRST tool call to help users discover
available capabilities. Never shown again after dismissal.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

_ONBOARDING_LOCK = threading.RLock()
_ONBOARDING_SHOWN_KEY = "onboarding_shown"
_ONBOARDING_SHOWN_IN_MEMORY = False


def reset_onboarding_state() -> None:
    """Reset onboarding state - called when user dismisses or on new session."""
    global _ONBOARDING_SHOWN_IN_MEMORY
    _ONBOARDING_SHOWN_IN_MEMORY = False
    config_path = Path.home() / ".claude-bridge" / "config.json"
    if config_path.exists():
        try:
            content = json.loads(config_path.read_text())
            content.pop(_ONBOARDING_SHOWN_KEY, None)
            config_path.write_text(json.dumps(content, indent=2))
        except (OSError, json.JSONDecodeError):
            pass


def _is_onboarding_enabled() -> bool:
    try:
        from claude_bridge.config import get_config_value

        val = get_config_value("onboarding_enabled")
        if val is not None:
            return bool(val)
    except Exception:
        pass
    return True


def _mark_onboarding_shown() -> None:
    global _ONBOARDING_SHOWN_IN_MEMORY
    _ONBOARDING_SHOWN_IN_MEMORY = True
    config_path = Path.home() / ".claude-bridge" / "config.json"
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    content = {}
    if config_path.exists():
        try:
            content = json.loads(config_path.read_text())
        except (OSError, json.JSONDecodeError):
            pass
    content[_ONBOARDING_SHOWN_KEY] = True
    try:
        config_path.write_text(json.dumps(content, indent=2))
    except OSError:
        return


def _was_onboarding_shown() -> bool:
    if _ONBOARDING_SHOWN_IN_MEMORY:
        return True
    config_path = Path.home() / ".claude-bridge" / "config.json"
    if not config_path.exists():
        return False
    try:
        content = json.loads(config_path.read_text())
        return bool(content.get(_ONBOARDING_SHOWN_KEY, False))
    except (OSError, json.JSONDecodeError):
        return False


def apply_onboarding(tool_name: str, result: str, *, enabled: bool) -> str:
    """Attach a one-time first-run hint on the very first tool call only.

    Never again after the first call, regardless of message count.
    """
    with _ONBOARDING_LOCK:
        if _was_onboarding_shown() or not enabled or not _is_onboarding_enabled():
            return result

        _mark_onboarding_shown()

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

    hint = {
        "title": "Getting Started",
        "message": "Run  claude-bridge doctor --project-dir .  to check setup, "
        "or  claude-bridge anomaly --help  to review logs.",
        "dismiss": "This hint will not repeat.",
    }
    details["onboarding"] = hint
    return json.dumps(payload, ensure_ascii=False)
