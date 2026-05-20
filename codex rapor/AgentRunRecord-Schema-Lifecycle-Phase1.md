# AgentRunRecord Schema and Lifecycle Design — Phase 1

**Date:** 2026-05-20
**Status:** Analysis Complete — Read-Only
**Constraints:** No autonomy, no DAG scheduler, no public MCP API change, schema versioned `agent_run.v1`

---

## 1. Minimal AgentRunRecord Schema

The existing schema (`run_record.py:29-46`) is already minimal and well-structured.

```python
AGENT_RUN_SCHEMA_VERSION = "agent_run.v1"

@dataclass
class AgentRunRecord:
    run_id: str                          # uuid.hex
    task_id: str                         # subtask identifier
    agent_name: str                      # e.g. "git_agent"
    task_kind: str                      # e.g. "git", "security"
    started_at: float                    # time.time() epoch
    ended_at: float | None = None
    status: str = "pending"             # running|success|partial|failure
    duration_ms: float | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    model_route: dict[str, Any] | None = None
    context_manifest_id: str | None = None
    artifact_ids: list[str] = field(default_factory=list)
    error_class: str | None = None
    error_message: str | None = None
```

**Assessment:** Schema is already lean. No additions required for Phase 1.

---

## 2. Lifecycle Events

| Event | Trigger | Status | Error Handling |
|-------|---------|--------|----------------|
| **start** | `start_agent_run()` — `AgentRunRecord` created, status=`"running"` | `running` | n/a |
| **success** | `finish_agent_run(record, result)` where `result.status == AgentStatus.SUCCESS` | `success` | no error_class set |
| **partial** | `finish_agent_run()` where `result.status == AgentStatus.PARTIAL` | `partial` | `error_class="AgentFailure"`, `error_message` set from `result.error` |
| **failure** | (a) `result.status == AgentStatus.FAILURE` (b) exception in `execute_subtask`/`execute_traced` → caught, `AgentResult.failure()` created, then `finish_agent_run()` | `failure` | `error_class=type(e).__name__` for exceptions; `error_class="AgentNotFound"` for missing agent |

**Status mapping to `AgentStatus` enum:**
- `AgentStatus.SUCCESS` → `"success"`
- `AgentStatus.PARTIAL` → `"partial"`
- `AgentStatus.FAILURE` → `"failure"`

**Existing code already implements this:**
- `dispatcher.py:78` — calls `finish_agent_run` on normal result
- `dispatcher.py:85-91` — handles exceptions

---

## 3. How Orchestrator and Dispatcher Emit Records

**Current flow** (already correct, no public behavior change):

```
OrchestratorAgent.execute(task)
  └─► dispatcher.distribute(subtasks, agents)
        └─► _start_run_record() → start_agent_run()
            └─► agent.execute(task, context)
                └─► finish_agent_run(record, result)
                    └─► log_agent_run_record(record) → audit JSONL
```

**Entry points** (no change needed):
- `TaskDispatcher.distribute()` — internal `_start_run_record()` → `start_agent_run()` → `finish_agent_run()` (`dispatcher.py:49-91`)
- `BaseAgent.execute_traced()` — calls `start_agent_run()` then `finish_agent_run()` (`base.py:46-64`)
- `TaskDispatcher.distribute_single()` — calls `agent.execute_traced()` which handles its own record (`dispatcher.py:130-137`)

**No public MCP tool changes required** — this is internal tracing infrastructure.

---

## 4. Error Class Taxonomy for v1

**Recommended v1 error classes** (aligned with existing patterns):

| Error Class | When Used |
|-------------|-----------|
| `AgentNotFound` | Dispatcher can't locate agent by name |
| `AgentFailure` | Agent returned `AgentStatus.FAILURE` or `PARTIAL` |
| `TaskTimeout` | Agent exceeded its `TaskBudget.timeout_seconds` |
| `PermissionDenied` | Agent tried tool outside `TaskPermissions.allowed_tools` |
| `ContextMissing` | Required context keys absent |
| `SynthesisFailure` | Orchestrator failed to merge results |

**Mapping from current ad-hoc usage:**
- `"AgentNotFound"` already exists (`dispatcher.py:64`)
- `"AgentFailure"` already used as fallback (`run_record.py:199`)
- `type(e).__name__` for caught exceptions (`base.py:61`, `dispatcher.py:88`)

**Where to define:** Create a new `src/claude_bridge/agents/errors.py` with constants, reused across `run_record.finish_agent_run()`, `dispatcher`, and `base`.

> **Note:** `detective.ErrorType` (SYNTAX/RUNTIME/SECURITY/NETWORK/UNKNOWN) is for error investigation, not agent run records — keep separate.

---

## 5. Serialization/Storage Recommendation

**Already compatible — use existing audit infrastructure:**

- Records written via `log_agent_run_record()` → `_append_audit_record()` → `~/.claude-bridge/audit/{session_id}.jsonl`
- Format: one JSON object per line, HMAC-signed with hash chain
- Key fields: `tool_name="agent_run"`, `agent_status`, `agent_error_class`, `agent_run` (nested full record)
- Index: `append_audit_index_record()` writes lightweight index to `session.index.jsonl`

**Recommendation:** Keep `agent_run.v1` schema nested in audit records as-is. No separate file needed. Ensure `error_class` values are consistent (use the v1 error class constants) rather than arbitrary exception names. HMAC/signature infrastructure already handles tamper detection.

---

## 6. Test Plan

### Unit Tests — `tests/agents/test_run_record.py`

| Test | Description |
|------|-------------|
| `test_start_agent_run_creates_running_record` | Verify status="running", timestamps set, run_id is valid hex |
| `test_finish_agent_run_maps_success_status` | Pass `AgentResult.success()`, verify status="success", no error_class |
| `test_finish_agent_run_maps_partial_status` | Pass `AgentResult(status=PARTIAL)`, verify error_class="AgentFailure" |
| `test_finish_agent_run_maps_failure_status` | Pass `AgentResult.failure()`, verify error_class="AgentFailure" |
| `test_finish_agent_run_exception_sets_error_class` | Call `finish_agent_run` with exception, verify `error_class=type(e).__name__` |
| `test_agent_run_record_to_dict_includes_schema_version` | Verify `"schema_version": "agent_run.v1"` in output |
| `test_compact_run_summary_aggregates_correctly` | Pass list of records, verify status_counts and total_duration_ms |
| `test_start_agent_run_unique_run_ids` | Call twice, verify different run_ids |

### Integration Tests — `tests/agents/test_dispatcher.py` / `test_orchestrator.py`

| Test | Description |
|------|-------------|
| `test_distribute_emits_run_records_for_each_subtask` | Dispatch subtasks, verify `dispatcher.run_records` length matches subtask count |
| `test_distribute_single_emits_record` | Call `distribute_single`, verify record created |
| `test_orchestrator_run_records_property_returns_latest` | Orchestrate, verify `orchestrator.run_records` accessible |

### Audit Integration Tests — `tests/audit/` (if exists)

| Test | Description |
|------|-------------|
| `test_log_agent_run_record_appends_to_audit_session` | Verify record written to audit JSONL |
| `test_finish_agent_run_with_error_class_audit_record` | Verify `agent_error_class` field in audit record |

---

## Summary

| Item | Status |
|------|--------|
| Schema | Already minimal (`agent_run.v1`), no changes needed |
| Lifecycle | Implemented via `start_agent_run`/`finish_agent_run`/`log_agent_run_record` |
| Orchestrator/Dispatcher emit | Already correct — no public API change |
| Error taxonomy | Ad-hoc — needs v1 constants in `agents/errors.py` |
| Serialization | Already JSONL + HMAC + hash chain via audit infrastructure |
| Tests | Need new test file `tests/agents/test_run_record.py` + integration tests |

---

## Recommended Phase 1 Implementation

1. Create `src/claude_bridge/agents/errors.py` with v1 error class constants
2. Update `finish_agent_run()` to use the new constants instead of raw strings
3. Add `tests/agents/test_run_record.py` with unit tests
4. Add integration tests for dispatcher and orchestrator record emission

**Constraints respected:** No new autonomy, no DAG scheduler, no public MCP API change, schema versioned `agent_run.v1`.
