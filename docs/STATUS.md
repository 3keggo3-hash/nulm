# Feature Status

Feature matrix for Nulm v0.1.2. Tracks implementation maturity and test coverage.

## Maturity Levels

- **Stable**: Production-ready, documented, well-tested
- **Beta**: Functional but may have edge cases; documented
- **Experimental**: Functional but immature; limited docs/tests

## Coverage Levels

- **High**: >80% coverage or dedicated test file
- **Medium**: Some tests, coverage gaps
- **Low**: Minimal or indirect testing only

---

## Core Features

| Feature | Module | Maturity | Tests | Notes |
|---------|--------|----------|-------|-------|
| MCP server | `server.py` | Stable | High | FastMCP-based, tool registration |
| File tools | `file_tools/` | Stable | High | read/write/patch/move/copy/search |
| Shell tools | `shell_tools.py` | Stable | High | guarded execution, process management |
| Git integration | `git_ops.py` | Stable | Medium | commit, status snapshot |
| Guard policy | `guard_policy.py` | Stable | High | JSON/YAML rules, builtin denies |
| Audit logging | `_audit_*.py` | Stable | High | JSONL records, session management |
| Config system | `config.py` | Stable | High | env vars, TOML, presets |
| Tool profiles | `config.py` | Stable | Medium | essential/standard/full profiles |

## Indexing & Search

| Feature | Module | Maturity | Tests | Notes |
|---------|--------|----------|-------|-------|
| Code indexing | `indexing.py` | Beta | Medium | symbolic index, multi-language |
| Relevance ranking | `relevance.py` | Beta | Medium | position-based, IDF weighting |
| Tree-sitter indexing | `indexing.py` | Beta | Low | optional dependency |
| Search in files | `file_tools/_search.py` | Stable | Medium | regex content search |

## Workflow & Agent Quality

| Feature | Module | Maturity | Tests | Notes |
|---------|--------|----------|-------|-------|
| Workflow engine | `workflow_tools.py` | Beta | Medium | review, optimize, test, quality modes |
| Workflow cache | `workflow_cache.py` | Beta | Medium | context pack caching |
| Agent advisor | `agent_advisor.py` | Experimental | Low | deterministic advisory only |
| Self-critique | `self_critique.py` | Experimental | Low | git-backed checkpoints |
| Plan engine | `plan_engine.py` | Experimental | Low | approach exploration |

## Security & Policy

| Feature | Module | Maturity | Tests | Notes |
|---------|--------|----------|-------|-------|
| Replay engine | `replay.py` | Stable | Medium | deterministic decision replay |
| Appeal workflow | `_audit_appeal.py` | Beta | Medium | post-hoc appeal with audit chain |
| Anomaly detection | `anomaly.py` | Beta | Medium | rule-based audit scoring |
| Team RBAC | `guard_policy.py` | Beta | Medium | role inheritance |
| Policy diff | `policy_diff.py` | Beta | Medium | CI-friendly policy comparison |

## CLI & Control Plane

| Feature | Module | Maturity | Tests | Notes |
|---------|--------|----------|-------|-------|
| CLI commands | `cli.py` | Stable | High | install, doctor, benchmark, audit |
| Control plane | `control_plane.py` | Beta | Medium | task/approval state management |
| Dashboard | `control_plane_dashboard.py` | Beta | Medium | localhost UI with tasks, approvals, CLI tab, workspace, activity; includes Web CLI with output UX and agent task runner |
| AI evaluator | `ai_evaluator.py` | Beta | Medium | local plus major cloud and OpenAI-compatible providers |

## Observability

| Feature | Module | Maturity | Tests | Notes |
|---------|--------|----------|-------|-------|
| Insights | `insights.py` | Beta | Medium | project, git, diff insights |
| Detective | `detective.py` | Beta | Medium | error classification, weighted patterns |
| Benchmarking | `benchmarking.py` | Beta | Low | query-based code search benchmarking |
| Context compression | `_context_compression.py` | Experimental | Low | token budget optimization |

## Optional Features

| Feature | Module | Maturity | Tests | Notes |
|---------|--------|----------|-------|-------|
| Multi-format reading | `multi_format.py` | Beta | Medium | image/PDF via Pillow/PyPDF2 |
| URL reading | `url_tool_server.py` | Beta | Medium | SSRF-protected HTTP/HTTPS |
| Skill registry | `skill_registry.py` | Beta | Medium | local-first skill discovery |
| Skill execution | `skill_executor.py` | Experimental | Low | skill runtime |

---

## Summary

- **Stable**: 13 features — core file/shell/security/policy tools
- **Beta**: 16 features — indexing, workflows, audit, CLI, observability
- **Experimental**: 7 features — agent quality, self-critique, context compression

Priority areas for test coverage improvement: skill execution, dashboard, tree-sitter indexing, benchmarking.
