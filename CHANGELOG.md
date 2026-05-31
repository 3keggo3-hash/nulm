# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.5] - 2026-05-31

### Changed

- Remove broken GitHub Actions CI and rate-limited PyPI download badges from README.

## [0.1.4] - 2026-05-30

### Security

- Remove leaked MiniMax API key from git history and stop tracking `.opencode/` local config.
- Add gitleaks pre-commit hook and `.gitleaks.toml` allowlist for test fixtures.

### Changed

- Document known limitations honestly: audit default key, shell rate-limit wiring status, experimental
  secret store, and `client_managed_approval` contract.
- Log warnings when `CLAUDE_BRIDGE_*_JSON` environment variables contain invalid JSON.
- Untrack `web/node_modules/`, internal planning docs, and local-only development paths.
- Add `examples/opencode.json.example` as a public OpenCode config template.

### Fixed

- Correct `secret_store` and `feedback` docstrings to match actual behavior.

## [0.1.3] - 2026-05-24

### Fixed

- Agent benchmark release gates now scan packaged subagent source files relative to the installed
  package instead of the current working directory, so `nulm agent-benchmark --gates-only` works
  from outside a source checkout.

## [0.1.2] - 2026-05-24

### Changed

- AI routing decisions now expose quality tier, token cap, and estimated maximum cost metadata for
  model selection transparency.
- README now leads with the concrete MCP safety use case, moves security up front, separates core,
  optional, and experimental surfaces, and explains `claude-bridge` compatibility naming.
- Multi-agent execution roadmap now includes a limited `MissionBrief`/context curator layer that
  packages subagent context without acting as a second master.
- Release docs now use the actual `nulm doctor --project-dir . security` command shape.

### Fixed

- AI evaluator configuration now fails closed when an enabled provider is unavailable instead of
  silently skipping advisory evaluation.
- Source distributions exclude root `web/node_modules` and `web/dist`, keeping the release package
  small and free of local frontend build dependencies.

## [0.1.1] - 2026-05-17

Public alpha candidate. The project is now positioned as a local-first agent quality and execution
layer, with deterministic Agent Quality tools implemented as the first advisory slice.

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
- Agent Quality tools: `advise_next_step`, `improve_request`, `plan_quality_review`,
  `suggest_bridge_config`, `apply_bridge_config_change`, and `review_result_quality`.
- Quality workflow integration with compact next prompts and result review guidance.
- CLI interface: `nulm install`, `setup`, `doctor`, `benchmark`, `policy`, `audit`,
  `replay`, `appeal`, `anomaly`.
- Multi-format readers as optional dependencies.
- Release quality gate script (`scripts/release-gate.sh`).
- CI pipeline (GitHub Actions) with matrix testing on Python 3.10–3.13 (Linux, macOS).
- PyPI publish workflow with Trusted Publisher support.
- Agent Quality Layer docs and example chat flows for prompt improvement, context strategy, plan
  critique, chat-driven safe config suggestions, result review, and token reduction.

### Fixed

- 39 bugs across insights, workflow, shell, config, server, and tool modules.
- Index validation and shell safety regressions.
- Security layer execution hardening.

### Changed

- Security model hardened to fail-closed by default.
- MCP tool registration split into separate modules.
- Meta prompt registration split into dedicated module.
- Public release docs updated to separate implemented advisory behavior from future provider-backed
  ambitions.

[0.1.3]: https://github.com/3keggo3-hash/nulm/releases/tag/v0.1.3
[0.1.2]: https://github.com/3keggo3-hash/nulm/releases/tag/v0.1.2
[0.1.1]: https://github.com/3keggo3-hash/nulm/releases/tag/v0.1.1
[0.1.0]: https://github.com/3keggo3-hash/nulm/releases/tag/v0.1.0
