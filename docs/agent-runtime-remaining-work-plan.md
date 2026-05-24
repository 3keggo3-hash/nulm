# Agent Runtime Remaining Work Plan

Date: 2026-05-24
Status: Implementation blueprint
Scope: Remaining multi-agent runtime work after the v0.1.2 release-readiness pass

This document turns the unfinished parts of `docs/multi-agent-execution-roadmap.md` into an
implementation plan. It is intentionally practical: small steps, clear ownership boundaries,
explicit tests, and no new autonomy until the runtime can observe and recover from its own work.

## Current Baseline

Already implemented on `main`:

- `AgentRunRecord` telemetry for dispatcher/orchestrator-visible execution.
- `TaskSpec`, `TaskBudget`, `TaskPermissions`, `AgentArtifact`, and `EvidenceRef`.
- Route decision telemetry for model/provider routing.
- `AgentToolBroker` for mediated subagent tool access.
- `ContextManifest` and budget/duplicate-context measurements.
- Deterministic agent benchmark harness and release gates.
- Durable DAG record schemas and append-only `AgentDagStore`.

Important limitation: durable DAG records are only a reconstruction layer today. They do not yet
schedule work, lease work, enforce dependency order, retry nodes, or adjudicate conflicts.

## Work That Is Still Not Done

| Area | Status | Size | Risk |
|---|---|---:|---:|
| Typed contract cleanup | Partial | Small | Low |
| `MissionBrief` / context curator | Not started | Medium | Low-medium |
| DAG record hardening | Partial | Small-medium | Medium |
| Minimal DAG scheduler | Not started | Large | Medium-high |
| Mutating-node write-set guard | Not started | Medium | Medium |
| Verifier node MVP | Not started | Medium-large | Medium |
| Conflict detection/adjudication | Not started | Medium-large | Medium |
| Behavioral enforcement | Not started | Large | High |

Do not start with behavioral enforcement. It depends on benchmark calibration and verifier
evidence. Starting there would create orchestration theater: more knobs, more traces, and worse
debuggability.

## Execution Order

The order matters.

1. Finish typed contract cleanup.
2. Add `MissionBrief` records and a deterministic context curator.
3. Harden DAG records without scheduling.
4. Add a read-only scheduler MVP.
5. Add write-set locks for mutating nodes.
6. Add verifier nodes.
7. Add conflict detection.
8. Add adjudication only after detection is stable.
9. Add limited behavioral enforcement.

## Phase A: Typed Contract Cleanup

Goal: make the roadmap and code agree before adding a new orchestration layer.

### Tasks

- Add the missing behavioral fields to `TaskSpec`:
  - `question`;
  - `acceptance_criteria`;
  - `escalation_policy`;
  - `allowed_failure_classes`;
  - `expected_evidence`.
- Update `TaskSpec.from_legacy_dict()` to round-trip these fields.
- Update `TaskSpec.to_legacy_context()` to expose only safe compatibility fields.
- Keep old callers working. No required new fields.
- Update roadmap status from "in progress" to "implemented" only after tests pass.

### Files

- `src/claude_bridge/agents/contracts.py`
- `tests/test_agents/test_contracts.py`
- `docs/multi-agent-execution-roadmap.md`

### Tests

- Legacy task dict without new fields still works.
- Typed task with behavioral fields round-trips.
- Invalid behavioral fields fail closed or coerce safely.
- Dispatcher still accepts old `{"id", "task", "agent_name"}` dictionaries.

### Exit Criteria

- Public APIs do not break.
- `TaskSpec` is the single internal contract boundary.
- Roadmap status matches implementation.

Estimated effort: 1-2 days.

## Phase B: MissionBrief / Context Curator MVP

Goal: give every subagent a compact, auditable brief without creating a second planner.

This is the "smart second agent" idea, but constrained. The component may package context. It must
not decide what work exists, alter the task, grant permissions, or replan the DAG.

### Data Model

Add a typed artifact similar to:

```python
@dataclass(frozen=True)
class MissionBrief:
    brief_id: str
    task_id: str
    agent_name: str
    context_manifest_id: str
    objective: str
    question: str
    must_know: tuple[str, ...]
    allowed_scope: tuple[str, ...]
    non_goals: tuple[str, ...]
    expected_artifacts: tuple[str, ...]
    escalation_triggers: tuple[str, ...]
    confidence_floor: float | None
    token_estimate: int
    source_reason: str
    omitted_context_reason: str
```

### Component

Add a deterministic `ContextCurator` first. Do not make it provider-backed in the MVP.

Responsibilities:

- consume `TaskSpec` + `ContextManifest`;
- produce `MissionBrief`;
- keep the task goal unchanged;
- keep read/write sets unchanged;
- keep permissions unchanged;
- emit an audit/run record reference.

Non-responsibilities:

- no new subtasks;
- no scheduler decisions;
- no tool permission decisions;
- no model routing decisions;
- no debate/council loop.

### Files

- New: `src/claude_bridge/agents/mission_brief.py`
- Update: `src/claude_bridge/agents/dispatcher.py`
- Update: `src/claude_bridge/agents/run_record.py`
- Update: `src/claude_bridge/agents/benchmark_harness.py`
- New: `tests/test_agents/test_mission_brief.py`

### Dispatcher Integration

Dispatcher context should include:

```python
context = {
    "subtask": subtask,
    "context_manifest": manifest,
    "mission_brief": brief,
    "mission_brief_id": brief.brief_id,
}
```

`AgentRunRecord` should store `mission_brief_id`.

### Benchmarks

Add at least one deterministic scenario:

- task has two candidate files;
- context manifest selects both;
- mission brief includes only the relevant allowed scope;
- benchmark verifies irrelevant context is not promoted into the brief.

### Exit Criteria

- Every dispatcher-managed subagent can answer: "what exactly was I told?"
- Brief reconstruction does not require replaying model reasoning.
- A brief cannot change `TaskSpec.goal`, dependencies, read/write sets, or permissions.
- Benchmark proves at least one irrelevant-context filtering case.

Estimated effort: 2-4 days.

## Phase C: DAG Record Hardening

Goal: make durable records ready for scheduling without introducing the scheduler yet.

### Tasks

- Add explicit record events for:
  - node ready;
  - node leased;
  - node running;
  - node completed;
  - node failed;
  - node blocked;
  - lease expired.
- Add helper methods on `AgentDagStore`:
  - `append_run_record`;
  - `append_node_record`;
  - `append_artifact_record`;
  - `append_conflict_record`;
  - `load_run_view`;
  - `list_nodes_for_run`;
  - `latest_node_records`.
- Add invariant checks in tests:
  - completed node cannot be reconstructed as running;
  - latest event wins;
  - invalid schema fails closed;
  - unknown node status is rejected.

### Files

- `src/claude_bridge/agents/dag_records.py`
- `src/claude_bridge/agents/dag_store.py`
- `tests/test_agents/test_dag_records.py`
- `tests/test_agents/test_dag_store.py`

### Non-goals

- No worker loop.
- No leases enforced by scheduler yet.
- No mutation execution.
- No automatic migration from control plane state.

### Exit Criteria

- A run can be reconstructed entirely from append-only records.
- Node latest-state materialization is deterministic.
- Existing dispatcher record-only integration still works.

Estimated effort: 1-3 days.

## Phase D: Minimal Read-Only DAG Scheduler

Goal: execute dependency-ordered read-only nodes using existing agents and durable records.

This is the first large runtime change. Keep it narrow.

### Scheduler MVP

Add `AgentDagScheduler` with:

- `run_once(run_id)`;
- `run_until_blocked(run_id, max_steps)`;
- conservative concurrency default: `1`;
- optional concurrency for read-only nodes only;
- ready-node selection by dependency completion;
- failure class preservation;
- capped retry policy.

### Node Rules

Read-only node can run when:

- all dependencies are completed;
- status is `pending` or `ready`;
- lease is absent or expired;
- `TaskPermissions.allow_mutation` is false.

Node must not run when:

- dependency failed;
- dependency blocked;
- failure class is fatal;
- retry limit is reached;
- required agent is missing.

### Failure Classes

Use typed failure strings consistently:

- `agent_not_found`;
- `schema_failure`;
- `policy_failure`;
- `transient_error`;
- `context_insufficiency`;
- `validation_failure`;
- `unknown_failure`.

### Files

- New: `src/claude_bridge/agents/dag_scheduler.py`
- Update: `src/claude_bridge/agents/dag_records.py`
- Update: `src/claude_bridge/agents/dag_store.py`
- New: `tests/test_agents/test_dag_scheduler.py`

### Tests

- Node with no dependencies becomes ready and runs.
- Node waits for dependency.
- Node does not run after failed dependency.
- Missing agent fails with typed class.
- Retryable failure retries up to cap.
- Fatal failure does not retry.
- Process restart reconstruction does not rerun completed node.

### Exit Criteria

- Read-only DAG can complete from records.
- Failed node has typed failure class.
- No infinite retry loop.
- Scheduler does not mutate files.

Estimated effort: 1-2 weeks.

## Phase E: Mutating Node Write-Set Guard

Goal: allow mutating nodes only when write-set ownership is deterministic and safe.

Do not start with automatic patch merging. Start with locks and refusal.

### Rules

- Mutating node must declare a non-empty `write_set`.
- Mutating node must have explicit permission:
  - `TaskPermissions.allow_mutation=True`;
  - required tool in `allowed_tools`.
- Two mutating nodes with overlapping write sets cannot run concurrently.
- Read-only node may run beside mutation only if its read set does not overlap the mutation write
  set, unless stale reads are explicitly allowed.
- If write-set overlap is detected, create `AgentDagConflictRecord`.

### Files

- `src/claude_bridge/agents/dag_scheduler.py`
- `src/claude_bridge/agents/dag_records.py`
- `tests/test_agents/test_dag_scheduler.py`
- `tests/test_agents/test_dag_store.py`

### Tests

- Mutation without write set is rejected.
- Mutation without permission is rejected.
- Disjoint write sets can run with configured concurrency.
- Overlapping write sets are blocked and recorded.
- Conflict record includes run id, node ids, files, type, and signal.

### Exit Criteria

- Parallel workers cannot silently overwrite each other.
- Conflict is a first-class record, not an exception string.
- No automatic merge or adjudication yet.

Estimated effort: 4-7 days.

## Phase F: Verifier Node MVP

Goal: add independent verification without turning verification into a second executor.

Verifier nodes should consume artifacts and evidence. They should not mutate files.

### Verifier Contract

Verifier input:

- task id;
- artifact ids;
- acceptance criteria;
- expected evidence;
- relevant `MissionBrief`;
- test command output if available.

Verifier output:

- `verified`;
- `failure_class`;
- `evidence_refs`;
- `reason`;
- `next_action`: `pass`, `retry`, `block`, `ask_user`.

### Implementation

Start deterministic:

- schema checks;
- artifact presence checks;
- acceptance criteria string checks;
- optional test result checks.

Provider-backed verification can come later behind a flag.

### Files

- Existing: `src/claude_bridge/agents/sub/verification_agent.py`
- New or update: `src/claude_bridge/agents/verifier.py`
- Update: `src/claude_bridge/agents/dag_scheduler.py`
- New: `tests/test_agents/test_verifier_nodes.py`

### Tests

- Verifier passes when required artifact exists.
- Verifier fails when required artifact missing.
- Verifier cannot mutate.
- Mutating DAG cannot be marked final success without verifier pass.
- Same verifier failure does not retry indefinitely.

### Exit Criteria

- Mutating DAG requires verifier pass before final success.
- Verifier output cites artifacts or evidence.
- Verifier failure is typed.

Estimated effort: 4-7 days.

## Phase G: Conflict Detection and Adjudication

Goal: detect conflicts first. Adjudicate later, deterministically.

### Detection MVP

Detect:

- overlapping declared write sets;
- overlapping patch hunks;
- task-boundary ambiguity when multiple nodes claim same file for different goals.

Record:

- `overlapping_write_set`;
- `overlapping_patch`;
- `task_boundary_ambiguity`.

### Adjudication MVP

Only after detection has benchmark coverage, add deterministic ordering:

1. passing tests;
2. verifier pass;
3. smaller diff;
4. lower-risk file set;
5. explicit user preference.

No LLM-based adjudication in the first implementation.

### Files

- New: `src/claude_bridge/agents/conflict_detector.py`
- Optional later: `src/claude_bridge/agents/adjudicator.py`
- `src/claude_bridge/agents/dag_records.py`
- `tests/test_agents/test_conflict_detector.py`
- `tests/test_agents/test_adjudicator.py`

### Tests

- Same file in two write sets produces conflict.
- Disjoint files do not conflict.
- Overlapping patch ranges produce conflict.
- Non-overlapping patch ranges do not conflict.
- Adjudication order is deterministic.

### Exit Criteria

- Conflicts cannot be silently merged.
- Conflict rate is measurable.
- Adjudication never hides rejected artifacts.

Estimated effort: 4-7 days for detection, 3-5 days for adjudication.

## Phase H: Behavioral Enforcement

Goal: turn telemetry into limited runtime decisions only after benchmarks show it helps.

This is high risk. Most systems get worse here by trusting weak confidence signals too early.

### Signals

- confidence score;
- grounding score;
- relevance score;
- context insufficiency;
- retry count;
- duplicate context ratio;
- low-relevance artifact promotion;
- verifier failure class.

### Allowed Enforcement, First Version

Safe:

- stop on schema failure;
- stop on policy failure;
- cap retries for same failure class;
- escalate context insufficiency;
- block low-relevance artifact promotion into final summary.

Unsafe at first:

- auto-replan from low confidence;
- learned thresholds;
- provider-backed confidence as hard truth;
- recursive delegation;
- always-on debate.

### Tests

- Same failure class cannot retry forever.
- Policy/schema failures stop.
- Context insufficiency escalates.
- Low-relevance artifacts remain audit-only by default.
- Confidence below threshold is logged but not enforced until explicitly enabled.

### Exit Criteria

- Enforcement reduces retry loops or bad promotions in benchmark scenarios.
- Operator sees fewer ambiguous failures, not more.
- Feature flag can disable enforcement.

Estimated effort: 1-2 weeks.

## Benchmark Additions

Add scenarios as phases land:

| Scenario | Phase |
|---|---|
| `mission_brief_filters_irrelevant_context` | B |
| `dag_readonly_dependency_order` | D |
| `dag_completed_node_not_rerun` | D |
| `dag_retry_cap_same_failure` | D |
| `dag_mutation_write_set_overlap_blocked` | E |
| `verifier_required_for_mutation_success` | F |
| `conflict_record_for_overlapping_patch` | G |
| `low_relevance_artifact_not_promoted` | H |

All scenarios must run without cloud provider keys.

## Suggested Sprint Plan

| Sprint | Work | Expected Result |
|---:|---|---|
| 1 | Typed cleanup + `MissionBrief` MVP | Subagents get auditable briefs |
| 2 | DAG record hardening | Durable state is scheduler-ready |
| 3 | Read-only scheduler | Dependency-ordered read-only DAGs run |
| 4 | Retry/failure hardening | No retry storms |
| 5 | Mutating write-set guard | Mutations are serialized or blocked |
| 6 | Verifier node MVP | Mutation success requires verification |
| 7 | Conflict detection | Overlaps become records |
| 8 | Limited enforcement | Fatal failures stop, context insufficiency escalates |

## Engineering Rules

- Do not weaken `shell_tools.py`, guard policy, path boundaries, or approval behavior.
- Do not add broad dependencies.
- Do not make provider-backed AI required.
- Do not build recursive delegation.
- Do not add always-on council/debate.
- Do not make the scheduler the only code path until compatibility tests exist.
- Every new runtime decision must have a record that explains it.

## Validation Commands

Run focused tests after each phase:

```bash
pytest tests/test_agents
python3 -m claude_bridge agent-benchmark --gates-only
ruff check src/claude_bridge/agents tests/test_agents
mypy src
```

Before release or main merge:

```bash
black --check .
ruff check .
mypy src
pytest
python3 -m build
python3 -m twine check dist/*
```

## Definition of Done

The remaining runtime work is done when:

- every subagent run has a `ContextManifest` and `MissionBrief`;
- read-only DAG nodes execute deterministically from durable records;
- mutating DAG nodes cannot overlap write sets silently;
- completed nodes are not rerun after restart;
- verifier nodes gate mutating DAG success;
- conflicts are recorded and visible;
- retry loops are capped by typed failure class;
- benchmark gates prove the behavior locally without provider keys;
- operator cognitive load goes down rather than up.

