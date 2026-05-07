# Compliance Readiness

This document outlines the security controls, audit capabilities, and operational practices that
support compliance objectives for Claude Bridge deployments.

---

## Control Mapping

### Access Control

| Control | Implementation |
|---------|---------------|
| Principle of least privilege | Tool-level approval gates; path-scoped allowed roots. |
| Role-based access | Optional `--role` flag enables role-specific policy bundles. |
| Authentication | MCP client authentication is delegated to the client (Claude Desktop, VS Code). |

### Audit Trail

| Control | Implementation |
|---------|---------------|
| User activity logging | Every tool call is recorded with timestamp, session ID, and result summary. |
| Tamper evidence | Audit files are append-only JSONL; records are content-addressed via SHA-256. |
| Retention | Configurable retention (default 90 days, 100 sessions). |
| Export | JSONL and summary-JSON export formats with filtering. |

### Policy Enforcement

| Control | Implementation |
|---------|---------------|
| Policy-as-code | Declarative JSON/YAML guard policies with version-controlled files. |
| Automated enforcement | Every tool call evaluated against active rules before execution. |
| Policy validation | CLI `policy validate` command; automated validation on load. |
| Policy diff | `policy diff` command for CI-driven policy review (supports PR workflows). |

### Data Protection

| Control | Implementation |
|---------|---------------|
| Secrets redaction | Sensitive parameter values redacted at audit write time. |
| Secret detection | Built-in regex patterns for API keys, tokens, passwords in file writes. |
| Sensitive path blocking | Configurable sensitive path patterns; built-in deny for `.env`, credentials. |

### Anomaly Detection

| Control | Implementation |
|---------|---------------|
| Session scoring | Multi-factor anomaly scoring per audit session. |
| Policy deviation | Compares actual decisions against expected policy outcomes. |
| CLI review | `anomaly scan` command with critical anomaly alerts. Anomaly results are advisory in v0.1 and do not enforce guard decisions. |

---

## Deployment Considerations

- **Local only**: The bridge does not expose a network port; all communication is over stdio.
- **Single-user**: The bridge inherits the permissions of the invoking user.
- **No external dependencies**: Policy evaluation, audit, and anomaly detection run entirely
  locally — no cloud APIs, no telemetry uploads.
- **CI integration**: Policy diff and validation commands return non-zero exit codes for failures.

---

## Self-Assessment Checklist

- [ ] Guard policy file committed and version-controlled.
- [ ] `power-user` / auto-approve disabled in production-adjacent deployments.
- [ ] Audit directory is backed up or on persistent storage.
- [ ] Retention policy matches organizational requirements.
- [ ] Policy diffs reviewed in CI before deployment.
- [ ] Anomaly scans reviewed after each session.
- [ ] Allowed roots scoped to the minimum required directories.
- [ ] `CLAUDE_BRIDGE_GUARD_POLICY` environment variable set to the reviewed policy file.
- [ ] Appeal and replay workflows tested for policy change validation.

---

## Related Documents

- `docs/security-model.md`
- `docs/policy-pr-workflow.md`
- `docs/product-vision.md`
- `docs/publishing-checklist.md`
