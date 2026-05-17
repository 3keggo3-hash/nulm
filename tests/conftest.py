"""Pytest configuration – shared fixtures."""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


import copy
import os
import tempfile
from pathlib import Path

import pytest

from claude_bridge import approach_explorer as ae
from claude_bridge import audit
from claude_bridge import ai_evaluator
from claude_bridge import config as config_module
from claude_bridge import file_tools
from claude_bridge import guard_policy
from claude_bridge import indexing
from claude_bridge import relevance
from claude_bridge import workflow_cache
from claude_bridge._process_session import reset_process_sessions

os.environ.setdefault("CLAUDE_BRIDGE_TOOL_PROFILE", "full")

_DEFAULT_CONFIG = {
    "project_dir": Path.cwd().resolve(),
    "allowed_roots": [Path.cwd().resolve()],
    "auto_approve": True,
    "client_managed_approval": False,
    "shell_timeout": 30,
    "approval_preset": None,
    "onboarding_enabled": True,
    "context_budget_profile": "balanced",
    "tool_profile": "full",
    "intent_compaction_enabled": False,
    "ai_evaluator_enabled": False,
    "ai_evaluator_provider": "local",
    "ai_evaluator_timeout": 5,
    "ai_evaluator_fallback_action": "ask",
    "role": None,
    "user": None,
    "auto_approve_risk_level": "medium",
    "auto_approve_patterns": {},
    "max_parallel": 4,
}


@pytest.fixture
def temp_project():
    from claude_bridge import server as mcp_server

    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        mcp_server.set_config(project_dir=project, auto_approve=True)
        yield project


@pytest.fixture
def temp_audit_project():
    from claude_bridge import server as mcp_server
    from claude_bridge.audit import reset_audit_session

    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        audit_dir = project / ".audit"
        os.environ["CLAUDE_BRIDGE_AUDIT_DIR"] = str(audit_dir)
        mcp_server.set_config(project_dir=project, auto_approve=True)
        reset_audit_session()
        yield project, audit_dir
        try:
            del os.environ["CLAUDE_BRIDGE_AUDIT_DIR"]
        except KeyError:
            pass
        reset_audit_session()


@pytest.fixture(autouse=True)
def _reset_global_state(monkeypatch, tmp_path):
    """Reset all global state between tests for full test isolation."""
    monkeypatch.setenv("CLAUDE_BRIDGE_AUDIT_DIR", str(tmp_path / "audit"))
    monkeypatch.setenv("CLAUDE_BRIDGE_UNSAFE_AUTO_APPROVE_CONFIRMED", "1")
    _do_reset = _make_reset(
        audit,
        ai_evaluator,
        config_module,
        file_tools,
        guard_policy,
        indexing,
        relevance,
        reset_process_sessions,
        workflow_cache,
    )
    _do_reset()
    yield
    _do_reset()


def _make_reset(
    audit,
    ai_evaluator,
    config_module,
    file_tools,
    guard_policy,
    indexing,
    relevance,
    reset_process_sessions,
    workflow_cache,
):
    def _reset():
        from claude_bridge._audit_core import _audit_dir, _cached_session_files
        reset_process_sessions()
        audit.reset_audit_session()
        _audit_dir.cache_clear()
        _cached_session_files.cache_clear()
        ai_evaluator.reset_ai_evaluator_state()
        _reset_config(config_module)
        _reset_last_bridge_change(file_tools)
        guard_policy._invalidate_policy_cache()
        indexing.clear_index_cache()
        relevance.clear_relevance_cache()
        workflow_cache.clear_workflow_caches()
        _reset_gitignore_cache(indexing)
        ae.invalidate_store_dir_cache()

    return _reset


def _reset_config(config_module):
    with config_module._CONFIG_LOCK:
        config_module._CONFIG.clear()
        config_module._CONFIG.update(copy.deepcopy(_DEFAULT_CONFIG))
        config_module._ALLOWED_ROOTS_SNAPSHOT = tuple(config_module._CONFIG["allowed_roots"])


def _reset_last_bridge_change(file_tools):
    file_tools.clear_last_bridge_change()


def _reset_gitignore_cache(indexing):
    with indexing._GITIGNORE_CACHE_LOCK:
        indexing._GITIGNORE_CACHE.clear()
