# Architecture

Claude Bridge is a local MCP server bridging Claude Desktop/VS Code to local filesystem and shell access.

## System Overview

```
MCP Client ──(stdio)──> FastMCP (server.py) ──> File System / Shell
                           │
                     Guard Policy
                     Approval Gate
                     Audit Log
```

## Module Map

| Layer | Files | Responsibility |
|-------|-------|----------------|
| Entry | `cli.py`, `__main__.py`, `mcp_server.py` | CLI commands, server startup |
| Core | `server.py` | FastMCP instance, tool registration, config, audit wiring |
| Tool Servers | `file_tool_server.py`, `shell_tool_server.py`, `indexing_tool_server.py`, `workflow_tool_server.py`, `meta_tool_server.py`, `control_plane_tool_server.py`, `skill_tool_server.py`, `multi_format_tool_server.py`, `url_tool_server.py`, `git_tool_server.py` | Thin wrappers that register tools with FastMCP |
| Implementations | `file_tools/`, `shell_tools.py`, `workflow_tools.py`, `url_tools.py` | Actual logic for file/shell/network ops |
| Security | `guard_policy.py`, `permissions.py`, `_shell_safety.py`, `_audit_*.py` | Policy evaluation, builtin denies, redaction |
| Agents | `agents/base.py`, `agents/orchestrator.py`, `agents/dispatcher.py`, `agents/sub/` | Multi-agent orchestration with permission matrix |
| State | `config.py`, `control_plane.py` | Runtime config, durable task/approval state |

## Data Flow

```
start ─> set_config() ─> run_mcp_server() ── stdio
                                     │
                             MCP request
                                     │
                         ┌───────────┴───────────┐
                         │  FastMCP routes to     │
                         │  registered tool       │
                         └───────────┬───────────┘
                                     │
                    ┌────────────────┴────────────────┐
                    │ Guard Policy evaluation        │
                    │ (builtin denies → rules)       │
                    └────────────────┬────────────────┘
                                     │
                         ┌───────────┴───────────┐
                         │ Approval gate (ask/   │
                         │ deny if not auto-ok)  │
                         └───────────┬───────────┘
                                     │
                         ┌───────────┴───────────┐
                         │ Tool implementation    │
                         │ (file_tools, etc.)     │
                         └───────────┬───────────┘
                                     │
                    ┌────────────────┴────────────────┐
                    │ Audit log (JSONL)               │
                    └────────────────┬────────────────┘
                                     │
                             JSON response
```

## Adding a New MCP Tool

1. **Implement** in `file_tools/`, `shell_tools.py`, or new module
2. **Create `*_tool_server.py`** registration helper (follow existing pattern)
3. **Wire in `server.py`**:
   ```python
   _MY_TOOLS = register_my_tools(mcp=mcp, tool_options=_tool_options, ...)
   my_tool = _tool_or_disabled(_MY_TOOLS, "my_tool")
   ```
4. **Export** from `mcp_server.py`

Registration pattern:
```python
def register_my_tools(*, mcp, tool_options, audit_tool_call, ...):
    ctx = ToolRegistrationContext(mcp=mcp, tool_options=tool_options,
                                   audit_tool_call=audit_tool_call)
    if ctx.should_register("my_tool"):
        async def my_tool(param: str) -> str:
            started_at = ctx.now_ms()
            result = await my_tool_impl(param)
            return audit_tool_call("my_tool", {"param": param}, result, started_at=started_at)
        ctx.register("my_tool", "Description", my_tool, read_only=True)
    return ctx.results
```

## Security Model Summary

- **Trust boundary**: Local process, stdio only, no network listeners
- **Policy layers**: builtin denies → guard rules → approval gate → execution
- **Approval modes**: read-only, dev-safe (default), ci-like, power-user
- **Path enforcement**: All file ops restricted to `project_dir` + `--allow-root`
- **Audit**: Every call logged to JSONL with redaction
- **Agent permissions**: Each sub-agent has allow/deny tool set via `permissions.py`

See `docs/security-model.md` for full details.

## Local Control Plane Dashboard

The dashboard provides a responsive localhost interface for monitoring and managing Claude Bridge
operations from the same machine. Phone access is available only when the user explicitly starts a
tunnel and opens the token-protected tunnel URL.

### Approvals

The approval workflow enables real-time decision-making on pending operations:

- **List pending**: Fetch all unresolved approvals with timestamp, tool name, and risk indicator
- **Approve/deny**: Resolve individual requests; approvals are durable and survive server restarts
- **Audit trail**: Resolution actions are written back to durable control-plane state

### Messages Queue

Asynchronous message handling for dashboard-to-agent communication:

- **Enqueue**: Submit a text instruction from the dashboard into the local message queue
- **Consume**: MCP tools can list, acknowledge, and complete queued dashboard messages

### Config/Status

Runtime state visibility:

- **Status overview**: Show task counts, pending approvals, and queued dashboard messages

### Mobile-Friendly Layout

The interface uses responsive CSS so the same token-protected dashboard remains usable on narrow
screens when exposed through an explicit tunnel:

- **Responsive layout**: Adapts to phone, tablet, and desktop viewports
- **Touch-friendly controls**: Action buttons and message input do not depend on hover

## Adaptive Skills Approval Model

Skills (reusable parameterized workflows) are generated from audit history by detecting repeating operation patterns. Before any skill is persisted, the system applies an adaptive approval model.

### Workflow Recommendation from Audit History

The system analyzes audit logs to identify recurring tool call sequences with consistent parameter patterns. When a sequence appears multiple times above a confidence threshold, a skill recommendation is generated with supporting evidence.

Recommendations are presented to the user for approval — not automatically applied.

### Approval Gate Criteria

Skills must pass all of the following before creation:

- **Confidence scoring**: Pattern match score >= configurable threshold (default 0.7)
- **Evidence trail**: Recommendation includes audit-derived justification
- **Permission alignment**: Required tools must be allowed under current permission profile
- **Risk assessment**: Guard policy evaluates tool combination risk; destructive patterns trigger scrutiny

### Privacy Filter

The skill creation pipeline excludes sensitive content:

- Secrets and credentials (detected via redaction patterns)
- Private or out-of-scope paths (outside `project_dir` and allowed roots)
- One-off commands (low frequency, no repeating structure)

Audit logs used for pattern detection are themselves redacted before analysis.

### Skill Lifecycle

```
Audit log -> Pattern detection -> Recommendation -> User approval -> Skill created
                                                       |
                                              Rejected / Modified
```

User approval is required at creation time. Skills do not self-modify.
