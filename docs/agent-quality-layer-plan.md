# Claude Bridge — Agent Quality Layer Plan

> **Last updated:** 2026-05-08
> **Status:** Canonical long-term plan for the AI agent layer

Claude Bridge should not depend on the user writing perfect prompts. The long-term product goal is
to let a non-expert describe what they want in ordinary language and still get professional-grade
software work: scoped plans, relevant context, safer execution, cleaner code, better tests, and
lower token waste.

The current MCP server already provides the execution substrate: file tools, shell tools, patching,
indexing, workflows, policy, audit, replay, and deterministic self-critique. The missing layer is a
real **Agent Quality Layer** between the chat client and those tools.

## Product Decision

Do not rush a broad public launch while the project still reads as only a safe MCP server. The
stronger product is to convert Claude Bridge from a **secure MCP tool server** into an **agent
quality layer** first.

This decision matters because a secure MCP server is useful but easy to compare with many other MCP
tool collections. The differentiator is the layer that helps ordinary, imperfect user requests
become professional software work. That means the public release should emphasize:

- better prompts without requiring the user to write them;
- context selection and token reduction;
- plan critique before broad edits;
- creative alternatives when the first approach is weak;
- safe chat-driven Bridge configuration;
- result review against a real quality bar.

Security remains mandatory, but it is not the whole product story. It is the foundation that lets
the quality layer operate safely.

## Product Thesis

Claude Bridge should be a local agent operating layer, not only a guarded tool server.

The user should be able to say:

- "Make this project public-ready."
- "Fix this bug."
- "Make this code professional."
- "Token usage is too high; optimize the setup."
- "I do not know what to ask next; turn my goal into the right next steps."

The bridge should then translate that rough request into a high-quality working process:

1. understand intent;
2. choose the smallest useful context;
3. critique the plan before execution;
4. suggest safe MCP configuration changes when useful;
5. guide implementation toward the existing codebase style;
6. check the result for correctness, maintainability, security, and test coverage;
7. reduce future prompt burden by producing the next useful instruction.

## Why the Current AI Layer Is Not Enough

The existing `ai_evaluator` layer is useful, but too narrow for this product thesis. Its current
center of gravity is a tool-call advisory decision: `allow`, `deny`, or `ask`, plus risk reasons.
That is a good security companion, but it does not yet solve the user's real problem:

- it does not turn vague goals into professional execution plans;
- it does not actively optimize token and context strategy;
- it does not review implementation quality as a senior collaborator;
- it does not suggest MCP/server configuration changes as part of the workflow;
- it does not produce improved follow-up prompts or task decompositions;
- it does not compare creative alternatives beyond the deterministic approach tools.

The product should keep hard security boundaries separate from agent intelligence. Built-in policy
and guard rails still decide what is allowed. The new agent layer should decide what is wise,
efficient, clear, and high-quality.

## Target User Experience

Installation should stay simple:

```bash
pipx install nulm
claude-bridge install
```

After that, the user should be able to configure and improve the bridge from chat:

```text
Bridge'i bu proje için optimize et.
```

Expected behavior:

- inspect current bridge status and project shape;
- propose a tool profile and context budget;
- explain tradeoffs in plain language;
- ask approval before mutating local config;
- apply only safe config changes through audited MCP tools;
- never accept secrets or API keys through ordinary chat payloads.

The user should also be able to give low-quality prompts and still receive useful work:

```text
Bu app'i daha kaliteli yap.
```

Expected behavior:

- convert the vague request into a scoped plan;
- identify the most relevant files and tests;
- ask at most one clarifying question if the ambiguity is blocking;
- otherwise choose a conservative first slice;
- produce or request validation commands;
- critique the result and propose next work.

## Architecture

### 1. Execution Layer

This is the existing MCP substrate:

- file read/write/move/copy;
- patch preview and application;
- guarded shell execution;
- indexing and relevance search;
- workflows and bounded agent loops;
- policy validation, simulation, diff, audit, replay, appeal;
- deterministic self-critique and checkpoints.

This layer should stay mostly deterministic, testable, and local-first.

### 2. Agent Quality Layer

New layer responsible for judgement, not raw execution. It may use local deterministic heuristics,
an API provider, or both.

Responsibilities:

- intent normalization;
- prompt improvement;
- context strategy;
- plan critique;
- implementation strategy;
- creative alternative generation;
- quality review;
- token/cost optimization;
- safe config recommendations;
- next-step generation.

This layer should call into the execution layer instead of bypassing it.

### 3. Configuration Control Layer

Chat-driven configuration should be possible, but governed.

Safe candidates for chat-driven config:

- tool profile: `essential`, `standard`, `full`;
- context budget profile: `low-cost`, `balanced`, `deep`;
- intent compaction enabled/disabled;
- bounded timeout values;
- onboarding hints enabled/disabled.

Restricted or admin-only config can be explained from chat, but should require explicit CLI,
environment, or local file action outside normal model-generated payloads.

Unsafe or restricted config:

- API keys;
- secrets;
- private tokens;
- remote AI evaluator/provider activation;
- broad allowed-root expansion;
- auto-approval expansion;
- shell hard-deny relaxation;
- destructive-command policy relaxation.

### 4. Product UX Layer

The public product should feel like a simple local assistant, not a bag of tools.

Key flows:

- install and connect to Claude Desktop;
- ask Bridge to inspect its own status;
- ask Bridge to optimize project settings;
- ask Bridge to transform a vague goal into a professional work plan;
- ask Bridge to run a quality pass after implementation;
- ask Bridge to explain what it changed and why.

## Core MCP Tools to Add

### `advise_next_step`

Turns a user goal and optional current state into a structured recommendation.

Inputs:

- `goal`;
- `target`;
- optional `recent_context_json`;
- optional `constraints_json`.

Output:

```json
{
  "intent_summary": "...",
  "recommended_next_step": "...",
  "why_this_step": "...",
  "needed_context": [],
  "risks": [],
  "validation": [],
  "token_strategy": [],
  "should_ask_user": false,
  "question": ""
}
```

### `improve_request`

Converts a rough user request into a clearer execution prompt or task spec.

Output should include:

- clarified goal;
- assumptions;
- constraints;
- acceptance criteria;
- suggested first slice;
- improved prompt text.

### `plan_quality_review`

Critiques an implementation plan before work begins.

Checks:

- scope too broad;
- wrong architectural layer;
- missing tests;
- excessive context read;
- risky shell/config behavior;
- opportunity for simpler implementation.

### `review_result_quality`

Runs after a code or docs change and reviews the result at a product-quality level.

Checks:

- behavior matches intent;
- tests cover changed behavior;
- docs match behavior;
- code follows project boundaries;
- token/context waste observed during the session;
- remaining risks and next slice.

### `suggest_bridge_config`

Recommends MCP configuration changes from current status and user goal.

Output:

```json
{
  "suggestions": [
    {
      "key": "tool_profile",
      "value": "essential",
      "reason": "Reduce tool surface and token overhead for a documentation-only session.",
      "risk": "low",
      "requires_approval": true
    }
  ]
}
```

### `apply_bridge_config_change`

Applies one safe config mutation after explicit approval.

Rules:

- validate the key and value;
- reject secrets and API keys;
- reject broad allowed-root or auto-approval escalation unless an explicit policy permits it;
- audit before and after values, with sensitive values redacted;
- return a rollback hint.

### Config Explanation

Explains current settings and tradeoffs in plain language through `bridge_status`,
`get_config`, and `tools_overview`.

This helps non-expert users understand why the bridge behaves the way it does.

## Structured Advisor Contract

The new layer should not reuse the narrow `EvaluationResponse` as its primary shape. Add a broader
contract, for example:

```json
{
  "schema_version": "agent_advice.v1",
  "intent_summary": "Prepare the project for a public alpha release.",
  "recommended_strategy": "Run a release-readiness pass before publishing.",
  "execution_plan": [
    "Check tracked public docs for stale claims.",
    "Run tests, lint, type check, and package build.",
    "Review package metadata and install flow."
  ],
  "context_plan": [
    "Read README.md, pyproject.toml, docs/publishing-checklist.md.",
    "Avoid archive/ unless stale references point there."
  ],
  "quality_risks": [
    "README may overclaim PyPI availability before the package is published."
  ],
  "token_savings": [
    "Use relevance search before broad file reads.",
    "Use essential tool profile for docs-only work."
  ],
  "config_suggestions": [
    {
      "key": "tool_profile",
      "value": "essential",
      "reason": "The session is documentation-heavy.",
      "risk": "low"
    }
  ],
  "validation": [
    "pytest",
    "ruff check .",
    "mypy src"
  ],
  "next_prompt": "Run the release-readiness checklist and fix only blocking issues."
}
```

Provider responses must be parsed strictly. Invalid JSON should degrade to deterministic local
advice, not crash the MCP server.

## Relationship to Security Policy

The Agent Quality Layer must not weaken existing safety controls.

Hard rules:

- built-in hard denies still win;
- policy rules still win;
- user approval still gates destructive actions;
- chat-driven config must not set secrets;
- AI suggestions are advisory unless routed through explicit safe apply tools;
- all config mutations must be audited;
- rollback or reset guidance must be visible.

This keeps the product trustworthy while making it smarter.

## Token and Context Strategy

The agent should actively reduce token burn. This is part of code quality, not a side concern.

Expected behavior:

- prefer targeted `rg` and file reads over broad scans;
- use index/relevance tools before opening many files;
- read summaries before long plans when possible;
- choose `essential` or `standard` tool profiles for narrow tasks;
- detect when old plans are stale and avoid re-reading them;
- compact prior session results for agent loops;
- recommend config changes when the current profile is too broad.

Future measurable goals:

- reduce average context read volume for common tasks by 40%;
- keep quality review recall stable while reducing prompt size;
- track advisor latency and recommendation usefulness in audit metadata.

## Implementation Phases

### Phase 0 — Documentation Realignment

Goal: stop publishing the project as only a security-controlled MCP runtime.

Tasks:

- make `docs/product-vision.md` point to the Agent Quality Layer as the long-term product center;
- update `docs/roadmap.md` around the new phases;
- remove or archive stale public docs that describe obsolete execution plans;
- keep README honest: current version has the execution substrate and early advisor pieces, not the
  full quality layer yet.

Exit criteria:

- no active docs claim the narrow AI security layer is the whole product;
- old roadmap files are marked historical or removed from public docs;
- public checklist includes Agent Quality Layer readiness before a broad launch.

### Phase 1 — Advisor Contract MVP

Goal: introduce the broad advice schema without changing dangerous behavior.

Tasks:

- add typed request/response models for `AgentAdvice`;
- implement deterministic local fallback advice;
- add strict JSON parsing for API provider advice;
- record latency and parse failures;
- add tests for malformed provider output;
- expose one read-only MCP tool: `advise_next_step`.

Exit criteria:

- vague requests can be converted into structured next-step advice;
- invalid provider responses fail safe;
- no config or filesystem mutation is possible through this tool.

### Phase 2 — Prompt and Plan Improvement

Goal: reduce dependence on high-quality user prompts.

Tasks:

- add `improve_request`;
- add `plan_quality_review`;
- connect workflow presets to advisor recommendations;
- add acceptance-criteria generation;
- add tests for ambiguous, broad, and risky prompts.

Exit criteria:

- user can provide a rough request and receive a scoped task plan;
- the advisor flags broad/refactor-heavy plans before work starts;
- workflow outputs can include improved prompt text.

### Phase 3 — Safe Chat-Driven Config

Goal: let users tune Bridge from chat without hand-editing config files.

Tasks:

- add `get_bridge_config` or reuse existing bridge status where appropriate;
- expose plain-language config explanation through existing status/config tools;
- add `suggest_bridge_config`;
- add `apply_bridge_config_change` for safe keys only;
- define a denylist for secrets and high-risk policy expansion;
- audit config changes with redaction;
- add rollback/reset instructions.

Exit criteria:

- user can ask for lower token usage and receive/apply safe settings;
- API keys and secrets cannot be set through MCP config mutation;
- risky approval/path/policy changes are refused or require a stronger explicit path.

### Phase 4 — Result Quality Review

Goal: make professional-quality output the default expectation.

Tasks:

- add `review_result_quality`;
- combine deterministic result heuristics with optional self-critique evidence;
- check changed files, tests, docs, risk, and validation depth;
- produce concise next actions;
- add focused fixtures for good/bad implementation plans.

Exit criteria:

- a completed change can be reviewed for correctness, maintainability, tests, and docs;
- the review recommends concrete next fixes rather than generic advice;
- quality review remains advisory and auditable.

### Phase 5 — Integrated Agent Workflow

Goal: make the quality layer feel like one coherent product.

Tasks:

- wire advisor calls into `run_workflow` modes where useful;
- add a "quality-first" workflow preset;
- make agent-loop sessions consult advice at boundaries, not every tiny step;
- generate compact handoff summaries;
- expose product-friendly docs and examples.

Exit criteria:

- a non-expert user can ask for a feature/fix and get a guided process;
- token strategy, plan quality, implementation quality, and config suggestions are visible;
- the workflow remains bounded, auditable, and reversible.

### Phase 6 — Public Alpha Readiness

Goal: publish the project with the right promise.

Tasks:

- update README around the agent quality thesis;
- document what exists now vs what is experimental;
- run release gate in a clean Python 3.10-3.13 matrix;
- validate package build and PyPI metadata;
- ensure setup flow works without private local paths;
- publish only after docs match behavior.

Exit criteria:

- public docs do not overclaim;
- first install path is simple;
- users understand the project is a local quality-and-execution bridge, not a remote SaaS or a
  sandbox.

## Open Decisions

- Should the new module be named `agent_advisor`, `quality_agent`, or `agent_quality`?
- Should API provider calls be allowed during every workflow, or only explicit advisor tools?
- How much of `ai_evaluator` should be renamed vs kept for backward compatibility?
- Which config keys are safe enough for chat-driven mutation in v0.1?
- Should config changes be persisted in project config, user config, or both?
- Should advisor outputs be stored in audit logs, separate session notes, or both?

## Non-Goals

- Do not build a remote SaaS control plane for v0.1.
- Do not accept API keys through normal chat/MCP tool parameters.
- Do not weaken shell hard denies or path boundaries.
- Do not create unbounded autonomous loops.
- Do not require cloud AI providers for the core install.

## Success Criteria

The Agent Quality Layer is working when:

- users can give rough goals and receive professional task plans;
- the bridge reduces context waste without losing useful code understanding;
- implementation plans are critiqued before broad edits;
- result quality checks catch missing tests, docs drift, and scope creep;
- safe MCP settings can be explained and adjusted from chat;
- security controls remain explicit and auditable.
