# Multi-Agent Execution Roadmap

Date: 2026-05-20
Horizon: 29 weeks
Status: Updated implementation roadmap

This roadmap translates the multi-agent architecture audit into an execution plan. It deliberately
prioritizes observability, deterministic orchestration, tool mediation, and measurable progress over
flashy autonomy.

Phase 0 baseline evidence lives in `docs/multi-agent-runtime-baseline.md`. Phase 0.5 feature surface
classification lives in `docs/multi-agent-feature-pruning-audit.md`.

The master/sub-agent architecture has two inseparable parts:

- the technical skeleton: typed contracts, leases, idempotency, tool mediation, durable records,
  DAG execution, verification, and audit;
- the behavioral nervous system: confidence signals, grounding through context manifests, typed
  failures, bounded critique, conflict records, low-relevance finding isolation, and operator-load
  metrics.

Do not implement the behavioral layer as open-ended autonomy. Add it first as structured telemetry,
then calibrate it through benchmarks, and only then use it to stop, escalate, or adjudicate runs.

## Guiding Rules

- Preserve current MCP tool names, CLI behavior, guard policy, approval semantics, and audit logs.
- Make the current agent layer measurable before making it more autonomous.
- Route agent work through mediated tools before adding parallel mutation.
- Prefer typed contracts and traceable state over bigger prompts.
- Keep provider-backed AI optional and deterministic local behavior intact.
- Hide experimental orchestration behind explicit/full profiles.
- Treat shell/file safety as a protected layer.
- Never combine safety refactors with autonomy changes.
- Treat operator cognitive load as a product metric. If a new mechanism adds traces, states, or
  knobs without reducing debugging or decision burden, the architecture is getting worse.
- Add confidence, relevance, and critique mechanisms in shadow/telemetry mode before enforcing
  runtime behavior. Raw model confidence is not reliable enough to gate production execution until
  benchmarked.

## Priority Stack

| Priority | Workstream | ROI | Risk | Why Now |
|---:|---|---|---|---|
| P0 | Agent run observability | Very high | Low | Enables every later decision to be measured |
| P0 | Typed task/artifact contracts | Very high | Low-medium | Removes loose dict orchestration |
| P0 | Subagent tool mediation | Critical | Medium | Closes the direct subprocess/tool-bypass gap |
| P1 | Context manifests/budget ledger | High | Low-medium | Reduces token waste |
| P1 | Benchmark/evaluation harness | High | Low-medium | Prevents demo-ware progress claims |
| P1 | Route decision telemetry | High | Low | Observes `ai_router.py` without autonomy |
| P1 | Behavioral telemetry | High | Low-medium | Shows drift and low relevance before enforcement |
| P2 | Durable DAG node persistence | High | Medium | Needed for resumability |
| P2 | Verification/adjudication gates | High | Medium | Enables safer parallelism |
| P3 | Sandbox/worktree envelopes | High | Medium-high | Valuable but operationally heavier |
| P3 | Adaptive routing/skills in shadow mode | Medium later | High | Needs labeled run data first |

## Updated Phase Timeline

| Week | Phase | Objective | Risk |
|---:|---|---|---|
| 1 | Phase 0 | Stabilize baseline and test reality | Low |
| 2 | Phase 0.5 | Classify unnecessary, early, or experimental surface | Low |
| 3-4 | Phase 1 | Agent run observability | Low |
| 5-6 | Phase 2 | Typed task/artifact contracts | Low-medium |
| 7 | Phase 3 | Route decision telemetry | Low |
| 8-11 | Phase 4 | Agent Tool Broker plus buffer | Medium |
| 12-13 | Phase 5 | Context manifest plus budget ledger | Low-medium |
| 14-16 | Phase 6 | Benchmark harness plus regression gates | Low-medium |
| 17-21 | Phase 7 | Durable DAG records plus buffer | Medium |
| 22 | Phase 7.5 | Wait, measure, and validate the state model | Low |
| 23-26 | Phase 8 | Minimal deterministic DAG scheduler | Medium |
| 27-29 | Phase 9 | Verification/adjudication MVP | Medium |

## Behavioral Protocol Integration

These additions refine the existing phases; they do not create a new autonomy track.

| Protocol | First Phase | Enforcement Phase | Implementation Rule |
|---|---:|---:|---|
| Confidence score | Phase 1 | Phase 9 | Shadow first; enforce only after calibration |
| Context grounding | Phase 5 | Phase 8 | Bind runs to `ContextManifest` ids before scheduling |
| Typed failure class | Phase 1 | Phase 8 | Log immediately; schedule from it later |
| One-turn critique | Phase 6 | Phase 9 | Benchmark as gated review; never make it always-on |
| Conflict record | Phase 8 | Phase 9 | Detect overlap first; adjudicate after verifier evidence |
| Low relevance flag | Phase 5 | Phase 9 | Store separately; keep out of final reports by default |
| Meta-cognition | Phase 6 | Phase 9 | Summarize health; hide raw trace noise |

The important sequencing constraint: behavioral metrics must not become hard stops before the system
has enough baseline data to show that they improve outcomes. Otherwise the roadmap replaces hidden
agent drift with visible but noisy orchestration theater.

## Phase 0: Baseline Stabilization

Scope:

- Run the existing test suite and record results.
- Separate flaky, slow, skipped, and cache-sensitive tests.
- Mark the agent-related test group as its own baseline.
- Do not improve coverage during this phase; make gaps visible only.

Exit criteria:

- Test baseline report exists.
- Agent-layer minimum regression commands are identified.
- The starting system state is answerable from evidence.

Current artifact: `docs/multi-agent-runtime-baseline.md`.

## Phase 0.5: Feature Surface Pruning Audit

Scope:

- Classify current feature/module/tool surface as Keep, Rework, Hide, Deprecate, or Remove later.
- Do not delete code in this phase.
- Move risky, noisy, or experimental behavior away from default profiles only when compatibility is
  preserved by keeping the implementation available in an explicit profile.
- Keep the deferred list visible throughout the roadmap.

Initial decisions:

- `run_council_session`: keep but gate; hidden from `standard`, available in `full`.
- Adaptive proposals: proposal-only/shadow; no automatic behavior.
- `run_skill`: full profile only; not default runtime behavior.
- `meta_agent_server`: hide/rework candidate for broad behavior.
- `agents/messaging.py`: experimental/test-only until durable event logs exist.
- `agents/shared_memory.py`: replacement candidate after context manifest/blackboard work.
- `workflow_engine.py`: preserve as a future compatibility facade.
- `VerificationAgent`: preserve and evolve into a real verifier node in Phase 9.

Exit criteria:

- Keep/Rework/Hide/Deprecate/Remove-later table exists.
- Deferred list is visible and preserved.
- Default tool-surface decisions are explicit.

Current artifact: `docs/multi-agent-feature-pruning-audit.md`.

## Month 1: Make the Current Agent Layer Observable and Honest

Objective: no new autonomy; make current orchestration inspectable, typed, and testable.

### 1. Add Agent Run Records

Status: Phase 1 exit criteria met. `agent_run.v1` records exist for dispatcher-managed subtasks,
direct `BaseAgent.execute_traced(...)` calls, and orchestrator-visible summaries. Records are
appended to the current audit session/index as `agent_run` records. Compact summaries surface
through orchestrator artifacts, `summarize_session`, MCP session-insight details, dashboard activity
payloads, and `audit summary` CLI output. Remaining direct subprocess/tool mediation work belongs
to Phase 4.

Deliverables:

- Add `AgentRunRecord` dataclass with:
  - `run_id`;
  - `task_id`;
  - `agent_name`;
  - `task_kind`;
  - `started_at` / `ended_at`;
  - `status`;
  - `duration_ms`;
  - `tool_calls`;
  - `model_route`;
  - `context_manifest_id`;
  - `artifact_ids`;
  - nullable `confidence_score`;
  - nullable `grounding_score`;
  - nullable `relevance_score`;
  - `error_class`;
  - `error_message`.
- Emit records from orchestrator, dispatcher, and subagents.
- Store records in audit/control-plane compatible JSONL, versioned as `agent_run.v1`.
- Add compact run summary helper for dashboard/CLI/reporting.
- Treat confidence and grounding scores as advisory telemetry in this phase. Do not stop execution
  based on these scores yet.

Exit criteria:

- Every orchestrated subtask produces one traceable run record.
- Failed subtasks include a typed failure class instead of only free-form `str(e)`.
- Confidence/grounding/relevance fields can be absent, but the schema has a stable place for them.
- Existing agent APIs keep working.

Estimated difficulty: Medium.
Operational risk: Low.
Primary tests:

- orchestrator emits run records for success, partial, and failure;
- dispatcher correlates subtask id to run id;
- malformed agent result still produces a failure record.

### 2. Introduce Typed Task Contracts Behind an Adapter

Status: In progress. `TaskSpec`, `TaskBudget`, `TaskPermissions`, `AgentArtifact`, and
`EvidenceRef` now exist. The dispatcher coerces legacy subtask dictionaries into `TaskSpec` at the
boundary and also accepts typed `TaskSpec` inputs directly. Keyword decomposition and public
orchestrator behavior are unchanged.

Deliverables:

- Add `TaskSpec`, `TaskBudget`, `TaskPermissions`, `AgentArtifact`, and `EvidenceRef`.
- Convert current loose subtask dicts to `TaskSpec` internally.
- Keep compatibility adapter from existing `{"id", "task", "agent_name"}` dicts.
- Add optional fields only; do not require planner sophistication yet.
- Add optional behavioral fields without enforcing them yet:
  - `question`: the task expressed as the question the subagent must answer;
  - `acceptance_criteria`;
  - `escalation_policy`;
  - `allowed_failure_classes`;
  - `expected_evidence`.

Minimum `TaskSpec` fields:

```json
{
  "task_id": "research_task",
  "kind": "research",
  "goal": "Analyze current agent layer",
  "agent_name": "research_agent",
  "question": "Which parts of the current agent layer bypass mediated tools?",
  "read_set": [],
  "write_set": [],
  "budget": {
    "max_tool_calls": 10,
    "timeout_seconds": 120
  },
  "expected_artifacts": ["findings"]
}
```

Exit criteria:

- Orchestrator and dispatcher no longer depend on untyped dict access except in adapter code.
- Existing keyword decomposition behavior is unchanged.
- Type hints and tests cover conversion and validation.
- Behavioral fields round-trip through adapters without requiring old callers to provide them.

Estimated difficulty: Medium.
Operational risk: Low-medium.

### 3. Add Route Decision Telemetry Without Changing Routing

Deliverables:

- Log `AIRouteDecision` from advisory/council/model-routing flows.
- Include candidate profile, selected profile, provider, model, mode, quality tier, estimated
  tokens, estimated cost, timeout, and failure/fallback status.
- Add metrics counters for local vs remote, provider failures, JSON parse failures, timeout count,
  and fallback count.
- Add `route_reason` and `fallback_reason` fields so later meta-cognition can distinguish quality
  fallback from policy fallback, timeout fallback, and provider parse failure.

Exit criteria:

- Router behavior is observable but unchanged.
- Provider-backed AI remains optional and off unless configured.
- Route logs explain why a fallback happened without requiring raw provider traces.

Estimated difficulty: Low-medium.
Operational risk: Low.

## Month 2: Mediate Tools and Measure Token/Context Waste

Objective: close the biggest safety gap and make token efficiency visible.

### 4. Create an Agent Tool Broker

Deliverables:

- Add `AgentToolBroker` with narrow methods:
  - `read_file`;
  - `search`;
  - `git_status`;
  - `git_log`;
  - `run_validation`;
  - `shell_readonly` if needed.
- Broker checks `TaskPermissions` and current policy before execution.
- Broker records every tool call against `AgentRunRecord`.
- Replace direct `subprocess.run` in:
  - `agents/sub/git_agent.py`;
  - `agents/sub/research_agent.py`;
  - `agents/sub/debug_agent.py`.

Non-goals:

- Do not redesign `shell_tools.py`.
- Do not add new shell permissions.
- Do not relax destructive command blocks.
- Do not make subagents mutating yet.

Exit criteria:

- No subagent directly shells out for git/search/test diagnostics.
- Bypass attempts are denied and audited.
- Existing agent outputs remain roughly equivalent.

Estimated difficulty: Medium-high.
Operational risk: Medium.
Primary tests:

- git agent uses broker path;
- research agent uses broker/search path;
- broker denies a tool outside task permission;
- broker preserves audit/policy metadata.

### 5. Add Context Manifest MVP

Deliverables:

- Add `ContextManifest` with:
  - manifest id;
  - task id;
  - selected files;
  - file digests;
  - short summaries;
  - token estimate;
  - source reason;
  - taint/source labels;
  - duplicate-context estimate;
  - low-relevance artifact ids.
- Generate manifests from existing relevance/indexing helpers.
- Agents receive manifest references in context.
- Add measurement for duplicate context ratio.
- Store low-relevance or weakly grounded findings as separate artifacts instead of mixing them into
  primary reports.

Exit criteria:

- Agent runs can report what context was selected and why.
- Repeated file summaries are cached by digest.
- Token estimates appear in run summary.
- Findings below relevance threshold are visible in audit data but excluded from final summaries
  unless explicitly requested.

Estimated difficulty: Medium.
Operational risk: Low-medium.

## Month 3: Build the Evaluation Spine

Objective: create a realistic harness before adding durable autonomy.

### 6. Add Agent Workflow Benchmark Harness

Deliverables:

- Add a small scenario runner for agent workflows.
- Start with 8-12 local deterministic scenarios:
  - read-only architecture lookup;
  - malformed task;
  - missing agent;
  - permission denied;
  - git status read;
  - research context selection;
  - advisor malformed provider output;
  - prompt-injection fixture;
  - policy-denied shell request;
  - token budget cap.
- Persist benchmark results as JSON with stable schema.

Metrics:

- verified success;
- total duration;
- tool call count;
- estimated token count;
- duplicate context ratio;
- confidence calibration error;
- low-relevance finding rate;
- context insufficiency rate;
- policy denial correctness;
- retry count;
- failure class;
- trace completeness.

Exit criteria:

- Benchmark can run locally without cloud provider keys.
- At least one CI-safe command exercises the suite.
- Results can compare current run to a saved baseline.
- Confidence and relevance signals are evaluated as predictions, not treated as proof of quality.

Estimated difficulty: Medium.
Operational risk: Low-medium.

### 7. Define Release Gates for Agent-Layer Changes

Deliverables:

- Add regression gates:
  - no direct subagent subprocess;
  - trace completeness above threshold;
  - no increase in duplicate context ratio above threshold;
  - no unclassified failure in orchestrated agent paths;
  - no low-relevance artifact promoted into a final answer by default;
  - no new policy bypass;
  - benchmark success not worse than baseline.
- Document gates in `docs/test-strategy.md` or a benchmark README.

Exit criteria:

- Agent-layer changes have measurable pass/fail criteria.
- The project stops relying on "looks smarter" as evidence.
- Behavioral telemetry either improves benchmark explainability or stays non-blocking.

Estimated difficulty: Low-medium.
Operational risk: Low.

## Months 4-5: Add Deterministic DAG Persistence

Objective: move from parallel calls to resumable orchestration without changing external UX.

### 8. Persist Runs, Nodes, and Artifacts

Deliverables:

- Extend control plane with append-only records:
  - `runs.jsonl`;
  - `nodes.jsonl`;
  - `artifacts.jsonl`.
- Add node statuses:
  - `pending`;
  - `ready`;
  - `leased`;
  - `running`;
  - `blocked`;
  - `completed`;
  - `failed`;
  - `cancelled`.
- Add leases with expiry and owner id.
- Add idempotency keys for mutating node execution.
- Add optional `ConflictRecord` entries for overlapping write-set or patch-hunk detection.
- Build materialized run view from append-only records.

Exit criteria:

- A run can be reconstructed from disk.
- Completed nodes are not rerun after process restart.
- Conflicts are recorded as first-class events instead of being silently hidden inside merge logic.
- Old control-plane task/approval APIs still work.

Estimated difficulty: High.
Operational risk: Medium.
Danger points:

- Avoid two canonical state stores.
- Do not migrate all workflow behavior at once.
- Keep old APIs as facades over new records where possible.

### 9. Add Minimal DAG Scheduler

Deliverables:

- Scheduler executes ready nodes in dependency order.
- Concurrency limit defaults to conservative value.
- Nodes declare read/write sets.
- Scheduler refuses parallel mutation with overlapping write sets.
- Retry policy is explicit and capped.
- Scheduler decisions are driven by typed failure classes:
  - retry capped for transient failures;
  - stop for policy/schema failures;
  - escalate for context insufficiency or low calibrated confidence;
  - require verifier/adjudication for conflict records.

Non-goals:

- No recursive delegation.
- No learned planning.
- No peer-to-peer agent messaging.
- No automatic broad refactors.

Exit criteria:

- Read-only/research nodes can run in parallel.
- Mutating nodes are sequential unless write sets are disjoint.
- Failed node produces typed failure and does not thrash.
- A node cannot retry indefinitely under the same failure class.

Estimated difficulty: High.
Operational risk: Medium.

## Month 6: Verification Gates and Controlled Parallelism

Objective: enable safer autonomy only where the system can verify itself.

### 10. Independent Verification Nodes

Deliverables:

- Add verifier node type with no mutation permission.
- Verification consumes artifacts and acceptance criteria.
- Verification classifies failures:
  - policy failure;
  - test failure;
  - schema failure;
  - context insufficiency;
  - merge conflict;
  - provider/tool transient failure.
- Scheduler uses failure class to choose stop, retry, replan, or ask user.
- Add bounded one-turn critique only for high-uncertainty or high-risk plan boundaries:
  - planner produces decomposition;
  - critic identifies why it may be wrong;
  - planner revises or rejects with evidence;
  - execution starts after the single critique round.

Exit criteria:

- Mutating DAG runs require verifier pass before final success.
- Same failure cannot retry indefinitely.
- Verification output cites artifacts/evidence.
- One-turn critique is traceable and capped; it cannot become an always-on council loop.

Estimated difficulty: Medium.
Operational risk: Low-medium.

### 11. Patch Conflict and Adjudication MVP

Deliverables:

- Detect overlapping write sets before execution.
- Detect overlapping patch hunks after proposal.
- Add adjudication record for accepted/rejected artifacts.
- Classify conflicts as:
  - `overlapping_write_set`;
  - `overlapping_patch`;
  - `task_boundary_ambiguity`.
- Keep adjudication deterministic where possible:
  - tests passed;
  - smaller diff;
  - lower-risk file set;
  - explicit user preference.

Exit criteria:

- Parallel workers cannot silently overwrite each other.
- Conflict decisions are traceable.
- Conflict rate becomes a decomposition-quality metric, not just a merge failure.

Estimated difficulty: Medium.
Operational risk: Medium.

## Work Explicitly Deferred

These are not 3-6 month priorities unless earlier phases prove they are necessary:

- learned model router;
- recursive delegation;
- always-on council/debate;
- autonomous skill installation or execution;
- self-modifying prompts;
- full A2A implementation;
- remote SaaS control plane;
- Docker sandbox by default;
- marketplace/auction routing;
- automatic cross-project memory sharing;
- learned confidence thresholds that mutate runtime behavior without benchmark evidence.

## Measurement Dashboard

Track these from Month 1 onward:

| Metric | Target Direction | First Useful Threshold |
|---|---|---|
| Trace completeness | Up | >95 percent agent runs have required fields |
| Direct subagent subprocess count | Down | 0 outside broker tests |
| Policy bypass test failures | Down | 0 |
| Duplicate context ratio | Down | baseline first, then -25 percent |
| Confidence calibration error | Down | baseline first; no enforcement before calibration |
| Low-relevance artifact promotion | Down | 0 promoted to final output by default |
| Context insufficiency escalations | Visible | baseline first; trend should explain blocked runs |
| Conflict rate | Down | baseline first; use as decomposition-quality signal |
| Cost per verified benchmark success | Down | baseline first |
| p95 workflow latency | Stable/down | no >20 percent regression without reason |
| Retry-loop incidents | Down | 0 uncapped retries |
| Human approval repeats | Down | no duplicate prompt for same operation |
| Benchmark verified success | Up/stable | no regression against baseline |
| Failed run explainability | Up | every failed run has failure class + next action |
| Operator attention load | Down | fewer unexplained failures and duplicate prompts |

## Suggested Sprint Breakdown

| Sprint | Focus | Deliverable |
|---|---|---|
| 1 | Agent run records | Traceable orchestrator/dispatcher/subagent execution |
| 2 | Typed task adapter | `TaskSpec` behind current decomposition |
| 3 | Route telemetry | Model route logs and counters, behavior unchanged |
| 4 | Broker skeleton | Broker interface and first git/research migration |
| 5 | Broker hardening | Remove remaining direct subagent subprocess paths |
| 6 | Context manifest MVP | Manifest ids, digest summaries, token estimates |
| 7 | Benchmark harness | First deterministic agent scenarios |
| 8 | Behavioral telemetry gates | Confidence/relevance/context-insufficiency metrics |
| 9 | Regression gates | CI-safe benchmark, behavioral telemetry, and bypass tests |
| 10-11 | Durable records | Runs/nodes/artifacts append-only state |
| 12-13 | Minimal scheduler | Ready-node execution, leases, capped retries |
| 14 | Verifier nodes | Independent verification and failure classes |
| 15 | Conflict/adjudication | Write-set and patch conflict handling |

## Final Priority Recommendation

Do these seven capabilities before touching durable DAG scheduling:

1. agent run observability;
2. typed task contracts;
3. route decision telemetry;
4. mediated subagent tools;
5. context manifests;
6. benchmark harness;
7. behavioral telemetry calibration.

That sequence is boring in the right way. It converts the current agent layer from a promising
demo surface into something measurable, debuggable, and safer. Only then is it worth paying the
complexity cost of durable DAGs, verification gates, and controlled parallel mutation.
