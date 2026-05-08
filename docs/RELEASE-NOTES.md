# Release Notes — claude-bridge v0.1.0

**Date:** 2026-05-03
**Status:** Public alpha candidate
**Python:** 3.10+

---

## Overview

Claude Bridge is a local MCP (Model Context Protocol) server that provides file system, shell,
controlled patch flows, audit, replay, policy, indexing, and bounded workflow tools for Claude
Desktop and other MCP clients. This release establishes the first public-alpha local bridge surface
with explicit approval and audit controls.

---

## Features

### Core MCP Tools
- **File operations:** read, write, copy, move, patch, search
- **Shell execution:** guarded non-interactive command execution with approval flow and dangerous command blocking
- **Codebase indexing:** symbolic index with Tree-sitter support (optional)
- **Relevance ranking:** token-aware, field-aware file relevance scoring
- **Workflow orchestration:** guided workflows for review, optimize, test, explain, commit, todo

### Security Layer
- **Fail-closed security model:** all tool calls pass through guard policy evaluation
- **Rule engine:** JSON/YAML-based custom rules with regex, glob, extension, and file_exists conditions
- **AI Advisor:** optional second-opinion provider path with fail-closed parsing and built-in hard-deny precedence
- **Policy-as-code:** version-controlled guard policies with validate, diff, and simulate commands
- **Approval flow:** interactive approval for sensitive operations

### Audit & Replay
- **Structured audit logging:** JSONL format with parameter summarization and secret masking
- **Session management:** audit session summary and export
- **Deterministic replay:** re-evaluate past decisions against updated policies
- **Anomaly detection foundations:** rule-based anomaly scoring for audit records

### Developer Experience
- **CLI interface:** `claude-bridge` command with install, config, doctor, and benchmark subcommands
- **Multi-format readers:** optional image (Pillow) and PDF (PyPDF2) content extraction
- **Doctor report:** environment diagnostics and dependency health check
- **Benchmarking:** repeatable indexing and relevance benchmark with baseline comparison

---

## Quality Gate

All releases must pass the quality gate script:

```bash
./scripts/release-gate.sh
```

Checks performed:
- `ruff check .` — lint compliance
- `mypy src` — type checking (strict)
- `pytest` — test suite (1050+ tests)
- Policy validate (JSON example)
- Audit summary & replay smoke tests
- Package metadata validation
- Import smoke tests

---

## Known Limitations

- Relevance scoring is keyword-based; no embedding or graph-based semantic search yet
- Linux/Windows end-to-end validation not yet performed
- Tree-sitter integration is optional; behavior may differ with/without it
- Index cache is in-memory; very large mono-repos may need disk cache in future
- PyYAML is optional; YAML policy files require manual installation
- Anomaly scoring is advisory in v0.1; high scores warn/log but do not enforce guard decisions
- Claude Bridge is a policy-gated local runner, not an OS/container sandbox

---

## Installation

```bash
# From PyPI (future)
# pipx install claude-bridge

# From source
pip install -e ".[dev]"
```

---

## Changelog

### v0.1.0 (2026-05-03)

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
| Name | claude-bridge |
| Version | 0.1.0 |
| License | MIT |
| Python | >=3.10 |
| Entry point | `claude_bridge.cli:main` |
| Core deps | mcp, pathspec, typer, rich, pydantic |
| Optional deps | tree-sitter, tiktoken, Pillow, PyPDF2 |

---

## Related Documents

- `docs/publishing-checklist.md`
- `docs/security-model.md`
- `docs/product-vision.md`
- `docs/roadmap.md`
