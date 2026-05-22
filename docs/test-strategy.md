# Test Strategy

## Test Layers

| Type | Location | Mark | When to use |
|------|----------|------|-------------|
| **Unit** | `tests/test_*.py` | none | Pure functions, no I/O, no server |
| **Integration** | `tests/integration/test_*.py` | `integration` marker | Cross-module, server calls, file I/O |
| **E2E** | `tests/e2e/test_*.py` | `e2e` marker | Full CLI, real MCP client flows |

## Marking Tests

```python
import pytest

@pytest.mark.integration
def test_cross_module(): ...

@pytest.mark.e2e
def test_full_flow(): ...
```

Run marked tests:
```bash
pytest -m integration tests/integration/
pytest -m e2e tests/e2e/
```

## Fixtures (`tests/conftest.py`)

- **`autouse=True` fixture `_reset_global_state`** — runs before every test; resets audit, config, cache, and process-session state for isolation. Do not use `_reset_global_state` directly; it is automatic.
- **`temp_project`** — creates a temp directory and sets it as `project_dir`; use for file/shell tool tests.
- **`temp_audit_project`** — like `temp_project` but also sets `CLAUDE_BRIDGE_AUDIT_DIR` and resets the audit session.

## Running Tests

```bash
pytest                          # all tests
pytest tests/test_control_plane.py           # single module
pytest tests/integration/ -m integration     # integration only
pytest tests/e2e/ -m e2e                     # e2e only
pytest tests/ -k "control_plane"             # by keyword
pytest tests/ --tb=short                      # short tracebacks
```

## Agent Benchmark Release Gates

Phase 6 agent release gates convert the deterministic agent benchmark into a local pass/fail
payload. Run them from Python:

```bash
python3 -c "\
from claude_bridge.agents.benchmark_gates import evaluate_agent_benchmark_gates; \
print(evaluate_agent_benchmark_gates().to_json())"
```

The gate checks benchmark success, trace completeness, context-manifest presence for context
scenarios, route telemetry, expected fallback counts, broker denial behavior, direct subprocess
bypass absence, and duplicate context ratio. The MVP intentionally does not add DAG scheduling,
verifier/adjudication nodes, recursive delegation, learned routing, provider requirements, or
historical baseline comparison. JSON is only written when `save_json(path)` is called explicitly.

## Naming Conventions

- **Files**: `test_<module>.py` (unit), `test_<feature>.py` (integration/e2e)
- **Functions**: `test_<what>_<expected_behavior>`
- **Fixtures**: descriptive names without `test_` prefix

## Writing New Tests

1. Place unit tests alongside source in `tests/test_<module>.py`
2. Place integration tests in `tests/integration/test_<feature>.py`
3. Use `temp_project` for tests that modify files or call shell tools
4. Use `monkeypatch` to isolate env vars and config; avoid modifying global state manually
5. Async tests use `async def test_...`; pytest handles them via pytest-asyncio
