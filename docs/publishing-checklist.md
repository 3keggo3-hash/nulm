# Publishing Checklist

Quick pre-release verification before sharing publicly.

## Security

- No real `claude_desktop_config.json` in the repo.
- Only `examples/claude_desktop_config.snippet.json` with placeholder paths is tracked.
- Personal paths, usernames, or home directory references have been cleaned.
- `.env`, `*.local`, log files, and private configs are gitignored.
- `rg -n "/Users/|API_KEY|SECRET|TOKEN|PASSWORD" .` scan is clean.

## Policy / Audit / Replay

- `claude-bridge policy validate --path .claude-bridge-guard.json` reports no errors.
- `claude-bridge policy simulate --path .claude-bridge-guard.json --tool run_shell --param "command=ls"` works.
- `claude-bridge audit --last` shows the latest session records.
- `claude-bridge replay --record-id <id>` re-evaluates an existing record.
- Audit records are JSONL with redaction applied.
- Policy changes are visible via `claude-bridge policy diff`.

## Installation Experience

- README covers installation in under 2 minutes.
- `claude-bridge install ...` flow is visible in README.
- If publishing to PyPI, `pipx install claude-bridge` flow is documented; for source releases, note future plans.
- Source install flow is clear.
- Example config is copy-pasteable and understandable.

## Value Proposition

- README clearly answers why the project exists.
- Differentiation from similar tools is stated.
- Distinguishing features like multi-root workspace switching, workflow tools, and structured JSON outputs are visible.

## Pre-Release Final Check

- Tests pass.
- `python -m build` and `twine check dist/*` pass before PyPI.
- README behavior matches actual behavior.
- README/security docs explain the `client_managed_approval` contract and "not a sandbox" boundary.
- Placeholder URLs, example usernames, and fake repo addresses are cleaned.

## Related Documents

- `docs/security-model.md`
- `docs/compliance-readiness.md`
- `docs/ai-collaboration-token-budget.md`
