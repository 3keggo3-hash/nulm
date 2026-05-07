# Overnight Autopilot Plan

This plan defines low-risk, low-usage autonomous work slices for overnight runs.

## Goals

- Keep weekly model usage controlled.
- Avoid risky refactors while unattended.
- Produce meaningful progress with clear morning handoff.

## Operating Constraints

- Prefer documentation consistency, small test hardening, and narrow bug fixes.
- One batch contains 3-5 tiny tasks, then one commit and one push.
- If a batch creates no tracked diff, skip commit/push and move to the next slice.
- No interactive or destructive commands.
- Skip large scans unless a task requires them.

## Execution Phases

### Phase 1: Documentation Consistency

- Normalize references to archived documents under `archive/`.
- Keep `docs/README.md` aligned with actual canonical vs historical files.
- Remove stale pointers and replace with source-of-truth references.

Validation:
- `rg` for known stale filenames.
- Optional: focused `ruff check` if Python files are touched.

### Phase 2: Low-Risk Test and Message Polish

- Tighten wording in CLI/help text where ambiguity is found.
- Add or refine narrow tests for touched behavior only.
- Prefer existing test modules and fixtures.

Validation:
- Run only directly related tests.

### Phase 3: Security and Policy Doc Hygiene

- Ensure security model and policy workflow docs reference current behavior.
- Clarify approval-flow language when needed without changing behavior.

Validation:
- Spot-check linked docs and command examples.

### Phase 4: Morning Handoff

- Summarize completed batches.
- List untouched high-risk items deferred for attended sessions.
- Include exact commit SHAs and validations run.

## Stop Conditions

- Stop after any unexpected state change in tracked files.
- Stop if a task needs architecture-level decision or broad refactor.
- Stop if validation indicates behavior risk outside the current slice.
- Delete or pause the heartbeat automation when overnight scope is completed.
