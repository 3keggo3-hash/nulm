"""Shared helpers for Claude Bridge tools."""

from __future__ import annotations

import fnmatch
import inspect
import json
import re
import sys
import threading
from pathlib import Path
from typing import Any, Awaitable, Callable, cast

from claude_bridge.config import (
    allowed_roots,
    apply_config,
    approval_mode,
    current_config,
    project_dir,
    shell_timeout,
    should_auto_approve_risk,
)
from claude_bridge.guard_policy import (
    DecisionAction,
    DecisionSource,
    PolicyDecision,
    RiskLevel,
    custom_secret_pattern_matches,
    custom_sensitive_path_reason,
)

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
    "id_ecdsa",
    "id_ed25519",
    "id_ed25519_sk",
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
    response_details = {k: v for k, v in (details or {}).items() if v is not None}
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


_LOAD_BRIDGEIGNORE_LOCK = threading.Lock()
_bridgeignore_cache: dict[tuple[str, float], list[str]] = {}


def load_bridgeignore_patterns(project_root: Path) -> list[str]:
    """Read .bridgeignore from *project_root* and return non-empty, non-comment lines.

    Cache is invalidated when the file's mtime changes.
    """
    bridgeignore = project_root / ".bridgeignore"
    try:
        mtime = bridgeignore.stat().st_mtime
    except OSError:
        with _LOAD_BRIDGEIGNORE_LOCK:
            stale_keys = [k for k in _bridgeignore_cache if k[0] == str(project_root)]
            for k in stale_keys:
                _bridgeignore_cache.pop(k, None)
        return []
    cache_key = (str(project_root), mtime)
    with _LOAD_BRIDGEIGNORE_LOCK:
        cached = _bridgeignore_cache.get(cache_key)
        if cached is not None:
            return list(cached)
    if not bridgeignore.is_file():
        with _LOAD_BRIDGEIGNORE_LOCK:
            _bridgeignore_cache[cache_key] = []
        return []
    patterns: list[str] = []
    try:
        for line in bridgeignore.read_text(errors="replace").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                patterns.append(stripped)
    except OSError:
        return []
    with _LOAD_BRIDGEIGNORE_LOCK:
        old_keys = [k for k in _bridgeignore_cache if k[0] == str(project_root) and k != cache_key]
        for k in old_keys:
            _bridgeignore_cache.pop(k, None)
        _bridgeignore_cache[cache_key] = patterns
    return list(patterns)


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
        return ".git directory"
    if ".docker" in parts:
        docker_idx = parts.index(".docker")
        rel = parts[docker_idx + 1 :]
        if rel == ["config.json"]:
            return ".docker/config.json"
    if ".ssh" in parts:
        return ".ssh directory"
    # Check bridgeignore patterns
    try:
        relative = target.resolve().relative_to(project_dir()).as_posix()
    except (OSError, ValueError):
        relative = target.name
    candidates = {target.name, relative}
    for pattern in load_bridgeignore_patterns(project_dir()):
        if any(fnmatch.fnmatchcase(c, pattern) for c in candidates):
            return f"bridgeignore pattern: {pattern}"
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


_COMPILED_SECRET_PATTERNS: list[tuple[str, re.Pattern]] | None = None
_COMPILED_SECRET_LOCK = threading.Lock()


def _get_compiled_secret_patterns() -> list[tuple[str, re.Pattern]]:
    global _COMPILED_SECRET_PATTERNS
    with _COMPILED_SECRET_LOCK:
        if _COMPILED_SECRET_PATTERNS is not None:
            return _COMPILED_SECRET_PATTERNS
        compiled = [(name, re.compile(pattern)) for name, pattern in _SECRET_PATTERNS.items()]
        _COMPILED_SECRET_PATTERNS = compiled
        return compiled


def _mask_secrets(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    masked = value
    for name, pattern in _get_compiled_secret_patterns():
        masked = pattern.sub("[REDACTED]", masked)
    from claude_bridge.guard_policy import load_guard_policy

    for custom_name, custom_pattern in load_guard_policy()["secret_patterns"].items():
        masked = re.sub(custom_pattern, "[REDACTED]", masked)
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
    target = (
        combined.resolve()
    )
    if not any(is_within_root(target, root) for root in allowed_roots()):
        raise PermissionError("Access denied: path outside allowed roots")
    return target


def resolve_path_safe(user_path: str) -> Path:
    candidate = Path(user_path)
    if candidate.is_absolute():
        if candidate.is_symlink():
            raise PermissionError("Access denied: symlink is not allowed")
        target = candidate.resolve()
        allowed = any(is_within_root(target, root) for root in allowed_roots())
        if not allowed:
            raise PermissionError("Access denied: path outside allowed roots")
    else:
        base = project_dir()
        combined = base / candidate
        is_link = False
        try:
            is_link = combined.is_symlink()
        except OSError:
            pass
        if is_link:
            raise PermissionError("Access denied: symlink is not allowed")
        target = combined.resolve()
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
    config = current_config()
    apply_config(
        project_dir=resolved,
        allowed_roots=cast(list[Path], config["allowed_roots"]),
        auto_approve=bool(config["auto_approve"]),
        client_managed_approval=bool(config["client_managed_approval"]),
        shell_timeout=int(config["shell_timeout"]),
        approval_preset=cast(str | None, config["approval_preset"]),
        onboarding_enabled=bool(config["onboarding_enabled"]),
        context_budget_profile=str(config["context_budget_profile"]),
        tool_profile=str(config["tool_profile"]),
        intent_compaction_enabled=bool(config["intent_compaction_enabled"]),
        ai_evaluator_enabled=bool(config["ai_evaluator_enabled"]),
        ai_evaluator_provider=str(config["ai_evaluator_provider"]),
        ai_evaluator_api_key=str(config["ai_evaluator_api_key"]),
        ai_evaluator_model=str(config["ai_evaluator_model"]),
        ai_evaluator_timeout=int(config["ai_evaluator_timeout"]),
        ai_evaluator_fallback_action=str(config["ai_evaluator_fallback_action"]),
        role=cast(str | None, config["role"]),
        user=cast(str | None, config["user"]),
    )
    from claude_bridge.indexing import clear_index_cache

    clear_index_cache()


_TR_LABELS = {
    "permission_card_title": "İzin Kartı",
    "agent": "Ajan",
    "action": "Eylem",
    "risk": "Risk",
    "files": "Dosyalar",
    "reason": "Açıklama",
    "allow_once": "Bir Kere İzin Ver",
    "allow_always": "Her Zaman İzin Ver",
    "deny": "Reddet",
    "and_more_files": "ve {count} dosya daha",
}

_RISK_CATEGORIES = {
    "Safe": "Güvenli",
    "Low Risk": "Düşük Risk",
    "Medium": "Orta",
    "High": "Yüksek",
    "Critical": "Kritik",
    "Blocked": "Engellendi",
}


async def request_approval(
    tool_name: str,
    params: dict[str, Any],
    *,
    card: PermissionCard | None = None,
) -> bool:
    auto_approve, client_managed_approval = approval_mode()
    if auto_approve or client_managed_approval:
        return True

    if card is not None:
        print(card.format_card(), file=sys.stderr)
    else:
        print(
            (
                f"[{tool_name}] approval requested but no approval handler is configured for MCP stdio. "
                "Enable client-managed approval in the MCP client, or run with auto-approve only in a trusted local environment."
            ),
            file=sys.stderr,
        )
        for key, value in params.items():
            safe_value = _mask_secrets(value)
            print(f"  {key}: {safe_value}", file=sys.stderr)
    return False


async def require_approval(
    tool_name: str,
    params: dict[str, Any],
    *,
    rejection_message: str,
    rejection_details: dict[str, Any] | None = None,
    request_approval_fn: Callable[..., Awaitable[bool]] = request_approval,
    card: PermissionCard | None = None,
    allow_auto_approve: bool = True,
    risk_level: str = "low",
) -> str | None:
    auto_approve, client_managed_approval = approval_mode()
    if auto_approve and not client_managed_approval:
        if not allow_auto_approve or not should_auto_approve_risk(risk_level):
            return json_response(
                False,
                rejection_message,
                code="approval_rejected",
                details=rejection_details or {},
            )
        return None
    try:
        result = request_approval_fn(tool_name, params, card=card)
    except TypeError as exc:
        if "card" not in str(exc):
            raise
        result = request_approval_fn(tool_name, params)
    approved = bool(await result) if inspect.isawaitable(result) else bool(result)
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


def current_allowed_roots() -> tuple[Path, ...]:
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


class PermissionCard:
    """Human-readable permission request card for agent actions."""

    def __init__(
        self,
        agent: str,
        action: str,
        reason: str,
        risk: int,
        files: list[str] | None = None,
        tool_name: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> None:
        self.agent = agent
        self.action = action
        self.reason = reason
        self.risk = risk
        self.files = files or []
        self.tool_name = tool_name
        self.params = params or {}

    @property
    def risk_category(self) -> str:
        if self.risk <= 20:
            return "Safe"
        elif self.risk <= 40:
            return "Low Risk"
        elif self.risk <= 60:
            return "Medium"
        elif self.risk <= 80:
            return "High"
        elif self.risk < 100:
            return "Critical"
        return "Blocked"

    @property
    def risk_emoji(self) -> str:
        if self.risk <= 20:
            return "🔒"
        elif self.risk <= 40:
            return "🔓"
        elif self.risk <= 60:
            return "⚠️"
        elif self.risk <= 80:
            return "🚨"
        elif self.risk < 100:
            return "🚨"
        return "🚫"

    def format_card(self) -> str:
        lines = [
            "┌─────────────────────────────────────────┐",
            "│ 🔐 Permission Card                      │",
            "├─────────────────────────────────────────┤",
            f"│ Agent: {self.agent:<32} │",
            f"│ Action: {self.action:<30} │",
            f"│ Risk: {self.risk}/100 ({self.risk_category}){'':<10} │",
            "├─────────────────────────────────────────┤",
        ]
        if self.files:
            lines.append("│ Files:")
            for f in self.files[:5]:
                lines.append(f"│   • {f:<33} │")
            if len(self.files) > 5:
                lines.append(f"│   ... and {len(self.files) - 5} more files         │")
            lines.append("├─────────────────────────────────────────┤")
        reason_str = self.reason[:33] if len(self.reason) > 33 else self.reason
        lines.append(f'│ "{reason_str}"{" " * (36 - len(reason_str))}│')
        lines.append("├─────────────────────────────────────────┤")
        lines.append("│ [Allow Once] [Allow Always] [Deny]      │")
        lines.append("└─────────────────────────────────────────┘")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "action": self.action,
            "reason": self.reason,
            "risk": self.risk,
            "risk_category": self.risk_category,
            "risk_emoji": self.risk_emoji,
            "files": self.files,
            "tool_name": self.tool_name,
            "params": self.params,
        }
