# Feature Proposals: claude-bridge

> Local-first agent quality and execution layer for MCP clients.  
> Branch: `feature/hybrid-self-improve-sprint2` | Python 3.10+ | MIT License

---

## Priority/Risk Overview

| # | Feature | Priority | Risk | Complexity |
|---|---------|----------|------|------------|
| 1 | MCP Protocol Stream Extensions | High | Low | Medium |
| 2 | Workflow Composition Engine | High | Medium | High |
| 3 | Structured Audit Pipeline | Medium | Low | Medium |
| 4 | Shell Command Sandboxing v2 | Medium | High | High |
| 5 | Distributed Skill Marketplace | Low | Medium | High |

---

## Feature 1: MCP Protocol Stream Extensions

**Priority: High | Risk: Low | Complexity: Medium**

### Problem Statement
Claude Bridge lacks bidirectional streaming capabilities for long-running operations. Clients must poll for status on workflow execution, indexing, and benchmark operations, creating unnecessary latency and token overhead.

### Proposed Solution
Extend the MCP protocol with server-initiated notifications and streaming responses for:
- Workflow progress events (step completion, errors, tokens spent)
- Indexing phase updates (files scanned, symbols extracted)
- Benchmark progress streaming

### Implementation Approach
- Add `stream_events` capability flag to `initialize` handshake
- Implement SSE-like callback mechanism via existing `streaming.py` module
- Reuse `observability.py` trace context for event correlation
- Extend `mcp_server.py` with `NotificationSink` interface

### Acceptance Criteria
- [ ] Client can subscribe to workflow progress via `stream_subscribe(tool_call_id)`
- [ ] Server pushes `workflow/progress` events without client polling
- [ ] Events include: step_id, status, tokens_spent, duration_ms
- [ ] Backward compatible: clients without streaming still work

### Risk Assessment
Minimal. Feature is additive only; existing synchronous APIs remain functional.

---

## Feature 2: Workflow Composition Engine

**Priority: High | Risk: Medium | Complexity: High**

### Problem Statement
Current `workflow_engine.py` executes linear sequences. Complex agentic loops require conditional branching, parallel execution branches, and dynamic step injection based on intermediate results.

### Proposed Solution
A DAG-based workflow composer that supports:
- Parallel branches with `fan_out` / `fan_in` patterns
- Conditional steps with `if/else` on output variables
- Sub-workflow imports from skill registry
- Timeout and retry policies per step

### API Draft

```python
# Endpoint: compose_workflow
# POST /workflow/compose

Request:
{
  "name": "quality-gate-pipeline",
  "steps": [
    {
      "id": "build",
      "tool": "run_shell",
      "params": {"command": "pytest -q", "timeout": 120},
      "on_failure": "abort | skip | continue"
    },
    {
      "id": "lint",
      "tool": "run_shell", 
      "params": {"command": "ruff check ."},
      "parallel": ["typecheck", "format-check"],  # fan-out
      "fan_in": true  # wait for all parallel
    },
    {
      "id": "gate",
      "type": "conditional",
      "condition": "build.status == 'pass' && lint.status == 'pass'",
      "then": {"tool": "finish", "params": {"result": "pass"}},
      "else": {"tool": "finish", "params": {"result": "fail"}}
    }
  ],
  "retry_policy": {
    "max_attempts": 3,
    "backoff": "exponential",
    "on": ["rate_limit", "timeout"]
  }
}

Response:
{
  "workflow_id": "wf_abc123",
  "dag": { /* visualized structure */ },
  "estimated_tokens": 4200
}
```

```python
# Endpoint: execute_workflow
# POST /workflow/{workflow_id}/execute

Response (Server-Sent Events):
event: step_start {"step_id": "build", "workflow_id": "wf_abc123"}
event: step_complete {"step_id": "build", "duration_ms": 4521, "status": "pass"}
event: step_start {"step_id": "lint", "parallel": ["typecheck", "format-check"]}
event: step_complete {"step_id": "typecheck", "status": "pass"}
event: step_complete {"step_id": "format-check", "status": "pass"}
event: step_complete {"step_id": "lint", "status": "pass"}
event: workflow_complete {"workflow_id": "wf_abc123", "status": "pass", "total_duration_ms": 12034}
```

### Risk Assessment
Medium risk. Requires careful integration with existing `workflow_engine.py` and `workflow_runner.py` without breaking existing workflows. Consider phase-rolled rollout.

---

## Feature 3: Structured Audit Pipeline

**Priority: Medium | Risk: Low | Complexity: Medium**

### Problem Statement
Current audit logging (`_audit_logging.py`) produces JSONL but lacks schema enforcement, queryable indexes, and exportable audit chains for compliance replay.

### Proposed Solution
Upgrade audit system with:
- Schema-validated audit events (JSON Schema via `skill_schema.py` patterns)
- Indexed audit store with `sqlite` FTS5 full-text search
- Exportable audit chains for post-hoc replay/appeal
- Configurable redaction rules for PII

### Implementation Approach
- Extend `_audit_core.py` with `AuditEvent` dataclass + schema
- Build query interface via `_audit_query.py` with FTS5
- Add `audit_export` tool: `to_jsonl | to_csv | to_sigma` formats
- Integrate with existing `replay.py` for deterministic replay

### Acceptance Criteria
- [ ] All tool calls emit schema-validated audit events
- [ ] `query_audit(query="tool:run_shell AND status:failure", since="24h")`
- [ ] Export produces tamper-evident chain with hash linking
- [ ] Redaction configurable per audit profile

### Risk Assessment
Low. Additive schema changes; existing JSONL output remains compatible.

---

## Feature 4: Shell Command Sandboxing v2

**Priority: Medium | Risk: High | Complexity: High**

### Problem Statement
Current `shell_tools.py` uses `shell=False` for basic isolation. Advanced attack vectors (symlink races, path traversal, signal injection) require stronger containment.

### Proposed Solution
Defense-in-depth sandboxing:
- **Container-like namespace isolation** via `unshare()` (Linux) / sandbox-exec (macOS)
- **Syscall filtering** via `seccomp` or `sandbox` policy
- **Filesystem overlay** for write operations (copy-on-write)
- **Resource limits**: CPU time, memory, open files

### Security Boundaries
```
┌─────────────────────────────────────────────┐
│ Claude Bridge Process                        │
│  ┌────────────────────────────────────────┐ │
│  │ Shell Tool Server                      │ │
│  │  ┌──────────────────────────────────┐  │ │
│  │  │ Sandbox (namespace + seccomp)   │  │ │
│  │  │  ┌────────────────────────────┐  │  │ │
│  │  │  │ Restricted Command Runner  │  │  │ │
│  │  │  │ (whitelist + resource lim) │  │  │ │
│  │  │  └────────────────────────────┘  │  │ │
│  │  └──────────────────────────────────┘  │ │
│  └────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

### Risk Assessment
High operational risk. Platform-specific syscalls (Linux-only for unshare). Must gracefully degrade on unsupported platforms. Recommend feature flag `CLAUDE_BRIDGE_SANDBOX=strict|permissive|off`.

---

## Feature 5: Distributed Skill Marketplace

**Priority: Low | Risk: Medium | Complexity: High**

### Problem Statement
Skills are locally defined. Teams cannot share workflow templates, prompt engineering patterns, or custom tool bundles without manual distribution.

### Proposed Solution
Local-first marketplace architecture:
- **Manifest registry** at `~/.claude-bridge/skills/` with YAML manifests
- **Skill bundles** as `.claude-skill` tarballs with metadata, schemas, and dependencies
- **Discovery API** via `skill_marketplace.py` for browsing local/remote bundles
- **Git-backed sync** for team distribution (optional remote URL)

### API Draft

```python
# Endpoint: register_skill
# POST /skills/register

Request:
{
  "manifest": {
    "name": "python-test-generator",
    "version": "1.0.0",
    "description": "Generates pytest fixtures from function signatures",
    "author": "team-platform",
    "tags": ["testing", "python", "fixtures"],
    "tools": ["generate_fixtures", "inject_conftest"],
    "dependencies": {"pytest": ">=7.0"}
  },
  "bundle_path": "/path/to/python-test-generator.claude-skill"
}

Response:
{
  "skill_id": "sk_xyz789",
  "status": "registered",
  "compatibility_check": "pass"
}
```

```python
# Endpoint: discover_skills
# GET /skills/discover?tags=testing,python&local=true

Response:
{
  "skills": [
    {
      "skill_id": "sk_xyz789",
      "name": "python-test-generator",
      "version": "1.0.0",
      "author": "team-platform",
      "rating": 4.8,
      "installs": 142
    }
  ],
  "total": 1
}
```

### Risk Assessment
Medium. Requires versioning strategy, dependency resolution, and potential remote URL validation. Start with local-only manifests; add remote sync in v2.

---

## Appendix: Existing Module Inventory

Key modules informing these proposals:

| Category | Modules |
|----------|---------|
| **Core** | `server.py`, `mcp_server.py`, `cli.py` |
| **Tools** | `shell_tools.py`, `file_tools/`, `git_tool_server.py`, `skill_tool_server.py` |
| **Workflow** | `workflow_engine.py`, `workflow_runner.py`, `workflow_tools.py`, `workflow_agent_loop.py` |
| **Audit** | `audit.py`, `_audit_logging.py`, `_audit_query.py`, `replay.py` |
| **Quality** | `detective.py`, `self_critique.py`, `trust_score.py`, `anomaly.py` |
| **Context** | `indexing.py`, `relevance.py`, `_context_compression.py`, `prompt.py` |
| **Skills** | `skill_registry.py`, `skill_executor.py`, `skill_marketplace.py`, `skill_builder.py` |
| **Infrastructure** | `distributed_cache.py`, `resilience.py`, `tracing.py`, `observability.py` |

---

## Next Steps

1. **Review** these proposals with maintainers
2. **Prioritize** Feature 1 or 2 for sprint implementation
3. **Draft**详细 design docs for selected features
4. **Validate** against existing test suite baseline