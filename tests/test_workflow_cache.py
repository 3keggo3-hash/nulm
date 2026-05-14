"""Tests for workflow_cache.py."""

from __future__ import annotations

import time
from collections import OrderedDict
from unittest.mock import patch

from claude_bridge.workflow_cache import (
    _CONTEXT_PACK_CACHE,
    _safe_cached_json_payload,
    _store_cache_entry,
    _touch_cache_entry,
    _workflow_cache_dir,
    _workflow_cache_file,
    clear_workflow_caches,
)


class TestCacheEntryOperations:
    def test_touch_cache_entry_moves_to_end(self) -> None:
        cache: OrderedDict[tuple[str, ...], tuple[str, float]] = OrderedDict()
        cache[("key1",)] = ("value1", time.time() + 3600)
        cache[("key2",)] = ("value2", time.time() + 3600)

        result = _touch_cache_entry(cache, ("key1",))
        assert result == "value1"
        keys = list(cache.keys())
        assert keys[-1] == ("key1",)

    def test_touch_cache_entry_missing(self) -> None:
        cache: OrderedDict[tuple[str, ...], tuple[str, float]] = OrderedDict()
        result = _touch_cache_entry(cache, ("missing",))
        assert result is None

    def test_touch_cache_entry_expired(self) -> None:
        cache: OrderedDict[tuple[str, ...], tuple[str, float]] = OrderedDict()
        cache[("key1",)] = ("value1", time.time() - 1)

        result = _touch_cache_entry(cache, ("key1",))
        assert result is None
        assert ("key1",) not in cache

    def test_store_cache_entry_evicts_oldest(self) -> None:
        cache: OrderedDict[tuple[str, ...], tuple[str, float]] = OrderedDict()
        with patch("claude_bridge.workflow_cache._MAX_WORKFLOW_CACHE_ENTRIES", 3):
            for i in range(5):
                _store_cache_entry(cache, (f"key{i}",), f"value{i}")

        assert len(cache) == 3
        assert ("key0",) not in cache
        assert ("key4",) in cache


class TestSafeCachedJsonPayload:
    def test_valid_payload(self) -> None:
        payload = _safe_cached_json_payload('{"ok": true, "data": 123}')
        assert payload is not None
        assert payload["ok"] is True
        assert payload["data"] == 123

    def test_invalid_json_returns_none(self) -> None:
        result = _safe_cached_json_payload("not valid json")
        assert result is None

    def test_non_dict_returns_none(self) -> None:
        result = _safe_cached_json_payload('["array", "not", "object"]')
        assert result is None

    def test_empty_string_returns_none(self) -> None:
        result = _safe_cached_json_payload("")
        assert result is None


class TestWorkflowCacheDir:
    def test_default_cache_dir(self, monkeypatch) -> None:
        monkeypatch.delenv("CLAUDE_BRIDGE_CACHE_DIR", raising=False)
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
        cache_dir = _workflow_cache_dir()
        assert cache_dir.name == "workflow"
        assert ".cache" in str(cache_dir)

    def test_custom_cache_dir_from_env(self, monkeypatch) -> None:
        monkeypatch.setenv("CLAUDE_BRIDGE_CACHE_DIR", "/custom/cache")
        cache_dir = _workflow_cache_dir()
        assert str(cache_dir) == "/custom/cache/workflow"

    def test_xdg_cache_dir(self, monkeypatch) -> None:
        monkeypatch.delenv("CLAUDE_BRIDGE_CACHE_DIR", raising=False)
        monkeypatch.setenv("XDG_CACHE_HOME", "/xdg/cache")
        cache_dir = _workflow_cache_dir()
        assert str(cache_dir) == "/xdg/cache/claude-bridge/workflow"


class TestWorkflowCacheFile:
    def test_cache_file_name_contains_prefix_and_version(self) -> None:
        key = ("context", "target", "goal")
        path = _workflow_cache_file("context-pack", key)
        filename = path.name
        assert filename.startswith("context-pack-v1-")
        assert filename.endswith(".json")

    def test_same_key_produces_same_file(self) -> None:
        key = ("same", "key")
        path1 = _workflow_cache_file("test", key)
        path2 = _workflow_cache_file("test", key)
        assert path1 == path2

    def test_different_keys_produce_different_files(self) -> None:
        key1 = ("key1",)
        key2 = ("key2",)
        path1 = _workflow_cache_file("test", key1)
        path2 = _workflow_cache_file("test", key2)
        assert path1 != path2


class TestClearWorkflowCaches:
    def test_clear_caches_removes_all_entries(self) -> None:
        _CONTEXT_PACK_CACHE.clear()
        _CONTEXT_PACK_CACHE[("test1",)] = ("value1", time.time() + 3600)
        _CONTEXT_PACK_CACHE[("test2",)] = ("value2", time.time() + 3600)

        clear_workflow_caches()

        assert len(_CONTEXT_PACK_CACHE) == 0


class TestDiskCachePruning:
    def test_prune_workflow_disk_cache_runs_without_error(self, temp_project, monkeypatch) -> None:
        cache_dir = temp_project / "cache"
        cache_dir.mkdir(parents=True)
        monkeypatch.setenv("CLAUDE_BRIDGE_CACHE_DIR", str(cache_dir))
        monkeypatch.setattr("claude_bridge.workflow_cache._MAX_WORKFLOW_DISK_CACHE_FILES", 10)
        monkeypatch.setattr(
            "claude_bridge.workflow_cache._MAX_WORKFLOW_DISK_CACHE_BYTES", 1024 * 1024 * 100
        )

        for i in range(3):
            path = cache_dir / f"test-v1-{i}.json"
            path.write_text("{}", encoding="utf-8")
            time.sleep(0.01)

        from claude_bridge.workflow_cache import _prune_workflow_disk_cache

        _prune_workflow_disk_cache()
        assert len(list(cache_dir.glob("*.json"))) >= 1
