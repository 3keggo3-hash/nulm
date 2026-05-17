# Competitive Analysis

Nulm should stay focused on the Agent Quality Layer and skill governance. The goal is not
to become an unbounded local runtime; the differentiator is helping an MCP client choose safer
context, safer actions, and better review loops around real workspace tools.

## Product Lessons

| Tool | What works well | Nulm response |
|---|---|---|
| Claude Code | Skills, hooks, permissions, subagents | Add inspect-before-import skill governance and review loops. |
| Cursor | Rules, modes, MCP discovery | Keep task-specific guidance visible and profile tools by capability. |
| Aider | Git-first workflow and repo maps | Keep recommendations deterministic and explain why files/skills were chosen. |
| OpenHands | Agent orchestration and sandbox framing | Keep orchestration bounded; do not claim OS sandboxing where none exists. |

## Product Bets

- Skill discovery should be local-first and explainable before it becomes remote.
- Remote skill search must be metadata-first; package install and execution need explicit review.
- Quality and security review should be a repeated workflow gate, not a one-time final check.
- Parallel agent work should use disjoint file ownership and controlled merge, not shared-file races.
- Creative feature ideation belongs after functional and security gates pass.

## Near-Term Scope

- Local skill recommendation with scores and reasons.
- Skill package inspection before import.
- CLI and MCP read-only surfaces for skill discovery and package inspection.
- `run_skill` kept in the full tool profile because execution is mutating.
- Post-implementation review by functionality, architecture, security, performance, observability,
  test, and product-review agents.

## Deferred

- Automatic internet skill download, install, or execution.
- Remote policy/skill marketplace with trust guarantees.
- Signed package verification.
- OS-level sandboxing for skill execution.
