# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-05-03

### Added

- Core MCP server with file, shell, and patch tools (`read_file`, `write_file`, `patch_file`,
  `run_shell`, `search_in_files`, `move_file`, `copy_path`).
- Image and PDF reading support via optional dependencies (Pillow, PyPDF2).
- URL reading tool (`read_url`) with SSRF protections.
- Git integration for automatic commits on file mutations.
- Code indexing and relevance ranking with optional Tree-sitter support.
- Workflow orchestration: `review`, `optimize`, `orchestrate`, `agent_loop`, `quality`, `test`,
  `todo`, `explain`, `commit`.
- Fail-closed security guard policy engine with JSON/YAML rule support.
- AI evaluator with fail-closed decision model (local, Anthropic, OpenAI, Ollama providers).
- Policy-as-code: `validate`, `simulate`, `diff` CLI commands.
- Team policy RBAC with role inheritance.
- Structured audit logging (JSONL) with secret masking and session management.
- Deterministic policy replay engine.
- Rule-based anomaly scoring for audit records.
- Audit appeal workflow with audit chain.
- Meta-agent tools: local plans, approach exploration, deterministic self-critique, git-backed
  checkpoints.
- Tool profiles (`essential`, `standard`, `full`) for token/capability tradeoffs.
- CLI interface: `claude-bridge install`, `setup`, `doctor`, `benchmark`, `policy`, `audit`,
  `replay`, `appeal`, `anomaly`.
- Multi-format readers as optional dependencies.
- Release quality gate script (`scripts/release-gate.sh`).
- CI pipeline (GitHub Actions) with matrix testing on Python 3.10–3.13 (Linux, macOS).
- PyPI publish workflow with Trusted Publisher support.

### Fixed

- 39 bugs across insights, workflow, shell, config, server, and tool modules.
- Index validation and shell safety regressions.
- Security layer execution hardening.

### Changed

- Security model hardened to fail-closed by default.
- MCP tool registration split into separate modules.
- Meta prompt registration split into dedicated module.

[0.1.0]: https://github.com/3keggo3-hash/claude-bridge/releases/tag/v0.1.0
