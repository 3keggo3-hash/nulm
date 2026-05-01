"""Shared helpers for Claude Bridge tools."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

from claude_bridge.config import (
    allowed_roots,
    approval_mode,
    apply_config,
    project_dir,
    shell_timeout,
)
from claude_bridge.indexing import clear_index_cache

_SENSITIVE_SUFFIXES = {".env", ".pem", ".key", ".p12", ".pfx"}
_SENSITIVE_FILENAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    ".env.staging",
    ".npmrc",
    ".netrc",
    ".pypirc",
    "credentials.json",
    "application_default_credentials.json",
    "id_rsa",
    "id_dsa",
    "id_ed25519",
    "credentials",
    "known_hosts",
    "claude_desktop_config.json",
}
_SECRET_PATTERNS: dict[str, str] = {
    "api_key_assignment": r"(?i)\bapi[_-]?key\s*[:=]\s*['\"][^'\"]+['\"]",
    "secret_assignment": r"(?i)\bsecret\s*[:=]\s*['\"][^'\"]+['\"]",
    "token_assignment": r"(?i)\btoken\s*[:=]\s*['\"][^'\"]+['\"]",
    "password_assignment": r"(?i)\bpassword\s*[:=]\s*['\"][^'\"]+['\"]",
    "api_key_unquoted": r"(?i)\bapi[_-]?key\s*[:=]\s*\S+",
    "secret_unquoted": r"(?i)\bsecret\s*[:=]\s*\S+",
    "token_unquoted": r"(?i)\btoken\s*[:=]\s*\S+",
    "password_unquoted": r"(?i)\bpassword\s*[:=]\s*\S+",
    "aws_access_key_id": r"AKIA[0-9A-Z]{16}",
    "github_token": r"ghp_[A-Za-z0-9]{20,}",
}


def json_response(
    ok: bool,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    code: str | None = None,
) -> str:
    payload: dict[str, Any] = {
        "ok": ok,
        "message": message,
        "details": details or {},
    }
    if code:
        payload["code"] = code
    return json.dumps(payload, ensure_ascii=False)


def path_outside_project_details(path: str) -> dict[str, Any]:
    return {
        "path": path,
        "active_project_dir": str(project_dir()),
        "allowed_roots": [str(root) for root in allowed_roots()],
        "hint": (
            "If the target lives in another allowed folder, call workspace_status() and then "
            "switch_project_root(path) instead of giving up."
        ),
        "suggested_next_tools": ["workspace_status", "switch_project_root"],
    }


def sensitive_path_reason(target: Path) -> str | None:
    name = target.name.lower()
    if name in _SENSITIVE_FILENAMES:
        return name
    if any(name.endswith(suffix) for suffix in _SENSITIVE_SUFFIXES):
        return target.suffix.lower()
    return None


def sensitive_file_blocked_details(path: str) -> dict[str, Any]:
    return {
        "path": path,
        "hint": "Sensitive files cannot be read, previewed, patched, or written through this tool.",
    }


def find_secret_patterns(content: str) -> list[str]:
    matches: list[str] = []
    for name, pattern in _SECRET_PATTERNS.items():
        if re.search(pattern, content):
            matches.append(name)
    return matches


def is_binary_bytes(raw: bytes) -> bool:
    if not raw:
        return False
    return b"\x00" in raw


def safe_read_text(target: Path) -> str:
    return target.read_bytes().decode("utf-8")


def is_within_root(target: Path, root: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_path(user_path: str) -> Path:
    candidate = Path(user_path)
    if candidate.is_absolute():
        target = candidate.resolve()
        allowed = any(is_within_root(target, root) for root in allowed_roots())
        if not allowed:
            raise PermissionError("Access denied: path outside allowed roots")
        return target

    base = project_dir()
    target = (base / candidate).resolve()
    if not is_within_root(target, base):
        raise PermissionError("Access denied: path outside active project directory")
    return target


def infer_project_root(target: Path) -> Path:
    active_root = project_dir()
    if is_within_root(target, active_root):
        return active_root
    matching_roots = [root for root in allowed_roots() if is_within_root(target, root)]
    if not matching_roots:
        raise PermissionError("Access denied: path outside allowed roots")
    return max(matching_roots, key=lambda root: len(root.parts))


def path_from_active_root(target: Path) -> str:
    return target.relative_to(project_dir()).as_posix()


def set_active_project_dir(next_project_dir: Path) -> None:
    resolved = next_project_dir.resolve()
    if not any(is_within_root(resolved, root) for root in allowed_roots()):
        raise PermissionError("Requested project root is not in allowed roots")
    auto_approve, client_managed_approval = approval_mode()
    apply_config(
        project_dir=resolved,
        allowed_roots=allowed_roots(),
        auto_approve=auto_approve,
        client_managed_approval=client_managed_approval,
        shell_timeout=shell_timeout(),
    )
    clear_index_cache()


async def request_approval(tool_name: str, params: dict[str, Any]) -> bool:
    auto_approve, client_managed_approval = approval_mode()
    if auto_approve or client_managed_approval:
        return True

    print(
        (
            f"[{tool_name}] approval requested but no approval handler is configured for MCP stdio. "
            "Enable client-managed approval in the MCP client, or run with auto-approve only in a trusted local environment."
        ),
        file=sys.stderr,
    )
    for key, value in params.items():
        print(f"  {key}: {value}", file=sys.stderr)
    return False


async def require_approval(
    tool_name: str,
    params: dict[str, Any],
    *,
    rejection_message: str,
    rejection_details: dict[str, Any] | None = None,
    request_approval_fn: Callable[[str, dict[str, Any]], Awaitable[bool]] = request_approval,
) -> str | None:
    approved = await request_approval_fn(tool_name, params)
    if approved:
        return None
    return json_response(
        False,
        rejection_message,
        code="approval_rejected",
        details=rejection_details or {},
    )


def current_project_dir() -> Path:
    return project_dir()


def current_allowed_roots() -> list[Path]:
    return allowed_roots()


def current_shell_timeout() -> int:
    return shell_timeout()
