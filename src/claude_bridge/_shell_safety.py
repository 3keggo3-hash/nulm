"""Shell command safety analysis and blocked-command detection."""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from claude_bridge._shell_constants import (
    _BLOCKED_DIRECT_COMMANDS,
    _BLOCKED_PIPE_TARGETS,
    _ENV_BLOCKED_COMMANDS,
    _FORK_BOMB_RE,
    _FULL_PATH_BLOCKED,
    _INLINE_INTERPRETER_FLAGS,
    _PIPE_TARGET_REGEX,
    _WRAPPER_COMMANDS,
)
from claude_bridge.guard_policy import (
    custom_shell_block_reason,
    load_guard_policy,
)

_DANGEROUS_ENV_VARS = frozenset(
    {"ld_preload", "dyld_insert_libraries", "dyld_library_path", "path"}
)


def _command_basename(token: str) -> str:
    return Path(token).name.lower()


def _tokens_after_env(tokens: list[str]) -> list[str]:
    if not tokens or _command_basename(tokens[0]) != "env":
        return tokens
    for index, token in enumerate(tokens[1:], start=1):
        if "=" in token and not token.startswith("-"):
            continue
        if token == "-S":
            if index + 1 < len(tokens):
                try:
                    split_tokens = shlex.split(tokens[index + 1])
                except ValueError:
                    split_tokens = [tokens[index + 1]]
                return split_tokens + list(tokens[index + 2 :])
            return []
        if token.startswith("-"):
            continue
        return tokens[index:]
    return []


def _interactive_target(tokens: list[str]) -> str | None:
    command_tokens = _tokens_after_env(tokens)
    if not command_tokens:
        return None
    head = _command_basename(command_tokens[0])
    if head in {"command", "exec", "builtin"}:
        if len(command_tokens) > 1:
            return _command_basename(command_tokens[1])
        return None
    return head


def normalize_command_for_safety(command: str) -> str:
    return re.sub(r"\s+", " ", command.strip()).lower()


def _find_unquoted_shell_construct(command: str) -> str | None:
    in_single = False
    in_double = False
    escaped = False

    for index, char in enumerate(command):
        if escaped:
            escaped = False
            continue
        if char == "\\" and not in_single:
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if in_single:
            continue
        if char == "`":
            return "backtick substitution"
        if char == "$" and index + 1 < len(command):
            next_char = command[index + 1]
            if next_char == "(":
                if index + 2 < len(command) and command[index + 2] == "(":
                    return "$(( arithmetic expansion"
                return "$() substitution"
            if next_char == "{":
                return "${} expansion"
            if next_char == "'":
                return "$' ANSI-C quoting"
            if next_char == '"':
                return '$" locale translation'
        if char == "<":
            if index + 1 < len(command):
                next_char = command[index + 1]
                if next_char == "(":
                    return "<() process substitution"
                if next_char == "<":
                    if index + 2 < len(command) and command[index + 2] == "<":
                        return "<<< here-string"
                    return "<< heredoc"
        if char == ">" and index + 1 < len(command) and command[index + 1] == "(":
            return ">() process substitution"
        if char == "(":
            prefix = command[:index].rstrip()
            if not prefix or prefix.endswith((";", "&&", "||", "|", "&")):
                return "subshell"
    return None


def _find_fork_bomb_unescaped(command: str) -> str | None:
    """Check for fork bomb patterns that might bypass lowercase regex."""
    unescaped = command.replace("\\:", ":").replace("\\|", "|").replace("\\&", "&")
    if _FORK_BOMB_RE.search(unescaped):
        return "fork bomb"
    return None


def _blocked_shell_construct(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    reason = _find_unquoted_shell_construct(stripped)
    if reason is not None:
        return reason
    return _find_fork_bomb_unescaped(stripped)


def _blocked_custom_policy(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    return custom_shell_block_reason(stripped)


def _blocked_whitelist(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    policy = load_guard_policy()
    if not policy.get("default_deny", False):
        return None
    allowed = policy.get("allowed_shell_commands", [])
    if head not in allowed:
        return f"not in shell whitelist: {head}"
    return None


def _blocked_direct_commands(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    if head in _BLOCKED_DIRECT_COMMANDS:
        return head
    return None


def _blocked_inline_interpreter(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    if head not in _INLINE_INTERPRETER_FLAGS:
        return None
    if any(token in _INLINE_INTERPRETER_FLAGS[head] for token in lower_tokens[1:]):
        flag = next(token for token in lower_tokens[1:] if token in _INLINE_INTERPRETER_FLAGS[head])
        return f"{head} {flag}"
    return None


def _blocked_curl_wget(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    if head not in {"curl", "wget"}:
        return None
    control_tokens_present = any(token in {"|", "&&", ";"} for token in all_lower_tokens)
    output_file_tokens: set[str] = set()
    output_flags = {"-o", "--output"} if head == "curl" else {"-O", "--output-document"}
    for i, token in enumerate(lower_tokens[:-1]):
        if token in output_flags:
            output_file_tokens.add(lower_tokens[i + 1])
    if re.search(r"[|;]|&&", stripped) and _PIPE_TARGET_REGEX.search(stripped):
        return f"{head} to shell"
    if control_tokens_present:
        suspect = [
            t
            for t in lower_tokens
            if _command_basename(t) in _BLOCKED_PIPE_TARGETS and t not in output_file_tokens
        ]
        if suspect:
            return f"{head} to shell"
    if head == "curl" and any(
        token in {"-K", "--config", "-A", "--user-agent", "-H", "--header"}
        for token in lower_tokens
    ):
        return f"{head} with config/header injection risk"
    if "--silent" in lower_tokens or "-s" in lower_tokens:
        has_output = output_file_tokens or any(
            token.startswith("-o") or token.startswith("--output") for token in lower_tokens
        )
        has_remote_url = any("http://" in token or "https://" in token for token in lower_tokens)
        if not has_output and has_remote_url and control_tokens_present:
            return f"{head} silent fetch to shell"
    return None


def _blocked_dd(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    if head != "dd":
        return None
    for token in lower_tokens[1:]:
        if token.startswith("if="):
            return "dd if="
        if token.startswith("of=") and len(token) > 3 and token[3:].startswith("/dev/"):
            return "dd of=/dev/"
    return None


def _blocked_wrappers(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    if head in _WRAPPER_COMMANDS:
        return f"{head} wrapper"
    return None


def _blocked_tee_pv(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    if head == "tee":
        for token in lower_tokens[1:]:
            if token.startswith("/dev/"):
                return "tee /dev/"
    elif head == "pv":
        for i, token in enumerate(lower_tokens):
            if token in {">", ">>"} and i + 1 < len(lower_tokens):
                if lower_tokens[i + 1].startswith("/dev/"):
                    return "pv > /dev/"
    return None


def _blocked_find_xargs(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    if head == "find":
        if re.search(r"(?:^|\s)find\b.*\|\s*xargs\b.*\brm\b", normalized):
            return "find to xargs rm"
        if any(
            token.startswith(("-exec", "-ok")) or token == "-delete" or token == "+"
            for token in lower_tokens[1:]
        ):
            return "find -exec"
    if head == "xargs" and len(lower_tokens) > 1:
        return "xargs"
    return None


def _blocked_rm(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    if head != "rm":
        return None
    option_chars = "".join(token.lstrip("-") for token in lower_tokens[1:] if token.startswith("-"))
    if "r" in option_chars:
        return "rm -r"
    if "--no-preserve-root" in lower_tokens:
        return "rm --no-preserve-root"
    return None


def _blocked_git(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    if head != "git" or len(lower_tokens) < 2:
        return None
    sub_start: int = 1
    while sub_start < len(lower_tokens):
        t = lower_tokens[sub_start]
        if t in {"-c", "-C"} and sub_start + 1 < len(lower_tokens):
            sub_start += 2
            continue
        if t.startswith("-"):
            sub_start += 1
            continue
        break
    subcommand = lower_tokens[sub_start] if sub_start < len(lower_tokens) else ""
    rest = lower_tokens[sub_start + 1 :]
    if subcommand == "reset" and any(token == "--hard" for token in rest):
        return "git reset --hard"
    if subcommand == "clean" and any(
        "f" in token.lstrip("-") for token in rest if token.startswith("-")
    ):
        return "git clean -f"
    if subcommand == "checkout" and any(token == "--" for token in rest):
        return "git checkout --"
    if subcommand == "restore" and any(token.startswith("--source") for token in rest):
        return "git restore --source"
    return None


def _blocked_pipe_targets(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    for index, token in enumerate(all_lower_tokens[:-1]):
        pipe_target = _command_basename(all_lower_tokens[index + 1])
        if token == "|" and pipe_target in _BLOCKED_PIPE_TARGETS:
            return f"| {pipe_target}"
    return None


def _blocked_dev_redirection(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    for idx, token in enumerate(all_lower_tokens):
        if token in {">", ">>"}:
            next_idx = idx + 1
            if next_idx < len(all_lower_tokens) and all_lower_tokens[next_idx].startswith("/dev/"):
                return f"{token} /dev"
        if re.match(r"^[12&]>>?$", token):
            next_idx = idx + 1
            if next_idx < len(all_lower_tokens) and all_lower_tokens[next_idx].startswith("/dev/"):
                return f"{token} /dev"
    dev_redirect_match = re.search(r"[12&]?>>?\s*/dev", normalized)
    if dev_redirect_match:
        match_start = dev_redirect_match.start()
        in_single = False
        in_double = False
        escaped = False
        for i in range(match_start):
            ch = normalized[i]
            if escaped:
                escaped = False
                continue
            if ch == "\\" and not in_single:
                escaped = True
                continue
            if ch == "'" and not in_double:
                in_single = not in_single
                continue
            if ch == '"' and not in_single:
                in_double = not in_double
                continue
        if not in_single and not in_double:
            return "> /dev"
    if normalized.startswith("/dev/"):
        return "/dev/ path"
    return None


def _blocked_fork_bomb(
    head: str,
    lower_tokens: list[str],
    all_lower_tokens: list[str],
    stripped: str,
    normalized: str,
) -> str | None:
    if _FORK_BOMB_RE.search(normalized):
        return "fork bomb"
    return None


_BLOCKED_MATCHERS = [
    _blocked_shell_construct,
    _blocked_custom_policy,
    _blocked_whitelist,
    _blocked_direct_commands,
    _blocked_inline_interpreter,
    _blocked_curl_wget,
    _blocked_dd,
    _blocked_wrappers,
    _blocked_tee_pv,
    _blocked_find_xargs,
    _blocked_rm,
    _blocked_git,
    _blocked_pipe_targets,
    _blocked_dev_redirection,
    _blocked_fork_bomb,
]


def blocked_command_reason(stripped: str, tokens: list[str]) -> str | None:
    if not tokens:
        return None

    command_tokens = _tokens_after_env(tokens)
    if not command_tokens:
        return None
    head = _command_basename(command_tokens[0])
    while head in {"command", "exec", "builtin"} and len(command_tokens) > 1:
        command_tokens = command_tokens[1:]
        while command_tokens and command_tokens[0].startswith("-"):
            command_tokens = command_tokens[1:]
        if not command_tokens:
            return None
        head = _command_basename(command_tokens[0])

    while head == "env":
        command_tokens = _tokens_after_env(command_tokens)
        if not command_tokens:
            return None
        head = _command_basename(command_tokens[0])
    lower_tokens = [token.lower() for token in command_tokens]
    all_lower_tokens = [token.lower() for token in tokens]
    normalized = normalize_command_for_safety(stripped)

    raw_head = command_tokens[0]
    if "/" in raw_head:
        if _command_basename(raw_head) in _FULL_PATH_BLOCKED:
            return f"full-path {_command_basename(raw_head)}"

    env_raw = tokens[0]
    if "/" in env_raw:
        env_basename = _command_basename(env_raw)
    else:
        env_basename = env_raw.lower()
    if env_basename == "env":
        env_target = _interactive_target(tokens)
        if env_target is not None and env_target in _ENV_BLOCKED_COMMANDS:
            return f"env {env_target}"
    for token in tokens:
        if "=" in token and not token.startswith("-"):
            var_name = token.split("=", 1)[0].lower()
            if var_name in _DANGEROUS_ENV_VARS:
                return f"env {var_name}"
            if var_name.upper() in {"LD_PRELOAD", "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH", "PATH"}:
                return f"env {var_name}"

    for matcher in _BLOCKED_MATCHERS:
        reason = matcher(head, lower_tokens, all_lower_tokens, stripped, normalized)
        if reason is not None:
            return reason
    return None


def _check_skill_code_blocked(skill_code: str) -> str | None:
    patterns = [
        (r"os\.system\s*\(", "os.system"),
        (r"os\.popen\s*\(", "os.popen"),
        (r"subprocess\.run\s*\(.*shell\s*=\s*True", "subprocess.run with shell=True"),
        (r"\beval\s*\(", "eval"),
        (r"\bexec\s*\(", "exec"),
        (r"\b__import__\s*\(", "__import__"),
        (r"importlib\.import_module\s*\(", "importlib.import_module"),
    ]
    for pattern, name in patterns:
        if re.search(pattern, skill_code):
            return f"skill code contains blocked pattern: {name}"
    return None
