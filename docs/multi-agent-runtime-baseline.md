# Multi-Agent Runtime Baseline

Date: 2026-05-20
Status: Phase 0 baseline

This baseline captures the current test reality before deeper multi-agent runtime changes. It is a
measurement artifact, not a coverage-improvement pass.

## Validation Snapshot

| Command | Result | Notes |
|---|---:|---|
| `pytest tests/test_agents` | 106 passed | Agent-layer regression subset |
| `pytest` | 2468 passed, 9 skipped in 83.10s | Full local suite on Python 3.14.5 |

## Agent Regression Commands

Use these as the minimum regression set before and after Phase 1 through Phase 4 changes:

- `pytest tests/test_agents`
- `pytest tests/test_config.py`
- `pytest tests/test_workflow_tools.py`
- `pytest tests/test_protocol.py`
- `pytest tests/test_shell_tools.py tests/test_security.py tests/test_policy_decisions.py`

Run the full suite before merging changes that touch tool registration, shell execution, guard
policy, or public MCP responses.

## Test Surface Notes

- Agent-layer tests live under `tests/test_agents` and currently cover orchestrator decomposition,
  dispatcher behavior, subagent result shapes, shared memory, permissions, and the legacy workflow
  engine adapter.
- The full suite has explicit `integration` and `e2e` markers, but no `slow` marker. Skipped tests
  are environment or optional-dependency dependent in the current run.
- `tests/conftest.py` sets `CLAUDE_BRIDGE_TOOL_PROFILE=full` for most in-process tests, so profile
  pruning must be verified with isolated subprocess profile tests in `tests/test_config.py`.
- Cache-sensitive areas include indexing, workflow cache, baseline/anomaly state, and audit/session
  records. Existing fixtures reset global state between tests; avoid xdist assumptions until the
  parallel-test isolation issue is closed.

## Phase 0 Exit Criteria

- Test baseline report exists: this document.
- Agent-layer minimum regression commands are listed above.
- Starting state is known: all current tests pass locally, with 9 skipped tests in the full suite.
