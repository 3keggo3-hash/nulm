"""Tests for incremental and disk-backed indexing behavior."""

from __future__ import annotations

import time
from pathlib import Path

from claude_bridge import indexing as indexing_module
from claude_bridge import server as mcp_server

from tests.helpers import parse_payload


class TestIndexingCache:
    async def test_index_codebase_can_restore_from_disk_cache(self, temp_project, monkeypatch):
        cache_dir = temp_project / ".cache"
        monkeypatch.setenv("CLAUDE_BRIDGE_CACHE_DIR", str(cache_dir))

        pkg = temp_project / "pkg"
        pkg.mkdir()
        (pkg / "module.py").write_text("def hello():\n    return 'hi'\n", encoding="utf-8")

        first = parse_payload(await mcp_server.index_codebase("pkg"))
        assert first["ok"] is True
        assert first["details"]["cached"] is False

        mcp_server.clear_index_cache()
        second = parse_payload(await mcp_server.index_codebase("pkg"))
        assert second["ok"] is True
        assert second["details"]["cached"] is True

    async def test_index_codebase_reuses_unchanged_file_symbols_incrementally(
        self, temp_project, monkeypatch
    ):
        pkg = temp_project / "pkg"
        pkg.mkdir()
        first_file = pkg / "first.py"
        second_file = pkg / "second.py"
        first_file.write_text("def first():\n    return 1\n", encoding="utf-8")
        second_file.write_text("def second():\n    return 2\n", encoding="utf-8")

        first = parse_payload(await mcp_server.index_codebase("pkg"))
        assert first["ok"] is True

        original_extract = indexing_module.extract_symbols_with_backend
        calls: list[str] = []

        def counting_extract(file: Path, source: str):
            calls.append(file.name)
            return original_extract(file, source)

        monkeypatch.setattr(indexing_module, "extract_symbols_with_backend", counting_extract)

        time.sleep(0.02)
        second_file.write_text("def second_changed():\n    return 3\n", encoding="utf-8")
        second = parse_payload(await mcp_server.index_codebase("pkg"))
        assert second["ok"] is True
        assert calls == ["second.py"]

    def test_prune_disk_cache_limits_file_count(self, temp_project, monkeypatch):
        cache_dir = temp_project / ".cache"
        cache_dir.mkdir()
        monkeypatch.setenv("CLAUDE_BRIDGE_CACHE_DIR", str(cache_dir))
        monkeypatch.setattr(indexing_module, "_MAX_DISK_CACHE_FILES", 2)

        for index in range(4):
            path = cache_dir / f"index-{index}.json"
            path.write_text("{}", encoding="utf-8")
            time.sleep(0.01)

        indexing_module._prune_disk_cache(cache_dir)
        remaining = sorted(path.name for path in cache_dir.glob("index-*.json"))
        assert len(remaining) == 2

    def test_get_cached_index_returns_defensive_copy(self):
        indexing_module.clear_index_cache()
        indexing_module.set_cached_index(
            "key",
            (("module.py", 1),),
            {"files": [{"path": "module.py"}], "cached": False},
        )

        cached = indexing_module.get_cached_index("key")
        assert cached is not None
        cached["payload"]["files"][0]["path"] = "mutated.py"

        fresh = indexing_module.get_cached_index("key")
        assert fresh is not None
        assert fresh["payload"]["files"][0]["path"] == "module.py"
