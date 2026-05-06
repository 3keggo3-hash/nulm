# Contributing to Claude Bridge

Thank you for your interest in contributing! This guide covers everything you need to get started.

## Quick Start

```bash
git clone https://github.com/3keggo3-hash/claude-bridge.git
cd claude-bridge
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

## Development Workflow

1. **Fork** the repository and create a feature branch from `main`.
2. **Make changes** with clear, focused commits.
3. **Run the quality gate** before pushing:
   ```bash
   ruff check .
   black --check .
   mypy src
   pytest -q
   ```
4. **Open a pull request** against `main` with a clear description of the change.

## Code Standards

- **Python 3.10+** compatibility required.
- **Formatting:** Black with 100-character line length.
- **Linting:** Ruff with zero warnings.
- **Type checking:** mypy with strict settings (`disallow_untyped_defs = true`).
- **Imports:** follow existing module boundaries (CLI, MCP surface, tool implementations, config/state, indexing, workflow layers).
- **No unnecessary dependencies or abstractions.**

## Commit Messages

Use clear, imperative-style commit messages:

```
feat: add multi-root workspace support
fix: resolve symlink escape in file_tools
docs: update security model documentation
test: add coverage for policy diff engine
refactor: extract shell safety into dedicated module
```

## Tests

- All new features and bug fixes must include tests.
- Tests live in `tests/` and use pytest.
- Run the full suite: `pytest`
- For smoke checks: `./scripts/release-gate.sh`

## Pull Request Process

- Keep PRs small and focused on a single concern.
- Include a clear description of **what** changed and **why**.
- Ensure all CI checks pass (lint, type check, test on Python 3.10–3.13, macOS and Linux).
- For larger changes, open an issue first to discuss the approach.

## Architecture Overview

```
src/claude_bridge/
  cli.py              # CLI entry point (typer)
  mcp_server.py       # MCP stdio server entry
  server.py           # MCP tool registration
  config.py           # Configuration and state
  guard_policy.py     # Security guard engine
  rules_engine.py     # Policy rule evaluation
  shell_tools.py      # Shell command execution
  file_tools/         # File operations
  indexing.py         # Code indexing
  relevance.py        # File relevance scoring
  workflow_tools.py   # Workflow orchestration
  audit.py            # Audit logging
  ...
```

## Reporting Issues

- **Bugs:** Open an issue with reproduction steps, Python version, and OS.
- **Security vulnerabilities:** See [SECURITY.md](SECURITY.md) for responsible disclosure.
- **Feature requests:** Open an issue with a clear use case description.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
