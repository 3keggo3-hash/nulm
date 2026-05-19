# Nulm — Roadmap

> **Last updated:** 2026-05-08
> **Status:** Active technical roadmap

Nulm is moving from a "security-controlled MCP runtime" toward a broader **agent quality
and execution layer**. The existing runtime remains the foundation, but the public product should be
judged by whether it helps ordinary user requests become professional software work.

For the product direction, read [`docs/product-vision.md`](./product-vision.md).
For the detailed AI/agent plan, read
[`docs/agent-quality-layer-plan.md`](./agent-quality-layer-plan.md).

## Roadmap Rules

- Keep safety and execution separate from AI judgement.
- Do not weaken shell hard denies, path boundaries, approval gates, or secret handling.
- Prefer small, testable MCP tools over broad autonomous behavior.
- Keep provider-backed AI optional; deterministic local behavior must still work.
- Public docs must say what exists today vs what is planned.

## Phase 0 — Repositioning and Public Docs

Goal: align public documentation with the new product thesis before a broad public launch.

Status: done for the current documentation pass.

Tasks:

- [x] Add canonical Agent Quality Layer plan.
- [x] Update product vision from "security runtime" to "quality and execution layer."
- [x] Replace stale phase roadmap with the new roadmap.
- [x] Remove public overnight/autopilot maintenance note from `docs/`.
- [x] Update README to describe the new product direction without overclaiming implementation.
- [x] Update publishing checklist with Agent Quality Layer readiness gates.
- [x] Run final docs consistency scan.

Exit criteria:

- public docs do not present the old security-only pivot as the final product;
- stale internal execution plans are archived, deleted, or marked historical;
- README clearly distinguishes current runtime features from planned quality-layer features.

## Phase 1 — Advisor Contract MVP

Goal: add a structured advisor contract that can reason about intent, context, plan quality, token
usage, validation, and safe config suggestions.

Tasks:

- [x] Add typed `AgentAdviceRequest` and `AgentAdviceResponse` models.
- [x] Add strict parser for provider-backed advice JSON.
- [x] Add deterministic local fallback advice.
- [x] Track advisor latency and parse failures.
- [x] Expose read-only `advise_next_step` MCP tool.
- [x] Add first tests for vague goals, malformed context input, and deterministic advice.

Exit criteria:

- a rough user goal can become structured next-step advice;
- invalid provider output fails safe;
- the tool cannot mutate files, shell, or config.

## Phase 2 — Prompt and Plan Quality

Goal: reduce dependence on expert prompt writing.

Tasks:

- [x] Add `improve_request` MCP tool.
- [x] Add `plan_quality_review` MCP tool.
- [x] Generate assumptions, acceptance criteria, first slice, and validation suggestions.
- [x] Flag broad, risky, or architecture-breaking plans before execution.
- [x] Connect workflow presets to advisor recommendations where useful.

Exit criteria:

- a vague user request can be converted into a scoped implementation plan;
- plan critique catches missing tests, broad refactors, wrong layers, and context waste;
- outputs are concise enough for normal chat use.

## Phase 3 — Safe Chat-Driven Configuration

Goal: let users inspect and tune Bridge from chat without hand-editing config files.

Tasks:

- [x] Add or refine config status/explanation tool.
- [x] Add `suggest_bridge_config`.
- [x] Add `apply_bridge_config_change` for safe keys only.
- [x] Define allowed config keys and restricted keys.
- [x] Reject API keys, secrets, broad allowed-root expansion, auto-approval expansion, and hard-deny
      relaxation through ordinary MCP payloads.
- [x] Audit config mutations with redaction and rollback hints.

Exit criteria:

- user can ask "token usage is high, optimize settings" and apply safe recommendations;
- secrets cannot be set through chat;
- risky config changes are refused or routed to an explicit stronger path.

## Phase 4 — Result Quality Review

Goal: make professional-quality output the normal finish line.

Tasks:

- [x] Add read-only deterministic `review_result_quality`.
- [x] Combine deterministic self-critique with advisor output.
- [x] Review changed files, tests, docs, security impact, and validation depth.
- [x] Produce concrete next fixes instead of generic advice.
- [x] Add focused good/bad result tests for the deterministic MVP.
- [x] Add broader fixtures that compare high-quality and weak implementation results.

Exit criteria:

- completed work can be reviewed for correctness, maintainability, test coverage, docs drift, and
  scope creep;
- review remains advisory, auditable, and bounded.

## Phase 5 — Integrated Quality Workflows

Goal: make the quality layer feel like one product rather than separate tools.

Tasks:

- [x] Add a quality-first workflow preset.
- [x] Surface advisor output in `run_workflow` at start/end boundaries.
- [x] Let agent-loop sessions consult advisor at boundaries, not every small step.
- [x] Generate compact workflow quality-gate summaries for result review.
- [x] Generate suggested next prompts for quality-first workflow output.
- [x] Generate next prompts after executed workflow results.
- [x] Document example chat flows for non-expert users.

Current polish:

- [x] Surface Agent Quality parser telemetry in `bridge_status`.
- [x] Surface metadata-only Skill Governance snapshot in `bridge_status`.
- [x] Group Agent Quality tools by planning, config, and workflow/result review in
      `tools_overview`.

Exit criteria:

- a user can ask for a feature/fix and get a guided process with context strategy, quality checks,
  validation, and safe config suggestions;
- loops stay small, reversible, and audited.

## Phase 6 — Runtime and Release Hardening

Goal: keep the execution substrate reliable while the quality layer grows.

Tasks:

- [x] Finish remaining low-risk CLI/module splits.
- [x] Keep lazy imports and tool profiles effective.
- [x] Validate package build and PyPI metadata locally in a clean environment.
- [x] Add CI matrix on Python 3.10-3.13.
- [x] Keep security model, policy docs, and README behavior aligned.

Exit criteria:

- tests, Ruff, Black, mypy, package build, and `twine check` pass;
- install flow is simple;
- public release messaging matches actual behavior.

External confirmation still required before a broad launch:

- GitHub Actions matrix must pass after push. As of 2026-05-19, local `main` matches
  `origin/main` at `79613f5`, but this environment could not read private-repo Actions run
  results.
- First external source/PyPI install smoke should pass. As of 2026-05-19,
  `pip install nulm==0.1.1` and `pip index versions nulm` returned no matching PyPI
  distributions, so publishing/visibility remains a release blocker.

## Deferred

- Remote skill marketplace with curated trust metadata.
- Remote policy marketplace.
- Remote SaaS control plane.
- HMAC audit integrity chain.
- Security budget per session.
- Agent Quality benchmark suite.
- Adaptive workflow learning loop.
- Unbounded autonomous execution.
- Accepting API keys through chat/MCP tool parameters.
- Weakening shell/path/security defaults for convenience.
