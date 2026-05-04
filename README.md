# Claude Bridge

> A local-first MCP server that brings file, shell, patch, workflow, indexing, and audit
> capabilities to Claude Desktop and other MCP clients.

Claude Bridge is a lightweight Python MCP server for local development workflows. It lets an MCP
client inspect project files, run guarded shell commands, apply controlled patches, build context
packs, search/index source code, and use bounded workflow helpers without giving up path boundaries
or approval controls.

It is designed for developers who want a Claude Code-like local workflow from Claude Desktop while
keeping the security model explicit and inspectable.

## Why It Exists

Claude Bridge is built for:

- developers who switch between multiple local project roots in the same session
- teams that want a Python-based, `pipx`-friendly MCP server
- users who need more than raw file access: workflows, context packs, relevance ranking, and bounded
  agent-loop helpers
- projects across Python, JavaScript, TypeScript, Rust, Go, Godot/GDScript, and other ecosystems

## Quick Start

```bash
pip install -e .
claude-bridge install
```

Then fully quit and reopen Claude Desktop, and start a new conversation.

## Features

- **File reading** (`read_file`): read local text files inside the allowed workspace.
- **Multi-format reading** (`read_image`, `read_pdf`): optional image metadata/base64 and PDF text
  extraction through the `multi-format` extra.
- **Directory listing** (`list_directory`): inspect project structure.
- **Shell execution** (`run_shell`): run tests and diagnostics through a guarded `shell=False`
  execution path.
- **Targeted edits** (`patch_file`, `preview_patch`): apply small SEARCH/REPLACE patches with
  preview support.
- **File move/copy** (`move_file`, `copy_path`): approved rename, move, and copy operations inside
  the configured workspace.
- **Workflow helpers** (`run_workflow`, `run_agent_loop_step`, `run_agent_loop_session`): structured
  review, explain, test, todo, quality, and bounded agent-loop flows.
- **Code indexing and relevance** (`index_codebase`, `find_relevant_files`): symbolic source index
  and lightweight relevance ranking.
- **Audit logging**: tool calls are recorded in structured form.
- **Git integration**: file mutations can be committed automatically when the target is in a Git
  repository.
- **MCP compatible**: works with Claude Desktop and other MCP clients.

## Installation

### Install the Package

```bash
pip install -e .
```

Or install from a local checkout:

```bash
git clone <your-repo-url>
cd claude-bridge
pip install -e .
```

For development:

```bash
pip install -e .[dev]
```

Optional extras:

```bash
pip install -e .[treesitter]
pip install -e .[smart]
pip install -e .[multi-format]
```

With extras, install multi-format support:

```bash
pip install -e .[multi-format]
```

### Add It to Claude Desktop

Generate a config snippet:

```bash
claude-bridge setup
```

Or update the Claude Desktop config automatically:

```bash
claude-bridge install
```

Manual config example:

```json
{
  "mcpServers": {
    "claude-bridge": {
      "command": "/absolute/path/to/python3",
      "args": ["-m", "claude_bridge.mcp_server"],
      "env": {
        "CLAUDE_BRIDGE_PROJECT_DIR": "/absolute/path/to/project",
        "CLAUDE_BRIDGE_ALLOWED_ROOTS": "/absolute/path/to/project:/absolute/path/to/projects-parent",
        "CLAUDE_BRIDGE_AUTO_APPROVE": "0",
        "CLAUDE_BRIDGE_CLIENT_MANAGED_APPROVAL": "0",
        "PYTHONUNBUFFERED": "1",
        "PYTHONPATH": "/absolute/path/to/repo/src"
      }
    }
  }
}
```

Fully quit and reopen Claude Desktop after changing the config.

### Start Manually

```bash
claude-bridge start --project-dir /absolute/path/to/project --allow-root /absolute/path/to/projects-parent
```

The server runs over stdio and keeps stdout clean for MCP traffic.

## Approval Model

Claude Bridge starts fail-closed by default.

- In MCP stdio mode, the server cannot safely prompt through terminal `input()`.
- Tools such as `run_shell`, `write_file`, `move_file`, `copy_path`, `patch_file`, and
  `undo_last_patch` require either client-managed approval or trusted local auto-approval.
- For Claude Desktop approval UI support, generate config with
  `claude-bridge setup --client-managed-approval ...`.
- For trusted local use, set `CLAUDE_BRIDGE_AUTO_APPROVE=1`.

## Usage

Claude can call these tools from a normal MCP conversation:

- `read_file(path="src/player.py")` - read a text file.
- `read_image(path="docs/screenshot.png")` - read image metadata and base64 content with the
  optional multi-format dependency.
- `read_pdf(path="docs/spec.pdf", page_start=1, page_end=3)` - extract PDF text with page bounds.
- `list_directory(path="src/")` - list a directory.
- `write_file(path="notes.txt", content="...", max_lines=500)` - write a new file or explicit
  overwrite; large content returns a structured warning recommending `patch_file`.
- `move_file(source="old.txt", destination="docs/old.txt")` - move or rename a file or directory.
- `copy_path(source="template.md", destination="docs/template.md")` - copy a file or directory.
- `search_in_files(query="TODO", path="src")` - search text without dropping to shell.
- `run_shell(command="pytest")` - run a guarded command.
- `patch_file(file="src/player.py", search="old", replace="new")` - apply a targeted edit.
- `preview_patch(...)` - preview a patch before applying it.
- `index_codebase(path=".")` - build a symbolic source index.
- `find_relevant_files(query="login auth", path="src")` - rank likely relevant files.
- `workspace_status()` - show active project root and allowed roots.
- `switch_project_root(path="/absolute/path/to/project")` - switch to another allowed root.
- `activity_summary()` - summarize recent touched paths, commands, writes, patches, approval
  rejections, risky actions, and the short session timeline.
- `appeal_decision(record_id="<record_id>", justification="...")` - appeal a policy decision
  and return allow, deny, or ask with an audit chain.
- `run_workflow(mode="review", target="src/")` - generate a structured workflow prompt.
- `run_workflow(mode="review", target="src/", execute=true)` - run the safe read-only discovery
  step for a workflow.
- `build_context_pack(target="src", goal="understand auth flow")` - build a framework-aware context
  pack.
- `suggest_validation_commands(target="src")` - suggest project-specific validation commands.

## Prompt Shortcuts

Claude Bridge registers MCP prompts for common workflows:

- `/review` - review a file or directory.
- `/optimize` - suggest performance and maintainability improvements.
- `/orchestrate` - split a large task into workstreams and integration gates.
- `/agent_loop` - plan a small bounded inspect-patch-validate loop.
- `/quality` - evaluate code against release-quality expectations.
- `/test` - identify missing tests and risky gaps.
- `/todo` - scan and prioritize TODO/FIXME/HACK comments.
- `/explain` - explain code for a chosen audience.
- `/commit` - summarize changes and suggest a commit message.

## Workflow Tool

Use `run_workflow` when your MCP client does not expose prompt shortcuts directly.

Examples:

- `run_workflow(mode="review", target="src/claude_bridge/server.py")`
- `run_workflow(mode="review", target="src/claude_bridge/server.py", execute=true)`
- `run_workflow(mode="optimize", target="src/", option="performance and readability")`
- `run_workflow(mode="orchestrate", target="src/", option="split by modules")`
- `run_workflow(mode="agent_loop", target="src/", option="fix failing behavior", max_iterations=3)`
- `run_workflow(mode="quality", target="src/", option="correctness and regression safety")`
- `run_workflow(mode="test", target="src/", option="regression tests")`
- `run_workflow(mode="todo", target=".", option="TODO, FIXME")`
- `run_workflow(mode="explain", target="src/claude_bridge/server.py", option="junior developer")`
- `run_workflow(mode="commit", target=".", option="short imperative message")`

Supported modes:

- `review`
- `optimize`
- `orchestrate`
- `agent_loop`
- `quality`
- `test`
- `todo`
- `explain`
- `commit`

With `execute=true`, the workflow runs only a safe read-only discovery step:

- for files, it calls `read_file`
- for directories, it calls `list_directory`, then `find_relevant_files`, then selected `read_file`
  calls
- it does not run `run_shell` or `patch_file` automatically

## Agent Loop Helpers

The `agent_loop` workflow is for small, controlled changes:

- defines an inspect -> patch -> validate -> decide cycle
- keeps an iteration budget
- lists allowed tools and validation boundaries
- returns stop conditions instead of looping indefinitely

`run_agent_loop_step(...)` can apply one patch, run one validation command, and return one of:

- `stop_success`
- `continue`
- `stop_failure`

`run_agent_loop_session(...)` accepts a structured step list, runs steps in order, stops early on
success or failure, and returns both raw step results and a compact `session_summary`.

## Codebase Indexing

`index_codebase` scans supported source files and returns a symbolic index with:

- files
- functions
- classes
- imports

It supports Python, GDScript (`.gd`), JavaScript, TypeScript, Rust, Go, Java, Kotlin, C#, Ruby, and
PHP source files. It skips common generated or dependency directories such as `.git`, `venv`,
`__pycache__`, `.pytest_cache`, and `node_modules`.

If the optional Tree-sitter backend is installed, Claude Bridge uses it for stronger multilingual
symbol extraction. If it is missing, the regex/AST fallback remains available. Index responses
include `parser_backend` and `parser_backends` metadata.

## Relevance Search

`find_relevant_files` ranks files from the symbolic index using:

- file paths
- function names
- class names
- imports

Examples:

- `find_relevant_files(query="login auth", path="src")`
- `find_relevant_files(query="todo parser", path="src", limit=3)`

## Multi-Format Readers

The `read_image` and `read_pdf` tools are optional. Core installs do not import Pillow or PyPDF2 at
startup, so missing optional dependencies do not crash the server.

- `read_image` supports PNG, JPEG, GIF, and WebP up to the configured byte limit. It returns image
  dimensions, MIME type, byte size, and base64 content.
- `read_pdf` is text-only in the first version. It supports page ranges, page limits, truncation
  metadata, and encrypted-PDF rejection.
- Both tools use the same path boundary and sensitive file protections as text file readers.

## Tool Response Format

Main tools return structured JSON text rather than ad hoc prose.

Successful response example:

```json
{
  "ok": true,
  "message": "Shell command completed successfully",
  "details": {
    "command": "pytest",
    "stdout": "...",
    "stderr": "",
    "exit_code": 0
  }
}
```

Error response example:

```json
{
  "ok": false,
  "code": "blocked_command",
  "message": "Command blocked for safety: contains 'sudo'",
  "details": {
    "command": "sudo apt update",
    "blocked_pattern": "sudo"
  }
}
```

Common error codes include:

- `approval_rejected`
- `blocked_command`
- `command_error`
- `command_failed`
- `command_timeout`
- `dependency_missing`
- `destination_exists`
- `directory_not_found`
- `directory_read_error`
- `empty_command`
- `file_not_found`
- `file_read_error`
- `file_write_error`
- `interactive_command_unsupported`
- `not_a_directory`
- `not_a_file`
- `path_outside_project`
- `python_syntax_error`
- `same_path`
- `search_ambiguous`
- `search_not_found`
- `source_not_found`

## Shell Safety Matrix

| Command type | Example | Expected behavior |
| --- | --- | --- |
| Safe read-only command | `ls`, `pytest`, `python -m pytest` | Runs after approval |
| Safe diagnostics | `git status`, `git diff`, `ruff check .` | Runs after approval |
| Dangerous command | `sudo ...`, `rm -rf ...`, `chmod 777 ...` | Blocked automatically |
| Script pipe | `curl ... \| bash` | Blocked automatically |
| Runtime pipe | `curl ... \| node`, `printf ... \| fish` | Blocked automatically |
| Inline runtime script | `node -e ...`, `ruby -e ...`, `php -r ...` | Blocked automatically |
| Long-running command | long build/test command | Times out after the configured limit |
| Interactive command | `python`, `vim`, `top` | Rejected as `interactive_command_unsupported` |
| Empty command | `""` | Rejected as `empty_command` |

Notes:

- `run_shell` does not allocate a TTY.
- Commands waiting on stdin are not reliable.
- `python3 -c ...` remains allowed for backwards compatibility; riskier inline runtime entrypoints
  are blocked.
- Commands are executed with `subprocess.run(..., shell=False)`.

## Security

- **Local-only by design**: the server does not need a remote service for core operation.
- **Explicit approval model**: mutating tools and shell tools require client approval or trusted
  local auto-approval.
- **Path boundaries**: tools resolve paths against the configured project root and allowed roots.
- **Command filtering**: risky patterns such as `rm -rf`, `sudo`, `chmod`, `| bash`, `curl | node`,
  and `node -e` are blocked.
- **Path traversal protection**: `../` cannot be used to escape configured roots.
- **Sensitive file protection**: `.env`, `.pem`, `.key`, `id_rsa`, `claude_desktop_config.json`,
  and similar files are blocked from direct reads/writes/patches. Error responses avoid leaking
  resolved paths or internal sensitive-match reasons.
- **Symlink hardening**: `copytree` does not follow symlinks; `rmtree` rejects symlink directories;
  file writes reject symlink targets with `O_NOFOLLOW`.
- **TOCTOU protection**: write operations use `O_CREAT | O_EXCL` and pre-write symlink checks.
- **Atomic writes**: file writes go to a temp file then `os.replace` to prevent partial writes.
- **ReDoS protection**: regex compilation has a 2-second timeout; glob patterns capped at 256 chars.
- **Size limits**: directory copies rejected above 500MB.
- **Audit logging**: tool calls are recorded as structured, masked audit records.
- **Optional dependency safety**: optional readers fail with structured `dependency_missing` errors
  instead of import-time crashes.

### AI Evaluator (Optional Advisor)

The AI evaluator is an **optional advisory layer** within the policy chain, not an independent
decision-maker. It is disabled by default and only activates when
`ai_evaluator_enabled` is set to `true`.

**Security boundaries:**

- The AI evaluator can suggest `allow`, `deny`, or `ask` for tool requests.
- It **cannot override** a built-in hard deny (e.g., `curl | bash`, `sudo rm -rf /`, path
  traversal, sensitive file access). The built-in guard always wins.
- An AI `allow` suggestion does not override a rule-level `deny`; deny rules from user policy
  still win.
- The AI evaluator's `allow` can bypass the approval prompt for user convenience, similar to
  a rule-level `allow`. This is configurable via `ai_evaluator_fallback_action`.
- On timeout or failure, the evaluator fails closed (default: `ask`). This behavior is
  configurable: `ai_evaluator_fallback_action` can be `allow`, `deny`, or `ask`.
- The local provider (`ai_evaluator_provider: "local"`) uses deterministic keyword matching
  with no network calls. Production SaaS endpoints are out of scope for this release.
- All AI decisions are recorded in audit records with `decision_source: "ai"` and include
  reasoning metadata (`ai_reason`, risk reasons).

**Configuration:**

```bash
# Enable the AI evaluator
export CLAUDE_BRIDGE_AI_EVALUATOR_ENABLED=1
# Provider: "local" (only supported provider)
export CLAUDE_BRIDGE_AI_EVALUATOR_PROVIDER=local
# Timeout in seconds
export CLAUDE_BRIDGE_AI_EVALUATOR_TIMEOUT=5
# Fallback action on timeout/failure: allow, deny, ask
export CLAUDE_BRIDGE_AI_EVALUATOR_FALLBACK_ACTION=ask
```

**Policy simulation with AI advisor:**

```bash
claude-bridge policy simulate \
  --path .claude-bridge-guard.json \
  --tool run_shell \
  --param "command=rm -rf /" \
  --with-ai \
  --ai-deny "rm -rf"
```

In simulation mode, `--with-ai` runs the local AI evaluator alongside the policy engine.
The output shows both the policy decision and the AI advisory with a delta indicator.
This helps evaluate how the AI would respond to tool requests before enabling it in
production.

### Custom Guard Policy

Add `.claude-bridge-guard.json` to the active project root to make the guard layer stricter without
writing code. Custom policy can add blocks, but it cannot disable the built-in safety rules.

```json
{
  "blocked_shell_patterns": ["npm publish*", "git push*"],
  "sensitive_path_patterns": ["private/**", "*.sqlite"],
  "secret_patterns": {
    "internal_ticket": "TICKET-[0-9]{4}"
  }
}
```

- `blocked_shell_patterns` uses shell-style wildcards against the normalized command string.
- `sensitive_path_patterns` uses shell-style wildcards against project-relative paths and filenames.
- `secret_patterns` adds named regular expressions checked before writing file content.
- To use a policy file outside the project root, set `CLAUDE_BRIDGE_GUARD_POLICY`.

### Rule Writing Guide

Policy files can also define ordered `rules`. The first matching rule wins. Conditions inside a
rule are combined with AND. Rule actions are `deny`, `ask`, or `allow`; built-in hard denies such as
dangerous shell patterns, sensitive paths, workspace escapes, and secret-like content still win over
custom `allow` rules.

```json
{
  "rules": [
    {
      "name": "deny-risky-shell",
      "scope": "run_shell",
      "action": "deny",
      "risk_level": "high",
      "conditions": [
        {"type": "regex", "field": "command", "pattern": "npm\\s+publish"}
      ]
    },
    {
      "name": "review-new-shell-scripts",
      "scope": "write_file",
      "action": "ask",
      "conditions": [
        {"type": "file_exists", "field": "path", "value": false},
        {"type": "extension", "field": "path", "values": [".sh"]}
      ]
    },
    {
      "name": "allow-safe-validation",
      "scope": "run_shell",
      "action": "allow",
      "risk_level": "low",
      "conditions": [
        {"type": "field_equals", "field": "command", "value": "npm test"}
      ]
    }
  ]
}
```

Supported condition types are `tool`, `field_equals`, `field_contains`, `regex`, `glob`,
`extension`, `file_exists`, `file_size`, `sensitive_path`, and `content_contains`.

Validate and dry-run policy decisions without executing tools:

```bash
claude-bridge policy validate --path .claude-bridge-guard.json
claude-bridge policy simulate --path .claude-bridge-guard.json --tool run_shell --param command="npm test"
```

### Audit Logs and Replay

Audit records are JSONL entries stored locally. Each record includes a `record_id`, timestamp,
session id, tool name, summarized params, result summary, duration, telemetry, hashes of summarized
params/result, replay context, and normalized policy decision fields when a tool response carries a
decision (`decision_action`, `decision_source`, `decision_risk_level`, reason, risk reasons, and
metadata). Audit records do not intentionally store full tool results, large file contents, or raw
secret values.

Secret masking is applied before audit records are written. Sensitive keys such as `api_key`,
`token`, `secret`, `password`, `authorization`, and `cookie` are replaced with deterministic
redaction metadata containing a hash and length. Secret-like string patterns such as key/value
assignments, AWS access key ids, and GitHub tokens are also redacted in previews. Masking is a
guardrail over summarized audit data; it is not a full PII classifier or encryption layer, and very
novel secret formats may require custom guard policy patterns.

Audit inspection keeps the existing latest-session behavior and can be filtered:

```bash
claude-bridge audit --last --tool run_shell --decision deny --risk high --source rule
```

Replay re-evaluates one audit record against the current deterministic rule engine without running
the original tool:

```bash
claude-bridge replay --record-id <record_id>
```

Replay is intentionally limited to deterministic rules and the masked params saved in the audit
record. It does not replay approval prompts, AI evaluators, filesystem snapshots, shell commands, or
tool side effects. If the current policy no longer matches the masked context, replay reports that
the decision changed instead of silently allowing the action.

### Appeal

Appeal lets you challenge a policy decision after it happened. You provide the audit `record_id` and
a `justification`; the bridge replays the decision deterministically and returns a new result
(`allow`, `deny`, or `ask`) chained to the audit log.

From the CLI:

```bash
claude-bridge appeal --record-id <record_id> --justification "Need access for debugging"
```

From MCP:

```
appeal_decision(record_id="<record_id>", justification="Need access for debugging")
```

What appeal does:

- Replays the original tool request against the current deterministic rule engine.
- Embeds your justification into the replay metadata.
- Logs an `appeal_event` audit record with the new decision.
- Returns the appeal result, original record summary, replay delta, and appeal history count.

What appeal does **not** do:

- It does **not** change the original audit record.
- It does **not** execute the tool or re-run side effects.
- It does **not** implement team-lead approval, trust scoring, or SaaS escalation.
- It does **not** override a built-in hard deny (e.g., `sudo`, `curl | bash`, path traversal);
  deterministic replay still produces `deny`, and the status becomes `ask` so a human can review.

### Anomaly Detection

Claude Bridge includes a rule-based anomaly detection system that scans audit records for
suspicious patterns. This is an MVP with deterministic heuristics only (no ML model).

From the CLI:

```bash
claude-bridge anomaly scan --last
claude-bridge anomaly scan --last --limit 100 --json
```

From MCP:

```
anomaly_summary(limit=50)
```

Detected anomaly types:

| Type | Description | Base score |
| --- | --- | --- |
| `new_tool_use` | First use of a tool in the session | 20 |
| `high_volume_file_access` | 10+ file-access calls within 5 min window | 30 |
| `sensitive_path_burst` | 3+ records touching sensitive paths within 5 min | 60 |
| `unusual_hour` | Tool called between 01:00-05:59 | 15 |
| `high_risk_spike` | 3+ high/critical risk decisions within 5 min | 40 |

Scores are additive and capped at 100. Severity levels: `normal` (0), `low` (1-25), `medium`
(26-55), `critical` (56-100).

Critical anomalies include policy decision metadata (`decision_action`, `decision_source`,
`decision_risk_level`, `decision_reason`) and a `recommended_action` (`escalate` or `review`)
to guide follow-up.

**MVP limits:**

- Rule-based only, no ML training or inference.
- Per-session analysis; no cross-session baseline or drift detection.
- No SOC/SIEM integration, email, or Slack alerting.
- No network-facing anomaly endpoint; audit data stays local.
- Sensitive path list is hardcoded; custom patterns require a guard policy file.

### Team Policy (RBAC)

Team policies bundle role-based access controls into version-controlled policy files. Roles define
permission sets for different team members and inherit from other roles:

```json
{
  "name": "my-team",
  "description": "Production repository guardrails",
  "roles": [
    {
      "name": "junior",
      "description": "Read, patch, and run approved commands",
      "permissions": [
        {"tool": "run_shell", "action": "deny"},
        {"tool": "read_file", "action": "allow"},
        {"tool": "patch_file", "action": "allow"},
        {"tool": "list_directory", "action": "allow"},
        {"tool": "search_in_files", "action": "allow"}
      ]
    },
    {
      "name": "senior",
      "extends": "junior",
      "description": "Full access including shell and writes",
      "permissions": [
        {"tool": "run_shell", "action": "ask"},
        {"tool": "write_file", "action": "allow"},
        {"tool": "move_file", "action": "allow"},
        {"tool": "copy_path", "action": "allow"}
      ]
    },
    {
      "name": "ci",
      "description": "Automated CI with restricted scope",
      "permissions": [
        {"tool": "run_shell", "action": "allow", "scope": {"command_pattern": "^(ruff|pytest|mypy|black).*"}}
      ]
    },
    {
      "name": "contractor",
      "extends": "junior",
      "description": "Read-only with no file mutations",
      "permissions": [
        {"tool": "patch_file", "action": "deny"}
      ]
    }
  ]
}
```

- Roles support `extends` for inheritance (junior → senior → lead chains).
- Built-in validation catches circular inheritance, missing bases, and self-references.
- Permissions are additive: child roles can add or tighten parent permissions.
- Policy bundles are validated with `claude-bridge policy validate`.

### Policy Diff (CI/CD Integration)

Compare team policy files to detect changes that affect security posture:

```bash
claude-bridge policy diff --base .claude-bridge/team.json --head pr/team.json
```

The diff reports added, removed, and modified permissions with structured output suitable for CI:

```json
{
  "status": "warning",
  "summary": "1 permission modified, 0 added, 0 removed",
  "changes": [
    {
      "tool": "run_shell",
      "status": "modified",
      "role": "junior",
      "old_action": "deny",
      "new_action": "allow"
    }
  ]
}
```

- Returns `ok` when policies are identical, `warning` for permission changes, `error` for
  structural problems.
- Designed for PR gates — block merges that weaken security constraints.
- Policies are text files (JSON); diff integration with `git diff` works natively.

## Development and Validation

Local validation flow:

```bash
pip install -e .[dev]
claude-bridge doctor --project-dir .
ruff check .
black --check .
mypy src
pytest
claude-bridge benchmark --project-dir . --path src --query "auth session login"
```

`doctor` checks:

- Python executable and version
- whether `claude_bridge` is importable
- dev tools: `pytest`, `pytest-asyncio`, `ruff`, `black`, `mypy`
- optional packages: `tiktoken`, `charset_normalizer`, `tree_sitter_language_pack`
- Claude Desktop config presence
- Git repository status

Missing optional packages do not block core use; the report explains which extra to install.

## Benchmarking

```bash
claude-bridge benchmark --query "login auth" --path src
```

The benchmark reports indexing time, repeated relevance-query timings, and top results. Use
`--json` for machine-readable output, `--baseline-file` for regression gates, or `--profile-file`
to load a reusable benchmark profile.

## Troubleshooting

### Claude Desktop says it has no file access

Claude Desktop can delay MCP tool routing on the first message. Try a more explicit follow-up:

- "Inspect this project with claude-bridge."
- "Use `workspace_status` and read the files."
- "Review this folder using the claude-bridge tools."

### macOS: Operation not permitted

Claude Desktop may fail to execute unsigned binaries directly from a virtualenv. Prefer:

```json
{
  "command": "/usr/bin/env",
  "args": ["python3", "-m", "claude_bridge.mcp_server"]
}
```

Generate this style of config with `claude-bridge setup`.

### What did the bridge do recently?

Ask the client to call `activity_summary()` when you want a user-facing recap of recent local
activity, such as "which files did you touch?" or "which commands did you run?". From the shell,
use:

```bash
claude-bridge audit --last
```

### Where are MCP logs?

On macOS, Claude Desktop MCP logs are usually under:

```text
~/Library/Logs/Claude/mcp-server-claude-bridge.log
```

Useful startup lines include:

- `Using MCP server command: /usr/bin/env`
- `Message from client: {"method":"initialize"...}`
- `Message from client: {"method":"tools/list"...}`

### Prompts do not appear

- Fully quit and reopen Claude Desktop.
- Make sure `claude_desktop_config.json` is valid JSON.
- Check whether `prompts/list` appears in the MCP log.
- Verify that `PYTHONPATH` points at the repo `src` directory when using a local checkout.

### Tool responses look unusual

Tool responses are JSON text:

- success uses `ok: true`
- failure uses `ok: false`
- details are under `details`
- machine-readable error names are under `code`

## Before Publishing Publicly

Before sharing a local checkout:

- Do not commit your real `claude_desktop_config.json`; use
  [claude_desktop_config.snippet.json](claude_desktop_config.snippet.json) with placeholders.
- Remove personal usernames, home directories, and private project paths from docs and examples.
- Ensure `.env`, `*.local`, private configs, and personal logs are ignored.
- Run a quick leak scan:

```bash
rg -n "/Users/|API_KEY|SECRET|TOKEN|PASSWORD" .
```

## Why Use It?

Claude Bridge is not just a file reader. Its value is the combination of:

- Claude Desktop-focused setup that preserves stdio MCP behavior
- local-first multi-root workspace control
- structured JSON tool results for reliable agent workflows
- guarded shell execution and controlled patching
- review, explain, test, todo, quality, and orchestration workflows
- source indexing and relevance ranking without requiring embeddings
- optional multi-format reading without making core installs fragile

The short positioning is:

> A secure, local-first, multi-project MCP bridge for Claude Desktop with explicit approval
> model, deterministic policy engine, audit logging, and replay capabilities.

## Requirements

- Python 3.8+
- Claude Desktop or another MCP client

## License

MIT. See [LICENSE](LICENSE).

## Contributing

Contributions are welcome. Please open an issue before larger changes.

This project is not an official Anthropic product.
