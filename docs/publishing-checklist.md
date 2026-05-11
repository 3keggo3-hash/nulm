# Publishing Checklist

Quick pre-release verification before sharing publicly.

## Product Positioning

- README describes Claude Bridge as an agent quality and execution layer, not only a security MCP
  tool server.
- README clearly separates current implemented runtime features from planned Agent Quality Layer
  features.
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

- `claude-bridge policy validate --path .claude-bridge-guard.json` reports no errors.
- `claude-bridge policy simulate` works for a simple allowed command.
- `claude-bridge audit --last` shows the latest session records.
- `claude-bridge replay --record-id <id>` re-evaluates an existing record.
- Audit records are JSONL with redaction applied.
- Policy changes are visible via `claude-bridge policy diff`.

## Installation Experience

- README covers installation in under 2 minutes.
- `claude-bridge install ...` flow is visible in README.
- If publishing to PyPI, `pipx install claude-bridge-mcp` flow is documented while the installed
  CLI remains `claude-bridge`.
- Source releases clearly note future install plans.
- Source install flow is clear.
- Example config is copy-pasteable and understandable.

## Value Proposition

- README clearly answers why the project exists.
- Differentiation from similar tools is stated.
- Distinguishing features like multi-root workspace switching are visible.
- Workflow tools and structured JSON outputs are visible.

## Pre-Release Final Check

- Tests pass.
- `python -m build` and `twine check dist/*` pass before PyPI.
- README behavior matches actual behavior.
- Agent Quality Layer claims match implemented behavior, or are explicitly marked planned.
- Example chat flows match current behavior in `docs/agent-quality-chat-flows.md`.
- Agent Quality provider/parser claims mention fail-safe parsing and telemetry, not automatic
  provider execution.
- README/security docs explain the `client_managed_approval` contract and "not a sandbox" boundary.
- Placeholder URLs, example usernames, and fake repo addresses are cleaned.

## Related Documents

- `docs/security-model.md`
- `docs/compliance-readiness.md`
- `docs/ai-collaboration-token-budget.md`
