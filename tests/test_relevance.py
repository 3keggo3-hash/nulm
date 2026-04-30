"""Unit tests for relevance scoring helpers."""

from __future__ import annotations

from collections import OrderedDict

from claude_bridge import relevance as relevance_module
from claude_bridge.relevance import rank_indexed_files


class TestRelevanceScoring:
    def test_rank_indexed_files_splits_identifier_tokens(self):
        payload = {
            "files": [
                {
                    "path": "api/AuthController.java",
                    "functions": ["loginUser"],
                    "classes": ["AuthController"],
                    "imports": [],
                    "content": "public class AuthController { public void loginUser() {} }",
                    "parser_backend": "fallback",
                },
                {
                    "path": "billing/payments.py",
                    "functions": ["charge_card"],
                    "classes": [],
                    "imports": [],
                    "content": "def charge_card():\n    return True\n",
                    "parser_backend": "fallback",
                },
            ]
        }

        ranked = rank_indexed_files(payload, query="auth login", limit=2)
        assert ranked["results"][0]["path"] == "api/AuthController.java"
        assert "classes" in ranked["results"][0]["matched_fields"]
        assert "functions" in ranked["results"][0]["matched_fields"]

    def test_rank_indexed_files_rewards_multi_field_matches(self):
        payload = {
            "files": [
                {
                    "path": "auth/session_manager.py",
                    "functions": ["create_session"],
                    "classes": ["SessionManager"],
                    "imports": ["auth"],
                    "content": "class SessionManager:\n    pass\n",
                    "parser_backend": "tree_sitter",
                },
                {
                    "path": "auth_helpers.py",
                    "functions": ["create_session"],
                    "classes": [],
                    "imports": [],
                    "content": "def create_session():\n    pass\n",
                    "parser_backend": "fallback",
                },
            ]
        }

        ranked = rank_indexed_files(payload, query="auth session", limit=2)
        assert ranked["results"][0]["path"] == "auth/session_manager.py"
        assert ranked["results"][0]["score"] > ranked["results"][1]["score"]

    def test_rank_indexed_files_uses_result_cache_for_same_snapshot(self):
        payload = {
            "_snapshot_key": "snapshot-1",
            "files": [
                {
                    "path": "auth.py",
                    "functions": ["login_user"],
                    "classes": ["AuthService"],
                    "imports": [],
                    "content": "def login_user():\n    return True\n",
                    "parser_backend": "fallback",
                }
            ],
        }

        first = rank_indexed_files(payload, query="auth login", limit=1)
        second = rank_indexed_files(payload, query="auth login", limit=1)
        assert first["cached"] is False
        assert second["cached"] is True
        assert second["strategy"] == "two_phase_token_scoring"

    def test_rank_indexed_files_evicts_old_cache_entries(self, monkeypatch):
        monkeypatch.setattr(relevance_module, "_MAX_RELEVANCE_CACHE_ENTRIES", 2)
        monkeypatch.setattr(relevance_module, "_RELEVANCE_CACHE", OrderedDict())

        base_files = [
            {
                "path": "auth.py",
                "functions": ["login_user"],
                "classes": ["AuthService"],
                "imports": [],
                "content": "def login_user():\n    return True\n",
                "parser_backend": "fallback",
            }
        ]
        rank_indexed_files({"_snapshot_key": "s1", "files": base_files}, query="auth", limit=1)
        rank_indexed_files({"_snapshot_key": "s2", "files": base_files}, query="auth", limit=1)
        rank_indexed_files({"_snapshot_key": "s3", "files": base_files}, query="auth", limit=1)

        assert len(relevance_module._RELEVANCE_CACHE) == 2
        assert ("s1", "auth") not in relevance_module._RELEVANCE_CACHE

    def test_rank_indexed_files_prefers_precomputed_tokens_without_content(self):
        payload = {
            "files": [
                {
                    "path": "docs/auth_flow.md",
                    "functions": [],
                    "classes": [],
                    "imports": [],
                    "path_tokens": ["docs", "auth", "flow", "md"],
                    "function_tokens": [],
                    "class_tokens": [],
                    "import_tokens": [],
                    "content_tokens": ["user", "login", "auth", "session"],
                    "parser_backend": "fallback",
                },
                {
                    "path": "misc/notes.txt",
                    "functions": [],
                    "classes": [],
                    "imports": [],
                    "path_tokens": ["misc", "notes", "txt"],
                    "function_tokens": [],
                    "class_tokens": [],
                    "import_tokens": [],
                    "content_tokens": ["random", "notes"],
                    "parser_backend": "fallback",
                },
            ]
        }

        ranked = rank_indexed_files(payload, query="user login", limit=2)
        assert ranked["results"][0]["path"] == "docs/auth_flow.md"
        assert ranked["results"][0]["matched_fields"] == ["content"]
