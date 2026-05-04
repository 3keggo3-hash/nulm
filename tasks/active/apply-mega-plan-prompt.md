# Execute This Plan

## 1. Setup

Read these files first:
- `AGENTS.md` — coding conventions
- `tasks/active/mega-action-plan.md` — master task list (82 tasks, 7 phases)

This project is `claude-bridge`, a Python MCP server providing secure filesystem/shell access for Claude Desktop.

**Convention rules:** `mypy src && ruff check . && pytest -q` after every change. Black 100-char lines. No unnecessary comments. Match existing code style.

---

## 2. Executing The Plan

Work through `mega-action-plan.md` sections in order: **P0 → P1 → P2 → P3 → P4 → P5 → P6**.

Below are code-level specifics for each task — use these alongside the plan to avoid wasted exploration.

### P0 — Critical Security + Build

**P0.1**: Add `"python": {"-c"}, "python3": {"-c"}` to `_INLINE_INTERPRETER_FLAGS` at `shell_tools.py:55`. The check at line 431 catches inline interpreter flags. Currently python/python3 are NOT in this set — `python3 -c "code"` bypasses all blocks.

**P0.2**: In `_interactive_target()` at `shell_tools.py:275`, when head is `"command"`, `"exec"`, or `"builtin"`, skip it and return `_command_basename(tokens[1])`. Currently only `env` stripping exists. `command sudo cat /etc/passwd` passes because `_command_basename("command")` is not `"sudo"`.

**P0.3**: In `_run_ripgrep_search()` at `file_tools.py:287`, change `command.extend([query, str(target)])` to `command.extend(["--", query, str(target)])`. Currently no `--` separator — queries starting with `-` get interpreted as flags.

**P0.4**: In `_FORK_BOMB_RE` at `shell_tools.py:51`, add a third alternative: `r"""|(\$\d+)\s*\(\s*\)\s*\{\s*\1\s*\|\s*\1\s*&\s*\}\s*;\s*\1"""`. Currently only `:(){ :|:& };:` and `name(){ name|name& };name` are caught. `$0(){ $0|$0& };$0` bypasses.

**P0.5**: In `ai_evaluator.py`, find the `EvaluationRequest` prompt builder. Before sending content/search/replace/command fields to the AI provider, apply `_mask_secrets()` from `tool_utils.py:163`, or replace raw content with `"[_MASKED_]"`.

**P0.6**: `pyproject.toml:3` — change `build-backend = "setuptools.backends.legacy:build"` → `"setuptools.build_meta"`.

**P0.7**: `scripts/release-gate.sh` — replace global `claude-bridge` call with local venv or `pip install -e .[dev]`.

**Verify after P0:** `mypy src && ruff check . && pytest -q`

---

### P1 — High Priority

**P1.1**: Implement shell allowlist mode. Add `allowed_shell_commands` to `.claude-bridge-guard.json` config in `guard_policy.py`. In `shell_tools.py`, add a `default_deny` mode where only explicitly listed commands run. Preserve existing deny-list as fallback mode.

**P1.2**: In `tool_utils.py`, `sensitive_path_reason` (line ~128): add `.git/**` (any path containing `.git/`) to blocked patterns. Currently `.git` directory itself may be catchable but contents aren't.

**P1.3**: In `shell_tools.py`, add detection for `tee /dev/sd*` and `pv > /dev/sd*` device writes. Add to `blocked_command_reason()` or create a separate device-write check.

**P1.4**: Extend `_mask_secrets()` at `tool_utils.py:163` to accept custom patterns from guard policy config. Read `.claude-bridge-guard.json` for user-defined regex patterns.

**P1.5**: In `patch_file` at `file_tools.py`, add `is_symlink()` check on target before patching (same protections as `write_file`).

**P1.6**: `pyproject.toml`: `requires-python = ">=3.10"`. `.github/workflows/ci.yml`: add Python 3.10-3.13 matrix, macOS runner. Remove 3.8/3.9 entries.

**P1.7**: Create `.github/workflows/publish.yml`: trigger on tag push, `pip install build twine`, `python -m build`, OIDC PyPI publish.

---

### P2 — Token Optimization

**P2.T1**: `tool_utils.py:63-100` — strip `null` values from `details` dict before JSON serialization. Keep only non-empty fields.

**P2.T2**: `file_tools.py` — change `_MAX_READ_FILE_LINES` from 200 → 50.

**P2.T3**: `shell_tools.py:80` — change `_MAX_PROCESS_OUTPUT_CHARS` (currently 200000) → 2000. Note: variable is `_MAX_PROCESS_OUTPUT_CHARS`, not `_MAX_PROCESS_OUTPUT_READ_CHARS`.

**P2.T4**: `file_tools.py` `search_in_files` — default `limit` from 50 → 20.

**P2.T5**: `ai_evaluator.py:341` — truncate `content`/`command` fields to 200 chars or replace with `"[_MASKED_]"` in evaluation prompt.

**P2.T6**: `audit.py` — add 500-char cap on `result_summary` field.

---

### P3 — Test Coverage

**P3.1**: Create `tests/test_workflow_tools.py`. Test: `detect_project_type`, `suggest_validation_commands`, `build_context_pack`, `run_workflow`, `run_agent_loop_step`, `run_agent_loop_session`.

**P3.2**: Create `tests/test_insights.py`. Test: `project_stats`, `todo_scan`, `recent_files`, `language_distribution`, `git_log_summary`.

**P3.3**: Create `tests/test_meta_tool_server.py`. Test: `get_recent_tool_calls`, `session_insights`, `bridge_status`, `appeal_decision`.

**P3.4**: Create `tests/test_indexing.py`. Test: `extract_symbols` for each supported language, `build_index`, `iter_searchable_files`.

**P3.5**: Create `tests/test_config.py`. Test: `apply_config` validation, `resolve_approval_mode`, thread safety.

**P3.6**: Split `tests/test_protocol.py` (2400+ lines) into: `test_file_tools.py`, `test_shell_tools.py`, `test_meta_tools.py`, `test_workflow_tools.py`.

---

### P4 — Product + Ecosystem

**P4.1**: Add Anthropic/OpenAI/Ollama provider backends to `ai_evaluator.py`. Each provider: build evaluation prompt → API call → parse response → return structured `{allow, reason}`. Keep existing `LocalEvaluatorProvider` as fallback.

**P4.2**: Add `claude-bridge init` to `cli.py` using Typer. Interactive prompts: project directory, approval mode (read-only/dev-safe/ci-like/power-user), allowed roots.

**P4.3**: Create `src/claude_bridge/trust_score.py`. Read audit log JSONL, calculate: deny rate past 7 days, anomaly frequency, approval rejection trend. Register as MCP tool: `get_trust_score()`.

**P4.4**: `README.md` — replace `pipx install claude-bridge` with `pip install -e .` or wait for PyPI publish (P1.7).

**P4.5**: Move completed tasks from `tasks/active/` to `tasks/done/`. Update `tasks/needs-review.md`.

**P4.6**: Create `src/claude_bridge/url_tools.py`. New tool `read_url(url: str)`. Security: http/https only, 10s timeout, 1MB limit, 5 redirects max, content-type text/* only, audit logs URL hash not content. Use stdlib `urllib`, optional `httpx`.

**P4.7**: Create `src/claude_bridge/update.py`. CLI command `claude-bridge update` → fetch current version (`importlib.metadata`), latest PyPI version, show install command. Check-only, no auto-install.

**P4.8**: Create `src/claude_bridge/feedback.py`. New tool `send_feedback(rating: int, comment: str, include_session: bool)`. Link feedback to audit log session.

**P4.9**: In `git_ops.py`, add `generate_pr_description(diff_text: str) -> str` that formats git diff for an LLM summary. Register as tool.

---

### P5 — Remaining From Documents

Execute tasks from mega-action-plan.md P5.1 through P5.7 in order. Key implementation notes:

**P5.3.1**: `_LAST_BRIDGE_CHANGE` at `file_tools.py:57` is a module-level global. Change to dict keyed by `str(project_dir.resolve())`.

**P5.3.2**: `onboarding.py:14` `_ONBOARDING_TRIGGER_CALLS = {1, 3, 6}` → `{1, 3, 5, 8, 12}`. Add 3 more stages.

**P5.3.3**: `indexing.py:718` `read_gitignore_patterns()` has no cache. Add `{path.resolve(): (mtime, patterns)}` dict.

**P5.3.4**: `relevance.py` `find_relevant_files` output: add `selection_reason: {path_match, function_match, class_match, ...}` to each result.

**P5.3.5**: `indexing.py`, `workflow_tools.py` — enforce total disk cache size ≤ ~50MB.

**P5.3.6**: `tests/conftest.py` — add `@pytest.fixture(autouse=True)` that resets config/state between tests.

**P5.3.7**: `indexing.py:859` — `raw = file_path.read_bytes()` reads entire file even after `is_likely_binary` pre-filter passes. Replace with size-only check using stat.

**P5.5.1**: `shell_tools.py` — extra bypass vectors: `env python3`, `env bash`, full-path calls like `/usr/bin/python3`. Address in P0.1/P0.2 first, then harden here.

**P5.7.1**: `git_ops.py` `git_commit()` — cache `git rev-parse --show-toplevel` result. Same repo root for entire session.

**P5.7.2**: `file_tools.py` `write_file`/`patch_file` — add `auto_commit: bool = True` parameter. New tool `commit_changes(message: str)` for batch commits.

**P5.7.3**: `relevance.py` — pre-compute lowercase haystacks in index, not per-query. Store `content_lower`, `path_lower` etc. in index entries.

**P5.7.4**: New MCP tool `autocomplete(partial_input: str, context: str)` — return file/tool/command suggestions.

**P5.7.5**: `tool_utils.py` — support `.bridgeignore` file in project root. User-defined glob patterns for blocked files.

**P5.7.6**: `indexing.py` — log `[indexing] N/M file.name` to stderr during long operations.

**P5.7.7**: `server.py:684` — `register_prompts()` runs at module import time. Move the call inside `run_mcp_server()`.

**P5.7.8**: `shell_tools.py` — detect long-running commands (`npm install`, `cargo build`, `go test`, etc.) and auto-bump timeout to 120s.

**P5.7.9**: `indexing.py` `iter_source_files` — return `list[tuple[Path, int, int]]` with `(path, mtime_ns, size)`. Eliminate separate `stat()` loop in `build_index`.

**P5.7.10**: `git_ops.py` — merge `git add` + `git commit` into single subprocess call.

---

### P6 — Meta-Agent Layer

Create three new modules in `src/claude_bridge/`:

**`plan_engine.py`**: CRUD for JSON plan files under `.claude-bridge/plans/`. Tools: `create_plan(goal, steps)`, `execute_step(plan_id, step_id)`, `get_plan_status(plan_id)`.

**`approach_explorer.py`**: Generate N alternative approaches to a problem. Tools: `explore_approaches(problem, count)`, `execute_approach(id)`, `compare_approaches(ids)`. Results stored as JSON under `.claude-bridge/approaches/`.

**`self_critique.py`**: Deterministic code review (no AI call). Use AST parsing + regex + test output analysis. Tool: `self_critique(scope: str, criteria: list[str])`.

**`checkpoint.py`** (or add to `plan_engine.py`): `create_checkpoint(name)` → git commit + plan state snapshot. `restore_checkpoint(name)` → git checkout + restore plan state.

Register all tools in `server.py` or a new `meta_agent_server.py`.

---

## 3. Critical Code Facts (From Audit)

- `_interactive_target()` at `shell_tools.py:275` — only strips `env`, not `command`/`exec`/`builtin`
- `_command_basename()` at `shell_tools.py:271` — returns `Path(token).name.lower()`
- `blocked_command_reason()` at `shell_tools.py:406` — inline interpreter check at line 431
- `_run_ripgrep_search()` at `file_tools.py:264` — command built at line 280, no `--` separator
- `_FORK_BOMB_RE` at `shell_tools.py:51` — two alternatives, missing `$N` variant
- `_INLINE_INTERPRETER_FLAGS` at `shell_tools.py:55` — `{lua, node, perl, php, ruby}`, missing python
- `_MAX_PROCESS_OUTPUT_CHARS` at `shell_tools.py:80` (NOT `_MAX_PROCESS_OUTPUT_READ_CHARS` — that doesn't exist)
- `resolve_path()` calls `.resolve()` which resolves ALL symlinks — `is_symlink()` checks in `write_file`/`move_file`/`copy_path` are reachable through the code path but the symlink target gets resolved away. Be aware.
- `analyze_shell_command()` returns a `dict` directly, NOT a JSON string
- `_estimate_patch_risk()` returns keys: `lines_added`, `lines_removed`, `large_deletion`, `touches_tests`, etc.
- `_LAST_BRIDGE_CHANGE` at `file_tools.py:57` — module-level global, protected by `_LAST_BRIDGE_CHANGE_LOCK`
- `_ONBOARDING_TRIGGER_CALLS` at `onboarding.py:14` — `{1, 3, 6}`
- `read_gitignore_patterns()` at `indexing.py:718` — no cache, reads disk every call
- `_load_tree_sitter_parser()` at `indexing.py:872` — no `@lru_cache`
- `_iter_tree_sitter_nodes()` at `indexing.py:888` — recursive, not iterative
- `register_prompts()` called at `server.py:684` — module level, not lazy
- `is_likely_binary()` exists at `indexing.py` as pre-filter, but `iter_searchable_files` still calls `file_path.read_bytes()` at line 859 for files that pass the pre-filter

## 4. Already Done — Do NOT Touch

- File security fixes (symlink, TOCTOU, atomic writes, ReDoS, copy limit): `file_tools.py`
- Server split: `meta_tool_server.py` (706L), `file_tool_server.py` (294L), `shell_tool_server.py` (189L), `workflow_tool_server.py` (396L)
- `multi_format.py`: `read_image` + `read_pdf` on MCP surface
- `move_file` + `copy_path` tools
- `write_file` `max_lines` parameter (`_WRITE_FILE_WARNING_LINES = 500`)
- `_INLINE_INTERPRETER_FLAGS` for lua/node/perl/php/ruby — EXISTS, just missing python
- Prompt dedup: single source in `workflow_presets.py`
- `switch_project_root` calls `reset_onboarding_state()`
- `client_managed_approval` test at `tests/test_security.py:426`
- Disk cache content removal, token-set memory, incremental indexing
- 147 unit tests across `test_file_tools.py`, `test_shell_tools.py`, `test_tool_utils.py`

## 5. Verification

After every phase:
```bash
mypy src && ruff check . && pytest -q
```
Current baseline: 1197 passed, 7 skipped, 0 failures.
