# AGENTS.md

## Project

`claude-bridge`: Python 3.10+ MCP server for local filesystem, shell, and patch flows.

- App: `src/claude_bridge/`
- Tests: `tests/`
- Docs: `docs/`
- Examples: `examples/`
- Benchmarks: `benchmarks/`

## Work Rules

- Low-token mode: no preamble, no apologies, concise output; explain only when useful or asked.
- DCP: use `.opencode/opencode.json` + `.opencode/dcp.jsonc`; prefer `/dcp` in long sessions.
- RTK: load `.opencode/rules/*.md` only when the task matches; do not paste all rules by default.
- Keep layers separate: CLI, MCP API, tools, config/state, indexing/relevance, workflows.
- Match existing naming, module boundaries, and style.
- Type-hint changed production code; keep strict `mypy`, Black, Ruff, and <=100-char lines.
- Avoid new deps, broad abstractions, and unrelated refactors.
- Preserve `shell_tools.py` security, path boundaries, approvals, and auto-approve behavior.
- Do not relax `sudo`, destructive git, `rm -r`, `curl|bash`, or `wget|bash` blocks.
- Use explicit shell commands and `subprocess.run(..., shell=False)`.
- Never add secrets, personal config, or private local paths to docs.
- Find relevant files first; avoid broad scans.
- Identify the affected layer before editing.
- Change only what is needed.
- Add/update focused tests when behavior changes.
- Run relevant validation.
- Summarize changed files and reasons.
- Plan first for large refactors, moves, or structural changes.

## Commands

- Install: `pip install -e .`
- Dev deps: `pip install -e .[dev]`
- Optional Tree-sitter: `pip install -e .[treesitter]`
- Test: `pytest`
- Lint: `ruff check .`
- Format: `black .`
- Type check: `mypy src`
- Benchmark: `claude-bridge benchmark --project-dir . --path src --query "auth session login"`

## Avoid

- `venv/`, `.git/`, `__pycache__/`
- `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/`
- `benchmarks/baselines/`, `benchmarks/profiles/` unless benchmarking

## Docs

- Durable docs: `docs/`; active tasks: `tasks/active/`; done tasks: `tasks/done/`.
- Archive old notes in `archive/`; keep root `README.md` and `AGENTS.md`.
