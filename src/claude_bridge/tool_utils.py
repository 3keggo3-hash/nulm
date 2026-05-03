"""Shared helpers for Claude Bridge tools."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

from claude_bridge.config import (
    allowed_roots,
    apply_config,
    approval_mode,
    project_dir,
    shell_timeout,
)
from claude_bridge.guard_policy import (
    DecisionAction,
    DecisionSource,
    PolicyDecision,
    RiskLevel,
    custom_secret_pattern_matches,
    custom_sensitive_path_reason,
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
    ".dockercfg",
    ".git-credentials",
    "credentials.json",
    "application_default_credentials.json",
    "id_rsa",
    "id_dsa",
    "id_ed25519",
    "credentials",
    "known_hosts",
    "claude_desktop_config.json",
}  # FIX: Added .dockercfg and .git-credentials
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
    decision: PolicyDecision | dict[str, Any] | None = None,
    decision_in_details: bool = False,
) -> str:
    """Build a JSON response string, optionally enriched with policy decision metadata.

    When a *decision* is provided it is serialized under the ``"decision"`` key
    using the standard fields: ``action``, ``source``, ``risk_level``, ``reason``,
    and ``risk_reasons``.  The existing ``code`` / ``message`` / ``details`` shape
    is never altered, so existing callers are unaffected.
    """
    response_details = details or {}
    decision_payload: dict[str, Any] | None = None
    if decision is not None:
        if isinstance(decision, PolicyDecision):
            decision_payload = decision.to_dict()
        elif isinstance(decision, dict):
            decision_payload = decision
        else:
            decision_payload = dict(decision)  # type: ignore[call-overload]
        if decision_in_details:
            response_details = dict(response_details)
            response_details["decision"] = decision_payload
    payload: dict[str, Any] = {
        "ok": ok,
        "message": message,
        "details": response_details,
    }
    if code:
        payload["code"] = code
    if decision_payload is not None:
        payload["decision"] = decision_payload
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
    # FIX: Block sensitive paths inside .git and .docker directories
    try:
        parts = [p.lower() for p in target.resolve().parts]
    except (OSError, ValueError):
        parts = [p.lower() for p in target.parts]
    if ".git" in parts:
        git_idx = parts.index(".git")
        rel = parts[git_idx + 1 :]
        if not rel:
            return ".git directory"
        if rel[0] == "hooks":
            return ".git/hooks/*"
        if rel[0] in ("config", "head", "orig_head", "packed-refs"):
            return f".git/{rel[0]}"
    if ".docker" in parts:
        docker_idx = parts.index(".docker")
        rel = parts[docker_idx + 1 :]
        if rel == ["config.json"]:
            return ".docker/config.json"
    custom_reason = custom_sensitive_path_reason(target)
    if custom_reason is not None:
        return custom_reason
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
    matches.extend(custom_secret_pattern_matches(content))
    return matches


def _mask_secrets(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    masked = value
    for name, pattern in _SECRET_PATTERNS.items():
        masked = re.sub(pattern, "[REDACTED]", masked)
    return masked


def is_binary_bytes(raw: bytes) -> bool:
    if not raw:
        return False
    return b"\x00" in raw


def safe_read_text(target: Path, *, errors: str = "replace") -> str:
    """Read a file as UTF-8 text, never raising UnicodeDecodeError.

    By default invalid byte sequences are replaced with the Unicode
    replacement character (U+FFFD) so callers always receive a string.
    Pass ``errors="strict"`` to restore the original raise-on-decode-error
    behaviour.
    """
    raw = target.read_bytes()
    try:
        return raw.decode("utf-8", errors=errors)
    except UnicodeDecodeError:
        # In case errors="strict" was passed explicitly, surface a clear
        # message instead of a raw traceback.
        raise UnicodeDecodeError(
            "utf-8",
            raw,
            0,
            len(raw),
            f"File '{target}' is not valid UTF-8; pass errors='replace' for fallback",
        ) from None


def is_within_root(target: Path, root: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
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
    combined = base / candidate
    target = combined.resolve()  # FIX: Removed pre-resolution ".." check; is_within_root after resolve() is sufficient
    # Check resolved target against ALL allowed roots, not just the active project dir.
    # This allows symlinks inside the workspace to point to secondary allowed roots.
    if not any(is_within_root(target, root) for root in allowed_roots()):
        raise PermissionError("Access denied: path outside allowed roots")
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
        safe_value = _mask_secrets(value)  # FIX: Mask sensitive param values before printing to stderr
        print(f"  {key}: {safe_value}", file=sys.stderr)
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


# ---------------------------------------------------------------------------
# Path and file-operation decision adapters (Paket 1D)
# ---------------------------------------------------------------------------


def path_guard_decision(
    user_path: str,
    operation: str = "access",
    *,
    sensitive_reason: str | None = None,
    outside_workspace: bool = False,
) -> PolicyDecision:
    """Evaluate a path access attempt and produce a structured PolicyDecision.

    This is the central decision adapter for all file/path tool operations.
    It maps workspace-boundary violations and sensitive-path blocks into the
    standard allow/deny/ask decision model.

    Args:
        user_path: The original path string supplied by the caller.
        operation: A short label for the operation (e.g. ``"read"``, ``"write"``).
        sensitive_reason: If the path matched a sensitive-file pattern, the reason
            string (e.g. ``".env"`` or ``"custom policy: private/**"``).
        outside_workspace: ``True`` when the resolved path falls outside every
            allowed root.

    Returns:
        A ``PolicyDecision`` with action DENY for blocked paths, ALLOW otherwise.
    """
    if outside_workspace:
        return PolicyDecision(
            action=DecisionAction.DENY,
            source=DecisionSource.BUILTIN_GUARD,
            risk_level=RiskLevel.HIGH,
            reason=f"Path '{user_path}' is outside allowed workspace roots",
            risk_reasons=["path outside allowed roots"],
            metadata={"path": user_path, "operation": operation},
        )
    if sensitive_reason is not None:
        return PolicyDecision(
            action=DecisionAction.DENY,
            source=DecisionSource.BUILTIN_GUARD,
            risk_level=RiskLevel.HIGH,
            reason=f"Sensitive path blocked: {sensitive_reason}",
            risk_reasons=[f"sensitive file pattern matched: {sensitive_reason}"],
            metadata={
                "path": user_path,
                "sensitive_reason": sensitive_reason,
                "operation": operation,
            },
        )
    return PolicyDecision(
        action=DecisionAction.ALLOW,
        source=DecisionSource.DEFAULT,
        risk_level=RiskLevel.LOW,
        reason=f"Path '{user_path}' is within allowed workspace",
        risk_reasons=[],
        metadata={"path": user_path, "operation": operation},
    )
