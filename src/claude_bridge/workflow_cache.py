"""Workflow caching infrastructure for Claude Bridge."""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
import os
import threading
import time
from collections import OrderedDict
from hashlib import sha256
from pathlib import Path
from typing import Any

_WORKFLOW_CACHE_LOCK = threading.RLock()
_MAX_WORKFLOW_CACHE_ENTRIES = 128
_WORKFLOW_CACHE_VERSION = 1
_MAX_WORKFLOW_DISK_CACHE_FILES = 64
_MAX_WORKFLOW_DISK_CACHE_BYTES = 50 * 1024 * 1024
_WORKFLOW_CACHE_TTL_SECONDS = 3600
_CONTEXT_PACK_CACHE: OrderedDict[tuple[str, ...], tuple[str, float]] = OrderedDict()
_WORKFLOW_PLAN_CACHE: OrderedDict[tuple[str, ...], tuple[str, float]] = OrderedDict()


def clear_workflow_caches() -> None:
    """Clear in-memory workflow caches."""
    with _WORKFLOW_CACHE_LOCK:
        _CONTEXT_PACK_CACHE.clear()
        _WORKFLOW_PLAN_CACHE.clear()


def _touch_cache_entry(
    cache: OrderedDict[tuple[str, ...], tuple[str, float]], key: tuple[str, ...]
) -> str | None:
    entry = cache.get(key)
    if entry is not None:
        value, expiry = entry
        if time.time() < expiry:
            cache.move_to_end(key)
            return value
        del cache[key]
    return None


def _store_cache_entry(
    cache: OrderedDict[tuple[str, ...], tuple[str, float]],
    key: tuple[str, ...],
    value: str,
    ttl: int = _WORKFLOW_CACHE_TTL_SECONDS,
) -> None:
    expiry = time.time() + ttl
    cache[key] = (value, expiry)
    cache.move_to_end(key)
    while len(cache) > _MAX_WORKFLOW_CACHE_ENTRIES:
        cache.popitem(last=False)


def _workflow_cache_dir() -> Path:
    raw = os.environ.get("CLAUDE_BRIDGE_CACHE_DIR", "").strip()
    if raw:
        return (Path(raw).expanduser().resolve() / "workflow").resolve()
    xdg = os.environ.get("XDG_CACHE_HOME", "").strip()
    if xdg:
        return (Path(xdg).expanduser() / "claude-bridge" / "workflow").resolve()
    return (Path.home() / ".cache" / "claude-bridge" / "workflow").resolve()


def _workflow_cache_file(prefix: str, key: tuple[str, ...]) -> Path:
    digest = sha256("|".join(key).encode("utf-8")).hexdigest()
    return _workflow_cache_dir() / f"{prefix}-v{_WORKFLOW_CACHE_VERSION}-{digest}.json"


def _load_disk_cached_response(prefix: str, key: tuple[str, ...]) -> str | None:
    cache_file = _workflow_cache_file(prefix, key)
    if not cache_file.exists():
        return None
    try:
        raw = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("version") != _WORKFLOW_CACHE_VERSION:
        return None
    payload = raw.get("response")
    return payload if isinstance(payload, str) else None


def _prune_workflow_disk_cache() -> None:
    cache_dir = _workflow_cache_dir()
    try:
        entries = sorted(
            [path for path in cache_dir.glob("*.json") if path.is_file()],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return
    for path in entries[_MAX_WORKFLOW_DISK_CACHE_FILES:]:
        try:
            path.unlink()
        except OSError:
            pass
    _prune_workflow_disk_cache_size(
        [path for path in entries[:_MAX_WORKFLOW_DISK_CACHE_FILES] if path.exists()]
    )


def _prune_workflow_disk_cache_size(entries: list[Path]) -> None:
    total_size = 0
    sized_entries: list[tuple[Path, int]] = []
    for path in entries:
        try:
            size = path.stat().st_size
        except OSError:
            continue
        total_size += size
        sized_entries.append((path, size))
    if total_size <= _MAX_WORKFLOW_DISK_CACHE_BYTES:
        return
    for path, size in reversed(sized_entries):
        try:
            path.unlink()
        except OSError:
            continue
        total_size -= size
        if total_size <= _MAX_WORKFLOW_DISK_CACHE_BYTES:
            return


def _expire_workflow_cache_entries(
    cache: OrderedDict[tuple[str, ...], tuple[str, float]],
) -> int:
    now = time.time()
    expired_keys = [key for key, (_, expiry) in cache.items() if now >= expiry]
    for key in expired_keys:
        del cache[key]
    return len(expired_keys)


def _invalidate_pattern_from_cache(
    cache: OrderedDict[tuple[str, ...], tuple[str, float]],
    prefix: str,
) -> int:
    removed = 0
    keys_to_remove = [key for key in cache.keys() if key and key[0] == prefix]
    for key in keys_to_remove:
        del cache[key]
        removed += 1
    return removed


def _write_disk_cached_response(prefix: str, key: tuple[str, ...], response: str) -> None:
    cache_file = _workflow_cache_file(prefix, key)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps({"version": _WORKFLOW_CACHE_VERSION, "response": response}, ensure_ascii=False),
        encoding="utf-8",
    )
    _prune_workflow_disk_cache()


def _safe_cached_json_payload(raw: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def clear_disk_cache() -> int:
    """Clear all workflow disk cache files. Returns count of files deleted."""
    cache_dir = _workflow_cache_dir()
    try:
        entries = [path for path in cache_dir.glob("*.json") if path.is_file()]
    except OSError:
        return 0
    removed = 0
    for path in entries:
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def invalidate_workflow_cache_pattern(prefix: str) -> int:
    """Invalidate in-memory cache entries matching prefix pattern."""
    removed = 0
    with _WORKFLOW_CACHE_LOCK:
        removed += _invalidate_pattern_from_cache(_CONTEXT_PACK_CACHE, prefix)
        removed += _invalidate_pattern_from_cache(_WORKFLOW_PLAN_CACHE, prefix)
    return removed
