# Publishing Checklist

Quick pre-release verification before sharing publicly.

## Product Positioning

- README describes Nulm as an agent quality and execution layer, not only a security MCP
  tool server.
- README clearly separates current implemented runtime features from planned Agent Quality Layer
  features.
- README is MCP-client-agnostic by default, with Claude Desktop, generic stdio, and VS Code framed
  as target examples rather than the whole product.
- Public docs describe Nulm as a local-first control plane direction only where accurate;
  they describe the localhost-only dashboard as local state inspection/intervention, not hosted
  monitoring or a remote service.
- `docs/product-vision.md`, `docs/roadmap.md`, and `docs/agent-quality-layer-plan.md` agree on the
  public direction.
- No active public doc presents the old AI-security-layer pivot as the final product.
- Internal task/autopilot notes are not tracked under public `docs/`.

## Security

- No real `claude_desktop_config.json` in the repo.
- Only `examples/claude_desktop_config.snippet.json` with placeholder paths is tracked.
- Personal paths, usernames, or home directory references have been cleaned.
- `.env`, `*.local`, log files, and private configs are gitignored.
- Public docs/config examples do not contain real local paths or secrets.

## Policy / Audit / Replay

- `nulm policy validate --path .claude-bridge-guard.json` reports no errors.
- `nulm policy simulate` works for a simple allowed command.
- `nulm audit --last` shows the latest session records.
- `nulm replay --record-id <id>` re-evaluates an existing record.
- Audit records are JSONL with redaction applied.
- Policy changes are visible via `nulm policy diff`.

## Installation Experience

- README covers installation in under 2 minutes.
- `pipx install nulm` is the primary public install path.
- `nulm init`, `nulm doctor`, and `nulm install ...` flow is visible in
  README.
- The installed CLI is consistently documented as `nulm`.
- Editable source install is kept under Development, not the user-facing quick start.
- Source install flow is clear for contributors.
- Example config is copy-pasteable and understandable.

## Value Proposition

- README clearly answers why the project exists.
- Differentiation from similar tools is stated.
- Distinguishing features like multi-root workspace switching are visible.
- Workflow tools and structured JSON outputs are visible.
- Feature evaluation principle is visible: keep, rework, hide, or remove; no feature should remain
  just for show.

## Pre-Release Final Check

- Tests pass.
- `python -m build` and `twine check dist/*` pass before PyPI.
- README behavior matches actual behavior.
- Agent Quality Layer claims match implemented behavior, or are explicitly marked planned.
- Feature lists do not overstate experimental, hidden, optional, or planned capabilities.
- Control-plane docs match implemented CLI, MCP, and localhost-dashboard behavior.
- Example chat flows match current behavior in `docs/agent-quality-chat-flows.md`.
- Agent Quality provider/parser claims mention fail-safe parsing and telemetry, not automatic
  provider execution.
- README/security docs explain the `client_managed_approval` contract and "not a sandbox" boundary.
- Placeholder URLs, example usernames, and fake repo addresses are cleaned.

## Related Documents

- `docs/security-model.md`
- `docs/compliance-readiness.md`
- `docs/ai-collaboration-token-budget.md`
