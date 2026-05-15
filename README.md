# Claude Bridge

## What's New

- **Context Compression Manager** — IMPLEMENTED (decompression bomb protection added to `_context_compression.py`)
- **Audit Trail Query Interface** — IMPLEMENTED (SQL-like parser in `_audit_query_parser.py`)
- **Autonomous Skill Discovery** — IMPLEMENTED security hardening (26 blocked patterns in `_shell_safety.py`)
- **Hierarchical Approval System** — IMPLEMENTED (`_approval_hierarchy.py` + `tool_utils.py` integration)
- **Parallel Workflow Executor** — IMPLEMENTED (`_parallel_executor.py` + `workflow_engine.py` extension)

<!-- GitHub Topics: mcp-server, claude-bridge, agent-quality, local-ai, developer-tools -->
CI: GitHub Actions | PyPI package: `claude-bridge-mcp` | CLI: `claude-bridge` |
Python: 3.10+ | License: MIT |
Code style: Black

> A local-first agent quality and execution layer for MCP clients.

Claude Bridge is a lightweight Python MCP server for local development and agent workflows. It lets
an MCP client inspect project files, run guarded shell commands, apply controlled patches, build
context packs, search/index source code, use bounded workflow helpers, and coordinate small
meta-agent tasks without giving up path boundaries, auditability, or approval controls.

It is designed to make rough user requests easier to turn into professional software work. Today it
provides the local MCP execution substrate and early advisory tools. The longer-term direction is a
local-first control plane for agentic development: prompt improvement, plan critique, smaller
context choices, safe Bridge settings, result review, and token-waste reduction while keeping the
security model explicit, inspectable, and replayable. The control plane is local-only: no remote
service or VPS is required for core operation.

## Quick Start

```bash
pipx install claude-bridge-mcp
claude-bridge init
claude-bridge doctor --project-dir .
TARGET=claude-desktop  # or generic-stdio / vscode
claude-bridge install --target "$TARGET" --project-dir .
```

Use `claude-bridge install --help` to see supported MCP targets. After installing the target
configuration, restart or reload that MCP client and start a new conversation/session. A successful
install gives the client access to `tools_overview` and `bridge_status`; mutating actions should
still ask for client approval when the client supports it.

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

- **File operations**: `read_file`, `read_multiple_files`, `list_directory`, `write_file`,
  `move_file`, `copy_path`, `search_in_files`
- **Targeted edits**: `patch_file`, `preview_patch` with SEARCH/REPLACE patches
- **Shell execution**: `run_shell` through a guarded `shell=False` execution path
- **Code indexing**: `index_codebase`, `find_relevant_files` — symbolic source index and relevance
  ranking without embeddings
- **Workflow helpers**: `run_workflow`, `run_agent_loop_step`, `run_agent_loop_session` —
  structured review, explain, test, todo, quality, and bounded agent-loop flows
- **Full-profile readers**: `read_image`, `read_pdf`, `read_url` — optional multi-format and
  constrained text-only HTTP/HTTPS reading
- **Full-profile Git commit helper**: `commit_changes` for explicit local commits
- **Audit logging**: tool calls recorded as structured JSONL
- **Policy engine**: custom guard rules, team RBAC, AI advisor, policy diff for CI/CD
- **Replay and appeal**: deterministic decision replay and post-hoc appeal with audit chain
- **Anomaly detection**: rule-based audit anomaly scanning
- **Full-profile meta-agent tools**: local plans, approach exploration, deterministic self-critique,
  git-backed checkpoints
- **Tool profiles**: `essential`, `standard`, `full` for token/capability tradeoffs
- **Agent Quality tools**: deterministic prompt improvement, context strategy, plan critique,
  safe config suggestions, workflow quality gates, result quality review, and fail-safe provider
  advice parsing telemetry
- **Local control plane**: task and approval state exposed through CLI, MCP tools, and a
  localhost-only dashboard

## Installation

```bash
pipx install claude-bridge-mcp
claude-bridge init
claude-bridge doctor --project-dir .
TARGET=claude-desktop  # or generic-stdio / vscode
claude-bridge install --target "$TARGET" --project-dir .
```

`claude-bridge` is the installed CLI command. The package name is `claude-bridge-mcp`.

Optional extras are available when installing from an environment that supports extras:

```bash
pip install "claude-bridge-mcp[treesitter]"    # optional Tree-sitter indexing
pip install "claude-bridge-mcp[multi-format]"  # optional image/PDF reading
```

### Add to an MCP client

`claude-bridge install` can write supported target configs, while `claude-bridge setup` prints a
copy-pasteable snippet:

```bash
claude-bridge install --target claude-desktop --project-dir .
claude-bridge setup --target generic-stdio --project-dir .
claude-bridge setup --target vscode --project-dir .
```

Generic stdio server entry:

```json
{
  "servers": {
    "claude-bridge": {
      "command": "python3",
      "args": ["-m", "claude_bridge.mcp_server"],
      "env": {
        "CLAUDE_BRIDGE_PROJECT_DIR": "/absolute/path/to/project",
        "CLAUDE_BRIDGE_ALLOWED_ROOTS": "/absolute/path/to/project",
        "CLAUDE_BRIDGE_AUTO_APPROVE": "0",
        "CLAUDE_BRIDGE_CLIENT_MANAGED_APPROVAL": "1",
        "CLAUDE_BRIDGE_TOOL_PROFILE": "standard",
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

Some clients use a different top-level wrapper than `servers`; keep the inner `claude-bridge`
entry and adapt the wrapper to the client's MCP configuration format.

### Claude Desktop example

```bash
claude-bridge install --target claude-desktop --project-dir .
```

Then fully quit and reopen Claude Desktop, and start a new conversation.

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

Skill governance is documented in [`docs/skill-discovery.md`](docs/skill-discovery.md). V1 skill
discovery is local-first: packages can be inspected before import, recommendations are explained,
and remote auto-download/install/run is intentionally out of scope.

The repository-root [`skills/`](skills/) directory contains development/example skill specs and
helpers. It is not packaged as runtime user skills in the PyPI distribution; user-imported skills
are handled through the documented local skill registry.

## Local Control Plane

When the machine is already running a long MCP task, Claude Bridge can keep local task and approval
state under `~/.claude-bridge/control-plane`. You can inspect or intervene from another terminal:

```bash
claude-bridge tasks list
claude-bridge tasks cancel latest --reason "Heading out"
claude-bridge approvals list --status pending
claude-bridge approvals approve latest
```

For a browser view on the same computer:

```bash
claude-bridge dashboard
```

The dashboard binds to `127.0.0.1` by default, uses a per-session token in the URL, and can list
tasks, list approvals, cancel tasks, approve actions, and reject actions without requiring a remote
server.

## Feature Evaluation

Claude Bridge should not keep features just for show. Each feature should have a clear local-first
job and an honest current status:

- **Keep** features that are implemented, useful, documented, and covered by focused tests.
- **Rework** features that point in the right direction but need clearer behavior, names, or
  boundaries.
- **Hide** experimental or niche surfaces from default profiles when they add confusion or token
  cost before they are broadly useful.
- **Remove** features that are mostly decorative, duplicate better paths, or cannot be made safe
  and explainable.

The product direction is a local control plane and quality layer for MCP-based development, not a
collection of impressive-sounding tools. Docs should distinguish implemented CLI/MCP behavior from
planned control-plane ideas, and should not imply remote monitoring or hosted sync unless code for
that surface is added.

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
pip install -e .
pip install -e .[dev]
pip install -e .[treesitter]
pip install -e .[multi-format]
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
| No file access | Restart or reload the MCP client; try "Use `workspace_status`" |
| macOS: Operation not permitted | Use `/usr/bin/env` with the module command in config. |
| Tools not appearing | Check the client MCP config is valid JSON; verify the Python environment. |
| Claude Desktop logs | `~/Library/Logs/Claude/mcp-server-claude-bridge.log` |

## Requirements

- Python 3.10+
- An MCP client

## License

MIT. See [LICENSE](LICENSE).

## Contributing

Contributions are welcome. Please open an issue before larger changes.

This project is not an official Anthropic product.
