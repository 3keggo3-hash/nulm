# Agent Quality Chat Flows

These examples show how a non-expert user can ask Claude Bridge for better software work without
writing a perfect engineering prompt. They describe current deterministic/local behavior: Bridge
can improve requests, critique plans, suggest context strategy, recommend safe config changes, add
quality workflow advice, and review result quality. It still relies on the MCP client and user
approval model for any mutating action.

Provider-backed advice is optional and not required for these flows. Hard denies, path boundaries,
secret handling, and approval rules remain separate from advisory output.
Current provider-response parsing is local and fail-safe: invalid or unsafe provider-shaped advice
falls back to deterministic guidance, and parse telemetry is visible in `bridge_status`.

## Public Readiness

Simple prompt:

```text
Bu projeyi public'e hazırla.
```

Bridge behavior:

- `improve_request` turns the request into a scoped release-readiness task.
- `advise_next_step` suggests docs, package metadata, tests, and release checks.
- `run_workflow(mode="quality", target=".")` exposes a quality-first plan with context and token
  strategy.
- `review_result_quality` can be used after changes to check docs drift, validation, and remaining
  risks.

Expected output:

- clarified goal and assumptions;
- first safe slice, usually docs and release metadata review;
- focused validation suggestions such as tests, lint, type checks, and build checks;
- a suggested next prompt for the next smallest release-readiness step.

Safety boundary:

- Publishing, package upload, credentials, and broad config changes are not applied silently.
- Any file edit or shell command still follows the normal approval and guard-policy path.

Operational example:

1. User says: `Use Claude Bridge to check whether this project is public-ready.`
2. Bridge calls: `tools_overview`, `bridge_status`, then `run_workflow(mode="quality", target=".")`.
3. User sees: a scoped release-readiness plan, key docs/files to inspect, validation commands, and
   a next prompt for the smallest safe release fix.
4. After changes, Bridge calls: `review_result_quality` with changed files and validation evidence.

## Professionalize Code

Simple prompt:

```text
Bu kodu daha profesyonel yap.
```

Bridge behavior:

- `improve_request` narrows the vague quality request into acceptance criteria.
- `plan_quality_review` flags broad refactors, missing tests, and risky scope.
- `run_workflow(mode="quality", target="src/")` makes the quality gate visible.
- Agent-loop sessions include advisory only at session start and handoff boundaries.

Expected output:

- a clarified quality target, such as readability, tests, structure, or maintainability;
- warnings if the request is too broad for one patch;
- context and token strategy for the smallest relevant files;
- a result quality checklist before accepting the work as done.

Safety boundary:

- Bridge should not mix unrelated refactors into the same slice.
- Mutating tools remain approval-gated, and destructive shell behavior remains blocked.

## Reduce Token Use

Simple prompt:

```text
Token çok gidiyor, azalt.
```

Bridge behavior:

- `advise_next_step` recommends a lower-cost context strategy.
- `suggest_bridge_config` can suggest safe settings such as a smaller tool profile or context
  budget.
- `apply_bridge_config_change` can apply only allowlisted chat-safe keys.
- Context tools such as `narrow_context` help keep file reads small.

Expected output:

- concrete context tactics such as relevance search before broad reads;
- safe config suggestions with reasons and approval requirements;
- notes about what can be deferred to a later pass;
- no request for secrets or private provider credentials.

Safety boundary:

- Chat-driven config cannot set secrets, widen allowed roots, relax hard denies, or expand
  auto-approval.
- Restricted settings should be changed only through explicit local configuration paths.

Operational example:

1. User says: `Token usage feels high; suggest safe Bridge settings.`
2. Bridge calls: `suggest_bridge_config`.
3. User sees: safe suggestions such as `context_budget_profile=low-cost` or
   `intent_compaction_enabled=true`, with restricted keys listed separately.
4. If accepted, Bridge calls: `apply_bridge_config_change` for one allowlisted key and returns a
   rollback hint.

## Fix A Bug

Simple prompt:

```text
Bu bug'ı çöz.
```

Bridge behavior:

- `advise_next_step` asks for reproduction details if the failure is unclear.
- `improve_request` turns the bug report into a narrow fix plan.
- `plan_quality_review` checks that validation is named before editing.
- `run_agent_loop_session` can run bounded inspect-patch-validate steps when explicit steps are
  provided.

Expected output:

- a request for the failing test, traceback, or reproduction if missing;
- likely files and tests to inspect first;
- validation commands that match the project type;
- session-level handoff advice after bounded loop execution.

Safety boundary:

- Bridge should inspect evidence before changing code.
- Shell validation remains allowlisted and guarded; patching remains controlled.

## Check Whether The Result Is Good

Simple prompt:

```text
Yaptığın iş kaliteli mi kontrol et.
```

Bridge behavior:

- `review_result_quality` reviews goal alignment, scope drift, validation, docs, security/config
  risk, token/context waste, and next small fixes.
- Executed `run_workflow` results include `agent_quality.suggested_next_prompt` based on execution
  summary.
- Quality-first workflow output includes a result quality gate checklist.

Expected output:

- a verdict such as pass with notes, needs follow-up, or needs clarification;
- validation gaps and docs drift risks when evidence is missing;
- concrete next small fixes instead of broad advice;
- a suggested next prompt shaped by success, failure, or missing validation.

Safety boundary:

- Result review is advisory and read-only.
- It cannot override guard policy, approve risky commands, or claim unverified behavior passed.

Operational example:

1. User says: `Review whether this completed change is actually good enough.`
2. Bridge calls: `review_result_quality` with the original goal, result summary, changed files, and
   validation commands.
3. User sees: `evidence_level`, goal alignment, validation gaps, docs/security risks, and next
   small fixes.
4. If validation is missing, the verdict should stay `needs_followup` even when the goal mentions
   tests or quality.
