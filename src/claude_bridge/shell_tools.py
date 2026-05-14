"""Shell-oriented tool implementations for Claude Bridge.

Backward-compatible re-export wrapper. All implementations live in
the ``_shell_*`` sub-modules; this module re-exports every public and
test-used private name so that existing imports continue to work.
"""

from __future__ import annotations

from claude_bridge._process_session import (  # noqa: F401
    _ProcessSession,
    _get_process_session,
    _process_session_capacity,
    _PROCESS_SESSIONS,
    _PROCESS_SESSIONS_LOCK,
    _register_process_session,
    _trim_process_sessions,
    reset_process_sessions,
)
from claude_bridge._shell_analysis import (  # noqa: F401
    _is_long_running_command,
    _policy_risk_from_shell_risk,
    _shell_analysis_decision,
    _truncate_output,
    analyze_shell_command,
    compute_risk_score,
    is_interactive_command,
    risk_score_category,
)
from claude_bridge._shell_constants import (  # noqa: F401
    _BLOCKED_DIRECT_COMMANDS,
    _BLOCKED_PIPE_TARGETS,
    _DESTRUCTIVE_GIT_SUBCOMMANDS,
    _ENV_BLOCKED_COMMANDS,
    _FORK_BOMB_RE,
    _FULL_PATH_BLOCKED,
    _INLINE_INTERPRETER_FLAGS,
    _INTERACTIVE_COMMANDS,
    _LONG_RUNNING_COMMANDS,
    _LONG_RUNNING_TIMEOUT,
    _MAX_PROCESS_OUTPUT_CHARS,
    _MAX_PROCESS_SESSIONS,
    _MAX_SHELL_OUTPUT_CHARS,
    _PIPE_TARGET_REGEX,
    _WRAPPER_COMMANDS,
)
from claude_bridge._shell_run import (  # noqa: F401
    _MAX_INTERACT_INPUT_CHARS,
    interact_with_process,
    kill_process,
    list_process_sessions,
    read_process_output,
    run_shell,
    start_process,
)
from claude_bridge._shell_safety import (  # noqa: F401
    _BLOCKED_MATCHERS,
    _blocked_custom_policy,
    _blocked_curl_wget,
    _blocked_dd,
    _blocked_dev_redirection,
    _blocked_direct_commands,
    _blocked_find_xargs,
    _blocked_fork_bomb,
    _blocked_git,
    _blocked_inline_interpreter,
    _blocked_pipe_targets,
    _blocked_rm,
    _blocked_shell_construct,
    _blocked_tee_pv,
    _blocked_whitelist,
    _blocked_wrappers,
    _command_basename,
    _find_unquoted_shell_construct,
    _find_fork_bomb_unescaped,
    _interactive_target,
    _tokens_after_env,
    blocked_command_reason,
    normalize_command_for_safety,
)

__all__ = [
    "analyze_shell_command",
    "blocked_command_reason",
    "interact_with_process",
    "is_interactive_command",
    "kill_process",
    "list_process_sessions",
    "normalize_command_for_safety",
    "read_process_output",
    "reset_process_sessions",
    "run_shell",
    "start_process",
]
