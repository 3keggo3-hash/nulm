# Security Model

Nulm provides a security model based on layered guard policies, explicit approval gates, and a
fully-audited tool call log. This document describes the trust boundaries, protection layers, and
configuration model.

---

## Trust Boundary

The bridge runs as a local MCP server on the user's machine. All tool calls originate from the MCP
client (Claude Desktop, VS Code, etc.) and are processed inside the bridge process.

```
  MCP Client  ──(stdio)──>  Nulm Server  ──>  File System / Shell
                                   │
                           Audit Log (disk)
```

- **No network boundary** — the bridge listens on stdin/stdout only.
- **No cloud component** — all policy evaluation, audit logging, and decision logic runs locally.
- **Client trust** — the MCP client is trusted with the ability to invoke any tool; the bridge
  enforces policy on each invocation.
- **Not a sandbox** — shell commands and file operations run as the invoking local user. Claude
  Bridge adds policy gates, path boundaries, approvals, and auditability; it does not provide an
  OS/container isolation boundary.

---

## Approval Modes

| Mode                | auto_approve | client_managed_approval | Behaviour |
|---------------------|--------------|-------------------------|-----------|
| read-only           | false        | false                   | Write/shell calls fail closed. |
| dev-safe (default)  | false        | true                    | Client prompts for approval on risky operations. |
| ci-like             | false        | true                    | Same as dev-safe; explicit preset for automation. |
| power-user          | true         | false                   | All operations approved automatically. |

The mode is set via `--approval-preset` or individual `--auto-approve` / `--client-managed-approval`
flags at startup or through environment variables.

`client_managed_approval=true` means the MCP client is expected to show and enforce approval prompts
before invoking destructive tools. Nulm treats that client-side approval contract as
satisfied; clients without equivalent approval handling should use read-only mode or fail-closed
defaults instead.

---

## Guard Policy Layer

A policy file (JSON or YAML) can define allow/deny/ask rules scoped by tool name, command content,
file path, or other conditions. Rules are evaluated before every tool call.

- Default location: `<project>/.claude-bridge-guard.json` or `<project>/.claude-bridge/rules.yaml`
- Override: `CLAUDE_BRIDGE_GUARD_POLICY` environment variable.
- Each rule has a name, action (allow/deny/ask), priority, conditions, and metadata.
- Rules are loaded and cached per-session; changes to the file take effect on the next tool call.

### Built-in Deny Patterns

Hard-coded deny rules that cannot be overridden by user policy:

- Shell commands with dangerous patterns (`sudo`, `curl | bash`, `rm -rf /`, etc.)
- Sensitive file paths (`.env`, `id_rsa`, `credentials.json`, etc.)
- Secret-like content in file writes (`api_key`, `password`, `token`, etc.)

---

## Audit Logging

Every tool call is recorded to a local JSONL audit file:

- **Session-based**: each `start` / `set_config` creates a new session.
- **Location**: `~/.claude-bridge/audit/` or `CLAUDE_BRIDGE_AUDIT_DIR`.
- **Contents**: timestamp, tool name, parameter summary, result summary, policy decision, telemetry.
- **Redaction**: sensitive parameter values (tokens, passwords, API keys) are masked at write time.
- **Retention**: default 90 days / 100 sessions (configurable).

---

## Path and Root Enforcement

All file operations are constrained to the configured project directory and allowed roots:

- `project_dir` is always an allowed root.
- Additional roots can be added with `--allow-root`.
- Paths are resolved and validated against allowed roots before any read/write operation.
- `..` traversal and symlink escapes are blocked.

---

## Configuration Security

Sensitive configuration is supplied through environment variables (not CLI flags for long-lived
deployments):

- `CLAUDE_BRIDGE_AUTO_APPROVE` — enable/disable auto-approve.
- `CLAUDE_BRIDGE_GUARD_POLICY` — path to guard policy file.
- `CLAUDE_BRIDGE_AUDIT_DIR` — path to audit log directory.
- `CLAUDE_BRIDGE_ALLOWED_ROOTS` — colon-separated list of allowed root paths.
- `CLAUDE_BRIDGE_APPROVAL_PRESET` — preset name for approval mode.

### Provider Keys and AI Routing

Bridge-internal AI routing is optional and disabled by default. It affects only Bridge advisory
workflows such as `run_council_session`; it does not switch the MCP client's primary chat model and
does not bypass file, shell, approval, or guard-policy checks.

Model profiles store provider names, model names, and `api_key_env` references only. Raw provider
keys must be supplied through environment variables such as `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
`DEEPSEEK_API_KEY`, `MINIMAX_API_KEY`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `MISTRAL_API_KEY`,
`COHERE_API_KEY`, `XAI_API_KEY`, `TOGETHER_API_KEY`, `OPENROUTER_API_KEY`,
`PERPLEXITY_API_KEY`, or `FIREWORKS_API_KEY`. Config inspection redacts key presence and never
returns secret values.

Custom cloud provider `base_url` values must use HTTPS and must not point to private/internal hosts
or hostnames resolving to private/internal addresses. Ollama routing is intentionally limited to
localhost/loopback URLs because it is expected to run on the user's own machine.

### Adaptive Proposals and MCP Discovery

Adaptive proposals are approval-gated recommendations. Skill comparison can create pending
proposals, but no skill is deactivated merely because a proposal exists or because the user accepts
it; `accept_proposal` records the user's decision for later, explicit configuration changes.
Proposal state is written under the project-local `.claude-bridge/proposals` directory.

MCP discovery is metadata-only. It records nearby MCP-like processes and filters already-known tool
schemas, but it does not launch peer commands, run package-manager probes, or execute discovered
tools. Schemas with blocked patterns, unsupported parameters, or high-risk descriptions are treated
as invalid for recommendation purposes.

---

## Guarded CLI Runner

The dashboard's CLI tab runs only explicitly allowlisted `nulm ...` / `claude-bridge ...` commands
through a strict argument parser. Arbitrary shell execution is not possible.

### Permission Levels

| Level | Commands | Behaviour |
|-------|----------|-----------|
| `read_only` | `version`, `--help`, `--version`, `doctor`, `envdoctor`, `policy`, `sessions` | Read-only diagnostics only. |
| `safe_local` | `control-plane`, `tasks`, `approvals` | Safe local control-plane operations. |
| `needs_approval` | `skill`, `audit`, `anomaly` | Require explicit approval before dashboard execution. |
| *(blocked)* | All other commands | Rejected — cannot run from dashboard. |

### Security Properties

- **Allowlist only** — only listed top-level commands and subcommands are permitted
- **No arbitrary shell** — commands are parsed and passed as arguments to `python -m claude_bridge`, not to a shell
- **Timeout** — 20-second timeout per command; background jobs tracked by session ID
- **Token required** — all dashboard API calls require a per-session bearer token
- **Local-only by default** — dashboard binds to `127.0.0.1` unless `--lan`, `--vpn`, or `--public` is set
- **stdout/stderr captured** — output is stored in message metadata and returned via polling endpoint

### Agent Task Dispatcher

Background agent tasks can be submitted via `POST /api/agent` and polled via
`GET /api/agent/task/{task_id}`. Tasks are stored in the control plane and managed
through the task lifecycle (pending → running → completed/failed/cancelled).
The dispatcher uses the existing approval hierarchy for permission levels.

## Mobile Dashboard and Remote Access Safety

The dashboard binds to `localhost`/`127.0.0.1` by default, restricting access to the local machine only.

### Access Modes

- `nulm dashboard` is local-only and safest.
- `nulm dashboard --lan` binds to the local network and should be used only on trusted Wi-Fi.
- `nulm dashboard --vpn` binds to the local Tailscale IPv4 address and is the recommended remote
  mode because it is not exposed to the public internet.
- `nulm dashboard --public` starts a temporary Cloudflare tunnel and should be used only briefly.

LAN, VPN, and public access require a mandatory token — requests without a valid token are rejected.
In remote modes, the API token is not embedded in `dashboard-config.js`; the printed tokenized URL is
the credential.

### Token Security Risks

- **URL exposure** — tokens may appear in browser history or shared links
- **Query parameters** — tokens in URLs can leak via referrer headers and server logs
- **Application logs** — framework and server logs often record requested URLs
- **Screenshots** — terminal or dashboard screenshots can capture visible tokens

### Mitigation Recommendations

- Use the default per-session token and stop the dashboard when remote access is no longer needed
- Prefer `--vpn` over `--public` for remote access
- Apply `Cache-Control: no-store` headers to prevent browser caching of pages containing tokens
- Redact tokens from log output before sharing diagnostics
- Avoid sending tokens via chat or screenshot-based communication channels

### Mutating Actions

Dashboard CLI execution is allowlisted to guarded `nulm ...` / `claude-bridge ...` commands and
does not run arbitrary shell commands. Write operations and destructive tool calls over tunnel
connections should require explicit confirmation and be logged to the audit trail with user
identity.

## Threat Model Summary

| Threat | Mitigation |
|--------|------------|
| Malicious prompt injection | Guard policy rules + built-in deny patterns. |
| Unauthorised file access | Path root enforcement + policy-based path conditions. |
| Arbitrary shell execution | Shell command analysis + policy denies + approval gate. |
| Secret exfiltration | Audit redaction + secret pattern detection in writes. |
| Tampered audit log | Append-only JSONL; session isolation. |
| Privilege escalation | No cloud component; all runs as the invoking user. |

## Related Documents

- `docs/compliance-readiness.md`
- `docs/policy-pr-workflow.md`
