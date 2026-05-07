# Security Model

Claude Bridge provides a security model based on layered guard policies, explicit approval gates, and a
fully-audited tool call log. This document describes the trust boundaries, protection layers, and
configuration model.

---

## Trust Boundary

The bridge runs as a local MCP server on the user's machine. All tool calls originate from the MCP
client (Claude Desktop, VS Code, etc.) and are processed inside the bridge process.

```
  MCP Client  ──(stdio)──>  Claude Bridge Server  ──>  File System / Shell
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
before invoking destructive tools. Claude Bridge treats that client-side approval contract as
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

---

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
