# AGENTS.md

## Project Purpose

This repo contains `claude-bridge`, a Python-based MCP server that provides local file system, shell,
and controlled patch flows for Claude Desktop and other MCP clients.

## Repo Structure

- `src/claude_bridge/`: application code
- `tests/`: pytest test suite
- `docs/`: persistent product, operations, and roadmap documentation
- `examples/`: example configurations and policy files
- `benchmarks/`: benchmark profiles, baseline files, and benchmark-specific materials

## Coding Conventions

- Maintain Python 3.10+ compatibility.
- Follow the existing architecture: CLI, MCP surface, tool implementations, config/state,
  indexing/relevance, and workflow layers must stay separate.
- Adhere to naming style, module boundaries, and existing code organization.
- 100-character line limit, Black formatting, and Ruff compliance required.
- Use type hints for all new or changed production code; `mypy` strict settings apply.
- Do not add unnecessary dependencies, abstractions, or large refactors.

## Task Workflow

1. Find relevant files first and outline a brief plan.
2. Read only the files needed for the task; avoid unnecessary scanning.
3. Clarify which architectural layer the change belongs to before modifying code.
4. Change only the necessary files.
5. Add or update relevant tests when possible.
6. Run appropriate validation after changes.
7. Briefly summarize changed files and reasons at the end.

Always produce a plan before large refactors, moves, or structural changes, and verify impact.

## Test / Lint / Build Commands

- Install: `pip install -e .`
- Dev dependencies: `pip install -e .[dev]`
- Optional Tree-sitter: `pip install -e .[treesitter]`
- Test: `pytest`
- Lint: `ruff check .`
- Format: `black .`
- Type check: `mypy src`
- Benchmark: `claude-bridge benchmark --project-dir . --path src --query "auth session login"`

## Shell and Security Rules

- The security model in `shell_tools.py` must be preserved.
- Do not add or relax `sudo`, destructive `git` commands, `rm -r`, `curl|bash`, `wget|bash` patterns.
- Shell commands must be explicit, decomposed, and follow the `subprocess.run(..., shell=False)` model.
- Path boundaries, approval flows, and auto-approve behavior must not be silently changed.
- Do not add secret information, local paths, or personal config data to documentation.

## Areas to Avoid Reading Unless Necessary

- `venv/`
- `.git/`
- `__pycache__/`
- `.pytest_cache/`
- `.ruff_cache/`
- `.mypy_cache/`
- `benchmarks/baselines/` and `benchmarks/profiles/` only for benchmark-related tasks

## Documentation Rules

- Place persistent documents under `docs/`.
- New tasks go in `tasks/active/`, completed ones in `tasks/done/`.
- Old notes that should not be deleted go under `archive/`.
- Check internal links when moving folders or renaming files.
- `README.md` and `AGENTS.md` must remain at the repo root.
