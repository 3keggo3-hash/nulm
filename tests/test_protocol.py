"""Tests for MCP Tool implementation."""

import asyncio
import json
import tempfile
from types import SimpleNamespace
from pathlib import Path

import pytest

from claude_bridge import insights as insights_module
from claude_bridge import indexing as indexing_module
from claude_bridge import server as mcp_server
from claude_bridge import workflow_tools as workflow_tools_module


def parse_payload(result: str) -> dict:
    return json.loads(result)


class FakeTSNode:
    def __init__(
        self,
        node_type: str,
        text: str = "",
        *,
        children: list["FakeTSNode"] | None = None,
        fields: dict[str, "FakeTSNode"] | None = None,
    ) -> None:
        self.type = node_type
        self._text = text
        self.children = children or []
        self._fields = fields or {}
        self.start_byte = 0
        self.end_byte = len(text.encode("utf-8"))

    def child_by_field_name(self, name: str):
        return self._fields.get(name)


@pytest.fixture
def temp_project():
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        mcp_server.set_config(project_dir=project, auto_approve=True)
        yield project


class TestReadTool:
    async def test_read_existing_file(self, temp_project):
        test_file = temp_project / "test.txt"
        test_file.write_text("hello world")
        payload = parse_payload(await mcp_server.read_file("test.txt"))
        assert payload["ok"] is True
        assert payload["details"]["content"] == "hello world"
        assert payload["details"]["estimated_tokens"] >= 1
        assert payload["details"]["context_budget_tokens"] == 4000

    async def test_read_missing_file(self, temp_project):
        payload = parse_payload(await mcp_server.read_file("nonexistent.txt"))
        assert payload["ok"] is False
        assert payload["code"] == "file_not_found"

    async def test_read_non_utf8_file_returns_structured_error(self, temp_project):
        test_file = temp_project / "bad.txt"
        test_file.write_bytes(b"\xff\xfe\x00")
        payload = parse_payload(await mcp_server.read_file("bad.txt"))
        assert payload["ok"] is True
        assert "\ufffd" in payload["details"]["content"]

    async def test_read_absolute_file_in_allowed_secondary_root(self, temp_project):
        secondary_root = temp_project.parent / "secondary-root"
        secondary_root.mkdir(exist_ok=True)
        external_file = secondary_root / "notes.txt"
        external_file.write_text("hello from outside active root")
        mcp_server.set_config(
            project_dir=temp_project,
            allowed_roots=[temp_project, secondary_root],
            auto_approve=True,
        )

        payload = parse_payload(await mcp_server.read_file(str(external_file)))
        assert payload["ok"] is True
        assert payload["details"]["content"] == "hello from outside active root"

    async def test_read_large_file_returns_truncated_preview_metadata(self, temp_project):
        lines = [f"line {index}" for index in range(250)]
        (temp_project / "big.txt").write_text("\n".join(lines), encoding="utf-8")

        payload = parse_payload(await mcp_server.read_file("big.txt"))

        assert payload["ok"] is True
        assert payload["details"]["truncated"] is True
        assert payload["details"]["line_limit"] == 50
        assert payload["details"]["returned_line_count"] == 50
        assert "line 49" in payload["details"]["content"]
        assert "line 50" not in payload["details"]["content"]

    async def test_read_file_supports_negative_offset(self, temp_project):
        lines = [f"line {index}" for index in range(10)]
        (temp_project / "tail.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

        payload = parse_payload(await mcp_server.read_file("tail.txt", offset=-3, limit=3))

        assert payload["ok"] is True
        assert payload["details"]["offset"] == 7
        assert payload["details"]["returned_line_count"] == 3
        assert payload["details"]["content"] == "line 7\nline 8\nline 9\n"

    async def test_read_multiple_files_returns_multiple_results(self, temp_project):
        (temp_project / "a.txt").write_text("alpha\nbeta\n", encoding="utf-8")
        (temp_project / "b.txt").write_text("gamma\ndelta\n", encoding="utf-8")

        payload = parse_payload(
            await mcp_server.read_multiple_files(["a.txt", "b.txt"], offset=0, limit=1)
        )

        assert payload["ok"] is True
        assert payload["details"]["requested_paths"] == 2
        assert len(payload["details"]["files"]) == 2
        assert payload["details"]["files"][0]["content"] == "alpha\n"
        assert payload["details"]["files"][1]["content"] == "gamma\n"


class TestListTool:
    async def test_list_directory(self, temp_project):
        (temp_project / "file1.txt").write_text("content")
        (temp_project / "subdir").mkdir()
        payload = parse_payload(await mcp_server.list_directory("."))
        assert payload["ok"] is True
        entry_names = [entry["name"] for entry in payload["details"]["entries"]]
        assert "file1.txt" in entry_names
        assert "subdir" in entry_names

    async def test_list_missing_dir(self, temp_project):
        payload = parse_payload(await mcp_server.list_directory("missing/"))
        assert payload["ok"] is False
        assert payload["code"] == "directory_not_found"

    async def test_list_outside_project_returns_recovery_details(self, temp_project):
        payload = parse_payload(await mcp_server.list_directory("../"))
        assert payload["ok"] is False
        assert payload["code"] == "path_outside_project"
        assert payload["details"]["active_project_dir"] == str(temp_project.resolve())
        assert "workspace_status" in payload["details"]["suggested_next_tools"]

    async def test_list_directory_truncates_large_directories(self, temp_project):
        for index in range(205):
            (temp_project / f"file_{index:03d}.txt").write_text("x", encoding="utf-8")

        payload = parse_payload(await mcp_server.list_directory("."))

        assert payload["ok"] is True
        assert payload["details"]["truncated"] is True
        assert payload["details"]["entry_limit"] == 200
        assert payload["details"]["returned_entry_count"] == 200
        assert payload["details"]["entry_count"] == 205


class TestWriteTool:
    async def test_write_new_file(self, temp_project):
        payload = parse_payload(
            await mcp_server.write_file("notes.txt", "hello from bridge", overwrite=False)
        )
        assert payload["ok"] is True
        assert (temp_project / "notes.txt").read_text() == "hello from bridge"

    async def test_write_rejects_existing_without_overwrite(self, temp_project):
        (temp_project / "notes.txt").write_text("old")
        payload = parse_payload(await mcp_server.write_file("notes.txt", "new"))
        assert payload["ok"] is False
        assert payload["code"] == "file_exists"

    async def test_write_handles_file_created_after_approval(self, temp_project, monkeypatch):
        def file_created_between_checks(*args, **kwargs):
            raise FileExistsError("created concurrently")

        from claude_bridge.file_tools import _write as write_mod

        monkeypatch.setattr(write_mod, "_write_text_exact", file_created_between_checks)

        payload = parse_payload(await mcp_server.write_file("notes.txt", "new"))

        assert payload["ok"] is False
        assert payload["code"] == "file_exists"

    async def test_write_blocks_sensitive_patterns(self, temp_project):
        payload = parse_payload(
            await mcp_server.write_file("notes.txt", 'API_KEY = "secret-value"')
        )
        assert payload["ok"] is False
        assert payload["code"] == "secret_pattern_detected"

    async def test_write_file_warns_when_content_exceeds_max_lines(self, temp_project):
        content = "\n".join(f"line {index}" for index in range(3))

        payload = parse_payload(
            await mcp_server.write_file("large.txt", content, overwrite=False, max_lines=2)
        )

        assert payload["ok"] is True
        assert payload["details"]["warnings"][0]["code"] == "content_exceeds_max_lines"
        assert payload["details"]["warnings"][0]["recommended_next_tool"] == "patch_file"

    async def test_write_file_rejects_invalid_max_lines(self, temp_project):
        payload = parse_payload(
            await mcp_server.write_file("large.txt", "hello", overwrite=False, max_lines=0)
        )

        assert payload["ok"] is False
        assert payload["code"] == "invalid_max_lines"

    async def test_move_file_moves_path_inside_workspace(self, temp_project):
        (temp_project / "old.txt").write_text("hello", encoding="utf-8")

        payload = parse_payload(
            await mcp_server.move_file("old.txt", "renamed/new.txt", create_parents=True)
        )

        assert payload["ok"] is True
        assert not (temp_project / "old.txt").exists()
        assert (temp_project / "renamed" / "new.txt").read_text(encoding="utf-8") == "hello"

    async def test_move_file_rejects_same_source_and_destination(self, temp_project):
        (temp_project / "same.txt").write_text("hello", encoding="utf-8")

        payload = parse_payload(await mcp_server.move_file("same.txt", "same.txt", overwrite=True))

        assert payload["ok"] is False
        assert payload["code"] == "same_path"
        assert (temp_project / "same.txt").read_text(encoding="utf-8") == "hello"

    async def test_copy_path_copies_file_inside_workspace(self, temp_project):
        (temp_project / "source.txt").write_text("hello", encoding="utf-8")

        payload = parse_payload(
            await mcp_server.copy_path("source.txt", "copies/source.txt", create_parents=True)
        )

        assert payload["ok"] is True
        assert (temp_project / "source.txt").read_text(encoding="utf-8") == "hello"
        assert (temp_project / "copies" / "source.txt").read_text(encoding="utf-8") == "hello"

    async def test_copy_path_rejects_same_source_and_destination(self, temp_project):
        (temp_project / "same.txt").write_text("hello", encoding="utf-8")

        payload = parse_payload(await mcp_server.copy_path("same.txt", "same.txt", overwrite=True))

        assert payload["ok"] is False
        assert payload["code"] == "same_path"


class TestSearchTool:
    async def test_search_in_files_finds_matches(self, temp_project):
        src = temp_project / "src"
        src.mkdir()
        (src / "a.py").write_text("TODO: fix login flow\n")
        (src / "b.py").write_text("print('no match')\n")

        payload = parse_payload(await mcp_server.search_in_files("TODO", path="src"))
        assert payload["ok"] is True
        assert payload["details"]["results"][0]["path"] == "a.py"
        assert payload["details"]["results"][0]["line_number"] == 1
        assert payload["details"]["search_backend"] in {"ripgrep", "python"}
        assert payload["details"]["estimated_tokens"] >= 1

    async def test_search_in_files_respects_include_glob(self, temp_project):
        src = temp_project / "src"
        src.mkdir()
        (src / "a.py").write_text("needle\n")
        (src / "a.txt").write_text("needle\n")

        payload = parse_payload(
            await mcp_server.search_in_files("needle", path="src", include_glob="*.py")
        )
        assert payload["ok"] is True
        assert [item["path"] for item in payload["details"]["results"]] == ["a.py"]

    async def test_search_in_files_reports_truncation_metadata(self, temp_project):
        src = temp_project / "src"
        src.mkdir()
        (src / "a.py").write_text("needle\nneedle\n")
        (src / "b.py").write_text("needle\n")

        payload = parse_payload(await mcp_server.search_in_files("needle", path="src", limit=1))
        assert payload["ok"] is True
        assert payload["details"]["truncated"] is True
        assert payload["details"]["files_searched"] >= 1
        assert len(payload["details"]["results"]) == 1

    async def test_search_in_files_supports_offset_pagination(self, temp_project):
        src = temp_project / "src"
        src.mkdir()
        (src / "a.py").write_text("needle one\nneedle two\nneedle three\n", encoding="utf-8")

        first = parse_payload(
            await mcp_server.search_in_files("needle", path="src", offset=0, limit=2)
        )
        assert first["ok"] is True
        assert [item["line"] for item in first["details"]["results"]] == [
            "needle one",
            "needle two",
        ]
        assert first["details"]["offset"] == 0
        assert first["details"]["next_offset"] == 2
        assert first["details"]["truncated"] is True

        second = parse_payload(
            await mcp_server.search_in_files("needle", path="src", offset=2, limit=2)
        )
        assert second["ok"] is True
        assert [item["line"] for item in second["details"]["results"]] == ["needle three"]
        assert second["details"]["offset"] == 2
        assert second["details"]["next_offset"] == -1
        assert second["details"]["truncated"] is False

    async def test_search_in_files_rejects_negative_offset(self, temp_project):
        src = temp_project / "src"
        src.mkdir()
        (src / "a.py").write_text("needle\n", encoding="utf-8")

        payload = parse_payload(await mcp_server.search_in_files("needle", path="src", offset=-1))

        assert payload["ok"] is False
        assert payload["code"] == "invalid_offset"

    async def test_search_in_files_falls_back_to_python_when_rg_is_unavailable(
        self, temp_project, monkeypatch
    ):
        src = temp_project / "src"
        src.mkdir()
        (src / "a.py").write_text("needle\n", encoding="utf-8")
        monkeypatch.setattr("claude_bridge.file_tools._helpers._rg_binary", lambda: None)

        payload = parse_payload(await mcp_server.search_in_files("needle", path="src"))

        assert payload["ok"] is True
        assert payload["details"]["search_backend"] == "python"


class TestPreviewPatchTool:
    async def test_preview_patch_returns_diff_and_risk(self, temp_project):
        test_file = temp_project / "module.py"
        test_file.write_text("def value():\n    return 1\n")
        payload = parse_payload(await mcp_server.preview_patch("module.py", "return 1", "return 2"))
        assert payload["ok"] is True
        assert "--- module.py" in payload["details"]["diff"]
        assert payload["details"]["risk"]["risk_level"] == "low"
        assert "return 1" in test_file.read_text()

    async def test_preview_patch_returns_fuzzy_suggestions_when_exact_match_is_missing(
        self, temp_project
    ):
        test_file = temp_project / "module.py"
        test_file.write_text("def value():\n    return 10\n", encoding="utf-8")

        payload = parse_payload(
            await mcp_server.preview_patch("module.py", "return 11", "return 2")
        )

        assert payload["ok"] is False
        assert payload["code"] == "search_fuzzy_match_available"
        assert payload["details"]["suggestions"]


class TestIndexTool:
    async def test_index_codebase_finds_python_symbols(self, temp_project):
        source_dir = temp_project / "pkg"
        source_dir.mkdir()
        (source_dir / "module.py").write_text(
            "import os\n\nclass Greeter:\n    pass\n\ndef hello():\n    return 'hi'\n"
        )

        payload = parse_payload(await mcp_server.index_codebase("pkg"))
        assert payload["ok"] is True
        assert payload["details"]["python_files"] == 1
        indexed = payload["details"]["files"][0]
        assert indexed["path"] == "module.py"
        assert "content" not in indexed
        assert "content_tokens" not in indexed
        assert "path_tokens" not in indexed
        assert indexed["classes"] == ["Greeter"]
        assert indexed["functions"] == ["hello"]
        assert indexed["imports"] == ["os"]
        assert indexed["parser_backend"] in ("fallback", "tree_sitter")

    async def test_index_codebase_caches_on_second_call(self, temp_project):
        source_dir = temp_project / "pkg"
        source_dir.mkdir()
        (source_dir / "module.py").write_text("def foo(): pass\n")

        mcp_server.clear_index_cache()
        first = parse_payload(await mcp_server.index_codebase("pkg"))
        assert first["ok"] is True
        assert first["details"]["cached"] is False

        second = parse_payload(await mcp_server.index_codebase("pkg"))
        assert second["ok"] is True
        assert second["details"]["cached"] is True

    async def test_index_codebase_invalidates_cache_when_file_changes(self, temp_project):
        source_dir = temp_project / "pkg"
        source_dir.mkdir()
        (source_dir / "module.py").write_text("def foo(): pass\n")

        mcp_server.clear_index_cache()
        first = parse_payload(await mcp_server.index_codebase("pkg"))
        assert first["details"]["cached"] is False

        import time

        time.sleep(0.02)
        (source_dir / "module.py").write_text("def bar(): pass\n")

        second = parse_payload(await mcp_server.index_codebase("pkg"))
        assert second["details"]["cached"] is False

    async def test_index_codebase_rejects_file_target(self, temp_project):
        (temp_project / "notes.txt").write_text("hello")
        payload = parse_payload(await mcp_server.index_codebase("notes.txt"))
        assert payload["ok"] is False
        assert payload["code"] == "not_a_directory"

    async def test_index_codebase_rejects_unexpected_payload(self, temp_project, monkeypatch):
        monkeypatch.setattr(mcp_server, "_build_index", lambda path: {"unexpected": []})

        payload = parse_payload(await mcp_server.index_codebase("."))

        assert payload["ok"] is False
        assert payload["code"] == "invalid_index_payload"

    async def test_index_codebase_respects_gitignore(self, temp_project):
        (temp_project / ".gitignore").write_text("ignored.py\nsecret.txt\n")
        pkg_dir = temp_project / "pkg"
        pkg_dir.mkdir()
        (pkg_dir / "module.py").write_text("def foo(): pass\n")
        (pkg_dir / "ignored.py").write_text("def bar(): pass\n")
        (pkg_dir / "secret.txt").write_text("password")

        mcp_server.clear_index_cache()
        payload = parse_payload(await mcp_server.index_codebase("."))
        assert payload["ok"] is True
        assert payload["details"]["python_files"] == 1
        assert payload["details"]["files"][0]["path"] == "pkg/module.py"

    async def test_index_codebase_respects_gitignore_directory_pattern(self, temp_project):
        (temp_project / ".gitignore").write_text("build/\n")
        build_dir = temp_project / "build"
        build_dir.mkdir()
        pkg_dir = temp_project / "pkg"
        pkg_dir.mkdir()
        (build_dir / "generated.py").write_text("def generated(): pass\n")
        (pkg_dir / "module.py").write_text("def foo(): pass\n")

        mcp_server.clear_index_cache()
        payload = parse_payload(await mcp_server.index_codebase("."))
        assert payload["ok"] is True
        paths = [item["path"] for item in payload["details"]["files"]]
        assert "pkg/module.py" in paths
        assert "build/generated.py" not in paths

    async def test_index_codebase_respects_gitignore_negation(self, temp_project):
        (temp_project / ".gitignore").write_text("*.py\n!keep.py\n")
        pkg_dir = temp_project / "pkg"
        pkg_dir.mkdir()
        (pkg_dir / "skip.py").write_text("def skip(): pass\n")
        (temp_project / "keep.py").write_text("def keep(): pass\n")

        mcp_server.clear_index_cache()
        payload = parse_payload(await mcp_server.index_codebase("."))
        assert payload["ok"] is True
        paths = [item["path"] for item in payload["details"]["files"]]
        assert "keep.py" in paths
        assert "pkg/skip.py" not in paths

    async def test_index_codebase_includes_gdscript_files(self, temp_project):
        source_dir = temp_project / "game"
        source_dir.mkdir()
        (source_dir / "grid_manager.gd").write_text(
            "class_name GridManager\nextends Node2D\n\nfunc build_grid():\n    pass\n"
        )

        payload = parse_payload(await mcp_server.index_codebase("game"))
        assert payload["ok"] is True
        assert payload["details"]["source_files"] == 1
        indexed = payload["details"]["files"][0]
        assert indexed["path"] == "grid_manager.gd"
        assert indexed["language"] == "gdscript"
        assert indexed["classes"] == ["GridManager"]
        assert indexed["functions"] == ["build_grid"]

    async def test_index_codebase_includes_typescript_symbols(self, temp_project):
        source_dir = temp_project / "web"
        source_dir.mkdir()
        (source_dir / "auth.ts").write_text(
            'import React from "react"\n'
            'import { login } from "./api"\n\n'
            "export class AuthService {}\n\n"
            "export async function loginUser(email: string) {\n"
            "    return login(email)\n"
            "}\n\n"
            "export const buildSession = async (token: string) => loginUser(token)\n"
        )

        payload = parse_payload(await mcp_server.index_codebase("web"))
        assert payload["ok"] is True
        assert payload["details"]["source_files"] == 1
        indexed = payload["details"]["files"][0]
        assert indexed["path"] == "auth.ts"
        assert indexed["language"] == "typescript"
        assert indexed["classes"] == ["AuthService"]
        assert "loginUser" in indexed["functions"]
        assert indexed["imports"] == ["api", "react"]

    async def test_index_codebase_includes_rust_symbols(self, temp_project):
        source_dir = temp_project / "rustapp"
        source_dir.mkdir()
        (source_dir / "auth.rs").write_text(
            "use std::collections::HashMap;\n"
            "use crate::session::SessionStore;\n\n"
            "pub struct AuthService;\n\n"
            "pub async fn login_user() {}\n"
            "fn build_session() {}\n"
        )

        payload = parse_payload(await mcp_server.index_codebase("rustapp"))
        assert payload["ok"] is True
        indexed = payload["details"]["files"][0]
        assert indexed["language"] == "rust"
        assert indexed["classes"] == ["AuthService"]
        assert indexed["functions"] == ["build_session", "login_user"]
        assert indexed["imports"] == ["crate", "std"]

    async def test_index_codebase_includes_go_symbols(self, temp_project):
        source_dir = temp_project / "goapp"
        source_dir.mkdir()
        (source_dir / "auth.go").write_text(
            "package auth\n\n"
            "import (\n"
            '    "context"\n'
            '    store "github.com/example/project/store"\n'
            ")\n\n"
            "type AuthService struct{}\n\n"
            "func LoginUser(ctx context.Context) error { return nil }\n"
            "func (s *AuthService) BuildSession() {}\n"
        )

        payload = parse_payload(await mcp_server.index_codebase("goapp"))
        assert payload["ok"] is True
        indexed = payload["details"]["files"][0]
        assert indexed["language"] == "go"
        assert indexed["classes"] == ["AuthService"]
        assert indexed["functions"] == ["BuildSession", "LoginUser"]
        assert indexed["imports"] == ["context", "store"]

    async def test_index_codebase_includes_java_symbols(self, temp_project):
        source_dir = temp_project / "javaapp"
        source_dir.mkdir()
        (source_dir / "AuthService.java").write_text(
            "import java.util.List;\n"
            "import com.example.auth.SessionStore;\n"
            "public class AuthService {\n"
            "    public void loginUser() {}\n"
            "}\n"
        )
        payload = parse_payload(await mcp_server.index_codebase("javaapp"))
        indexed = payload["details"]["files"][0]
        assert indexed["language"] == "java"
        assert indexed["classes"] == ["AuthService"]
        assert "loginUser" in indexed["functions"]
        assert indexed["imports"] == ["com", "java"]

    async def test_index_codebase_includes_kotlin_symbols(self, temp_project):
        source_dir = temp_project / "kotlinapp"
        source_dir.mkdir()
        (source_dir / "AuthService.kt").write_text(
            "import kotlin.collections.List\n"
            "import com.example.auth.SessionStore\n"
            "class AuthService\n"
            "fun loginUser() {}\n"
        )
        payload = parse_payload(await mcp_server.index_codebase("kotlinapp"))
        indexed = payload["details"]["files"][0]
        assert indexed["language"] == "kotlin"
        assert indexed["classes"] == ["AuthService"]
        assert indexed["functions"] == ["loginUser"]
        assert indexed["imports"] == ["com", "kotlin"]

    async def test_index_codebase_includes_csharp_symbols(self, temp_project):
        source_dir = temp_project / "csharpapp"
        source_dir.mkdir()
        (source_dir / "AuthService.cs").write_text(
            "using System.Collections.Generic;\n"
            "using Example.Auth;\n"
            "public class AuthService {\n"
            "    public void LoginUser() {}\n"
            "}\n"
        )
        payload = parse_payload(await mcp_server.index_codebase("csharpapp"))
        indexed = payload["details"]["files"][0]
        assert indexed["language"] == "csharp"
        assert indexed["classes"] == ["AuthService"]
        assert "LoginUser" in indexed["functions"]
        assert indexed["imports"] == ["Example", "System"]

    async def test_index_codebase_includes_ruby_symbols(self, temp_project):
        source_dir = temp_project / "rubyapp"
        source_dir.mkdir()
        (source_dir / "auth_service.rb").write_text(
            'require "json"\nclass AuthService\n  def login_user\n  end\nend\n'
        )
        payload = parse_payload(await mcp_server.index_codebase("rubyapp"))
        indexed = payload["details"]["files"][0]
        assert indexed["language"] == "ruby"
        assert indexed["classes"] == ["AuthService"]
        assert "login_user" in indexed["functions"]
        assert "json" in indexed.get("imports", []) or indexed.get("imports") == []

    async def test_index_codebase_includes_php_symbols(self, temp_project):
        source_dir = temp_project / "phpapp"
        source_dir.mkdir()
        (source_dir / "AuthService.php").write_text(
            "<?php\n"
            "use App\\Session\\Store;\n"
            "class AuthService {\n"
            "    public function loginUser() {}\n"
            "}\n"
        )
        payload = parse_payload(await mcp_server.index_codebase("phpapp"))
        indexed = payload["details"]["files"][0]
        assert indexed["language"] == "php"
        assert indexed["classes"] == ["AuthService"]
        assert indexed["functions"] == ["loginUser"]
        assert indexed["imports"] == ["App"]

    async def test_index_codebase_skips_non_utf8_files(self, temp_project):
        source_dir = temp_project / "pkg"
        source_dir.mkdir()
        (source_dir / "valid.py").write_text("def ok(): pass\n")
        (source_dir / "broken.py").write_bytes(b"\xff\xfe\x00\x00")

        payload = parse_payload(await mcp_server.index_codebase("pkg"))
        assert payload["ok"] is True
        assert payload["details"]["python_files"] == 1
        assert payload["details"]["files"][0]["path"] == "valid.py"

    async def test_index_codebase_prefers_tree_sitter_when_available(
        self, temp_project, monkeypatch
    ):
        source_dir = temp_project / "pkg"
        source_dir.mkdir()
        (source_dir / "module.py").write_text("def hello():\n    return 'hi'\n")

        monkeypatch.setattr(
            indexing_module,
            "_extract_tree_sitter_symbols",
            lambda file, source: {
                "functions": ["hello"],
                "classes": [],
                "imports": [],
                "language": "python",
            },
        )

        payload = parse_payload(await mcp_server.index_codebase("pkg"))
        assert payload["ok"] is True
        assert payload["details"]["parser_backends"] == ["tree_sitter"]
        assert payload["details"]["files"][0]["parser_backend"] == "tree_sitter"

    async def test_index_codebase_falls_back_when_tree_sitter_unavailable(
        self, temp_project, monkeypatch
    ):
        source_dir = temp_project / "pkg"
        source_dir.mkdir()
        (source_dir / "module.py").write_text("def hello():\n    return 'hi'\n")

        monkeypatch.setattr(
            indexing_module, "_extract_tree_sitter_symbols", lambda file, source: None
        )

        payload = parse_payload(await mcp_server.index_codebase("pkg"))
        assert payload["ok"] is True
        assert payload["details"]["parser_backends"] == ["fallback"]

    def test_load_tree_sitter_parser_uses_first_available_backend(self, monkeypatch):
        fake_module = SimpleNamespace(get_parser=lambda language_name: f"parser:{language_name}")

        def fake_import_module(name: str):
            if name == "tree_sitter_languages":
                raise ImportError("not installed")
            if name == "tree_sitter_language_pack":
                return fake_module
            raise ImportError(name)

        monkeypatch.setattr(indexing_module.importlib, "import_module", fake_import_module)

        parser = indexing_module._load_tree_sitter_parser("python")
        assert parser == "parser:python"

    def test_extract_tree_sitter_symbols_uses_language_specific_rules_for_typescript(
        self, monkeypatch
    ):
        function_name = FakeTSNode("identifier", "loginUser")
        class_name = FakeTSNode("identifier", "AuthService")
        import_source = FakeTSNode("string", '"@org/auth"')
        ts_tree = SimpleNamespace(
            root_node=FakeTSNode(
                "program",
                children=[
                    FakeTSNode("function_declaration", fields={"name": function_name}),
                    FakeTSNode("class_declaration", fields={"name": class_name}),
                    FakeTSNode("import_statement", fields={"source": import_source}),
                ],
            )
        )
        fake_parser = SimpleNamespace(parse=lambda source_bytes: ts_tree)
        monkeypatch.setattr(
            indexing_module, "_load_tree_sitter_parser", lambda language_name: fake_parser
        )

        symbols = indexing_module._extract_tree_sitter_symbols(Path("auth.ts"), "placeholder")
        assert symbols is not None
        assert symbols["functions"] == ["loginUser"]
        assert symbols["classes"] == ["AuthService"]
        assert symbols["imports"] == ["@org/auth"]

    def test_extract_tree_sitter_symbols_uses_language_specific_rules_for_java(self, monkeypatch):
        method_name = FakeTSNode("identifier", "loginUser")
        class_name = FakeTSNode("identifier", "AuthService")
        import_path = FakeTSNode("scoped_identifier", "com.example.auth")
        java_tree = SimpleNamespace(
            root_node=FakeTSNode(
                "program",
                children=[
                    FakeTSNode("method_declaration", fields={"name": method_name}),
                    FakeTSNode("class_declaration", fields={"name": class_name}),
                    FakeTSNode("import_declaration", fields={"path": import_path}),
                ],
            )
        )
        fake_parser = SimpleNamespace(parse=lambda source_bytes: java_tree)
        monkeypatch.setattr(
            indexing_module, "_load_tree_sitter_parser", lambda language_name: fake_parser
        )

        symbols = indexing_module._extract_tree_sitter_symbols(
            Path("AuthService.java"), "placeholder"
        )
        assert symbols is not None
        assert symbols["functions"] == ["loginUser"]
        assert symbols["classes"] == ["AuthService"]
        assert symbols["imports"] == ["com"]

    def test_extract_tree_sitter_symbols_uses_language_specific_rules_for_csharp(self, monkeypatch):
        method_name = FakeTSNode("identifier", "LoginUser")
        class_name = FakeTSNode("identifier", "AuthService")
        import_name = FakeTSNode("qualified_name", "System.Collections")
        cs_tree = SimpleNamespace(
            root_node=FakeTSNode(
                "compilation_unit",
                children=[
                    FakeTSNode("method_declaration", fields={"name": method_name}),
                    FakeTSNode("class_declaration", fields={"name": class_name}),
                    FakeTSNode("using_directive", fields={"name": import_name}),
                ],
            )
        )
        fake_parser = SimpleNamespace(parse=lambda source_bytes: cs_tree)
        monkeypatch.setattr(
            indexing_module, "_load_tree_sitter_parser", lambda language_name: fake_parser
        )

        symbols = indexing_module._extract_tree_sitter_symbols(
            Path("AuthService.cs"), "placeholder"
        )
        assert symbols is not None
        assert symbols["functions"] == ["LoginUser"]
        assert symbols["classes"] == ["AuthService"]
        assert symbols["imports"] == ["System"]

    def test_extract_tree_sitter_symbols_uses_language_specific_rules_for_javascript(
        self, monkeypatch
    ):
        function_name = FakeTSNode("identifier", "loginUser")
        class_name = FakeTSNode("identifier", "AuthService")
        import_source = FakeTSNode("string", '"react"')
        js_tree = SimpleNamespace(
            root_node=FakeTSNode(
                "program",
                children=[
                    FakeTSNode("function_declaration", fields={"name": function_name}),
                    FakeTSNode("class_declaration", fields={"name": class_name}),
                    FakeTSNode("import_statement", fields={"source": import_source}),
                ],
            )
        )
        fake_parser = SimpleNamespace(parse=lambda source_bytes: js_tree)
        monkeypatch.setattr(
            indexing_module, "_load_tree_sitter_parser", lambda language_name: fake_parser
        )

        symbols = indexing_module._extract_tree_sitter_symbols(Path("auth.js"), "placeholder")
        assert symbols is not None
        assert symbols["functions"] == ["loginUser"]
        assert symbols["classes"] == ["AuthService"]
        assert symbols["imports"] == ["react"]

    def test_extract_tree_sitter_symbols_uses_language_specific_rules_for_tsx(self, monkeypatch):
        function_name = FakeTSNode("identifier", "LoginPanel")
        class_name = FakeTSNode("identifier", "AuthShell")
        import_source = FakeTSNode("string", '"./components/LoginPanel"')
        tsx_tree = SimpleNamespace(
            root_node=FakeTSNode(
                "program",
                children=[
                    FakeTSNode("function_declaration", fields={"name": function_name}),
                    FakeTSNode("class_declaration", fields={"name": class_name}),
                    FakeTSNode("import_statement", fields={"source": import_source}),
                ],
            )
        )
        fake_parser = SimpleNamespace(parse=lambda source_bytes: tsx_tree)
        monkeypatch.setattr(
            indexing_module, "_load_tree_sitter_parser", lambda language_name: fake_parser
        )

        symbols = indexing_module._extract_tree_sitter_symbols(Path("auth.tsx"), "placeholder")
        assert symbols is not None
        assert symbols["functions"] == ["LoginPanel"]
        assert symbols["classes"] == ["AuthShell"]
        assert symbols["imports"] == ["components"]

    def test_extract_tree_sitter_symbols_uses_language_specific_rules_for_ruby(self, monkeypatch):
        method_name = FakeTSNode("identifier", "login_user")
        class_name = FakeTSNode("constant", "AuthService")
        import_arg = FakeTSNode("string", '"json"')
        ruby_tree = SimpleNamespace(
            root_node=FakeTSNode(
                "program",
                children=[
                    FakeTSNode("method", fields={"name": method_name}),
                    FakeTSNode("class", fields={"name": class_name}),
                    FakeTSNode("call", fields={"argument": import_arg}),
                ],
            )
        )
        fake_parser = SimpleNamespace(parse=lambda source_bytes: ruby_tree)
        monkeypatch.setattr(
            indexing_module, "_load_tree_sitter_parser", lambda language_name: fake_parser
        )

        symbols = indexing_module._extract_tree_sitter_symbols(
            Path("auth_service.rb"), "placeholder"
        )
        assert symbols is not None
        assert symbols["functions"] == ["login_user"]
        assert symbols["classes"] == ["AuthService"]
        assert symbols["imports"] == ["json"]

    def test_extract_tree_sitter_symbols_uses_language_specific_rules_for_php(self, monkeypatch):
        function_name = FakeTSNode("identifier", "loginUser")
        class_name = FakeTSNode("identifier", "AuthService")
        import_name = FakeTSNode("qualified_name", "App\\Support\\Auth")
        php_tree = SimpleNamespace(
            root_node=FakeTSNode(
                "program",
                children=[
                    FakeTSNode("function_definition", fields={"name": function_name}),
                    FakeTSNode("class_declaration", fields={"name": class_name}),
                    FakeTSNode("namespace_use_declaration", fields={"clause": import_name}),
                ],
            )
        )
        fake_parser = SimpleNamespace(parse=lambda source_bytes: php_tree)
        monkeypatch.setattr(
            indexing_module, "_load_tree_sitter_parser", lambda language_name: fake_parser
        )

        symbols = indexing_module._extract_tree_sitter_symbols(
            Path("AuthService.php"), "placeholder"
        )
        assert symbols is not None
        assert symbols["functions"] == ["loginUser"]
        assert symbols["classes"] == ["AuthService"]
        assert symbols["imports"] == ["App"]

    def test_extract_tree_sitter_symbols_uses_language_specific_rules_for_kotlin(self, monkeypatch):
        function_name = FakeTSNode("identifier", "loginUser")
        class_name = FakeTSNode("identifier", "AuthService")
        import_name = FakeTSNode("scoped_identifier", "com.example.auth")
        kotlin_tree = SimpleNamespace(
            root_node=FakeTSNode(
                "source_file",
                children=[
                    FakeTSNode("function_declaration", fields={"name": function_name}),
                    FakeTSNode("class_declaration", fields={"name": class_name}),
                    FakeTSNode("import_header", fields={"path": import_name}),
                ],
            )
        )
        fake_parser = SimpleNamespace(parse=lambda source_bytes: kotlin_tree)
        monkeypatch.setattr(
            indexing_module, "_load_tree_sitter_parser", lambda language_name: fake_parser
        )

        symbols = indexing_module._extract_tree_sitter_symbols(
            Path("AuthService.kt"), "placeholder"
        )
        assert symbols is not None
        assert symbols["functions"] == ["loginUser"]
        assert symbols["classes"] == ["AuthService"]
        assert symbols["imports"] == ["com"]

    def test_extract_tree_sitter_symbols_uses_language_specific_rules_for_rust(self, monkeypatch):
        function_name = FakeTSNode("identifier", "login_user")
        class_name = FakeTSNode("type_identifier", "AuthService")
        import_name = FakeTSNode("scoped_identifier", "crate::auth::service")
        rust_tree = SimpleNamespace(
            root_node=FakeTSNode(
                "source_file",
                children=[
                    FakeTSNode("function_item", fields={"name": function_name}),
                    FakeTSNode("struct_item", fields={"name": class_name}),
                    FakeTSNode("use_declaration", fields={"argument": import_name}),
                ],
            )
        )
        fake_parser = SimpleNamespace(parse=lambda source_bytes: rust_tree)
        monkeypatch.setattr(
            indexing_module, "_load_tree_sitter_parser", lambda language_name: fake_parser
        )

        symbols = indexing_module._extract_tree_sitter_symbols(Path("auth.rs"), "placeholder")
        assert symbols is not None
        assert symbols["functions"] == ["login_user"]
        assert symbols["classes"] == ["AuthService"]
        assert symbols["imports"] == ["crate"]

    def test_extract_tree_sitter_symbols_uses_language_specific_rules_for_go(self, monkeypatch):
        function_name = FakeTSNode("identifier", "LoginUser")
        class_name = FakeTSNode("type_identifier", "AuthService")
        import_name = FakeTSNode("interpreted_string_literal", '"net/http"')
        go_tree = SimpleNamespace(
            root_node=FakeTSNode(
                "source_file",
                children=[
                    FakeTSNode("function_declaration", fields={"name": function_name}),
                    FakeTSNode("type_spec", fields={"name": class_name}),
                    FakeTSNode("import_spec", fields={"path": import_name}),
                ],
            )
        )
        fake_parser = SimpleNamespace(parse=lambda source_bytes: go_tree)
        monkeypatch.setattr(
            indexing_module, "_load_tree_sitter_parser", lambda language_name: fake_parser
        )

        symbols = indexing_module._extract_tree_sitter_symbols(Path("auth.go"), "placeholder")
        assert symbols is not None
        assert symbols["functions"] == ["LoginUser"]
        assert symbols["classes"] == ["AuthService"]
        assert symbols["imports"] == ["http"]


class TestRelevantFilesTool:
    async def test_find_relevant_files_ranks_symbol_matches(self, temp_project):
        pkg = temp_project / "pkg"
        pkg.mkdir()
        (pkg / "auth_service.py").write_text(
            "class AuthManager:\n    pass\n\ndef login_user():\n    return True\n"
        )
        (pkg / "payments.py").write_text("def charge_card():\n    return True\n")

        payload = parse_payload(
            await mcp_server.find_relevant_files(query="login auth", path="pkg", limit=3)
        )

        assert payload["ok"] is True
        assert payload["details"]["strategy"] == "two_phase_token_scoring"
        assert payload["details"]["results"][0]["path"] == "auth_service.py"
        assert "login" in payload["details"]["results"][0]["matched_terms"]

    async def test_find_relevant_files_rejects_empty_query(self, temp_project):
        payload = parse_payload(await mcp_server.find_relevant_files(query="   ", path="."))
        assert payload["ok"] is False
        assert payload["code"] == "empty_query"

    async def test_find_relevant_files_rejects_invalid_limit(self, temp_project):
        payload = parse_payload(await mcp_server.find_relevant_files(query="auth", limit=0))
        assert payload["ok"] is False
        assert payload["code"] == "invalid_limit"

    async def test_find_relevant_files_matches_docstring_content(self, temp_project):
        pkg = temp_project / "pkg"
        pkg.mkdir()
        (pkg / "auth_service.py").write_text(
            'def authenticate():\n    """Handle user login authentication."""\n    pass\n'
        )
        (pkg / "payments.py").write_text("def charge_card():\n    pass\n")

        payload = parse_payload(
            await mcp_server.find_relevant_files(query="user login", path="pkg", limit=3)
        )

        assert payload["ok"] is True
        assert payload["details"]["strategy"] == "two_phase_token_scoring"
        assert payload["details"]["context_budget_tokens"] == 4000
        assert payload["details"]["results"][0]["path"] == "auth_service.py"

    async def test_find_relevant_files_prefers_tree_sitter_symbol_matches(self, monkeypatch):
        monkeypatch.setattr(
            mcp_server,
            "_build_index",
            lambda path: {
                "files": [
                    {
                        "path": "auth_service.ts",
                        "functions": ["loginUser"],
                        "classes": [],
                        "imports": [],
                        "content": "const noop = true",
                        "parser_backend": "tree_sitter",
                    },
                    {
                        "path": "legacy_auth.ts",
                        "functions": ["loginUser"],
                        "classes": [],
                        "imports": [],
                        "content": "const noop = true",
                        "parser_backend": "fallback",
                    },
                ]
            },
        )

        payload = parse_payload(
            await mcp_server.find_relevant_files(query="login", path="pkg", limit=2)
        )
        assert payload["ok"] is True
        assert payload["details"]["results"][0]["path"] == "auth_service.ts"
        assert payload["details"]["results"][0]["parser_backend"] == "tree_sitter"
        assert payload["details"]["results"][0]["score"] > payload["details"]["results"][1]["score"]
        assert "login" in payload["details"]["results"][0]["matched_terms"]

    async def test_find_relevant_files_matches_gdscript_symbols(self, temp_project):
        game = temp_project / "game"
        game.mkdir()
        (game / "grid_manager.gd").write_text(
            "class_name GridManager\nextends Node2D\n\nconst GRID_SIZE := 6\n\nfunc build_grid():\n    pass\n"
        )

        payload = parse_payload(
            await mcp_server.find_relevant_files(
                query="GRID_SIZE build grid",
                path="game",
                limit=3,
            )
        )

        assert payload["ok"] is True
        assert payload["details"]["results"][0]["path"] == "grid_manager.gd"
        assert "grid_size" in payload["details"]["results"][0]["matched_terms"]

    async def test_find_relevant_files_matches_typescript_symbols(self, temp_project):
        web = temp_project / "web"
        web.mkdir()
        (web / "auth.ts").write_text(
            'import { createSession } from "./session"\n'
            "export class AuthGateway {}\n"
            "export const loginUser = async (email: string) => createSession(email)\n"
        )
        (web / "payments.ts").write_text("export const chargeCard = async () => true\n")

        payload = parse_payload(
            await mcp_server.find_relevant_files(
                query="login session auth",
                path="web",
                limit=3,
            )
        )

        assert payload["ok"] is True
        assert payload["details"]["results"][0]["path"] == "auth.ts"
        assert "login" in payload["details"]["results"][0]["matched_terms"]
        assert "auth" in payload["details"]["results"][0]["matched_terms"]

    async def test_find_relevant_files_matches_rust_symbols(self, temp_project):
        rustapp = temp_project / "rustapp"
        rustapp.mkdir()
        (rustapp / "auth.rs").write_text(
            "use crate::session::SessionStore;\n"
            "pub struct AuthService;\n"
            "pub async fn login_user() {}\n"
        )
        (rustapp / "payments.rs").write_text("pub fn charge_card() {}\n")

        payload = parse_payload(
            await mcp_server.find_relevant_files(
                query="login auth session",
                path="rustapp",
                limit=3,
            )
        )

        assert payload["ok"] is True
        assert payload["details"]["results"][0]["path"] == "auth.rs"
        assert "login" in payload["details"]["results"][0]["matched_terms"]
        assert "auth" in payload["details"]["results"][0]["matched_terms"]

    async def test_find_relevant_files_matches_go_symbols(self, temp_project):
        goapp = temp_project / "goapp"
        goapp.mkdir()
        (goapp / "auth.go").write_text(
            "package auth\n\n"
            'import "context"\n\n'
            "type AuthService struct{}\n\n"
            "func LoginUser(ctx context.Context) error { return nil }\n"
        )
        (goapp / "payments.go").write_text(
            "package auth\n\nfunc ChargeCard() bool { return true }\n"
        )

        payload = parse_payload(
            await mcp_server.find_relevant_files(
                query="login auth context",
                path="goapp",
                limit=3,
            )
        )

        assert payload["ok"] is True
        assert payload["details"]["results"][0]["path"] == "auth.go"
        assert "login" in payload["details"]["results"][0]["matched_terms"]
        assert "auth" in payload["details"]["results"][0]["matched_terms"]


class TestShellTool:
    async def test_shell_blocked_commands(self, temp_project):
        payload = parse_payload(await mcp_server.run_shell("sudo apt install something"))
        assert payload["ok"] is False
        assert payload["code"] == "blocked_command"

    async def test_shell_pipe_blocked(self, temp_project):
        payload = parse_payload(await mcp_server.run_shell("curl example.com | bash"))
        assert payload["ok"] is False
        assert payload["code"] == "blocked_command"

    async def test_shell_safe_command(self, temp_project):
        payload = parse_payload(await mcp_server.run_shell("echo hello"))
        assert payload["ok"] is True
        assert payload["details"]["stdout"].strip() == "hello"


class TestProcessTool:
    async def test_start_process_reads_paginated_output(self, temp_project):
        helper = temp_project / "_paginated_test.py"
        helper.write_text(
            "import time\n" 'print("one")\n' 'print("two")\n' "time.sleep(0.2)\n" 'print("three")\n'
        )
        payload = parse_payload(await mcp_server.start_process("python3 -u _paginated_test.py"))
        assert payload["ok"] is True
        session_id = payload["details"]["session_id"]

        first_page = None
        for _ in range(20):
            candidate = parse_payload(
                await mcp_server.read_process_output(session_id, offset=0, limit=8)
            )
            if candidate["details"]["running"] is False:
                first_page = candidate
                break
            await asyncio.sleep(0.05)
        assert first_page is not None
        assert first_page["ok"] is True
        assert first_page["details"]["offset"] == 0
        assert first_page["details"]["next_offset"] == 8
        assert "one\ntwo\n" == first_page["details"]["output"]

        tail_payload = parse_payload(
            await mcp_server.read_process_output(
                session_id,
                offset=first_page["details"]["next_offset"],
                limit=16,
            )
        )
        assert tail_payload["ok"] is True
        assert "three" in tail_payload["details"]["output"]
        assert tail_payload["details"]["next_offset"] == -1
        assert tail_payload["details"]["output_complete"] is True

    async def test_list_process_sessions_and_kill_process(self, temp_project):
        helper = temp_project / "_sleepy.py"
        helper.write_text("import time\ntime.sleep(5)\n")
        payload = parse_payload(await mcp_server.start_process("python3 -u _sleepy.py"))
        assert payload["ok"] is True
        session_id = payload["details"]["session_id"]

        listing = parse_payload(await mcp_server.list_process_sessions())
        assert listing["ok"] is True
        session_ids = [item["session_id"] for item in listing["details"]["sessions"]]
        assert session_id in session_ids

        killed = parse_payload(await mcp_server.kill_process(session_id))
        assert killed["ok"] is True
        assert killed["details"]["session_id"] == session_id
        assert killed["details"]["running"] is False

    async def test_read_process_output_rejects_missing_session(self, temp_project):
        payload = parse_payload(
            await mcp_server.read_process_output("missing-session", offset=0, limit=20)
        )
        assert payload["ok"] is False
        assert payload["code"] == "process_session_not_found"

    async def test_interact_with_process_sends_input(self, temp_project):
        payload = parse_payload(await mcp_server.start_process("echo ready"))
        assert payload["ok"] is True
        session_id = payload["details"]["session_id"]

        await asyncio.sleep(0.2)

        output = parse_payload(
            await mcp_server.read_process_output(session_id, offset=0, limit=200)
        )
        assert "ready" in output["details"]["output"]

    async def test_interact_with_process_rejects_missing_session(self, temp_project):
        payload = parse_payload(await mcp_server.interact_with_process("missing", input="test"))
        assert payload["ok"] is False
        assert payload["code"] == "process_session_not_found"

    async def test_interact_with_process_rejects_long_input(self, temp_project):
        payload = parse_payload(await mcp_server.start_process("true"))
        session_id = payload["details"]["session_id"]
        long_input = "x" * 5000
        result = parse_payload(await mcp_server.interact_with_process(session_id, input=long_input))
        assert result["ok"] is False
        assert result["code"] == "input_too_long"

    async def test_interact_with_process_can_close_stdin(self, temp_project):
        payload = parse_payload(await mcp_server.start_process("echo done"))
        assert payload["ok"] is True
        session_id = payload["details"]["session_id"]

        await asyncio.sleep(0.2)

        output = parse_payload(
            await mcp_server.read_process_output(session_id, offset=0, limit=200)
        )
        assert "done" in output["details"]["output"]


class TestPatchTool:
    async def test_patch_simple_replace(self, temp_project):
        test_file = temp_project / "test.py"
        test_file.write_text("def foo():\n    pass")
        result = await mcp_server.patch_file(
            file="test.py",
            search="def foo():\n    pass",
            replace="def foo():\n    return 42",
        )
        payload = parse_payload(result)
        assert payload["ok"] is True
        assert "Patched" in payload["message"]
        assert "return 42" in test_file.read_text()

    async def test_patch_ambiguous_search(self, temp_project):
        test_file = temp_project / "test.py"
        test_file.write_text("pass\npass")
        result = await mcp_server.patch_file(file="test.py", search="pass", replace="changed")
        payload = parse_payload(result)
        assert payload["ok"] is False
        assert payload["code"] == "search_ambiguous"

    async def test_patch_python_syntax_check(self, temp_project):
        test_file = temp_project / "test.py"
        test_file.write_text("def valid():\n    pass")
        result = await mcp_server.patch_file(
            file="test.py",
            search="def valid():\n    pass",
            replace="def valid(:\n    invalid syntax here",
        )
        payload = parse_payload(result)
        assert payload["ok"] is False
        assert payload["code"] == "python_syntax_error"

    async def test_patch_file_preserves_crlf_line_endings(self, temp_project):
        test_file = temp_project / "windows.py"
        test_file.write_bytes(b"def value():\r\n    return 1\r\n")
        result = await mcp_server.patch_file(
            file="windows.py",
            search="return 1",
            replace="return 2",
        )
        payload = parse_payload(result)
        assert payload["ok"] is True
        assert test_file.read_bytes() == b"def value():\r\n    return 2\r\n"


class TestAgentLoopStepTool:
    async def test_agent_loop_step_runs_patch_and_validation(self, temp_project):
        test_file = temp_project / "module.py"
        test_file.write_text("def value():\n    return 1\n")

        payload = parse_payload(
            await mcp_server.run_agent_loop_step(
                file="module.py",
                search="return 1",
                replace="return 2",
                validation_command="pytest --version",
                iteration=1,
                max_iterations=2,
            )
        )

        assert payload["ok"] is True
        assert payload["details"]["patch_result"]["ok"] is True
        assert payload["details"]["validation_result"]["ok"] is True
        assert payload["details"]["decision"] == "stop_success"
        assert "return 2" in test_file.read_text()

    async def test_agent_loop_step_can_continue_after_failed_validation(self, temp_project):
        test_file = temp_project / "module.py"
        test_file.write_text("def value():\n    return 1\n")

        payload = parse_payload(
            await mcp_server.run_agent_loop_step(
                file="module.py",
                search="return 1",
                replace="return 2",
                validation_command="python3 -m pytest missing_tests",
                iteration=1,
                max_iterations=2,
            )
        )

        assert payload["ok"] is True
        assert payload["details"]["validation_result"]["ok"] is False
        assert payload["details"]["decision"] == "continue"

    async def test_agent_loop_step_rejects_invalid_budget(self, temp_project):
        payload = parse_payload(
            await mcp_server.run_agent_loop_step(
                file="missing.py",
                search="x",
                replace="y",
                validation_command="git diff",
                iteration=2,
                max_iterations=1,
            )
        )
        assert payload["ok"] is False
        assert payload["code"] == "invalid_iteration_budget"


class TestAgentLoopSessionTool:
    async def test_agent_loop_session_accepts_structured_steps(self, temp_project):
        test_file = temp_project / "module.py"
        test_file.write_text("def value():\n    return 1\n")
        payload = parse_payload(
            await mcp_server.run_agent_loop_session(
                steps=[
                    {
                        "file": "module.py",
                        "search": "return 1",
                        "replace": "return 2",
                        "validation_command": "pytest --version",
                    }
                ],
                max_iterations=1,
            )
        )
        assert payload["ok"] is True
        assert payload["details"]["final_decision"] == "stop_success"
        assert "return 2" in test_file.read_text()

    async def test_agent_loop_session_stops_after_success(self, temp_project):
        test_file = temp_project / "module.py"
        test_file.write_text("def value():\n    return 1\n")
        steps = json.dumps(
            [
                {
                    "file": "module.py",
                    "search": "return 1",
                    "replace": "return 2",
                    "validation_command": "pytest --version",
                },
                {
                    "file": "module.py",
                    "search": "return 2",
                    "replace": "return 3",
                    "validation_command": "pytest --version",
                },
            ]
        )

        payload = parse_payload(await mcp_server.run_agent_loop_session(steps, max_iterations=2))
        assert payload["ok"] is True
        assert payload["details"]["executed_steps"] == 1
        assert payload["details"]["final_decision"] == "stop_success"
        assert payload["details"]["session_summary"] == {
            "executed_steps": 1,
            "final_decision": "stop_success",
            "files_touched": ["module.py"],
            "last_successful_file": "module.py",
            "last_validation_ok": True,
            "last_validation_command": "pytest --version",
            "remaining_budget": 1,
            "next_recommended_action": "stop",
            "results_compacted": False,
            "compacted_steps": 0,
            "retained_recent_steps": 1,
            "handoff_summary": (
                "Executed 1 step(s); final decision: stop_success. "
                "Files touched: module.py. "
                "Last validation passed via pytest --version. "
                "Next action: stop."
            ),
        }
        assert "return 2" in test_file.read_text()

    async def test_agent_loop_session_can_continue_to_second_step(self, temp_project):
        test_file = temp_project / "module.py"
        test_file.write_text("def value():\n    return 1\n")
        steps = json.dumps(
            [
                {
                    "file": "module.py",
                    "search": "return 1",
                    "replace": "return 2",
                    "validation_command": "python3 -m pytest missing_tests",
                },
                {
                    "file": "module.py",
                    "search": "return 2",
                    "replace": "return 3",
                    "validation_command": "pytest --version",
                },
            ]
        )

        payload = parse_payload(await mcp_server.run_agent_loop_session(steps, max_iterations=2))
        assert payload["ok"] is True
        assert payload["details"]["executed_steps"] == 2
        assert payload["details"]["final_decision"] == "stop_success"
        assert payload["details"]["session_summary"]["files_touched"] == ["module.py"]
        assert payload["details"]["session_summary"]["last_successful_file"] == "module.py"
        assert payload["details"]["session_summary"]["last_validation_ok"] is True
        assert payload["details"]["session_summary"]["remaining_budget"] == 0
        assert payload["details"]["session_summary"]["results_compacted"] is False
        assert "return 3" in test_file.read_text()

    async def test_agent_loop_session_compacts_older_results_after_threshold(self, temp_project):
        test_file = temp_project / "module.py"
        test_file.write_text("def value():\n    return 1\n")
        steps = json.dumps(
            [
                {
                    "file": "module.py",
                    "search": "return 1",
                    "replace": "return 2",
                    "validation_command": "python3 -m pytest missing_tests",
                },
                {
                    "file": "module.py",
                    "search": "return 2",
                    "replace": "return 3",
                    "validation_command": "python3 -m pytest missing_tests",
                },
                {
                    "file": "module.py",
                    "search": "return 3",
                    "replace": "return 4",
                    "validation_command": "pytest --version",
                },
            ]
        )

        payload = parse_payload(
            await mcp_server.run_agent_loop_session(
                steps,
                max_iterations=3,
                compact_threshold=2,
                keep_recent_results=1,
            )
        )
        assert payload["ok"] is True
        assert payload["details"]["results_compacted"] is True
        assert payload["details"]["compacted_steps"] == 2
        assert len(payload["details"]["compacted_history"]) == 2
        assert len(payload["details"]["results"]) == 1
        assert payload["details"]["results"][0]["details"]["iteration"] == 3
        assert payload["details"]["session_summary"]["results_compacted"] is True
        assert payload["details"]["session_summary"]["compacted_steps"] == 2
        assert payload["details"]["session_summary"]["retained_recent_steps"] == 1

    async def test_agent_loop_session_rejects_invalid_json(self, temp_project):
        payload = parse_payload(
            await mcp_server.run_agent_loop_session("{bad json}", max_iterations=2)
        )
        assert payload["ok"] is False
        assert payload["code"] == "invalid_steps_json"

    async def test_agent_loop_session_rejects_missing_fields(self, temp_project):
        steps = json.dumps([{"file": "module.py"}])
        payload = parse_payload(await mcp_server.run_agent_loop_session(steps, max_iterations=1))
        assert payload["ok"] is False
        assert payload["code"] == "invalid_step_fields"


class TestWorkflowTool:
    async def test_review_workflow_returns_prompt(self, temp_project):
        payload = parse_payload(
            await mcp_server.run_workflow(
                mode="review",
                target="src/",
                option="bugs and missing tests",
            )
        )
        assert payload["ok"] is True
        assert payload["details"]["mode"] == "review"
        assert payload["details"]["recommended_tools"] == ["list_directory", "read_file"]
        assert len(payload["details"]["steps"]) >= 3
        assert len(payload["details"]["examples"]) >= 2
        assert len(payload["details"]["warnings"]) >= 2
        assert payload["details"]["quality_bar"][0] == "correctness"
        assert "review" in payload.get("details", {}).get(
            "prompt_entrypoint", payload["details"]["mode"]
        )
        assert "Target: src/" in payload["details"]["prompt"]
        assert "Focus: bugs and missing tests" in payload["details"]["prompt"]
        assert (
            "Do not stop after finding a single matching constant" in payload["details"]["prompt"]
        )

    async def test_prompt_shortcuts_reports_catalog_and_client_side_limits(self, temp_project):
        payload = parse_payload(await mcp_server.prompt_shortcuts())
        assert payload["ok"] is True
        shortcut_names = [item["name"] for item in payload["details"]["shortcuts"]]
        assert "compact" in shortcut_names
        assert "shadow" in shortcut_names
        assert "platform" in shortcut_names
        client_only_names = [item["name"] for item in payload["details"]["client_side_only"]]
        assert "/model" in client_only_names
        assert "Lowest-token path is a client-native MCP prompt" in payload["details"]["notes"][0]

    async def test_quality_workflow_returns_prompt(self, temp_project):
        payload = parse_payload(
            await mcp_server.run_workflow(
                mode="quality",
                target="src/",
                option="correctness and regression safety",
            )
        )
        assert payload["ok"] is True
        assert payload["details"]["mode"] == "quality"
        assert "Target: src/" in payload["details"]["prompt"]
        assert "Focus: correctness and regression safety" in payload["details"]["prompt"]

    async def test_orchestrate_workflow_returns_prompt(self, temp_project):
        payload = parse_payload(
            await mcp_server.run_workflow(
                mode="orchestrate",
                target="src/",
                option="split by modules and define integration gates",
            )
        )
        assert payload["ok"] is True
        assert payload["details"]["mode"] == "orchestrate"
        assert (
            payload["details"]["orchestration_rules"][0]
            == "split only along clear ownership boundaries"
        )
        assert "parallelizable tracks" in payload["details"]["prompt"]

    async def test_agent_loop_workflow_returns_policy(self, temp_project):
        payload = parse_payload(
            await mcp_server.run_workflow(
                mode="agent_loop",
                target="src/",
                option="fix the failing behavior with bounded iterations",
                max_iterations=4,
            )
        )
        assert payload["ok"] is True
        assert payload["details"]["mode"] == "agent_loop"
        assert payload["details"]["max_iterations"] == 4
        assert payload["details"]["agent_loop_policy"]["max_iterations"] == 4
        assert payload["details"]["agent_loop_policy"]["loop_shape"] == [
            "inspect",
            "patch",
            "validate",
            "decide",
        ]
        assert "iteration cap" in payload["details"]["prompt"]

    async def test_agent_loop_rejects_invalid_iteration_budget(self, temp_project):
        payload = parse_payload(await mcp_server.run_workflow(mode="agent_loop", max_iterations=0))
        assert payload["ok"] is False
        assert payload["code"] == "invalid_max_iterations"

    async def test_agent_loop_execute_returns_loop_plan_for_directory(self, temp_project):
        src_dir = temp_project / "src"
        src_dir.mkdir()
        (src_dir / "module.py").write_text("def hello():\n    return 'hi'\n")
        (temp_project / "tests").mkdir()

        payload = parse_payload(
            await mcp_server.run_workflow(
                mode="agent_loop",
                target=".",
                option="fix the failing behavior with bounded iterations",
                max_iterations=3,
                execute=True,
            )
        )

        assert payload["ok"] is True
        loop_plan = payload["details"]["execution"]["loop_plan"]
        assert loop_plan["iteration_budget"] == 3
        assert loop_plan["current_iteration"] == 1
        assert "python3 -m pytest" in loop_plan["validation_commands"]
        assert loop_plan["proposed_patch_strategy"].startswith(
            "make the smallest reversible change"
        )

    async def test_agent_loop_execute_returns_loop_plan_for_file(self, temp_project):
        target_file = temp_project / "module.py"
        target_file.write_text("def hello():\n    return 'hi'\n")

        payload = parse_payload(
            await mcp_server.run_workflow(
                mode="agent_loop",
                target="module.py",
                max_iterations=2,
                execute=True,
            )
        )

        assert payload["ok"] is True
        loop_plan = payload["details"]["execution"]["loop_plan"]
        assert loop_plan["iteration_budget"] == 2
        assert loop_plan["focus_target"] == "module.py"
        assert "git diff" in loop_plan["validation_commands"]

    async def test_explain_workflow_uses_language(self, temp_project):
        payload = parse_payload(
            await mcp_server.run_workflow(
                mode="explain",
                target="src/claude_bridge/server.py",
                option="a junior Python developer",
                language="English",
            )
        )
        assert payload["ok"] is True
        assert payload["details"]["mode"] == "explain"
        assert payload["details"]["recommended_tools"] == ["list_directory", "read_file"]
        assert "Response language: English" in payload["details"]["prompt"]

    async def test_todo_workflow_recommends_shell_when_useful(self, temp_project):
        payload = parse_payload(await mcp_server.run_workflow(mode="todo", target="."))
        assert payload["ok"] is True
        assert payload["details"]["recommended_tools"] == [
            "list_directory",
            "read_file",
            "run_shell",
        ]
        assert payload["details"]["steps"][1] == "Search for TODO-style markers."
        assert (
            'run_workflow(mode="todo", target=".", option="TODO, FIXME")'
            in payload["details"]["examples"]
        )
        assert len(payload["details"]["warnings"]) >= 2

    async def test_workflow_execute_reads_file_for_file_target(self, temp_project):
        target_file = temp_project / "notes.txt"
        target_file.write_text("hello execute mode")

        payload = parse_payload(
            await mcp_server.run_workflow(mode="review", target="notes.txt", execute=True)
        )

        assert payload["ok"] is True
        assert payload["details"]["execute"] is True
        assert payload["details"]["execution"]["performed_actions"] == ["read_file"]
        assert (
            payload["details"]["execution"]["results"][0]["details"]["content"]
            == "hello execute mode"
        )

    async def test_workflow_execute_reads_godot_supplemental_files_for_gd_target(
        self, temp_project
    ):
        script_file = temp_project / "grid_manager.gd"
        project_file = temp_project / "project.godot"
        export_file = temp_project / "export_presets.cfg"
        script_file.write_text("const GRID_SIZE := 6\n")
        project_file.write_text('[application]\nconfig/name="Tertis"\n')
        export_file.write_text('[preset.0]\nname="Android"\n')

        payload = parse_payload(
            await mcp_server.run_workflow(mode="review", target="grid_manager.gd", execute=True)
        )

        assert payload["ok"] is True
        assert payload["details"]["execution"]["performed_actions"] == [
            "read_file",
            "read_file",
            "read_file",
        ]
        contents = [
            item["details"]["content"]
            for item in payload["details"]["execution"]["results"]
            if item["ok"] and "content" in item["details"]
        ]
        assert "const GRID_SIZE := 6\n" in contents
        assert '[application]\nconfig/name="Tertis"\n' in contents
        assert '[preset.0]\nname="Android"\n' in contents
        assert payload["details"]["project_type"] == "godot"

    async def test_workflow_execute_lists_directory_for_directory_target(self, temp_project):
        (temp_project / "subdir").mkdir()
        (temp_project / "subdir" / "edge_tests.py").write_text(
            "class AuthManager:\n    pass\n\ndef login_user():\n    return True\n"
        )
        (temp_project / "subdir" / "misc.py").write_text("def helper():\n    return None\n")

        payload = parse_payload(
            await mcp_server.run_workflow(mode="review", target="subdir", execute=True)
        )

        assert payload["ok"] is True
        assert payload["details"]["execution"]["performed_actions"][:2] == [
            "list_directory",
            "find_relevant_files",
        ]
        entries = payload["details"]["execution"]["results"][0]["details"]["entries"]
        assert len(entries) == 2
        relevant = payload["details"]["execution"]["results"][1]["details"]["results"]
        assert relevant[0]["path"] == "edge_tests.py"
        assert "tests" in payload["details"]["execution"]["results"][1]["details"]["terms"]
        planned_targets = payload["details"]["execution"]["results"][2]["details"]["targets"]
        assert "subdir/edge_tests.py" in planned_targets
        read_contents = [
            item["details"]["content"]
            for item in payload["details"]["execution"]["results"][3:]
            if item["ok"] and "content" in item["details"]
        ]
        assert any("login_user" in content for content in read_contents)

    async def test_workflow_execute_reads_python_project_context(self, temp_project):
        module = temp_project / "module.py"
        pyproject = temp_project / "pyproject.toml"
        module.write_text("def hello():\n    return 'hi'\n")
        pyproject.write_text('[project]\nname = "bridge"\n')

        payload = parse_payload(
            await mcp_server.run_workflow(mode="review", target="module.py", execute=True)
        )

        assert payload["ok"] is True
        assert payload["details"]["project_type"] == "python"
        contents = [
            item["details"]["content"]
            for item in payload["details"]["execution"]["results"]
            if item["ok"] and "content" in item["details"]
        ]
        assert '[project]\nname = "bridge"\n' in contents

    async def test_agent_loop_plan_uses_node_validation_when_package_json_exists(
        self, temp_project
    ):
        src_dir = temp_project / "src"
        src_dir.mkdir()
        (temp_project / "package.json").write_text('{"name":"demo","scripts":{"test":"vitest"}}')
        (src_dir / "app.ts").write_text("export const x = 1;\n")

        payload = parse_payload(
            await mcp_server.run_workflow(mode="agent_loop", target="src", execute=True)
        )

        assert payload["ok"] is True
        loop_plan = payload["details"]["execution"]["loop_plan"]
        assert payload["details"]["project_type"] == "node"
        assert "npm test" in loop_plan["validation_commands"]
        assert "git diff" in loop_plan["validation_commands"]

    async def test_build_context_pack_for_python_project(self, temp_project):
        src_dir = temp_project / "src"
        tests_dir = temp_project / "tests"
        src_dir.mkdir()
        tests_dir.mkdir()
        (temp_project / "pyproject.toml").write_text('[project]\nname = "bridge"\n')
        (temp_project / "README.md").write_text("# Demo\n")
        (src_dir / "auth.py").write_text("def login_user():\n    return True\n")
        (tests_dir / "test_auth.py").write_text("def test_login_user():\n    assert True\n")

        payload = parse_payload(
            await mcp_server.build_context_pack(
                target="src",
                goal="understand auth flow",
                max_files=6,
            )
        )

        assert payload["ok"] is True
        assert payload["details"]["project_type"] == "python"
        assert "pyproject.toml" in payload["details"]["config_files"]
        assert "tests/test_auth.py" in payload["details"]["test_files"]
        assert "python3 -m pytest" in payload["details"]["validation_commands"]
        assert "README.md" in payload["details"]["selected_files"]
        assert "git_status" in payload["details"]
        assert payload["details"]["estimated_tokens"] >= 1
        assert payload["details"]["file_estimates"]
        assert payload["details"]["cached"] is False

        second = parse_payload(
            await mcp_server.build_context_pack(
                target="src",
                goal="understand auth flow",
                max_files=6,
            )
        )
        assert second["ok"] is True
        assert second["details"]["cached"] is True

    async def test_build_context_pack_restores_from_disk_cache(self, temp_project, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_CACHE_DIR", str(temp_project / ".cache"))
        src_dir = temp_project / "src"
        tests_dir = temp_project / "tests"
        src_dir.mkdir()
        tests_dir.mkdir()
        (temp_project / "pyproject.toml").write_text('[project]\nname = "bridge"\n')
        (src_dir / "auth.py").write_text("def login_user():\n    return True\n")
        (tests_dir / "test_auth.py").write_text("def test_login_user():\n    assert True\n")

        first = parse_payload(
            await mcp_server.build_context_pack(
                target="src", goal="understand auth flow", max_files=6
            )
        )
        assert first["ok"] is True
        assert first["details"]["cached"] is False

        workflow_tools_module._CONTEXT_PACK_CACHE.clear()
        second = parse_payload(
            await mcp_server.build_context_pack(
                target="src", goal="understand auth flow", max_files=6
            )
        )
        assert second["ok"] is True
        assert second["details"]["cached"] is True

    async def test_build_context_pack_for_node_project(self, temp_project):
        app_dir = temp_project / "app"
        app_dir.mkdir()
        (temp_project / "package.json").write_text('{"name":"demo","scripts":{"test":"vitest"}}')
        (temp_project / "tsconfig.json").write_text('{"compilerOptions":{}}\n')
        (app_dir / "client.ts").write_text("export const run = () => true;\n")
        (temp_project / "client.spec.ts").write_text("it('works', () => {})\n")

        payload = parse_payload(
            await mcp_server.build_context_pack(
                target="app",
                goal="inspect frontend entry flow",
                max_files=5,
            )
        )

        assert payload["ok"] is True
        assert payload["details"]["project_type"] == "node"
        assert "package.json" in payload["details"]["config_files"]
        assert "npm test" in payload["details"]["validation_commands"]
        assert "client.spec.ts" in payload["details"]["test_files"]

    async def test_build_context_pack_for_rust_project(self, temp_project):
        src_dir = temp_project / "src"
        src_dir.mkdir()
        tests_dir = temp_project / "tests"
        tests_dir.mkdir()
        (temp_project / "Cargo.toml").write_text('[package]\nname = "bridge"\nversion = "0.1.0"\n')
        (temp_project / "Cargo.lock").write_text("# lockfile\n")
        (src_dir / "auth.rs").write_text("pub async fn login_user() {}\n")
        (tests_dir / "auth_spec.rs").write_text("#[test]\nfn login_user_works() {}\n")

        payload = parse_payload(
            await mcp_server.build_context_pack(
                target="src",
                goal="inspect rust auth flow",
                max_files=6,
            )
        )

        assert payload["ok"] is True
        assert payload["details"]["project_type"] == "rust"
        assert "Cargo.toml" in payload["details"]["config_files"]
        assert "Cargo.lock" in payload["details"]["config_files"]
        assert "cargo test" in payload["details"]["validation_commands"]
        assert "tests/auth_spec.rs" in payload["details"]["test_files"]

    async def test_build_context_pack_for_go_project(self, temp_project):
        app_dir = temp_project / "app"
        app_dir.mkdir()
        (temp_project / "go.mod").write_text("module github.com/example/bridge\n")
        (temp_project / "go.sum").write_text("example v1.0.0 h1:abc\n")
        (app_dir / "auth.go").write_text("package app\n\nfunc LoginUser() error { return nil }\n")
        (temp_project / "auth_test.go").write_text(
            "package app\n\nfunc TestLoginUser(t *testing.T) {}\n"
        )

        payload = parse_payload(
            await mcp_server.build_context_pack(
                target="app",
                goal="inspect go auth flow",
                max_files=6,
            )
        )

        assert payload["ok"] is True
        assert payload["details"]["project_type"] == "go"
        assert "go.mod" in payload["details"]["config_files"]
        assert "go.sum" in payload["details"]["config_files"]
        assert "go test ./..." in payload["details"]["validation_commands"]
        assert "auth_test.go" in payload["details"]["test_files"]

    async def test_build_context_pack_skips_python_files_with_syntax_errors(self, temp_project):
        src_dir = temp_project / "src"
        src_dir.mkdir()
        (src_dir / "broken.py").write_text("def broken(:\n")
        (src_dir / "valid.py").write_text("def valid():\n    return True\n")

        payload = parse_payload(
            await mcp_server.build_context_pack(
                target="src",
                goal="inspect valid module",
                max_files=5,
            )
        )

        assert payload["ok"] is True
        assert "src/valid.py" in payload["details"]["selected_files"]

    async def test_build_context_pack_rejects_missing_target(self, temp_project):
        payload = parse_payload(
            await mcp_server.build_context_pack(
                target="missing-dir",
                goal="inspect auth flow",
                max_files=4,
            )
        )

        assert payload["ok"] is False
        assert payload["code"] == "path_not_found"

    async def test_build_context_pack_handles_invalid_find_relevant_payload(
        self, temp_project, monkeypatch
    ):
        src_dir = temp_project / "src"
        src_dir.mkdir()

        async def _invalid_find_relevant_files(*args, **kwargs):
            return "{not-json"

        monkeypatch.setattr(mcp_server, "find_relevant_files", _invalid_find_relevant_files)

        payload = parse_payload(
            await mcp_server.build_context_pack(
                target="src",
                goal="inspect auth flow",
                max_files=4,
            )
        )

        assert payload["ok"] is False
        assert payload["code"] == "invalid_tool_payload"

    async def test_build_context_pack_uses_secondary_allowed_root_context(self, temp_project):
        secondary_root = temp_project.parent / f"{temp_project.name}-secondary-root"
        secondary_root.mkdir()
        app_dir = secondary_root / "app"
        app_dir.mkdir()
        (secondary_root / "package.json").write_text('{"name":"demo","scripts":{"test":"vitest"}}')
        (secondary_root / "README.md").write_text("# Secondary\n")
        (secondary_root / "client.spec.ts").write_text("it('works', () => {})\n")
        (app_dir / "client.ts").write_text("export const run = () => true;\n")
        mcp_server.set_config(
            project_dir=temp_project,
            allowed_roots=[temp_project, secondary_root],
            auto_approve=True,
        )

        payload = parse_payload(
            await mcp_server.build_context_pack(
                target=str(secondary_root),
                goal="inspect frontend entry flow",
                max_files=5,
            )
        )

        assert payload["ok"] is True
        assert payload["details"]["project_type"] == "node"
        assert (
            str((secondary_root / "package.json").resolve()) in payload["details"]["config_files"]
        )
        assert str((secondary_root / "README.md").resolve()) in payload["details"]["selected_files"]
        assert (
            str((secondary_root / "client.spec.ts").resolve()) in payload["details"]["test_files"]
        )
        assert "npm test" in payload["details"]["validation_commands"]

    async def test_narrow_context_respects_budget(self, temp_project):
        src_dir = temp_project / "src"
        src_dir.mkdir()
        (temp_project / "pyproject.toml").write_text('[project]\nname = "bridge"\n')
        (src_dir / "auth.py").write_text("def login_user():\n    return True\n" * 50)
        (src_dir / "billing.py").write_text("def charge_card():\n    return True\n" * 50)

        payload = parse_payload(
            await mcp_server.narrow_context(
                goal="understand auth flow",
                target="src",
                budget_tokens=40,
                max_files=4,
                include_tests=False,
                include_docs=False,
            )
        )

        assert payload["ok"] is True
        assert payload["details"]["context_budget_tokens"] == 40
        assert payload["details"]["selected_files"]
        assert payload["details"]["budget_spent"] <= 40
        assert "source_context_pack_files" in payload["details"]

    async def test_narrow_context_handles_invalid_context_pack_payload(
        self, temp_project, monkeypatch
    ):
        async def _invalid_context_pack(**kwargs):
            return "{not-json"

        # Re-register workflow tools with a fake build_context_pack_impl
        # that returns invalid JSON, then call the returned narrow_context
        # directly to verify the error path is exercised.
        tools = mcp_server.register_workflow_tools(
            mcp=mcp_server.mcp,
            tool_options=mcp_server._tool_options,
            audit_tool_call=mcp_server._audit_tool_call,
            json_response=mcp_server._json_response,
            run_agent_loop_step_impl=mcp_server._run_agent_loop_step_impl,
            build_context_pack_impl=_invalid_context_pack,
            build_validation_suggestions_impl=(mcp_server._build_validation_suggestions_impl),
            run_agent_loop_session_impl=mcp_server._run_agent_loop_session_impl,
            run_workflow_impl=mcp_server._run_workflow_impl,
            patch_file_getter=lambda: mcp_server.patch_file,
            run_shell_getter=lambda: mcp_server.run_shell,
            read_file_getter=lambda: mcp_server.read_file,
            list_directory_getter=lambda: mcp_server.list_directory,
            find_relevant_files_getter=lambda: mcp_server.find_relevant_files,
            resolve_path=mcp_server._resolve_path,
            path_from_active_root=mcp_server._path_from_active_root,
            project_dir=mcp_server._project_dir,
            infer_project_root=mcp_server._infer_project_root,
            iter_searchable_files=mcp_server._iter_searchable_files,
            git_status_snapshot=mcp_server._git_status_snapshot,
            effective_budget_tokens=mcp_server._effective_budget_tokens,
            safe_json_object_load=mcp_server._safe_json_object_load,
            smart_budget_metadata=mcp_server._smart_budget_metadata,
        )
        fake_narrow_context = tools["narrow_context"]

        payload = parse_payload(
            await fake_narrow_context(
                goal="understand auth flow",
                target=".",
                budget_tokens=40,
            )
        )

        assert payload["ok"] is False
        assert payload["code"] == "invalid_tool_payload"

    async def test_run_workflow_returns_structured_error_for_path_outside_project(
        self, temp_project
    ):
        payload = parse_payload(
            await mcp_server.run_workflow(mode="review", target="../outside-project")
        )

        assert payload["ok"] is False
        assert payload["code"] == "path_outside_project"
        assert payload["details"]["active_project_dir"] == str(temp_project.resolve())
        assert "switch_project_root" in payload["details"]["suggested_next_tools"]

    async def test_run_workflow_uses_secondary_allowed_root_project_type(self, temp_project):
        secondary_root = temp_project.parent / f"{temp_project.name}-secondary-root"
        secondary_root.mkdir()
        (secondary_root / "package.json").write_text('{"name":"demo","scripts":{"test":"vitest"}}')
        target_file = secondary_root / "app.ts"
        target_file.write_text("export const x = 1;\n")
        mcp_server.set_config(
            project_dir=temp_project,
            allowed_roots=[temp_project, secondary_root],
            auto_approve=True,
        )

        payload = parse_payload(
            await mcp_server.run_workflow(mode="review", target=str(target_file))
        )

        assert payload["ok"] is True
        assert payload["details"]["project_type"] == "node"

    async def test_run_workflow_caches_non_execute_planning(self, temp_project):
        src_dir = temp_project / "src"
        src_dir.mkdir()
        (src_dir / "module.py").write_text("def value():\n    return 1\n")

        first = parse_payload(await mcp_server.run_workflow(mode="review", target="src"))
        second = parse_payload(await mcp_server.run_workflow(mode="review", target="src"))

        assert first["ok"] is True
        assert first["details"]["cached"] is False
        assert second["ok"] is True
        assert second["details"]["cached"] is True
        assert second["details"]["recipe"]["mode"] == "review"

    async def test_run_workflow_execute_mode_skips_plan_cache(self, temp_project):
        src_dir = temp_project / "src"
        src_dir.mkdir()
        (src_dir / "module.py").write_text("def value():\n    return 1\n")

        first = parse_payload(
            await mcp_server.run_workflow(mode="review", target="src", execute=True)
        )
        second = parse_payload(
            await mcp_server.run_workflow(mode="review", target="src", execute=True)
        )

        assert first["ok"] is True
        assert first["details"]["cached"] is False
        assert second["ok"] is True
        assert second["details"]["cached"] is False

    async def test_run_workflow_restores_plan_from_disk_cache(self, temp_project, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_CACHE_DIR", str(temp_project / ".cache"))
        src_dir = temp_project / "src"
        src_dir.mkdir()
        (src_dir / "module.py").write_text("def value():\n    return 1\n")

        first = parse_payload(await mcp_server.run_workflow(mode="review", target="src"))
        assert first["ok"] is True
        assert first["details"]["cached"] is False

        workflow_tools_module._WORKFLOW_PLAN_CACHE.clear()
        second = parse_payload(await mcp_server.run_workflow(mode="review", target="src"))
        assert second["ok"] is True
        assert second["details"]["cached"] is True

    async def test_suggest_validation_commands_for_python_project(self, temp_project):
        (temp_project / "pyproject.toml").write_text('[project]\nname = "bridge"\n')
        payload = parse_payload(await mcp_server.suggest_validation_commands("."))

        assert payload["ok"] is True
        assert payload["details"]["project_type"] == "python"
        assert "python3 -m pytest" in payload["details"]["validation_commands"]
        assert "git diff" in payload["details"]["validation_commands"]

    async def test_suggest_validation_commands_for_rust_project(self, temp_project):
        src_dir = temp_project / "src"
        src_dir.mkdir()
        (temp_project / "Cargo.toml").write_text('[package]\nname = "bridge"\nversion = "0.1.0"\n')
        (src_dir / "lib.rs").write_text("pub fn value() -> i32 { 1 }\n")

        payload = parse_payload(await mcp_server.suggest_validation_commands("src"))

        assert payload["ok"] is True
        assert payload["details"]["project_type"] == "rust"
        assert "cargo test" in payload["details"]["validation_commands"]
        assert "git diff" in payload["details"]["validation_commands"]

    async def test_suggest_validation_commands_outside_project_includes_recovery_details(
        self, temp_project
    ):
        payload = parse_payload(await mcp_server.suggest_validation_commands("../outside-project"))

        assert payload["ok"] is False
        assert payload["code"] == "path_outside_project"
        assert payload["details"]["active_project_dir"] == str(temp_project.resolve())
        assert "workspace_status" in payload["details"]["suggested_next_tools"]

    async def test_suggest_validation_commands_rejects_missing_path(self, temp_project):
        payload = parse_payload(await mcp_server.suggest_validation_commands("missing-dir"))
        assert payload["ok"] is False
        assert payload["code"] == "path_not_found"

    async def test_unknown_workflow_mode_returns_error(self, temp_project):
        payload = parse_payload(await mcp_server.run_workflow(mode="shipit"))
        assert payload["ok"] is False
        assert payload["code"] == "unknown_workflow_mode"


class TestWorkspaceTools:
    async def test_workspace_status_lists_active_and_allowed_roots(self, temp_project):
        secondary_root = temp_project.parent / "secondary-root"
        secondary_root.mkdir(exist_ok=True)
        mcp_server.set_config(
            project_dir=temp_project,
            allowed_roots=[temp_project, secondary_root],
            auto_approve=True,
        )

        payload = parse_payload(await mcp_server.workspace_status())
        assert payload["ok"] is True
        assert payload["details"]["active_project_dir"] == str(temp_project.resolve())
        assert str(secondary_root.resolve()) in payload["details"]["allowed_roots"]
        assert payload["details"]["root_rules"]["can_switch_to_subdirectories"] is True

    async def test_switch_project_root_can_move_to_subdirectory_of_allowed_root(self, temp_project):
        desktop_root = temp_project.parent / "desktop-root"
        desktop_root.mkdir(exist_ok=True)
        tertis_dir = desktop_root / "tertis"
        tertis_dir.mkdir(exist_ok=True)
        mcp_server.set_config(
            project_dir=temp_project,
            allowed_roots=[temp_project, desktop_root],
            auto_approve=True,
        )

        payload = parse_payload(await mcp_server.switch_project_root(str(tertis_dir)))
        assert payload["ok"] is True
        assert payload["details"]["active_project_dir"] == str(tertis_dir.resolve())
        assert payload["details"]["switched_from_subdirectory_rule"] is True

    async def test_switch_project_root_preserves_security_config(self, temp_project):
        desktop_root = temp_project.parent / "desktop-root-preserve"
        desktop_root.mkdir(exist_ok=True)
        nested_dir = desktop_root / "nested"
        nested_dir.mkdir(exist_ok=True)
        mcp_server.apply_config(
            project_dir=temp_project,
            allowed_roots=[temp_project, desktop_root],
            auto_approve=False,
            client_managed_approval=True,
            shell_timeout=7,
            tool_profile="full",
            ai_evaluator_enabled=True,
            ai_evaluator_provider="local",
            ai_evaluator_timeout=3,
            role="junior",
            user="tester",
        )

        payload = parse_payload(await mcp_server.switch_project_root(str(nested_dir)))
        config = mcp_server.current_config()

        assert payload["ok"] is True
        assert config["project_dir"] == nested_dir.resolve()
        assert config["client_managed_approval"] is True
        assert config["auto_approve"] is False
        assert config["shell_timeout"] == 7
        assert config["tool_profile"] == "full"
        assert config["ai_evaluator_enabled"] is True
        assert config["ai_evaluator_timeout"] == 3
        assert config["role"] == "junior"
        assert config["user"] == "tester"


class TestAuditTools:
    async def test_get_recent_tool_calls_returns_logged_history(self, temp_project, monkeypatch):
        audit_dir = temp_project / ".audit"
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))
        mcp_server.set_config(project_dir=temp_project, auto_approve=True)

        await mcp_server.read_file("missing.txt")
        await mcp_server.list_directory(".")

        payload = parse_payload(await mcp_server.get_recent_tool_calls(limit=5))

        assert payload["ok"] is True
        assert payload["details"]["returned_records"] >= 2
        tool_names = [record["tool_name"] for record in payload["details"]["records"]]
        assert "list_directory" in tool_names
        assert "read_file" in tool_names
        record = payload["details"]["records"][0]
        assert "telemetry" in record
        assert record["telemetry"]["estimated_total_tokens"] >= 1
        assert audit_dir.exists()

    async def test_session_insights_returns_telemetry_summary(self, temp_project, monkeypatch):
        audit_dir = temp_project / ".audit"
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))
        mcp_server.set_config(project_dir=temp_project, auto_approve=True)

        await mcp_server.read_file("missing.txt")
        await mcp_server.list_directory(".")
        await mcp_server.run_shell("echo hello")

        payload = parse_payload(await mcp_server.session_insights(limit=10))

        assert payload["ok"] is True
        activity = payload["details"]["activity"]
        assert "missing.txt" in activity["touched_paths"]
        assert activity["commands"][0]["command"] == "echo hello"
        telemetry = payload["details"]["telemetry"]
        assert telemetry["total_estimated_tokens"] >= 1
        assert telemetry["total_input_chars"] >= 1
        assert telemetry["total_output_chars"] >= 1
        assert "list_directory" in telemetry["tool_estimated_tokens"]

    async def test_activity_summary_returns_user_facing_activity(self, temp_project, monkeypatch):
        audit_dir = temp_project / ".audit"
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))
        mcp_server.set_config(project_dir=temp_project, auto_approve=True)

        target = temp_project / "note.txt"
        target.write_text("hello", encoding="utf-8")

        await mcp_server.read_file("note.txt")
        await mcp_server.patch_file("note.txt", "hello", "hello bridge")
        await mcp_server.run_shell("echo hello")

        payload = parse_payload(await mcp_server.activity_summary(limit=10))

        assert payload["ok"] is True
        details = payload["details"]
        assert details["session_id"]
        assert "note.txt" in details["activity"]["touched_paths"]
        assert details["activity"]["commands"][0]["command"] == "echo hello"
        validation = details["activity"]["validation"]
        assert validation["has_changes"] is True
        assert validation["needs_validation"] is True
        assert validation["recommended_next_step"]
        assert details["suggested_response_topics"]

    async def test_activity_summary_detects_validation_after_changes(
        self, temp_project, monkeypatch
    ):
        audit_dir = temp_project / ".audit"
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))
        mcp_server.set_config(project_dir=temp_project, auto_approve=True)

        target = temp_project / "note.txt"
        target.write_text("hello", encoding="utf-8")

        await mcp_server.patch_file("note.txt", "hello", "hello bridge")
        await mcp_server.run_shell("pytest --version")

        payload = parse_payload(await mcp_server.activity_summary(limit=10))

        validation = payload["details"]["activity"]["validation"]
        assert validation["has_changes"] is True
        assert validation["validation_after_changes"] is True
        assert validation["needs_validation"] is False
        assert validation["validation_commands"][0]["command"] == "pytest --version"

    async def test_usage_insights_lists_top_cost_tools(self, temp_project, monkeypatch):
        audit_dir = temp_project / ".audit"
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(audit_dir))
        mcp_server.set_config(project_dir=temp_project, auto_approve=True)

        await mcp_server.list_directory(".")
        await mcp_server.read_file("missing.txt")

        payload = parse_payload(await mcp_server.usage_insights(limit=10))

        assert payload["ok"] is True
        assert payload["details"]["top_cost_tools"]
        assert payload["details"]["recommended_next_step"]

    async def test_bridge_status_reports_budget_profile(self, temp_project):
        payload = parse_payload(await mcp_server.bridge_status())

        assert payload["ok"] is True
        assert payload["details"]["context_budget_profile"] == "balanced"
        assert payload["details"]["context_budget_tokens"] == 4000
        assert payload["details"]["intent_compaction_enabled"] is False
        assert "session_telemetry" in payload["details"]

    async def test_tools_overview_groups_low_cost_tools(self, temp_project):
        payload = parse_payload(await mcp_server.tools_overview())

        assert payload["ok"] is True
        assert "compact_user_intent" in payload["details"]["groups"]["low_cost_context"]
        assert "narrow_context" in payload["details"]["groups"]["low_cost_context"]
        assert payload["details"]["notes"]


class TestConfigTools:
    async def test_get_config_returns_runtime_snapshot(self, temp_project):
        mcp_server.set_config(
            project_dir=temp_project, auto_approve=True, approval_preset="power-user"
        )

        payload = parse_payload(await mcp_server.get_config())

        assert payload["ok"] is True
        assert payload["details"]["approval_preset"] == "power-user"
        assert payload["details"]["auto_approve"] is True
        assert "approval_presets" in payload["details"]
        assert "budget_profiles" in payload["details"]
        assert "guard_policy" in payload["details"]
        assert payload["details"]["guard_policy"]["exists"] is False
        assert "context_budget_profile" in payload["details"]["editable_keys"]
        assert "intent_compaction_enabled" in payload["details"]["editable_keys"]
        assert "shell_timeout" in payload["details"]["editable_keys"]

    async def test_set_config_value_updates_shell_timeout(self, temp_project):
        mcp_server.set_config(project_dir=temp_project, auto_approve=True)

        payload = parse_payload(await mcp_server.set_config_value("shell_timeout", 45))

        assert payload["ok"] is True
        assert payload["details"]["shell_timeout"] == 45

    async def test_set_config_value_rejects_approval_preset(self, temp_project):
        mcp_server.set_config(
            project_dir=temp_project, auto_approve=False, client_managed_approval=False
        )

        payload = parse_payload(await mcp_server.set_config_value("approval_preset", "dev-safe"))

        assert payload["ok"] is False
        assert payload["code"] == "invalid_config_value"

    async def test_set_config_value_rejects_invalid_key(self, temp_project):
        mcp_server.set_config(project_dir=temp_project, auto_approve=True)

        payload = parse_payload(await mcp_server.set_config_value("allowed_roots", []))

        assert payload["ok"] is False
        assert payload["code"] == "invalid_config_value"

    async def test_set_config_value_can_disable_onboarding(self, temp_project):
        mcp_server.set_config(project_dir=temp_project, auto_approve=True)
        (temp_project / "note.txt").write_text("hello", encoding="utf-8")

        disable_payload = parse_payload(
            await mcp_server.set_config_value("onboarding_enabled", False)
        )
        read_payload = parse_payload(await mcp_server.read_file("note.txt"))

        assert disable_payload["ok"] is True
        assert disable_payload["details"]["onboarding_enabled"] is False
        assert "onboarding" not in read_payload["details"]

    async def test_set_config_value_can_enable_intent_compaction(self, temp_project):
        mcp_server.set_config(project_dir=temp_project, auto_approve=True)

        payload = parse_payload(
            await mcp_server.set_config_value("intent_compaction_enabled", True)
        )

        assert payload["ok"] is True
        assert payload["details"]["intent_compaction_enabled"] is True

    async def test_set_config_value_rejects_ai_evaluator_provider(self, temp_project):
        mcp_server.set_config(project_dir=temp_project, auto_approve=True)

        payload = parse_payload(await mcp_server.set_config_value("ai_evaluator_provider", "local"))

        assert payload["ok"] is False
        assert payload["code"] == "invalid_config_value"

    async def test_set_config_value_rejects_invalid_ai_evaluator_provider(self, temp_project):
        mcp_server.set_config(project_dir=temp_project, auto_approve=True)

        payload = parse_payload(
            await mcp_server.set_config_value("ai_evaluator_provider", "invalid_provider")
        )

        assert payload["ok"] is False
        assert payload["code"] == "invalid_config_value"

    async def test_set_config_value_rejects_ai_evaluator_toggle(self, temp_project):
        mcp_server.set_config(project_dir=temp_project, auto_approve=True)

        enable_payload = parse_payload(
            await mcp_server.set_config_value("ai_evaluator_enabled", True)
        )

        assert enable_payload["ok"] is False
        assert enable_payload["code"] == "invalid_config_value"

    async def test_compact_user_intent_returns_canonical_summary(self, temp_project):
        mcp_server.set_config(project_dir=temp_project, auto_approve=True)

        payload = parse_payload(
            await mcp_server.compact_user_intent(
                "Compact review request: review src/claude_bridge/server.py cheaply with cross-platform linux support"
            )
        )

        assert payload["ok"] is True
        details = payload["details"]
        assert details["canonical_intent"]["target_hint"] == "src/claude_bridge/server.py"
        assert "cross_platform" in details["canonical_intent"]["constraints"]
        assert details["intent_compaction_enabled"] is False

    async def test_compact_user_intent_reflects_enabled_mode(self, temp_project):
        mcp_server.set_config(project_dir=temp_project, auto_approve=True)
        await mcp_server.set_config_value("intent_compaction_enabled", True)

        payload = parse_payload(
            await mcp_server.compact_user_intent("Review src/claude_bridge for low token cost")
        )

        assert payload["ok"] is True
        assert payload["details"]["intent_compaction_enabled"] is True
        assert payload["details"]["mode_behavior"] == "active"


class TestInsightsTools:
    async def test_todo_scan_skips_banner_style_hash_lines(self, temp_project):
        (temp_project / "notes.py").write_text(
            "# TODO #\n# normal comment TODO should count\nvalue = 1  # FIXME: adjust later\n",
            encoding="utf-8",
        )

        payload = parse_payload(await mcp_server.todo_scan("."))

        assert payload["ok"] is True
        findings = payload["details"]["findings"]
        assert len(findings) == 3
        assert any(item["content"] == "# TODO #" for item in findings)

    async def test_dependency_insights_detects_nested_local_package(self, temp_project):
        package_dir = temp_project / "src" / "feature"
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("", encoding="utf-8")
        (temp_project / "consumer.py").write_text("import feature\n", encoding="utf-8")

        payload = parse_payload(await mcp_server.dependency_insights("."))

        assert payload["ok"] is True
        most_connected = payload["details"]["most_connected"]
        consumer = next(item for item in most_connected if item["file"] == "consumer.py")
        assert "feature" in consumer["imports"]

    def test_save_note_stores_data_outside_project_root(self, temp_project, monkeypatch):
        notes_dir = temp_project.parent / "bridge-notes"
        monkeypatch.setenv("CLAUDE_BRIDGE_NOTES_DIR", str(notes_dir))

        saved = insights_module.save_note(temp_project, "secret note")

        assert saved["ok"] is True
        assert not (temp_project / ".claude-bridge-notes.json").exists()
        assert any(notes_dir.glob("*.json"))

        notes = insights_module.read_notes(temp_project)
        assert notes["total"] >= 1
        assert notes["notes"][-1]["note"] == "secret note"

    def test_human_size_handles_large_values(self):
        assert insights_module._human_size(1024 * 1024) == "1.0 MB"


class TestAppealDecision:
    async def test_appeal_decision_on_deny_record(self, temp_project, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(temp_project / "audit"))
        mcp_server.set_config(project_dir=temp_project, auto_approve=True)

        # Trigger a deny decision
        payload = parse_payload(await mcp_server.run_shell("sudo apt update"))
        assert payload["ok"] is False
        assert payload["code"] == "blocked_command"

        # Get the recent tool call record
        recent = parse_payload(await mcp_server.get_recent_tool_calls(limit=1))
        assert recent["ok"] is True
        records = recent["details"]["records"]
        assert len(records) >= 1
        record_id = records[0]["record_id"]

        # Appeal the decision
        appeal_payload = parse_payload(
            await mcp_server.appeal_decision(record_id, "I need this for debugging")
        )
        assert appeal_payload["ok"] is True
        details = appeal_payload["details"]
        assert "appeal_request" in details
        assert "appeal_result" in details
        assert "original_record" in details
        assert "replay_result" in details
        assert "appeal_history_count" in details
        assert details["original_record"]["record_id"] == record_id

        # Verify appeal status is one of allow/deny/ask
        status = details["appeal_result"]["status"]
        assert status in ("allow", "deny", "ask")

        # Verify appeal history is non-empty
        assert details["appeal_history_count"] >= 1

    async def test_appeal_decision_can_create_pending_escalation(self, temp_project, monkeypatch):
        import claude_bridge.replay as replay_module
        from claude_bridge.guard_policy import (
            DecisionAction,
            DecisionSource,
            PolicyDecision,
            RiskLevel,
        )
        from claude_bridge.replay import ReplayResult

        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(temp_project / "audit"))
        mcp_server.set_config(project_dir=temp_project, auto_approve=True)

        payload = parse_payload(await mcp_server.run_shell("sudo apt update"))
        assert payload["ok"] is False

        recent = parse_payload(await mcp_server.get_recent_tool_calls(limit=1))
        record_id = recent["details"]["records"][0]["record_id"]

        def _deny_replay(record, *, justification, **kwargs):
            decision = PolicyDecision(
                action=DecisionAction.DENY,
                source=DecisionSource.BUILTIN_GUARD,
                risk_level=RiskLevel.CRITICAL,
                reason="still denied after appeal",
            )
            return ReplayResult(
                original_decision=decision,
                replayed_decision=decision,
                changed=False,
                change_reason="unchanged",
                metadata={"appeal_justification": justification},
            )

        monkeypatch.setattr(replay_module, "replay_with_justification", _deny_replay)

        appeal_payload = parse_payload(
            await mcp_server.appeal_decision(
                record_id,
                "Escalate this denied command for review",
                escalate=True,
            )
        )

        assert appeal_payload["ok"] is True
        details = appeal_payload["details"]
        assert details["appeal_result"]["status"] == "deny"
        assert details["escalation"]["created"] is True
        assert details["escalation"]["event"]["status"] == "pending"
        assert details["escalation"]["event"]["target"] == "team_lead"

        status_payload = parse_payload(await mcp_server.bridge_status())
        assert status_payload["ok"] is True
        escalations = status_payload["details"]["escalations"]
        assert escalations["pending_count"] >= 1
        assert escalations["recent_pending"][0]["tool_name"] == "escalation_event"


class TestSmartTools:
    async def test_compact_user_intent_reports_summary_delta_separately(self, temp_project):
        payload = parse_payload(
            await mcp_server.compact_user_intent(
                "Review src/claude_bridge/server.py and fix the auth flow with low token cost"
            )
        )

        assert payload["ok"] is True
        details = payload["details"]
        assert (
            details["estimated_token_delta"]
            == details["estimated_compact_summary_tokens"] - details["estimated_original_tokens"]
        )
        assert (
            details["estimated_prompt_overhead_tokens"]
            == details["estimated_compact_tokens"] - details["estimated_compact_summary_tokens"]
        )


class TestAnomalyTools:
    async def test_anomaly_summary_returns_scores_and_metadata(self, temp_project, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(temp_project / "audit"))
        mcp_server.set_config(project_dir=temp_project, auto_approve=True)

        await mcp_server.read_file("missing.txt")
        await mcp_server.list_directory(".")

        payload = parse_payload(await mcp_server.anomaly_summary(limit=10))

        assert payload["ok"] is True
        details = payload["details"]
        assert "anomaly_scores" in details
        assert "anomaly_counts" in details
        assert "overall_max_score" in details
        assert "overall_level" in details
        assert "critical_count" in details
        assert "policy_decisions" in details
        assert "mvp_limits" in details
        assert details["mvp_limits"]["scope"] == "rule-based, no ML model"
        assert len(details["mvp_limits"]["rules"]) == 10
        assert "recommended_action" in details
        assert "baseline" in details

    async def test_anomaly_summary_e2e_critical_result(self, temp_project, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(temp_project / "audit"))
        mcp_server.set_config(project_dir=temp_project, auto_approve=True)

        policy_path = temp_project / "policy.json"
        policy_path.write_text(
            json.dumps(
                {
                    "rules": [
                        {
                            "name": "deny-sensitive-read",
                            "scope": "read_file",
                            "action": "deny",
                            "risk_level": "high",
                            "conditions": [
                                {
                                    "type": "regex",
                                    "field": "path",
                                    "pattern": r"\.ssh/",
                                }
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("CLAUDE_BRIDGE_GUARD_POLICY", str(policy_path))

        await mcp_server.read_file(".ssh/id_rsa")
        await mcp_server.read_file(".ssh/authorized_keys")
        await mcp_server.read_file("/etc/passwd")

        payload = parse_payload(await mcp_server.anomaly_summary(limit=10))

        assert payload["ok"] is True
        details = payload["details"]
        assert details["total_records_scanned"] >= 3
        assert isinstance(details["anomaly_counts"], dict)
        if details["critical_count"] > 0:
            pd = details["policy_decisions"][0]
            assert pd["level"] == "critical"
            assert "decision_action" in pd
            assert "decision_source" in pd
            assert "decision_risk_level" in pd
            assert "recommended_action" in pd

    async def test_anomaly_summary_uses_project_baseline(self, temp_project, monkeypatch):
        monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(temp_project / "audit"))
        mcp_server.set_config(project_dir=temp_project, auto_approve=True)
        baseline_dir = temp_project / ".claude-bridge"
        baseline_dir.mkdir()
        (baseline_dir / "baseline.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "session_count": 3,
                    "record_count": 9,
                    "avg_records_per_session": 3,
                    "command_prefixes": ["git status"],
                    "path_roots": ["src"],
                    "active_hours": [10],
                }
            ),
            encoding="utf-8",
        )

        await mcp_server.read_file("docs/new-area.md")

        payload = parse_payload(await mcp_server.anomaly_summary(limit=10))

        assert payload["ok"] is True
        details = payload["details"]
        assert details["baseline"]["enabled"] is True
        assert details["baseline"]["session_count"] == 3
        assert details["anomaly_counts"].get("path_anomaly") == 1
