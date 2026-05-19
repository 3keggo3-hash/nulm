"""Shell tool constants, limits, and blocked-command sets."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import regex  # type: ignore[import-untyped]

_INTERACTIVE_COMMANDS = {
    "python",
    "python3",
    "bash",
    "sh",
    "zsh",
    "fish",
    "ksh",
    "tcsh",
    "elvish",
    "nu",
    "nushell",
    "vim",
    "vi",
    "nano",
}
_DESTRUCTIVE_GIT_SUBCOMMANDS = {"reset", "clean", "checkout", "restore", "revert"}
_COMPOUND_CONTROL_COMMANDS = frozenset({"&&", "||", ";"})
_DANGEROUS_GLOB_COMMANDS = {"rm", "rmdir", "mkdir", "mv", "cp", "find"}
_FORK_BOMB_RE = regex.compile(
    r""":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"""
    r"""|(\w+)\s*\(\s*\)\s*\{\s*\1\s*\|\s*\1\s*&\s*\}\s*;\s*\1"""
    r"""|(\$\d+)\s*\(\s*\)\s*\{\s*\1\s*\|\s*\1\s*&\s*\}\s*;\s*\1""",
)
_INLINE_INTERPRETER_FLAGS = {
    "bash": {"-c"},
    "lua": {"-e"},
    "node": {"-e"},
    "perl": {"-e"},
    "php": {"-r"},
    "python": {"-c"},
    "python3": {"-c"},
    "ruby": {"-e"},
    "sh": {"-c"},
    "zsh": {"-c"},
}
_BLOCKED_PIPE_TARGETS = {
    "bash",
    "sh",
    "zsh",
    "fish",
    "ksh",
    "tcsh",
    "elvish",
    "nu",
    "nushell",
    "python",
    "python3",
    "perl",
    "ruby",
    "node",
    "xargs",
}
_WRAPPER_COMMANDS = {
    "nohup",
    "setsid",
    "script",
    "timeout",
    "nice",
    "unshare",
    "chroot",
    "nsenter",
    "prlimit",
    "taskset",
    "stdbuf",
    "ionice",
    "pkexec",
    "sudoedit",
    "su",
    "watch",
    "flock",
    "systemd-run",
}
_MAX_SHELL_OUTPUT_CHARS = 6000
_MAX_PROCESS_SESSIONS = 16
_MAX_PROCESS_OUTPUT_CHARS = 2000
_MAX_INTERACTIVE_INPUT_CHARS = 8000
_MAX_INTERACTIVE_TOTAL_INPUT = 80000

_LONG_RUNNING_TIMEOUT = 120

_LONG_RUNNING_COMMANDS = {
    "npm install",
    "npm ci",
    "cargo build",
    "cargo test",
    "go build",
    "go test",
    "pip install",
    "pip3 install",
    "make",
    "cmake",
    "docker build",
    "docker compose",
}

_FULL_PATH_BLOCKED = {
    "sudo",
    "chmod",
    "chown",
    "chgrp",
    "mkfs",
    "mount",
    "umount",
    "kill",
    "pkill",
    "killall",
    "systemctl",
    "service",
    "launchctl",
    "crontab",
    "nc",
    "ncat",
    "socat",
    "openssl",
    "telnet",
}

_ENV_BLOCKED_COMMANDS = {
    "sudo",
    "chmod",
    "chown",
    "chgrp",
    "mkfs",
    "mount",
    "umount",
    "kill",
    "systemctl",
    "nc",
    "ncat",
    "socat",
    "openssl",
    "telnet",
}

_BLOCKED_DIRECT_COMMANDS = frozenset(
    {
        "sudo",
        "chmod",
        "chown",
        "chgrp",
        "mkfs",
        "mount",
        "umount",
        "kill",
        "pkill",
        "killall",
        "systemctl",
        "service",
        "launchctl",
        "crontab",
        "fdisk",
        "parted",
        "nc",
        "ncat",
        "socat",
        "openssl",
        "telnet",
        "doas",
    }
)

_PIPE_TARGET_REGEX = regex.compile(
    rf"(?:[|;]|&&)\s*(?:\S*/)?({'|'.join(sorted(_BLOCKED_PIPE_TARGETS))})\b",
    regex.IGNORECASE,
)
_COMPOUND_OPERATOR_REGEX = regex.compile(r"\s*(?:&&|\|\|)\s*")
_UNQUOTED_GLOB_CHARS = frozenset({"*", "?", "["})