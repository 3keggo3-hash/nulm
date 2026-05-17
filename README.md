# Nulm

[![PyPI version](https://img.shields.io/pypi/v/nulm)](https://pypi.org/project/nulm/)
[![PyPI downloads](https://img.shields.io/pypi/dm/nulm)](https://pypi.org/project/nulm/)
[![Tests](https://img.shields.io/github/actions/workflow/status/3keggo3-hash/nulm/ci.yml?branch=main)](https://github.com/3keggo3-hash/nulm/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/downloads/)
[![Code style: Black](https://img.shields.io/badge/code%20style-Black-000000.svg)](https://github.com/psf/black)

## What's New

- **AI council workflow** — `run_council_session` and `/council` create read-only specialist
  debate sessions and return approval-gated implementation plans.
- **Bridge-internal model routing** — optional provider/model profiles route council/advisory calls
  without changing the host chat model.
- **Adaptive proposal tools** — optional, approval-gated recommendation helpers can surface
  accept/reject decisions without silently changing active behavior.
- **Context Compression Manager** — decompression bomb protection added to `_context_compression.py`.
- **Audit Trail Query Interface** — SQL-like parser in `_audit_query_parser.py`.

<!-- GitHub Topics: mcp-server, nulm, agent-quality, local-ai, developer-tools -->
CI: GitHub Actions | PyPI package: `nulm` | CLI: `nulm` |
Python: 3.10+ | License: MIT |
Code style: Black

> A local-first agent quality and execution layer for MCP clients.

Nulm is a lightweight Python MCP server for local development and agent workflows. It lets
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
pipx install nulm
nulm install
```

Runs an interactive setup — choose detailed or simple, AI provider, approval mode, and more. Restart Claude Desktop and start a new conversation.

For quick setup with defaults:

```bash
nulm install --simple
```

For other MCP clients:

```bash
nulm install --target vscode
nulm install --target generic-stdio
```

## First 5 Minutes

Try a natural request first:

```text
Use Nulm to check whether this project is public-ready.
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
- **AI council**: `run_council_session` and `/council` assign specialist roles, collect bounded
  debate rounds, synthesize consensus, and return `steps_json` for approval-gated execution
- **Bridge-internal AI routing**: optional model profiles and keyword/task rules choose providers
  for Bridge advisory calls while keeping API keys in environment variables
- **Adaptive proposals**: `list_pending_proposals`, `get_proposal_details`, `accept_proposal`, and
  `reject_proposal` expose advisory skill recommendations and record user decisions
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
pipx install nulm
nulm install         # interactive setup
nulm install --simple # quick setup with defaults
```

`nulm` is the installed CLI command. The package name is `nulm`. The older
`claude-bridge` command remains as a compatibility alias for this alpha cycle.

Optional extras are available when installing from an environment that supports extras:

```bash
pip install "nulm[treesitter]"    # optional Tree-sitter indexing
pip install "nulm[multi-format]"  # optional image/PDF reading
pip install "nulm[smart]"         # token-aware helpers
pip install "nulm[memory]"        # encrypted local memory support
pip install "nulm[policy-yaml]"   # YAML policy files
pip install "nulm[redis]"         # experimental Redis-backed cache
pip install "nulm[observability]" # Prometheus metrics
pip install "nulm[tracing]"       # OpenTelemetry tracing
pip install "nulm[streaming]"     # SSE streaming helpers
```

See [docs/optional-dependencies.md](docs/optional-dependencies.md) for the full extras matrix.

### Add to an MCP client

`nulm install` can write supported target configs, while `nulm setup` prints a
copy-pasteable snippet:

```bash
nulm install --target claude-desktop --project-dir .
nulm setup --target generic-stdio --project-dir .
nulm setup --target vscode --project-dir .
```

Generic stdio server entry:

```json
{
  "servers": {
    "nulm": {
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

Some clients use a different top-level wrapper than `servers`; keep the inner `nulm`
entry and adapt the wrapper to the client's MCP configuration format.

### Claude Desktop example

```bash
nulm install --target claude-desktop --project-dir .
```

Then fully quit and reopen Claude Desktop, and start a new conversation.

## Approval Model

Nulm starts fail-closed by default. Mutating tools and shell tools require either
client-managed approval or trusted local auto-approval (`CLAUDE_BRIDGE_AUTO_APPROVE=1`).

For Claude Desktop approval UI support:
`nulm setup --client-managed-approval ...`.

## Workflow Modes

`run_workflow` supports: `review`, `optimize`, `orchestrate`, `agent_loop`, `quality`, `test`,
`todo`, `explain`, `commit`. Prompt shortcuts (`/review`, `/optimize`, etc.) are also registered.

With `execute=true`, workflows run a safe read-only discovery step (file reads and listing only,
no shell or patch execution).

## AI Council and Model Routing

The council workflow is read-only. It asks a bounded set of specialist roles to debate a task,
synthesizes consensus, lists dissent and risks, and returns `steps_json` that can be applied through
the existing plan/approval tools. It does not patch files, run shell commands, or override policy.

```text
/council target="src/" task="add model routing"
```

Equivalent MCP tool call:

```text
run_council_session(task="add model routing", target="src/", agent_count=5, rounds=2)
```

Bridge-internal AI routing is disabled by default. When enabled, it affects only Bridge advisory
calls such as the council workflow; it cannot switch the MCP client's main chat model.

```bash
export CLAUDE_BRIDGE_AI_ROUTING_ENABLED=1
export CLAUDE_BRIDGE_AI_ROUTING_MODE=auto
export CLAUDE_BRIDGE_AI_DEFAULT_PROFILE=local
export CLAUDE_BRIDGE_AI_PROFILES_JSON='{
  "fast": {"provider": "openai", "model": "gpt-4o-mini", "api_key_env": "OPENAI_API_KEY"},
  "deep": {
    "provider": "anthropic",
    "model": "claude-3-5-sonnet-latest",
    "api_key_env": "ANTHROPIC_API_KEY"
  }
}'
export CLAUDE_BRIDGE_AI_ROUTING_RULES_JSON='[
  {"name": "security", "profile": "deep", "keywords": ["security", "secret", "approval"]}
]'
```

Provider API keys must be supplied through the named environment variables (`OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, etc.). Raw keys are not stored in Bridge config or returned
by `get_config`. Custom cloud provider `base_url` values must use HTTPS and must not point to
private/internal hosts; Ollama routing is limited to localhost/loopback URLs.

## Adaptive Proposals

The adaptive proposal layer stores approval-gated recommendations under
`.claude-bridge/proposals`. Proposals are inert until explicitly accepted with `accept_proposal`;
accepting or rejecting a proposal records the user's decision, but does not directly disable or
mutate skills.

MCP peer discovery is metadata-only. It can identify nearby MCP-like processes and filter
already-known tool schemas, but it does not launch peer commands, run package-manager probes, or
execute discovered MCP tools. High-risk or invalid schemas are filtered out of recommendations.

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

When the machine is already running a long MCP task, Nulm can keep local task and approval
state under `~/.claude-bridge/control-plane`. You can inspect or intervene from another terminal:

```bash
nulm tasks list
nulm tasks cancel latest --reason "Heading out"
nulm approvals list --status pending
nulm approvals approve latest
```

For a browser view on the same computer:

```bash
nulm dashboard
```

The dashboard binds to `127.0.0.1` by default, uses a per-session token in the URL, and can list
tasks, list approvals, list queued dashboard messages, cancel tasks, approve actions, reject
actions, and enqueue text instructions for agents to pick up without requiring a remote server.
Phone access requires an explicit tunnel URL plus the active dashboard token; the default loopback
server is intentionally reachable only from the same machine.

## Feature Evaluation

Nulm should not keep features just for show. Each feature should have a clear local-first
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
nulm policy validate --path .claude-bridge-guard.json
nulm policy simulate \
  --path .claude-bridge-guard.json \
  --tool run_shell \
  --param command="npm test"
```

See [docs/security-model.md](docs/security-model.md) for full rule-writing guide.

## Team Policy (RBAC)

Team policies define role-based access controls with inheritance. See
[docs/security-model.md](docs/security-model.md) for the full schema.

```bash
nulm policy diff --base .claude-bridge/team.json --head pr/team.json
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
nulm audit --last --tool run_shell --decision deny --risk high
nulm replay --record-id <record_id>
nulm anomaly scan --last
nulm appeal --record-id <record_id> --justification "reason"
```

Anomaly scoring is advisory in v0.1: high scores are surfaced in summaries and audit metadata, but
they do not silently change guard-policy decisions. Nulm is a policy-gated local runner,
not an OS or container sandbox.

## Development

```bash
pip install -e .
pip install -e .[dev]
pip install -e .[treesitter]
pip install -e .[multi-format]
nulm doctor --project-dir .
ruff check .
black --check .
mypy src
pytest
```

## Benchmarking

```bash
nulm benchmark --query "login auth" --path src --json
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
