# AI Collaboration Token Budget

> Status: Practical working rules for humans and AI agents

Claude Bridge is useful, but this repository is large enough that careless AI collaboration burns
context quickly. The problem is not only model behavior; it is also repo shape, tool schema size,
long test output, large diffs, and broad Markdown plans.

## Main Token Burn Sources

- Large files: `tests/test_protocol.py`, `src/claude_bridge/cli.py`,
  `src/claude_bridge/shell_tools.py`, `src/claude_bridge/workflow_tools.py`,
  `src/claude_bridge/audit.py`, `src/claude_bridge/indexing.py`, and `src/claude_bridge/server.py`.
- Long planning docs: active plans and roadmap/audit documents are useful but expensive to paste
  into a chat repeatedly.
- Full test output: one full `pytest` run is fine for validation, but repeated full logs should be
  summarized, not pasted back into the model.
- Dirty worktree diffs: `git diff` on this repo can be enormous while refactors are in progress.
- MCP tool schemas: registering every niche tool increases the tool list the MCP client may need to
  carry in context.

## Default Operating Mode

Generated MCP configs should include:

```json
{
  "CLAUDE_BRIDGE_TOOL_PROFILE": "standard",
  "CLAUDE_BRIDGE_CONTEXT_BUDGET_PROFILE": "balanced"
}
```

Use `CLAUDE_BRIDGE_TOOL_PROFILE=essential` for low-token sessions that only need file, shell,
workspace, and indexing tools. Switch to `full` only for meta-agent, fun, URL, multi-format, or
extra insights work.

## Collaboration Rules

1. Start from `docs/product-vision.md`, `docs/roadmap.md`, and
   `docs/agent-quality-layer-plan.md` when planning; after that, read only the section being
   implemented.
2. Use `rg` and narrow `sed -n` ranges instead of opening whole large files.
3. Do not paste full `pytest`, `git diff`, or `git status` output into the chat; summarize counts and
   failures.
4. Prefer focused tests during development, then one full `pytest`, `ruff check .`, and `mypy src`
   before handoff.
5. Keep a short handoff note after each implementation slice: changed files, reason, validation,
   and next slice.

## Night Mode (Low Usage)

When weekly budget is tight, run short maintenance slices instead of feature work:

1. Commit and push current work first so recovery is easy.
2. Run one focused test target instead of the full suite.
3. Run `ruff check` only on touched paths (`src`, `tests`, or specific files).
4. Limit each slice to one tiny patch and one verification command.
5. End each slice with a 3-line note: what changed, what passed, what is next.

## Codebase Direction

Reducing token use is also a code quality task:

- Keep splitting large registration and workflow modules into focused packages.
- Keep tool profiles enforced at MCP registration time.
- Keep disk/index caches token-based instead of content-heavy.
- Keep docs canonical and avoid duplicate long plans for the same roadmap.

## Related Documents

- `docs/agent-quality-layer-plan.md`
- `docs/README.md`
