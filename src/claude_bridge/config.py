"""Runtime configuration state for Claude Bridge."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Sequence, cast

APPROVAL_PRESETS: dict[str, dict[str, Any]] = {
    "read-only": {
        "auto_approve": False,
        "client_managed_approval": False,
        "description": (
            "Only read-only tools are practical; approval-requiring writes and shell calls "
            "fail closed."
        ),
    },
    "dev-safe": {
        "auto_approve": False,
        "client_managed_approval": True,
        "description": (
            "Recommended daily development mode with client-managed approvals for writes and "
            "shell commands."
        ),
    },
    "ci-like": {
        "auto_approve": False,
        "client_managed_approval": True,
        "description": (
            "Reviewable automation mode with explicit approvals and no blanket auto-approve."
        ),
    },
    "power-user": {
        "auto_approve": True,
        "client_managed_approval": False,
        "description": "Trusted local mode with auto-approve enabled.",
    },
}

BUDGET_PROFILES: dict[str, dict[str, Any]] = {
    "low-cost": {
        "context_budget_tokens": 2000,
        "description": "Aggressive context minimization for lower token usage.",
    },
    "balanced": {
        "context_budget_tokens": 4000,
        "description": "Default balance between context quality and token cost.",
    },
    "deep": {
        "context_budget_tokens": 8000,
        "description": "Higher context budget for more thorough analysis.",
    },
}

TOOL_PROFILES: dict[str, dict[str, Any]] = {
    "essential": {
        "description": (
            "Minimal tool set for lowest token overhead. "
            "Best for free-tier usage where every token counts."
        ),
        "groups": {
            "agent_quality",
            "file_core",
            "shell_core",
            "indexing",
            "workspace",
        },
    },
    "standard": {
        "description": (
            "Commonly used tools without niche features. "
            "Good balance of capability and token cost."
        ),
        "groups": {
            "agent_quality",
            "file_core",
            "shell_core",
            "indexing",
            "workspace",
            "workflow_core",
            "meta_core",
            "smart",
            "insights_core",
        },
    },
    "full": {
        "description": "All available tools. Maximum capability but highest per-turn token cost.",
        "groups": {
            "agent_quality",
            "file_core",
            "shell_core",
            "indexing",
            "workspace",
            "workflow_core",
            "meta_core",
            "meta_agent",
            "smart",
            "insights_core",
            "insights_extra",
            "fun",
            "multi_format",
            "url",
            "git_commit",
        },
    },
}

TOOL_GROUPS: dict[str, set[str]] = {
    "agent_quality": {
        "advise_next_step",
        "improve_request",
        "plan_quality_review",
        "review_result_quality",
        "suggest_bridge_config",
        "apply_bridge_config_change",
    },
    "file_core": {
        "read_file",
        "read_multiple_files",
        "list_directory",
        "write_file",
        "move_file",
        "copy_path",
        "search_in_files",
        "patch_file",
        "preview_patch",
        "undo_last_patch",
    },
    "shell_core": {
        "run_shell",
        "analyze_shell_command",
        "start_process",
        "read_process_output",
        "list_process_sessions",
        "kill_process",
        "interact_with_process",
    },
    "indexing": {
        "index_codebase",
        "find_relevant_files",
    },
    "workspace": {
        "workspace_status",
        "switch_project_root",
    },
    "workflow_core": {
        "build_context_pack",
        "narrow_context",
        "suggest_validation_commands",
        "run_workflow",
        "run_agent_loop_step",
        "run_agent_loop_session",
    },
    "meta_core": {
        "bridge_status",
        "get_config",
        "set_config_value",
        "compact_user_intent",
        "tools_overview",
        "get_recent_tool_calls",
        "session_insights",
        "activity_summary",
        "usage_insights",
        "prompt_shortcuts",
        "appeal_decision",
        "send_feedback",
        "anomaly_summary",
        "generate_pr_description",
        "get_trust_score",
        "autocomplete",
    },
    "meta_agent": {
        "create_plan",
        "execute_step",
        "get_plan_status",
        "explore_approaches",
        "execute_approach",
        "compare_approaches",
        "self_critique",
        "create_checkpoint",
        "restore_checkpoint",
        "list_checkpoints",
    },
    "smart": {
        "count_file_tokens",
        "context_fit",
        "smart_status",
    },
    "insights_core": {
        "project_insights",
        "git_insights",
        "git_diff_insights",
    },
    "insights_extra": {
        "todo_scan",
        "recent_files",
        "language_distribution",
        "duplicate_code_scan",
        "dependency_insights",
    },
    "fun": {
        "bridge_doodle",
        "bridge_save_note",
        "bridge_read_notes",
    },
    "multi_format": {
        "read_image",
        "read_pdf",
    },
    "url": {
        "read_url",
    },
    "git_commit": {
        "commit_changes",
    },
}

SAFE_CHAT_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "tool_profile",
        "context_budget_profile",
        "intent_compaction_enabled",
        "ai_evaluator_timeout",
        "onboarding_enabled",
        "shell_timeout",
    }
)

RESTRICTED_CHAT_CONFIG_KEYS: frozenset[str] = frozenset(
    {
        "allowed_roots",
        "project_dir",
        "approval_preset",
        "auto_approve",
        "client_managed_approval",
        "ai_evaluator_enabled",
        "ai_evaluator_provider",
        "ai_evaluator_api_key",
        "ai_evaluator_model",
        "ai_evaluator_fallback_action",
        "role",
        "user",
    }
)

_CONFIG: dict[str, Any] = {
    "project_dir": Path.cwd().resolve(),
    "allowed_roots": [Path.cwd().resolve()],
    "auto_approve": False,
    "client_managed_approval": False,
    "shell_timeout": 30,
    "approval_preset": None,
    "onboarding_enabled": False,
    "context_budget_profile": "balanced",
    "tool_profile": "full",
    "intent_compaction_enabled": False,
    "ai_evaluator_enabled": False,
    "ai_evaluator_provider": "local",
    "ai_evaluator_api_key": "",
    "ai_evaluator_model": "",
    "ai_evaluator_timeout": 5,
    "ai_evaluator_fallback_action": "ask",
    "role": None,
    "user": None,
}
_ALLOWED_ROOTS_SNAPSHOT: tuple[Path, ...] = tuple(_CONFIG["allowed_roots"])

_CONFIG_LOCK = threading.RLock()


def resolve_approval_mode(
    *,
    approval_preset: str | None = None,
    auto_approve: bool = False,
    client_managed_approval: bool = False,
) -> tuple[bool, bool, str | None]:
    if approval_preset is None:
        return auto_approve, client_managed_approval, None
    if approval_preset not in APPROVAL_PRESETS:
        raise ValueError(f"Unknown approval preset: {approval_preset}")
    preset = APPROVAL_PRESETS[approval_preset]
    return (
        bool(preset["auto_approve"]),
        bool(preset["client_managed_approval"]),
        approval_preset,
    )


def apply_config(
    project_dir: Path,
    allowed_roots: Sequence[Path] | None = None,
    auto_approve: bool = False,
    client_managed_approval: bool = False,
    shell_timeout: int = 30,
    approval_preset: str | None = None,
    onboarding_enabled: bool = False,
    context_budget_profile: str = "balanced",
    tool_profile: str = "standard",
    intent_compaction_enabled: bool = False,
    ai_evaluator_enabled: bool = False,
    ai_evaluator_provider: str = "local",
    ai_evaluator_api_key: str = "",
    ai_evaluator_model: str = "",
    ai_evaluator_timeout: int = 5,
    ai_evaluator_fallback_action: str = "ask",
    role: str | None = None,
    user: str | None = None,
) -> None:
    global _ALLOWED_ROOTS_SNAPSHOT
    resolved_project_dir = project_dir.resolve()
    resolved_allowed_roots = [root.resolve() for root in (allowed_roots or [resolved_project_dir])]
    if resolved_project_dir not in resolved_allowed_roots:
        resolved_allowed_roots.insert(0, resolved_project_dir)
    resolved_auto_approve, resolved_client_managed, resolved_preset = resolve_approval_mode(
        approval_preset=approval_preset,
        auto_approve=auto_approve,
        client_managed_approval=client_managed_approval,
    )
    if context_budget_profile not in BUDGET_PROFILES:
        raise ValueError(f"Unknown context budget profile: {context_budget_profile}")
    if tool_profile not in TOOL_PROFILES:
        raise ValueError(f"Unknown tool profile: {tool_profile}")
    if not isinstance(shell_timeout, int) or shell_timeout <= 0:
        raise ValueError(f"shell_timeout must be a positive integer, got {shell_timeout!r}")
    if ai_evaluator_provider not in {"local", "openai", "anthropic", "ollama", "deepseek"}:
        raise ValueError(
            f"ai_evaluator_provider must be one of local/openai/anthropic/ollama/deepseek, "
            f"got {ai_evaluator_provider!r}"
        )
    if not isinstance(ai_evaluator_timeout, int) or ai_evaluator_timeout <= 0:
        raise ValueError(
            f"ai_evaluator_timeout must be a positive integer, got {ai_evaluator_timeout!r}"
        )
    if ai_evaluator_fallback_action not in {"deny", "ask"}:
        raise ValueError(
            f"ai_evaluator_fallback_action must be one of deny/ask, "
            f"got {ai_evaluator_fallback_action!r}"
        )
    with _CONFIG_LOCK:
        _CONFIG["project_dir"] = resolved_project_dir
        _CONFIG["allowed_roots"] = resolved_allowed_roots
        _ALLOWED_ROOTS_SNAPSHOT = tuple(resolved_allowed_roots)
        _CONFIG["auto_approve"] = resolved_auto_approve
        _CONFIG["client_managed_approval"] = resolved_client_managed
        _CONFIG["shell_timeout"] = shell_timeout
        _CONFIG["approval_preset"] = resolved_preset
        _CONFIG["onboarding_enabled"] = bool(onboarding_enabled)
        _CONFIG["context_budget_profile"] = context_budget_profile
        _CONFIG["tool_profile"] = tool_profile
        _CONFIG["intent_compaction_enabled"] = bool(intent_compaction_enabled)
        _CONFIG["ai_evaluator_enabled"] = bool(ai_evaluator_enabled)
        _CONFIG["ai_evaluator_provider"] = ai_evaluator_provider
        _CONFIG["ai_evaluator_api_key"] = ai_evaluator_api_key
        _CONFIG["ai_evaluator_model"] = ai_evaluator_model
        _CONFIG["ai_evaluator_timeout"] = ai_evaluator_timeout
        _CONFIG["ai_evaluator_fallback_action"] = ai_evaluator_fallback_action
        if role is not None:
            _CONFIG["role"] = role
        if user is not None:
            _CONFIG["user"] = user


def configure_from_env_state(*, force_auto_approve: bool | None = None) -> None:
    project_dir = Path(os.environ.get("CLAUDE_BRIDGE_PROJECT_DIR", str(Path.cwd()))).resolve()
    raw_allowed_roots = os.environ.get("CLAUDE_BRIDGE_ALLOWED_ROOTS", "")
    allowed_roots = [
        Path(item).resolve() for item in raw_allowed_roots.split(os.pathsep) if item.strip()
    ] or [project_dir]
    raw_auto_approve = os.environ.get("CLAUDE_BRIDGE_AUTO_APPROVE", "0").strip().lower()
    auto_approve = raw_auto_approve in {"1", "true", "yes", "on"}
    raw_client_managed = (
        os.environ.get("CLAUDE_BRIDGE_CLIENT_MANAGED_APPROVAL", "0").strip().lower()
    )
    client_managed_approval = raw_client_managed in {"1", "true", "yes", "on"}
    safety_confirm = (
        os.environ.get("CLAUDE_BRIDGE_UNSAFE_AUTO_APPROVE_CONFIRMED", "0").strip().lower()
    )
    noapproval_confirm = (
        os.environ.get("CLAUDE_BRIDGE_UNSAFE_NOAPPROVAL_CONFIRMED", "0").strip().lower()
    )
    auto_approve_confirmed = (
        safety_confirm in {"1", "true", "yes", "on"} or noapproval_confirm == "1"
    )
    if auto_approve and not auto_approve_confirmed:
        auto_approve = False
        client_managed_approval = True
    raw_approval_preset = os.environ.get("CLAUDE_BRIDGE_APPROVAL_PRESET", "").strip() or None
    raw_onboarding_enabled = os.environ.get("CLAUDE_BRIDGE_ONBOARDING_ENABLED", "0").strip().lower()
    onboarding_enabled = raw_onboarding_enabled in {"1", "true", "yes", "on"}
    raw_shell_timeout = os.environ.get("CLAUDE_BRIDGE_SHELL_TIMEOUT", "30").strip()
    raw_context_budget_profile = (
        os.environ.get("CLAUDE_BRIDGE_CONTEXT_BUDGET_PROFILE", "balanced").strip() or "balanced"
    )
    raw_tool_profile = (
        os.environ.get("CLAUDE_BRIDGE_TOOL_PROFILE", "standard").strip() or "standard"
    )
    raw_intent_compaction_enabled = (
        os.environ.get("CLAUDE_BRIDGE_INTENT_COMPACTION_ENABLED", "0").strip().lower()
    )
    intent_compaction_enabled = raw_intent_compaction_enabled in {"1", "true", "yes", "on"}
    try:
        parsed = int(raw_shell_timeout)
        if parsed <= 0:
            shell_timeout_val = 30
        else:
            shell_timeout_val = parsed
    except ValueError:
        shell_timeout_val = 30
    raw_ai_enabled = os.environ.get("CLAUDE_BRIDGE_AI_EVALUATOR_ENABLED", "0").strip().lower()
    ai_evaluator_enabled = raw_ai_enabled in {"1", "true", "yes", "on"}
    raw_ai_provider = (
        os.environ.get("CLAUDE_BRIDGE_AI_EVALUATOR_PROVIDER", "local").strip().lower() or "local"
    )
    ai_evaluator_api_key = os.environ.get("CLAUDE_BRIDGE_AI_EVALUATOR_API_KEY", "").strip()
    ai_evaluator_model = os.environ.get("CLAUDE_BRIDGE_AI_EVALUATOR_MODEL", "").strip()
    raw_ai_timeout = os.environ.get("CLAUDE_BRIDGE_AI_EVALUATOR_TIMEOUT", "5").strip()
    try:
        ai_timeout_parsed = int(raw_ai_timeout)
        if ai_timeout_parsed <= 0:
            ai_evaluator_timeout = 5
        else:
            ai_evaluator_timeout = ai_timeout_parsed
    except ValueError:
        ai_evaluator_timeout = 5
    ai_evaluator_fallback_action = (
        os.environ.get("CLAUDE_BRIDGE_AI_EVALUATOR_FALLBACK_ACTION", "ask").strip().lower() or "ask"
    )
    if ai_evaluator_fallback_action == "allow":
        ai_evaluator_fallback_action = "ask"
    raw_role = os.environ.get("CLAUDE_BRIDGE_ROLE", "").strip() or None
    raw_user = os.environ.get("CLAUDE_BRIDGE_USER", "").strip() or None
    if force_auto_approve is not None:
        auto_approve = force_auto_approve and auto_approve_confirmed
        if force_auto_approve and not auto_approve_confirmed:
            client_managed_approval = True
    apply_config(
        project_dir=project_dir,
        allowed_roots=allowed_roots,
        auto_approve=auto_approve,
        client_managed_approval=client_managed_approval,
        shell_timeout=shell_timeout_val,
        approval_preset=raw_approval_preset,
        onboarding_enabled=onboarding_enabled,
        context_budget_profile=raw_context_budget_profile,
        tool_profile=raw_tool_profile,
        intent_compaction_enabled=intent_compaction_enabled,
        ai_evaluator_enabled=ai_evaluator_enabled,
        ai_evaluator_provider=raw_ai_provider,
        ai_evaluator_api_key=ai_evaluator_api_key,
        ai_evaluator_model=ai_evaluator_model,
        ai_evaluator_timeout=ai_evaluator_timeout,
        ai_evaluator_fallback_action=ai_evaluator_fallback_action,
        role=raw_role,
        user=raw_user,
    )


def project_dir() -> Path:
    with _CONFIG_LOCK:
        return cast(Path, _CONFIG["project_dir"])


def allowed_roots() -> tuple[Path, ...]:
    with _CONFIG_LOCK:
        return tuple(_CONFIG["allowed_roots"])


def shell_timeout() -> int:
    with _CONFIG_LOCK:
        return int(_CONFIG["shell_timeout"])


def approval_mode() -> tuple[bool, bool]:
    with _CONFIG_LOCK:
        return bool(_CONFIG["auto_approve"]), bool(_CONFIG["client_managed_approval"])


def current_config() -> dict[str, Any]:
    with _CONFIG_LOCK:
        api_key = str(_CONFIG.get("ai_evaluator_api_key", ""))
        return {
            "project_dir": _CONFIG["project_dir"],
            "allowed_roots": list(_CONFIG["allowed_roots"]),
            "auto_approve": bool(_CONFIG["auto_approve"]),
            "client_managed_approval": bool(_CONFIG["client_managed_approval"]),
            "shell_timeout": int(_CONFIG["shell_timeout"]),
            "approval_preset": _CONFIG["approval_preset"],
            "onboarding_enabled": bool(_CONFIG["onboarding_enabled"]),
            "context_budget_profile": str(_CONFIG["context_budget_profile"]),
            "tool_profile": str(_CONFIG["tool_profile"]),
            "intent_compaction_enabled": bool(_CONFIG["intent_compaction_enabled"]),
            "ai_evaluator_enabled": bool(_CONFIG["ai_evaluator_enabled"]),
            "ai_evaluator_provider": str(_CONFIG["ai_evaluator_provider"]),
            "ai_evaluator_api_key": "[REDACTED]" if api_key else "",
            "ai_evaluator_model": str(_CONFIG.get("ai_evaluator_model", "")),
            "ai_evaluator_timeout": int(_CONFIG["ai_evaluator_timeout"]),
            "ai_evaluator_fallback_action": str(_CONFIG["ai_evaluator_fallback_action"]),
            "role": _CONFIG["role"],
            "user": _CONFIG["user"],
        }


def raw_ai_evaluator_config() -> dict[str, Any]:
    """Return private AI evaluator settings for provider construction."""
    with _CONFIG_LOCK:
        return {
            "enabled": bool(_CONFIG["ai_evaluator_enabled"]),
            "provider": str(_CONFIG["ai_evaluator_provider"]),
            "api_key": str(_CONFIG.get("ai_evaluator_api_key", "")),
            "model": str(_CONFIG.get("ai_evaluator_model", "")),
            "timeout": int(_CONFIG["ai_evaluator_timeout"]),
        }


def active_role() -> str | None:
    """Return the currently configured role name, or None if not set."""
    with _CONFIG_LOCK:
        return _CONFIG.get("role")


def active_user() -> str | None:
    """Return the currently configured user identifier, or None if not set."""
    with _CONFIG_LOCK:
        return _CONFIG.get("user")


def active_tool_names() -> set[str]:
    """Return the set of tool names enabled by the current tool_profile."""
    with _CONFIG_LOCK:
        profile_name = str(_CONFIG.get("tool_profile", "standard"))
    profile = TOOL_PROFILES.get(profile_name, TOOL_PROFILES["standard"])
    groups = profile.get("groups", set())
    names: set[str] = set()
    for group in groups:
        names.update(TOOL_GROUPS.get(group, set()))
    return names


def update_runtime_config(key: str, value: Any) -> dict[str, Any]:
    with _CONFIG_LOCK:
        if key == "approval_preset":
            preset = None if value in {None, "", "none"} else str(value)
            resolved_auto, resolved_client, resolved_preset = resolve_approval_mode(
                approval_preset=preset,
                auto_approve=_CONFIG["auto_approve"],
                client_managed_approval=_CONFIG["client_managed_approval"],
            )
            _CONFIG["approval_preset"] = resolved_preset
            _CONFIG["auto_approve"] = resolved_auto
            _CONFIG["client_managed_approval"] = resolved_client
            return current_config()

        if key == "shell_timeout":
            try:
                timeout = int(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("shell_timeout must be a positive integer") from exc
            if timeout <= 0:
                raise ValueError("shell_timeout must be a positive integer")
            _CONFIG["shell_timeout"] = timeout
            return current_config()

        if key in {"auto_approve", "client_managed_approval"}:
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be a boolean")
            _CONFIG[key] = value
            return current_config()

        if key == "onboarding_enabled":
            if not isinstance(value, bool):
                raise ValueError("onboarding_enabled must be a boolean")
            _CONFIG[key] = value
            return current_config()

        if key == "context_budget_profile":
            profile = str(value)
            if profile not in BUDGET_PROFILES:
                raise ValueError(f"Unknown context budget profile: {profile}")
            _CONFIG["context_budget_profile"] = profile
            return current_config()

        if key == "tool_profile":
            profile = str(value)
            if profile not in TOOL_PROFILES:
                raise ValueError(
                    f"Unknown tool profile: {profile}. Available: {', '.join(TOOL_PROFILES)}"
                )
            _CONFIG["tool_profile"] = profile
            return current_config()

        if key == "intent_compaction_enabled":
            if not isinstance(value, bool):
                raise ValueError("intent_compaction_enabled must be a boolean")
            _CONFIG[key] = value
            return current_config()

        if key == "ai_evaluator_enabled":
            if not isinstance(value, bool):
                raise ValueError("ai_evaluator_enabled must be a boolean")
            _CONFIG[key] = value
            return current_config()

        if key == "ai_evaluator_provider":
            provider = str(value).lower()
            if provider not in {"local", "openai", "anthropic", "ollama", "deepseek"}:
                raise ValueError(
                    "ai_evaluator_provider must be one of local/openai/anthropic/ollama/deepseek"
                )
            _CONFIG[key] = provider
            return current_config()

        if key == "ai_evaluator_api_key":
            raise ValueError(
                "ai_evaluator_api_key cannot be set via MCP tool; "
                "use CLAUDE_BRIDGE_AI_EVALUATOR_API_KEY environment variable instead"
            )

        if key == "ai_evaluator_model":
            _CONFIG[key] = str(value)
            return current_config()

        if key == "ai_evaluator_timeout":
            try:
                timeout = int(value)
            except (TypeError, ValueError) as exc:
                raise ValueError("ai_evaluator_timeout must be a positive integer") from exc
            if timeout <= 0:
                raise ValueError("ai_evaluator_timeout must be a positive integer")
            _CONFIG[key] = timeout
            return current_config()

        if key == "ai_evaluator_fallback_action":
            action = str(value).lower()
            if action not in {"deny", "ask"}:
                raise ValueError("ai_evaluator_fallback_action must be one of deny/ask")
            _CONFIG[key] = action
            return current_config()

        if key == "role":
            if value is not None and not isinstance(value, str):
                raise ValueError("role must be a string or None")
            _CONFIG[key] = value
            return current_config()

        if key == "user":
            if value is not None and not isinstance(value, str):
                raise ValueError("user must be a string or None")
            _CONFIG[key] = value
            return current_config()

        raise ValueError(f"Unsupported config key: {key}")


def update_safe_chat_config(key: str, value: Any) -> dict[str, Any]:
    """Update a runtime config key that is safe for chat-driven mutation."""
    if key in RESTRICTED_CHAT_CONFIG_KEYS:
        raise ValueError(
            f"{key} cannot be changed through chat-driven config; use explicit local config"
        )
    if key not in SAFE_CHAT_CONFIG_KEYS:
        raise ValueError(f"Unsupported safe chat config key: {key}")
    if key == "shell_timeout":
        timeout = int(value)
        if timeout > 120:
            raise ValueError("shell_timeout cannot exceed 120 seconds through chat config")
    if key == "ai_evaluator_timeout":
        timeout = int(value)
        if timeout > 30:
            raise ValueError("ai_evaluator_timeout cannot exceed 30 seconds through chat config")
    return update_runtime_config(key, value)
