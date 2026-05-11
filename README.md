# Claude Bridge

CI: GitHub Actions | PyPI package: `claude-bridge-mcp` | CLI: `claude-bridge` |
Python: 3.10+ | License: MIT |
Code style: Black

> A local-first agent quality and execution layer for Claude Desktop and other MCP clients.

Claude Bridge is a lightweight Python MCP server for local development and agent workflows. It lets
an MCP client inspect project files, run guarded shell commands, apply controlled patches, build
context packs, search/index source code, use bounded workflow helpers, and coordinate small
meta-agent tasks without giving up path boundaries, auditability, or approval controls.

It is designed to make rough user requests easier to turn into professional software work. Today it
provides the local MCP execution substrate and early advisory tools. The longer-term direction is an
Agent Quality Layer that improves prompts, critiques plans, chooses smaller context, suggests safe
Bridge settings, reviews results, and reduces token waste while keeping the security model explicit,
inspectable, and replayable.

## Quick Start

```bash
pip install -e .
claude-bridge doctor --project-dir .
claude-bridge install
```

Then fully quit and reopen Claude Desktop, and start a new conversation. A successful install gives
Claude access to `tools_overview` and `bridge_status`; mutating actions should still ask for client
approval.

For lower-token sessions, set `CLAUDE_BRIDGE_TOOL_PROFILE=essential`. See
[`docs/ai-collaboration-token-budget.md`](docs/ai-collaboration-token-budget.md).

## First 5 Minutes

Try a natural request first:

```text
Use Claude Bridge to check whether this project is public-ready.
```

The useful first path is `tools_overview`, `bridge_status`, then
`run_workflow(mode="quality")`. For completed work, call `review_result_quality` with the changed
files and validation commands. For token or tool-surface tuning, call `suggest_bridge_config` before
`apply_bridge_config_change`.

## Features

- **File operations**: `read_file`, `read_image`, `read_pdf`, `list_directory`, `write_file`,
  `move_file`, `copy_path`, `search_in_files`
- **Targeted edits**: `patch_file`, `preview_patch` with SEARCH/REPLACE patches
- **Shell execution**: `run_shell` through a guarded `shell=False` execution path
- **Code indexing**: `index_codebase`, `find_relevant_files` — symbolic source index and relevance
  ranking without embeddings
- **Workflow helpers**: `run_workflow`, `run_agent_loop_step`, `run_agent_loop_session` — structured
  review, explain, test, todo, quality, and bounded agent-loop flows
- **URL reading**: `read_url` — constrained text-only HTTP/HTTPS reader with SSRF protections
- **Git integration**: file mutations committed automatically when target is in a Git repository
- **Audit logging**: tool calls recorded as structured JSONL
- **Policy engine**: custom guard rules, team RBAC, AI advisor, policy diff for CI/CD
- **Replay and appeal**: deterministic decision replay and post-hoc appeal with audit chain
- **Anomaly detection**: rule-based audit anomaly scanning
- **Meta-agent tools**: local plans, approach exploration, deterministic self-critique, git-backed
  checkpoints
- **Tool profiles**: `essential`, `standard`, `full` for token/capability tradeoffs
- **Agent Quality tools**: deterministic prompt improvement, context strategy, plan critique,
  safe config suggestions, workflow quality gates, result quality review, and fail-safe provider
  advice parsing telemetry

## Installation

```bash
pip install -e .          # core
pip install -e .[dev]     # development
pip install -e .[treesitter]  # optional Tree-sitter indexing
pip install -e .[multi-format] # optional image/PDF reading
```

### Add to Claude Desktop

```bash
claude-bridge install    # auto-update config
claude-bridge setup      # print config snippet
```

Manual config example:

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
        "CLAUDE_BRIDGE_TOOL_PROFILE": "standard",
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": "/absolute/path/to/repo/src"
      }
    }
  }
}
```

## Approval Model

Claude Bridge starts fail-closed by default. Mutating tools and shell tools require either
client-managed approval or trusted local auto-approval (`CLAUDE_BRIDGE_AUTO_APPROVE=1`).

For Claude Desktop approval UI support:
`claude-bridge setup --client-managed-approval ...`.

## Workflow Modes

`run_workflow` supports: `review`, `optimize`, `orchestrate`, `agent_loop`, `quality`, `test`,
`todo`, `explain`, `commit`. Prompt shortcuts (`/review`, `/optimize`, etc.) are also registered.

With `execute=true`, workflows run a safe read-only discovery step (file reads and listing only,
no shell or patch execution).

## Agent Quality examples

The current Agent Quality Layer is deterministic and advisory by default. It can clarify rough
requests, critique plans, suggest context/token strategy, expose quality-first workflow gates, and
review result quality. Provider-backed advice parsing has a strict local fail-safe contract, but
this layer does not make network provider calls by itself. It does not replace approvals, hard
denies, or local configuration rules.

See [`docs/agent-quality-chat-flows.md`](docs/agent-quality-chat-flows.md) for non-expert chat
flows such as public readiness, professionalizing code, reducing token use, fixing bugs, and
checking whether completed work is good enough.

## Security

- **Local-only by design**: no remote service needed for core operation
- **Path boundaries**: tools resolve paths against configured project root and allowed roots
- **Command filtering**: `sudo`, `rm -rf`, `chmod 777`, `| bash`, `curl | node`, `node -e` blocked
- **Path traversal protection**: `../` cannot escape configured roots
- **Sensitive file protection**: `.env`, `.pem`, `.key`, `id_rsa` blocked from reads/writes/patches
- **Symlink hardening**: copy/move operations reject symlink attacks
- **TOCTOU protection**: writes use `O_CREAT | O_EXCL` and pre-write symlink checks
- **Atomic writes**: temp file then `os.replace` to prevent partial writes
- **ReDoS protection**: regex compilation has 2-second timeout
- **Audit logging**: structured, masked audit records with replay capability

## Custom Policy

Add `.claude-bridge-guard.json` to the project root to customize the guard layer. Supports
`blocked_shell_patterns`, `sensitive_path_patterns`, `secret_patterns`, and ordered `rules` with
conditions (`tool`, `field_equals`, `regex`, `glob`, `extension`, etc.).

```bash
claude-bridge policy validate --path .claude-bridge-guard.json
claude-bridge policy simulate \
  --path .claude-bridge-guard.json \
  --tool run_shell \
  --param command="npm test"
```

See [docs/security-model.md](docs/security-model.md) for full rule-writing guide.

## Team Policy (RBAC)

Team policies define role-based access controls with inheritance. See
[docs/security-model.md](docs/security-model.md) for the full schema.

```bash
claude-bridge policy diff --base .claude-bridge/team.json --head pr/team.json
```

## AI Advisor and Agent Quality Direction

An optional second-opinion layer for proposed agent actions. It can suggest `allow`, `deny`, or
`ask`, but its broader role is to critique whether the next step is necessary, scoped, safe, and
aligned with the user's intent. It acts like a debate partner between the coding agent and local
execution, without overriding built-in hard denies.

Disabled by default. The local deterministic provider works without network access; Anthropic,
OpenAI, and Ollama providers are optional and fail closed on invalid responses or provider errors.
The current Python module and environment variables still use the `ai_evaluator` name for backward
compatibility.

The current advisor is an early slice of the larger Agent Quality Layer planned in
[`docs/agent-quality-layer-plan.md`](docs/agent-quality-layer-plan.md). That layer is intended to
help users write less-perfect prompts while still getting scoped plans, lower token usage, safer
config choices, and stronger result review. `bridge_status` also exposes Agent Quality telemetry
for provider-response parsing and fallback counts so failures stay visible.

```bash
export CLAUDE_BRIDGE_AI_EVALUATOR_ENABLED=1
export CLAUDE_BRIDGE_AI_EVALUATOR_PROVIDER=local
```

## Audit, Replay, and Anomaly Detection

```bash
claude-bridge audit --last --tool run_shell --decision deny --risk high
claude-bridge replay --record-id <record_id>
claude-bridge anomaly scan --last
claude-bridge appeal --record-id <record_id> --justification "reason"
```

Anomaly scoring is advisory in v0.1: high scores are surfaced in summaries and audit metadata, but
they do not silently change guard-policy decisions. Claude Bridge is a policy-gated local runner,
not an OS or container sandbox.

## Development

```bash
pip install -e .[dev]
claude-bridge doctor --project-dir .
ruff check .
black --check .
mypy src
pytest
```

## Benchmarking

```bash
claude-bridge benchmark --query "login auth" --path src --json
```

## Troubleshooting

| Issue | Fix |
|---|---|
| No file access | Fully quit and reopen Claude Desktop; try "Use `workspace_status`" |
| macOS: Operation not permitted | Use `/usr/bin/env` with the module command in config. |
| Prompts not appearing | Check `claude_desktop_config.json` is valid JSON; verify `PYTHONPATH` |
| MCP logs | `~/Library/Logs/Claude/mcp-server-claude-bridge.log` |

## Requirements

- Python 3.10+
- Claude Desktop or another MCP client

## License

MIT. See [LICENSE](LICENSE).

## Contributing

Contributions are welcome. Please open an issue before larger changes.

This project is not an official Anthropic product.
