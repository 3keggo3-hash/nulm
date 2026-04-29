"""Runtime configuration state for Claude Bridge."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, cast

APPROVAL_PRESETS: dict[str, dict[str, Any]] = {
    "read-only": {
        "auto_approve": False,
        "client_managed_approval": False,
        "description": "Only read-only tools are practical; approval-requiring writes and shell calls fail closed.",
    },
    "dev-safe": {
        "auto_approve": False,
        "client_managed_approval": True,
        "description": "Recommended daily development mode with client-managed approvals for writes and shell commands.",
    },
    "ci-like": {
        "auto_approve": False,
        "client_managed_approval": True,
        "description": "Reviewable automation mode with explicit approvals and no blanket auto-approve.",
    },
    "power-user": {
        "auto_approve": True,
        "client_managed_approval": False,
        "description": "Trusted local mode with auto-approve enabled.",
    },
}

_CONFIG: dict[str, Any] = {
    "project_dir": Path.cwd().resolve(),
    "allowed_roots": [Path.cwd().resolve()],
    "auto_approve": False,
    "client_managed_approval": False,
    "shell_timeout": 30,
    "approval_preset": None,
    "onboarding_enabled": True,
}

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
    allowed_roots: list[Path] | None = None,
    auto_approve: bool = False,
    client_managed_approval: bool = False,
    shell_timeout: int = 30,
    approval_preset: str | None = None,
    onboarding_enabled: bool = True,
) -> None:
    resolved_project_dir = project_dir.resolve()
    resolved_allowed_roots = [root.resolve() for root in (allowed_roots or [resolved_project_dir])]
    if resolved_project_dir not in resolved_allowed_roots:
        resolved_allowed_roots.insert(0, resolved_project_dir)
    resolved_auto_approve, resolved_client_managed, resolved_preset = resolve_approval_mode(
        approval_preset=approval_preset,
        auto_approve=auto_approve,
        client_managed_approval=client_managed_approval,
    )
    with _CONFIG_LOCK:
        _CONFIG["project_dir"] = resolved_project_dir
        _CONFIG["allowed_roots"] = resolved_allowed_roots
        _CONFIG["auto_approve"] = resolved_auto_approve
        _CONFIG["client_managed_approval"] = resolved_client_managed
        _CONFIG["shell_timeout"] = shell_timeout
        _CONFIG["approval_preset"] = resolved_preset
        _CONFIG["onboarding_enabled"] = bool(onboarding_enabled)


def configure_from_env_state(*, force_auto_approve: bool | None = None) -> None:
    project_dir = Path(os.environ.get("CLAUDE_BRIDGE_PROJECT_DIR", str(Path.cwd()))).resolve()
    raw_allowed_roots = os.environ.get("CLAUDE_BRIDGE_ALLOWED_ROOTS", "")
    allowed_roots = [
        Path(item).resolve()
        for item in raw_allowed_roots.split(os.pathsep)
        if item.strip()
    ] or [project_dir]
    raw_auto_approve = os.environ.get("CLAUDE_BRIDGE_AUTO_APPROVE", "0").strip().lower()
    auto_approve = raw_auto_approve in {"1", "true", "yes", "on"}
    raw_client_managed = os.environ.get("CLAUDE_BRIDGE_CLIENT_MANAGED_APPROVAL", "0").strip().lower()
    client_managed_approval = raw_client_managed in {"1", "true", "yes", "on"}
    raw_approval_preset = os.environ.get("CLAUDE_BRIDGE_APPROVAL_PRESET", "").strip() or None
    raw_onboarding_enabled = os.environ.get("CLAUDE_BRIDGE_ONBOARDING_ENABLED", "1").strip().lower()
    onboarding_enabled = raw_onboarding_enabled in {"1", "true", "yes", "on"}
    raw_shell_timeout = os.environ.get("CLAUDE_BRIDGE_SHELL_TIMEOUT", "30").strip()
    try:
        shell_timeout = max(1, int(raw_shell_timeout))
    except ValueError:
        shell_timeout = 30
    if force_auto_approve is not None:
        auto_approve = force_auto_approve
    apply_config(
        project_dir=project_dir,
        allowed_roots=allowed_roots,
        auto_approve=auto_approve,
        client_managed_approval=client_managed_approval,
        shell_timeout=shell_timeout,
        approval_preset=raw_approval_preset,
        onboarding_enabled=onboarding_enabled,
    )


def project_dir() -> Path:
    with _CONFIG_LOCK:
        return cast(Path, _CONFIG["project_dir"])


def allowed_roots() -> list[Path]:
    with _CONFIG_LOCK:
        return list(_CONFIG["allowed_roots"])


def shell_timeout() -> int:
    with _CONFIG_LOCK:
        return int(_CONFIG["shell_timeout"])


def approval_mode() -> tuple[bool, bool]:
    with _CONFIG_LOCK:
        return bool(_CONFIG["auto_approve"]), bool(_CONFIG["client_managed_approval"])


def current_config() -> dict[str, Any]:
    with _CONFIG_LOCK:
        return {
            "project_dir": _CONFIG["project_dir"],
            "allowed_roots": list(_CONFIG["allowed_roots"]),
            "auto_approve": bool(_CONFIG["auto_approve"]),
            "client_managed_approval": bool(_CONFIG["client_managed_approval"]),
            "shell_timeout": int(_CONFIG["shell_timeout"]),
            "approval_preset": _CONFIG["approval_preset"],
            "onboarding_enabled": bool(_CONFIG["onboarding_enabled"]),
        }


def update_runtime_config(key: str, value: Any) -> dict[str, Any]:
    current = current_config()
    if key == "approval_preset":
        preset = None if value in {None, "", "none"} else str(value)
        apply_config(
            project_dir=current["project_dir"],
            allowed_roots=current["allowed_roots"],
            auto_approve=current["auto_approve"],
            client_managed_approval=current["client_managed_approval"],
            shell_timeout=current["shell_timeout"],
            approval_preset=preset,
            onboarding_enabled=current["onboarding_enabled"],
        )
        return current_config()

    if key == "shell_timeout":
        try:
            timeout = max(1, int(value))
        except (TypeError, ValueError) as exc:
            raise ValueError("shell_timeout must be a positive integer") from exc
        apply_config(
            project_dir=current["project_dir"],
            allowed_roots=current["allowed_roots"],
            auto_approve=current["auto_approve"],
            client_managed_approval=current["client_managed_approval"],
            shell_timeout=timeout,
            approval_preset=current["approval_preset"],
            onboarding_enabled=current["onboarding_enabled"],
        )
        return current_config()

    if key in {"auto_approve", "client_managed_approval"}:
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be a boolean")
        next_auto = current["auto_approve"]
        next_client = current["client_managed_approval"]
        if key == "auto_approve":
            next_auto = value
        else:
            next_client = value
        apply_config(
            project_dir=current["project_dir"],
            allowed_roots=current["allowed_roots"],
            auto_approve=next_auto,
            client_managed_approval=next_client,
            shell_timeout=current["shell_timeout"],
            approval_preset=None,
            onboarding_enabled=current["onboarding_enabled"],
        )
        return current_config()

    if key == "onboarding_enabled":
        if not isinstance(value, bool):
            raise ValueError("onboarding_enabled must be a boolean")
        apply_config(
            project_dir=current["project_dir"],
            allowed_roots=current["allowed_roots"],
            auto_approve=current["auto_approve"],
            client_managed_approval=current["client_managed_approval"],
            shell_timeout=current["shell_timeout"],
            approval_preset=current["approval_preset"],
            onboarding_enabled=value,
        )
        return current_config()

    raise ValueError(f"Unsupported config key: {key}")
