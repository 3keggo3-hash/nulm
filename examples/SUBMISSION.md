# Awesome MCP — Claude Bridge Submission

[Awesome MCP Servers](https://github.com/mcp-server/awesome-mcp-servers) | [Submit a Server](https://github.com/mcp-server/awesome-mcp-servers/blob/main/CONTRIBUTING.md)

## Claude Bridge

A local-first agent quality and execution layer for Claude Desktop and other MCP clients. It provides
a lightweight Python MCP server for local development workflows, combining file operations, guarded
shell execution, code indexing, workflow helpers, and an advisory Agent Quality Layer—all with
explicit security boundaries and auditability.

## Key Features

- **MCP Protocol Server**: Full Model Context Protocol server implementation for Claude Desktop,
  Cursor, and other MCP clients
- **Local-First Architecture**: No remote service required for core operation; works entirely offline
- **Guarded Shell Execution**: `run_shell` through `shell=False` execution with pattern blocking
  (`sudo`, `rm -rf`, `| bash`, `curl | node`, etc.)
- **Code Indexing**: Symbolic source index and relevance ranking without embeddings
- **Workflow Helpers**: `run_workflow`, `run_agent_loop_step`, `run_agent_loop_session` for review,
  explain, test, todo, quality, and bounded agent-loop flows
- **Agent Quality Layer**: Deterministic prompt improvement, context strategy, plan critique, safe
  config suggestions, and result quality review
- **Path Boundaries**: Tools resolve paths against configured project root and allowed roots
- **Audit Logging**: Structured JSONL tool call records with replay and anomaly detection
- **Policy Engine**: Custom guard rules, team RBAC, AI advisor, and policy diff for CI/CD
- **Replay and Appeal**: Deterministic decision replay and post-hoc appeal with audit chain

## Installation

```bash
pip install -e .
claude-bridge doctor --project-dir .
claude-bridge install
```

### Add to Claude Desktop

```bash
claude-bridge install
```

Manual configuration in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "claude-bridge": {
      "command": "/usr/bin/env",
      "args": ["python3", "-m", "claude_bridge.mcp_server"],
      "env": {
        "CLAUDE_BRIDGE_PROJECT_DIR": "/absolute/path/to/project",
        "CLAUDE_BRIDGE_ALLOWED_ROOTS": "/absolute/path/to/project",
        "CLAUDE_BRIDGE_AUTO_APPROVE": "0",
        "CLAUDE_BRIDGE_TOOL_PROFILE": "standard"
      }
    }
  }
}
```

## Example Usage

```bash
claude-bridge doctor --project-dir .

claude-bridge run-workflow --mode quality --execute

claude-bridge policy validate --path .claude-bridge-guard.json

claude-bridge audit --last --tool run_shell --decision deny --risk high
```

## Differentiator

Unlike general-purpose MCP servers, Claude Bridge is designed as an **Agent Quality Layer** that
improves prompts, critiques plans, chooses smaller context, suggests safe settings, reviews
results, and reduces token waste—while keeping the security model explicit, inspectable, and
replayable. Its local-first design ensures no data leaves the machine for core operations, with
optional provider-backed advisory calls that fail closed on errors.

## Links

- [Documentation](https://github.com/3keggo3-hash/claude-bridge#readme)
- [PyPI Package](https://pypi.org/project/claude-bridge-mcp/)
- [Security Model](docs/security-model.md)
- [Agent Quality Plan](docs/agent-quality-layer-plan.md)
