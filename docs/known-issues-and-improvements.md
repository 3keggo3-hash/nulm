# Known Issues and Improvement Plan

This document lists known gaps identified through code reviews and test analysis, along with
proposed solutions. Product-direction work for the Agent Quality Layer lives in
`docs/agent-quality-layer-plan.md`; this file tracks technical gaps around the current runtime
substrate.

---

## High Priority

### 1. Feature evaluation and public surface pruning

**Current state:** Nulm has accumulated implemented tools, advisory Agent Quality
surfaces, optional extras, and planned product-direction language. Some features may be valuable
only in niche profiles, need clearer naming, or read stronger in docs than they are in the current
runtime.

**Principle:** No feature should exist just for show. Every public feature should be evaluated as
one of:

- **Keep** when it is implemented, useful, documented, and covered by focused tests.
- **Rework** when the idea is sound but behavior, naming, safety, or docs are not yet clear enough.
- **Hide** when it is experimental, niche, or too costly/noisy for the default tool profile.
- **Remove** when it duplicates better paths, is mostly decorative, or cannot be made safe and
  explainable.

**Open decision:**
- Which full-profile and Agent Quality tools should be hidden from default docs until they have
  stronger user workflows?
- Which roadmap/control-plane ideas need explicit "planned" labels to avoid implying hosted sync,
  mobile access, or remote monitoring exists today?

**Affected files:** `README.md`, `docs/*`, tool profile registration tests

---

### 2. Anomaly baseline runtime policy

**Current state:** Anomaly scoring and baseline-backed rules exist. Runtime behavior for v0.1
is intentionally `warn_and_log`: scores are visible in audit/summary, but do not modify guard
decisions.

**Open decision:**
- Should `ask` / `deny` enforcement thresholds be configurable in v0.2 or later?
- If enforcement is enabled, what audit detail and appeal flow must be mandatory?

**Affected files:** `src/claude_bridge/anomaly.py`, policy/guard integration tests

---

## Medium Priority

### 3. Global state lock inconsistency

**Current state:** `file_tools.py` uses `_LAST_BRIDGE_CHANGE` with `threading.Lock()`, `config.py`
uses `_CONFIG` with `threading.RLock()`. No coordination.

**Risk:** Race condition potential under multi-session usage.

**Proposed solution:**
- Create a single central lock module (`src/claude_bridge/state.py`)
- All global mutable state managed through this module
- Or: document that single-threaded MCP stdio flow makes this a non-issue in practice

**Affected files:** `src/claude_bridge/tool_utils.py` or new `state.py`

### 4. Remaining registration/module split work

**Current state:** `server.py` is smaller than the original single-file registration design and now
delegates many tool groups to focused `*_tool_server.py` modules. It still contains orchestration
glue, conditional imports, config handling, and some registration sequencing. The remaining
release-hardening pass keeps this stable: workflow registration now preserves public MCP function
names, and the standard tool profile includes the documented workflow and bounded agent-loop tools.

**Proposed solution:**
- Defer any larger split until there is a concrete ownership boundary.
- Keep lazy imports for heavier optional groups.
- Preserve tool-profile filtering and MCP public names.
- Do not split everything in one pass.

**Affected files:** `src/claude_bridge/server.py`, `src/claude_bridge/*_tool_server.py`

### 5. client_managed_approval real client contract

**Current state:** Server tool path is tested for `client_managed_approval=True` mode for
write/shell. This mode assumes the MCP client actually implements an approval UI.

**Remaining risk:** Not all MCP clients implement approval semantics identically.

**Proposed solution:**
- Keep README/security docs clear that this is a client contract
- Add manual smoke guide for non-Claude Desktop clients

---

## Low Priority

### 6. test_protocol.py size

**Current state:** 2788 lines, all MCP tool tests in a single file.

**Proposed solution:**
- Split by category: `test_file_tools.py`, `test_shell_tools.py`, `test_meta_tools.py`,
  `test_workflow_tools.py`
- Shared fixtures in `conftest.py`

### 7. Parallel test isolation

**Current state:** Global state (`mcp_server.set_config`) causes issues with parallel testing
(`pytest-xdist`).

**Proposed solution:**
- Fixtures reset state after each test
- Or: document no-xdist policy

---

## Resolved / Partially Resolved

- **power-user auto_approve risk** → Partially resolved with audit logging
- **Python 3.8 annotations** → Closed by moving minimum to Python 3.10+
- **Missing async test decorator** → `asyncio_mode = "auto"` in pyproject.toml, no issue
- **Shell blocklist bypass vectors** → basename/full-path/env normalization and extended shell
  list added
- **Output truncation semantic integrity** → `TRUNCATED:` marker added when shell output is cut
- **Disk cache size quota** → Indexing and workflow disk caches now prune by file count and total
  byte size.
- **Root skills directory ambiguity** → README now clarifies that repository-root `skills/`
  contains development/example skill specs and is not packaged as the runtime user skill registry.

---

## Related Documents

- Claude Code review (2026-04-29)
- `docs/product-vision.md`
- `docs/agent-quality-layer-plan.md`
- `docs/roadmap.md`
