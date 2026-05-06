"""Integration matrix for tree-sitter enabled and fallback indexing."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from claude_bridge import indexing as indexing_module
from claude_bridge import server as mcp_server

from tests.helpers import FakeTSNode, parse_payload


def _fake_parser_for(root_node: FakeTSNode):
    return SimpleNamespace(parse=lambda source_bytes: SimpleNamespace(root_node=root_node))


LANGUAGE_CASES = [
    {
        "name": "typescript",
        "dirname": "web",
        "filename": "auth.ts",
        "source": 'import { createSession } from "./session"\nexport class AuthGateway {}\nexport const loginUser = async (email: string) => createSession(email)\n',
        "language_name": "typescript",
        "expected_language": "typescript",
        "expected_functions": ["loginUser"],
        "expected_classes": ["AuthGateway"],
        "expected_imports": ["session"],
        "root_node": FakeTSNode(
            "program",
            children=[
                FakeTSNode(
                    "function_declaration", fields={"name": FakeTSNode("identifier", "loginUser")}
                ),
                FakeTSNode(
                    "class_declaration", fields={"name": FakeTSNode("identifier", "AuthGateway")}
                ),
                FakeTSNode(
                    "import_statement", fields={"source": FakeTSNode("string", '"./session"')}
                ),
            ],
        ),
    },
    {
        "name": "javascript",
        "dirname": "web",
        "filename": "auth.js",
        "source": 'import session from "./session"\nclass AuthGateway {}\nfunction loginUser() { return session }\n',
        "language_name": "javascript",
        "expected_language": "javascript",
        "expected_functions": ["loginUser"],
        "expected_classes": ["AuthGateway"],
        "expected_imports": ["session"],
        "root_node": FakeTSNode(
            "program",
            children=[
                FakeTSNode(
                    "function_declaration", fields={"name": FakeTSNode("identifier", "loginUser")}
                ),
                FakeTSNode(
                    "class_declaration", fields={"name": FakeTSNode("identifier", "AuthGateway")}
                ),
                FakeTSNode(
                    "import_statement", fields={"source": FakeTSNode("string", '"./session"')}
                ),
            ],
        ),
    },
    {
        "name": "go",
        "dirname": "goapp",
        "filename": "auth.go",
        "source": 'package auth\n\nimport "context"\n\ntype AuthService struct{}\n\nfunc LoginUser() error { return nil }\n',
        "language_name": "go",
        "expected_language": "go",
        "expected_functions": ["LoginUser"],
        "expected_classes": ["AuthService"],
        "expected_imports": ["context"],
        "root_node": FakeTSNode(
            "source_file",
            children=[
                FakeTSNode(
                    "function_declaration", fields={"name": FakeTSNode("identifier", "LoginUser")}
                ),
                FakeTSNode(
                    "type_spec", fields={"name": FakeTSNode("type_identifier", "AuthService")}
                ),
                FakeTSNode(
                    "import_spec",
                    fields={"path": FakeTSNode("interpreted_string_literal", '"context"')},
                ),
            ],
        ),
    },
    {
        "name": "rust",
        "dirname": "rustapp",
        "filename": "auth.rs",
        "source": "use crate::session::SessionStore;\npub struct AuthService;\npub async fn login_user() {}\n",
        "language_name": "rust",
        "expected_language": "rust",
        "expected_functions": ["login_user"],
        "expected_classes": ["AuthService"],
        "expected_imports": ["crate"],
        "root_node": FakeTSNode(
            "source_file",
            children=[
                FakeTSNode(
                    "function_item", fields={"name": FakeTSNode("identifier", "login_user")}
                ),
                FakeTSNode(
                    "struct_item", fields={"name": FakeTSNode("type_identifier", "AuthService")}
                ),
                FakeTSNode(
                    "use_declaration",
                    fields={
                        "argument": FakeTSNode("scoped_identifier", "crate::session::SessionStore")
                    },
                ),
            ],
        ),
    },
    {
        "name": "java",
        "dirname": "javaapp",
        "filename": "AuthService.java",
        "source": "import com.example.auth.SessionStore;\npublic class AuthService {\n    public void loginUser() {}\n}\n",
        "language_name": "java",
        "expected_language": "java",
        "expected_functions": ["loginUser"],
        "expected_classes": ["AuthService"],
        "expected_imports": ["com"],
        "root_node": FakeTSNode(
            "program",
            children=[
                FakeTSNode(
                    "method_declaration", fields={"name": FakeTSNode("identifier", "loginUser")}
                ),
                FakeTSNode(
                    "class_declaration", fields={"name": FakeTSNode("identifier", "AuthService")}
                ),
                FakeTSNode(
                    "import_declaration",
                    fields={
                        "path": FakeTSNode("scoped_identifier", "com.example.auth.SessionStore")
                    },
                ),
            ],
        ),
    },
    {
        "name": "kotlin",
        "dirname": "kotlinapp",
        "filename": "AuthService.kt",
        "source": "import com.example.auth.SessionStore\nclass AuthService\nfun loginUser() {}\n",
        "language_name": "kotlin",
        "expected_language": "kotlin",
        "expected_functions": ["loginUser"],
        "expected_classes": ["AuthService"],
        "expected_imports": ["com"],
        "root_node": FakeTSNode(
            "source_file",
            children=[
                FakeTSNode(
                    "function_declaration", fields={"name": FakeTSNode("identifier", "loginUser")}
                ),
                FakeTSNode(
                    "class_declaration",
                    fields={"name": FakeTSNode("type_identifier", "AuthService")},
                ),
                FakeTSNode(
                    "import_header",
                    fields={"path": FakeTSNode("identifier", "com.example.auth.SessionStore")},
                ),
            ],
        ),
    },
    {
        "name": "csharp",
        "dirname": "csharpapp",
        "filename": "AuthService.cs",
        "source": "using Example.Auth;\npublic class AuthService {\n    public void LoginUser() {}\n}\n",
        "language_name": "c_sharp",
        "expected_language": "csharp",
        "expected_functions": ["LoginUser"],
        "expected_classes": ["AuthService"],
        "expected_imports": ["Example"],
        "root_node": FakeTSNode(
            "compilation_unit",
            children=[
                FakeTSNode(
                    "method_declaration", fields={"name": FakeTSNode("identifier", "LoginUser")}
                ),
                FakeTSNode(
                    "class_declaration", fields={"name": FakeTSNode("identifier", "AuthService")}
                ),
                FakeTSNode(
                    "using_directive", fields={"name": FakeTSNode("qualified_name", "Example.Auth")}
                ),
            ],
        ),
    },
    {
        "name": "ruby",
        "dirname": "rubyapp",
        "filename": "auth_service.rb",
        "source": 'require "json"\nclass AuthService\n  def login_user\n  end\nend\n',
        "language_name": "ruby",
        "expected_language": "ruby",
        "expected_functions": ["login_user"],
        "expected_classes": ["AuthService"],
        "expected_imports": ["json"],
        "root_node": FakeTSNode(
            "program",
            children=[
                FakeTSNode("method", fields={"name": FakeTSNode("identifier", "login_user")}),
                FakeTSNode("class", fields={"name": FakeTSNode("constant", "AuthService")}),
                FakeTSNode("call", fields={"argument": FakeTSNode("string", '"json"')}),
            ],
        ),
    },
    {
        "name": "php",
        "dirname": "phpapp",
        "filename": "AuthService.php",
        "source": "<?php\nuse App\\Session\\Store;\nclass AuthService { public function loginUser() {} }\n",
        "language_name": "php",
        "expected_language": "php",
        "expected_functions": ["loginUser"],
        "expected_classes": ["AuthService"],
        "expected_imports": ["App"],
        "root_node": FakeTSNode(
            "program",
            children=[
                FakeTSNode(
                    "method_declaration", fields={"name": FakeTSNode("identifier", "loginUser")}
                ),
                FakeTSNode("class_declaration", fields={"name": FakeTSNode("name", "AuthService")}),
                FakeTSNode(
                    "namespace_use_declaration",
                    fields={"clause": FakeTSNode("namespace_name", "App\\Session\\Store")},
                ),
            ],
        ),
    },
]


class TestTreeSitterMatrix:
    @pytest.mark.parametrize("case", LANGUAGE_CASES, ids=[case["name"] for case in LANGUAGE_CASES])
    async def test_index_codebase_fallback_matrix(self, temp_project, monkeypatch, case):
        monkeypatch.setattr(indexing_module, "_load_tree_sitter_parser", lambda language_name: None)

        source_dir = temp_project / case["dirname"]
        source_dir.mkdir()
        (source_dir / case["filename"]).write_text(case["source"], encoding="utf-8")

        payload = parse_payload(await mcp_server.index_codebase(case["dirname"]))
        assert payload["ok"] is True
        indexed = payload["details"]["files"][0]
        assert indexed["language"] == case["expected_language"]
        assert indexed["functions"] == case["expected_functions"]
        assert indexed["classes"] == case["expected_classes"]
        assert indexed["imports"] == case["expected_imports"]
        assert indexed["parser_backend"] == "fallback"
        assert payload["details"]["parser_backends"] == ["fallback"]

    @pytest.mark.parametrize("case", LANGUAGE_CASES, ids=[case["name"] for case in LANGUAGE_CASES])
    async def test_index_codebase_tree_sitter_matrix(self, temp_project, monkeypatch, case):
        def fake_load_tree_sitter_parser(language_name: str):
            if language_name == case["language_name"]:
                return _fake_parser_for(case["root_node"])
            return None

        monkeypatch.setattr(
            indexing_module, "_load_tree_sitter_parser", fake_load_tree_sitter_parser
        )

        source_dir = temp_project / case["dirname"]
        source_dir.mkdir()
        (source_dir / case["filename"]).write_text(case["source"], encoding="utf-8")

        payload = parse_payload(await mcp_server.index_codebase(case["dirname"]))
        assert payload["ok"] is True
        indexed = payload["details"]["files"][0]
        assert indexed["language"] == case["expected_language"]
        assert indexed["functions"] == case["expected_functions"]
        assert indexed["classes"] == case["expected_classes"]
        if case["name"] == "ruby":
            assert sorted(indexed["imports"]) == ["json"]
        else:
            assert indexed["imports"] == case["expected_imports"]
        assert indexed["parser_backend"] == "tree_sitter"
        assert payload["details"]["parser_backends"] == ["tree_sitter"]
