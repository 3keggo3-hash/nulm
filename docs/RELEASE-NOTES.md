# Release Notes — claude-bridge v0.1.0

**Date:** 2026-05-03
**Status:** Pre-release / Alpha
**Python:** 3.8+

---

## Overview

Claude Bridge is a local MCP (Model Context Protocol) server that provides file system, shell, and controlled patch flows for Claude Desktop and other MCP clients. This release establishes the core security evaluation layer with AI-driven allow/deny/ask decision making.

---

## Features

### Core MCP Tools
- **File operations:** read, write, copy, move, delete, patch, search
- **Shell execution:** sandboxed command execution with approval flow and dangerous command blocking
- **Codebase indexing:** symbolic index with Tree-sitter support (optional)
- **Relevance ranking:** token-aware, field-aware file relevance scoring
- **Workflow orchestration:** guided workflows for review, optimize, test, explain, commit, todo

### Security Layer
- **Fail-closed security model:** all tool calls pass through guard policy evaluation
- **Rule engine:** JSON/YAML-based custom rules with regex, glob, extension, and file_exists conditions
- **AI evaluator:** configurable AI-driven security evaluation (allow/deny/ask)
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
- AI evaluator with fail-closed decision model
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
| Python | >=3.8 |
| Entry point | `claude_bridge.cli:main` |
| Core deps | mcp, pathspec, typer, rich, pydantic |
| Optional deps | tree-sitter, tiktoken, Pillow, PyPDF2 |
