"""Pytest configuration – shared fixtures."""

import copy
from pathlib import Path

import pytest

from tests.helpers import temp_audit_project, temp_project  # noqa: F401

_DEFAULT_CONFIG = {
    "project_dir": Path.cwd().resolve(),
    "allowed_roots": [Path.cwd().resolve()],
    "auto_approve": False,
    "client_managed_approval": False,
    "shell_timeout": 30,
    "approval_preset": None,
    "onboarding_enabled": True,
    "context_budget_profile": "balanced",
    "intent_compaction_enabled": False,
    "ai_evaluator_enabled": False,
    "ai_evaluator_provider": "local",
    "ai_evaluator_timeout": 5,
    "ai_evaluator_fallback_action": "ask",
    "role": None,
    "user": None,
}


@pytest.fixture(autouse=True)
def _reset_global_state():
    """Reset all global state between tests for full test isolation."""
    from claude_bridge import config as config_module
    from claude_bridge import file_tools
    from claude_bridge import indexing
    from claude_bridge import shell_tools

    _do_reset = _make_reset(config_module, shell_tools, file_tools, indexing)
    _do_reset()
    yield
    _do_reset()


def _make_reset(config_module, shell_tools, file_tools, indexing):
    def _reset():
        _reset_config(config_module)
        _reset_process_sessions(shell_tools)
        _reset_last_bridge_change(file_tools)
        _reset_gitignore_cache(indexing)

    return _reset


def _reset_config(config_module):
    with config_module._CONFIG_LOCK:
        config_module._CONFIG.clear()
        config_module._CONFIG.update(copy.deepcopy(_DEFAULT_CONFIG))


def _reset_process_sessions(shell_tools):
    shell_tools.reset_process_sessions()


def _reset_last_bridge_change(file_tools):
    file_tools.clear_last_bridge_change()


def _reset_gitignore_cache(indexing):
    with indexing._GITIGNORE_CACHE_LOCK:
        indexing._GITIGNORE_CACHE.clear()
