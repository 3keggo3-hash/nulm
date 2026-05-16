"""Tests for indexing functions."""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


import json
from pathlib import Path

from claude_bridge import server as mcp_server
from claude_bridge import indexing as indexing_module


def parse_payload(result: str) -> dict:
    return json.loads(result)


def _always_within_root(target: Path, root: Path) -> bool:
    return True


class TestExtractSymbols:
    def test_extract_python_symbols(self):
        source = "import os\n\nclass Greeter:\n    pass\n\ndef hello():\n    return 'hi'\n"
        symbols = indexing_module.extract_symbols(Path("mod.py"), source)
        assert symbols["functions"] == ["hello"]
        assert symbols["classes"] == ["Greeter"]
        assert symbols["imports"] == ["os"]
        assert symbols["language"] == "python"

    def test_extract_javascript_symbols(self):
        source = 'function loginUser() {}\nclass AuthService {}\nimport {x} from "react"\n'
        symbols = indexing_module.extract_symbols(Path("auth.js"), source)
        assert symbols["functions"] == ["loginUser"]
        assert symbols["classes"] == ["AuthService"]
        assert symbols["imports"] == ["react"]
        assert symbols["language"] == "javascript"

    def test_extract_rust_symbols(self):
        source = "pub fn login_user() {}\npub struct AuthService;\nuse std::collections::HashMap;\n"
        symbols = indexing_module.extract_symbols(Path("auth.rs"), source)
        assert symbols["functions"] == ["login_user"]
        assert symbols["classes"] == ["AuthService"]
        assert symbols["imports"] == ["std"]
        assert symbols["language"] == "rust"

    def test_extract_go_symbols(self):
        source = 'func LoginUser() {}\ntype AuthService struct{}\nimport "context"\n'
        symbols = indexing_module.extract_symbols(Path("auth.go"), source)
        assert symbols["functions"] == ["LoginUser"]
        assert symbols["classes"] == ["AuthService"]
        assert symbols["imports"] == ["context"]
        assert symbols["language"] == "go"

    def test_extract_unknown_extension_returns_empty(self):
        result = indexing_module.extract_symbols(Path("readme.md"), "# Hello")
        assert result["symbols"] == []
        assert "No extractor available for suffix .md" in result["errors"][0]


class TestIterSearchableFiles:
    async def test_text_files_found(self, temp_project):
        (temp_project / "hello.txt").write_text("hello world")
        (temp_project / "notes.md").write_text("# notes")
        files = indexing_module.iter_searchable_files(
            temp_project,
            temp_project,
            is_within_root=_always_within_root,
        )
        paths = {f.name for f in files}
        assert "hello.txt" in paths
        assert "notes.md" in paths

    async def test_binary_files_skipped(self, temp_project):
        (temp_project / "data.txt").write_text("plain text")
        (temp_project / "img.bin").write_bytes(b"\x00\x01\x02\x03")
        files = indexing_module.iter_searchable_files(
            temp_project,
            temp_project,
            is_within_root=_always_within_root,
        )
        paths = {f.name for f in files}
        assert "data.txt" in paths
        assert "img.bin" not in paths

    async def test_dot_git_dir_skipped(self, temp_project):
        (temp_project / "README.md").write_text("readme")
        git_dir = temp_project / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("[core]")
        files = indexing_module.iter_searchable_files(
            temp_project,
            temp_project,
            is_within_root=_always_within_root,
        )
        paths = {f.name for f in files}
        assert "README.md" in paths
        assert "config" not in paths

    async def test_gitignore_respected(self, temp_project):
        (temp_project / ".gitignore").write_text("secret.txt\n")
        (temp_project / "visible.txt").write_text("hello")
        (temp_project / "secret.txt").write_text("password")
        files = indexing_module.iter_searchable_files(
            temp_project,
            temp_project,
            is_within_root=_always_within_root,
        )
        paths = {f.name for f in files}
        assert "visible.txt" in paths
        assert "secret.txt" not in paths


class TestBuildIndex:
    def _resolve(self, temp_project):
        def _fn(path: str) -> Path:
            return temp_project / path

        return _fn

    def _infer_root(self, temp_project):
        def _fn(target: Path) -> Path:
            return temp_project

        return _fn

    async def test_indexes_python_and_js_files(self, temp_project):
        mcp_server.clear_index_cache()
        pkg = temp_project / "pkg"
        pkg.mkdir()
        (pkg / "module.py").write_text("def hello():\n    return 'hi'\n")
        (pkg / "helper.js").write_text("function greet() {}\n")
        result = indexing_module.build_index(
            "pkg",
            resolve_path=self._resolve(temp_project),
            infer_project_root=self._infer_root(temp_project),
            is_within_root=_always_within_root,
        )
        assert result["source_files"] == 2
        assert result["python_files"] == 1
        assert result["cached"] is False

    async def test_cached_on_second_call(self, temp_project):
        mcp_server.clear_index_cache()
        pkg = temp_project / "pkg"
        pkg.mkdir()
        (pkg / "mod.py").write_text("def foo(): pass\n")
        resolve = self._resolve(temp_project)
        infer_root = self._infer_root(temp_project)
        first = indexing_module.build_index(
            "pkg",
            resolve_path=resolve,
            infer_project_root=infer_root,
            is_within_root=_always_within_root,
        )
        assert first["cached"] is False
        second = indexing_module.build_index(
            "pkg",
            resolve_path=resolve,
            infer_project_root=infer_root,
            is_within_root=_always_within_root,
        )
        assert second["cached"] is True
        assert second["source_files"] == first["source_files"]

    async def test_disk_cache_excludes_full_content_fields(self, temp_project, monkeypatch):
        cache_dir = temp_project / "cache"
        monkeypatch.setenv("CLAUDE_BRIDGE_CACHE_DIR", str(cache_dir))
        mcp_server.clear_index_cache()
        pkg = temp_project / "pkg"
        pkg.mkdir()
        (pkg / "mod.py").write_text("def login_user():\n    return 'auth session'\n")

        result = indexing_module.build_index(
            "pkg",
            resolve_path=self._resolve(temp_project),
            infer_project_root=self._infer_root(temp_project),
            is_within_root=_always_within_root,
        )

        cache_files = list(cache_dir.glob("index-*.json"))
        assert result["cached"] is False
        assert len(cache_files) == 1
        raw_cache = json.loads(cache_files[0].read_text())
        payload = raw_cache["payload"]
        assert "content_lower" not in payload["files"][0]
        assert "content" not in payload["files"][0]
        cached_file = payload["_file_cache"]["mod.py"]
        assert "content_lower" not in cached_file
        assert "content" not in cached_file
        assert "auth" in cached_file["content_tokens"]

    async def test_source_files_and_python_count(self, temp_project):
        mcp_server.clear_index_cache()
        pkg = temp_project / "pkg"
        pkg.mkdir()
        (pkg / "a.py").write_text("pass\n")
        (pkg / "b.py").write_text("pass\n")
        (pkg / "c.js").write_text("// js file\n")
        result = indexing_module.build_index(
            "pkg",
            resolve_path=self._resolve(temp_project),
            infer_project_root=self._infer_root(temp_project),
            is_within_root=_always_within_root,
        )
        assert result["source_files"] == 3
        assert result["python_files"] == 2
        assert {f["path"] for f in result["files"]} == {"a.py", "b.py", "c.js"}

    async def test_public_index_payload_paginates_files(self, temp_project):
        raw = {
            "root": ".",
            "files": [
                {
                    "path": f"{index}.py",
                    "functions": [],
                    "classes": [],
                    "imports": [],
                    "language": "python",
                    "parser_backend": "fallback",
                    "content_lower": "def hidden(): pass",
                    "content_tokens": ["hidden"],
                }
                for index in range(3)
            ],
            "python_files": 3,
            "source_files": 3,
            "parser_backends": ["fallback"],
            "cached": False,
            "_snapshot_key": "abc",
        }

        payload = indexing_module.public_index_payload(raw, offset=1, limit=1)

        assert [item["path"] for item in payload["files"]] == ["1.py"]
        assert payload["returned_files"] == 1
        assert payload["total_files"] == 3
        assert payload["files_truncated"] is True
        assert payload["next_file_offset"] == 2
        assert "content_lower" not in payload["files"][0]
        assert "content_tokens" not in payload["files"][0]
