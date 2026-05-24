# Release Notes — nulm v0.1.2

**Date:** 2026-05-24
**Status:** Public alpha
**Python:** 3.10+

---

## Overview

Nulm is a local MCP (Model Context Protocol) server that provides file system, shell,
controlled patch flows, audit, replay, policy, indexing, and bounded workflow tools for Claude
Desktop and other MCP clients. This release establishes the local execution substrate with explicit
approval and audit controls.

The broader product direction is now the Agent Quality Layer described in
`docs/agent-quality-layer-plan.md`: prompt improvement, context strategy, plan critique, safe
configuration guidance, result review, and token reduction. This release includes the deterministic
advisory MVP for those flows while keeping provider-backed behavior optional and fail-safe.

---

## Features

### Core MCP Tools
- **File operations:** read, write, copy, move, patch, search
- **Shell execution:** guarded non-interactive command execution with approval flow and dangerous
  command blocking
- **Codebase indexing:** symbolic index with Tree-sitter support (optional)
- **Relevance ranking:** token-aware, field-aware file relevance scoring
- **Workflow orchestration:** guided workflows for review, optimize, test, explain, commit, todo,
  and quality-first release/code review flows

### Security Layer
- **Fail-closed security model:** all tool calls pass through guard policy evaluation
- **Rule engine:** JSON/YAML-based custom rules with regex, glob, extension, and file_exists
  conditions
- **AI Advisor:** optional second-opinion provider path with fail-closed parsing and built-in
  hard-deny precedence
- **Agent Quality Layer tools:** deterministic request improvement, next-step advice, plan review,
  safe config suggestions, safe config mutation, result quality review, and workflow quality gates
- **Policy-as-code:** version-controlled guard policies with validate, diff, and simulate commands
- **Approval flow:** interactive approval for sensitive operations

### Audit & Replay
- **Structured audit logging:** JSONL format with parameter summarization and secret masking
- **Session management:** audit session summary and export
- **Deterministic replay:** re-evaluate past decisions against updated policies
- **Anomaly detection foundations:** rule-based anomaly scoring for audit records

### Developer Experience
- **CLI interface:** `nulm` command with install, config, doctor, and benchmark subcommands
- **Multi-format readers:** optional image (Pillow) and PDF (PyPDF2) content extraction
- **Doctor report:** environment diagnostics and dependency health check
- **Benchmarking:** repeatable indexing and relevance benchmark with baseline comparison
- **Tool profiles:** essential, standard, and full MCP surfaces for token/capability tradeoffs

---

## Quality Gate

All releases must pass the quality gate script:

```bash
./scripts/release-gate.sh
```

Checks performed:
- `ruff check .` — lint compliance
- `mypy src` — type checking (strict)
- `pytest` — test suite (2500+ tests)
- Policy validate (JSON example)
- Audit summary & replay smoke tests
- Package metadata validation
- Import smoke tests
- Package build and `twine check`
- GitHub Actions matrix for Python 3.10-3.13 on Ubuntu and macOS

---

## Known Limitations

- Agent Quality Layer tools are an advisory deterministic MVP; they do not replace human review or
  independently prove correctness
- Relevance scoring is keyword-based; no embedding or graph-based semantic search yet
- GitHub CI covers Linux and macOS; Windows end-to-end validation is not yet performed
- Tree-sitter integration is optional; behavior may differ with/without it
- Index cache is in-memory; very large mono-repos may need disk cache in future
- PyYAML is optional; YAML policy files require manual installation
- Anomaly scoring is advisory in v0.1; high scores warn/log but do not enforce guard decisions
- Nulm is a policy-gated local runner, not an OS/container sandbox

---

## Installation

```bash
# From source
pip install -e ".[dev]"
```

---

## Changelog

### v0.1.2 (2026-05-24)

**Added:**
- Web CLI tab (formerly Messages) with output UX: exit badge, stdout/stderr blocks,
  copy, rerun, collapse, and filter controls
- Backend CLI streaming via subprocess.Popen and `GET /api/cli/{id}/stream` polling
- CLI permission levels: `read_only`, `safe_local`, `needs_approval`, and blocked commands
  enforced server-side in the dashboard runner
- Agent task runner: `POST /api/agent` to submit tasks, `GET /api/agent/task/{task_id}` to poll
- Guarded CLI runner security properties documented in `docs/security-model.md`

**Changed:**
- Dashboard CLI runner now captures and stores stdout/stderr separately in message metadata
- Background CLI jobs tracked by session ID with process lifecycle management
- AI routing telemetry now exposes quality tier, token cap, and estimated maximum cost metadata
- Release docs use the actual `nulm doctor --project-dir . security` command shape

**Fixed:**
- Enabled but unavailable AI evaluator providers now fail closed instead of silently skipping the
  advisory layer
- Source distributions exclude root `web/node_modules` and `web/dist`, reducing the sdist from
  local-build size to release size

### v0.1.0 (2026-05-10)

**Added:**
- Core MCP server with file, shell, and patch tools
- Security guard policy engine with JSON/YAML rule support
- AI Advisor/evaluator with fail-closed decision model and audit-visible recommendations
- Audit logging with secret masking and session management
- Deterministic policy replay engine
- Rule-based anomaly scoring for audit records
- Codebase indexing with Tree-sitter support (optional)
- Relevance ranking with token and field awareness
- Workflow orchestration with agent loop support
- Agent Quality Layer advisory tools and quality workflow integration
- CLI with install, config, doctor, and benchmark commands
- Multi-format readers (image, PDF) as optional dependencies
- Release quality gate script (`scripts/release-gate.sh`)
- Exception handling for all JSON/YAML parsing paths

**Fixed:**
- 39 bugs across insights, workflow, shell, config, server, and tool modules
- Index validation and shell safety regressions
- Security layer execution hardening

**Changed:**
- Security model hardened to fail-closed by default
- MCP tool registration split into separate modules
- Meta prompt registration split

---

## Package Metadata

| Field | Value |
|-------|-------|
| Distribution name | nulm |
| Version | 0.1.2 |
| License | MIT |
| Python | >=3.10 |
| CLI entry point | `nulm` → `claude_bridge.cli:main`; `claude-bridge` compatibility alias |
| Core deps | mcp, pathspec, typer, rich, pydantic |
| Optional deps | treesitter, smart, memory, multi-format, policy-yaml, redis, observability, tracing, streaming, legacy |

---

## Related Documents

- `docs/publishing-checklist.md`
- `docs/security-model.md`
- `docs/product-vision.md`
- `docs/agent-quality-layer-plan.md`
- `docs/roadmap.md`
