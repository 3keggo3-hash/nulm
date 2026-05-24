"""Context manifest construction for dispatcher-managed agent runs."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

from collections.abc import Iterable
from hashlib import sha256
import json
from pathlib import Path
import time
from typing import Any

from claude_bridge.agents.contracts import BudgetLedger, ContextManifest, TaskSpec

_SMALL_FILE_BYTES = 64 * 1024


def build_context_manifest(
    *,
    task: TaskSpec,
    run_id: str,
    session_id: str = "",
    context: dict[str, Any] | None = None,
    parent_manifest: ContextManifest | None = None,
) -> ContextManifest:
    """Build a cheap deterministic context manifest for one agent run."""
    ctx = context or {}
    parent = parent_manifest or _context_manifest(ctx.get("parent_context_manifest"))
    target = str(ctx.get("target") or ctx.get("path") or _default_target(task))
    selected_files, source_reason = _select_files(task, ctx)
    file_signatures = tuple(_file_signature(path) for path in selected_files)
    token_budget = _token_budget(ctx)
    estimated_tokens = _estimate_manifest_tokens(
        goal=task.goal,
        target=target,
        selected_files=selected_files,
        file_signatures=file_signatures,
    )
    digest = _manifest_digest(
        goal=task.goal,
        target=target,
        selected_files=selected_files,
        file_signatures=file_signatures,
    )
    manifest_id = _manifest_id(
        session_id=session_id,
        task_id=task.task_id,
        run_id=run_id,
        digest=digest,
    )
    duplicate_ratio = duplicate_context_ratio(
        selected_files=selected_files,
        previous_selected_files=parent.selected_files if parent is not None else (),
    )
    return ContextManifest(
        manifest_id=manifest_id,
        session_id=session_id,
        created_at=time.time(),
        goal=task.goal,
        target=target,
        selected_files=selected_files,
        file_signatures=file_signatures,
        token_budget=token_budget,
        estimated_tokens=estimated_tokens,
        digest=digest,
        summary_text=_summary_text(task.goal, selected_files),
        source_reason=source_reason,
        taint=str(ctx.get("taint") or "none"),
        labels=_string_tuple(ctx.get("labels", ())),
        duplicate_ratio=duplicate_ratio,
        parent_manifest_id=parent.manifest_id if parent is not None else None,
        budget_ledger=BudgetLedger.from_allocated(token_budget, estimated_tokens),
    )


def duplicate_context_ratio(
    *,
    selected_files: Iterable[str],
    previous_selected_files: Iterable[str],
) -> float:
    """Return explicit file overlap ratio for context duplication."""
    current = tuple(dict.fromkeys(str(path) for path in selected_files if str(path)))
    if not current:
        return 0.0
    previous = {str(path) for path in previous_selected_files if str(path)}
    if not previous:
        return 0.0
    overlap = sum(1 for path in current if path in previous)
    return overlap / len(current)


def _select_files(task: TaskSpec, context: dict[str, Any]) -> tuple[tuple[str, ...], str]:
    if task.read_set:
        return tuple(task.read_set), "task_read_set"
    context_files = _string_tuple(
        context.get("selected_files") or context.get("context_files") or context.get("files") or (),
    )
    if context_files:
        return context_files, "context_selected_files"
    return (), "none"


def _file_signature(path_value: str) -> dict[str, str]:
    signature = {"path": path_value, "exists": "false"}
    path = Path(path_value)
    try:
        stat = path.stat()
    except OSError:
        return signature
    signature.update(
        {
            "exists": "true",
            "mtime_ns": str(stat.st_mtime_ns),
            "size": str(stat.st_size),
        }
    )
    if path.is_file() and stat.st_size <= _SMALL_FILE_BYTES:
        try:
            signature["sha256"] = sha256(path.read_bytes()).hexdigest()
        except OSError:
            pass
    return signature


def _estimate_manifest_tokens(
    *,
    goal: str,
    target: str,
    selected_files: tuple[str, ...],
    file_signatures: tuple[dict[str, str], ...],
) -> int:
    estimate_text = "\n".join((goal, target, *selected_files))
    estimated = _estimate_token_count(estimate_text) if estimate_text.strip() else 0
    for signature in file_signatures:
        size = _safe_int(signature.get("size"))
        if signature.get("exists") == "true" and size > 0:
            estimated += max(1, (min(size, _SMALL_FILE_BYTES) + 3) // 4)
    return estimated


def _manifest_digest(
    *,
    goal: str,
    target: str,
    selected_files: tuple[str, ...],
    file_signatures: tuple[dict[str, str], ...],
) -> str:
    payload = {
        "goal": goal,
        "target": target,
        "selected_files": list(selected_files),
        "file_signatures": list(file_signatures),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(raw.encode("utf-8")).hexdigest()


def _manifest_id(*, session_id: str, task_id: str, run_id: str, digest: str) -> str:
    raw = json.dumps(
        {
            "session_id": session_id,
            "task_id": task_id,
            "run_id": run_id,
            "digest": digest,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "ctx_" + sha256(raw.encode("utf-8")).hexdigest()[:16]


def _token_budget(context: dict[str, Any]) -> int:
    value = context.get("token_budget") or context.get("budget_tokens") or 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _default_target(task: TaskSpec) -> str:
    return task.read_set[0] if task.read_set else "."


def _summary_text(goal: str, selected_files: tuple[str, ...]) -> str:
    return f"{goal[:120]} | files={len(selected_files)}"


def _string_tuple(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list | tuple | set):
        return ()
    return tuple(str(item) for item in raw if str(item))


def _context_manifest(raw: Any) -> ContextManifest | None:
    return raw if isinstance(raw, ContextManifest) else None


def _safe_int(raw: Any) -> int:
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def _estimate_token_count(text: str) -> int:
    try:
        from claude_bridge.smart import estimate_token_count

        return estimate_token_count(text)
    except Exception:
        return max(1, (len(text) + 3) // 4)
