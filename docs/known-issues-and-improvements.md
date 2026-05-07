# Known Issues and Improvement Plan

This document lists known gaps identified through code reviews and test analysis, along with proposed solutions.

---

## High Priority

### 1. Anomaly baseline runtime policy

**Current state:** Anomaly scoring and baseline-backed rules exist. Runtime behavior for v0.1 is
intentionally `warn_and_log`: scores are visible in audit/summary, but do not modify guard decisions.

**Open decision:**
- Should `ask` / `deny` enforcement thresholds be configurable in v0.2 or later?
- If enforcement is enabled, what audit detail and appeal flow must be mandatory?

**Affected files:** `src/claude_bridge/anomaly.py`, policy/guard integration tests

---

## Medium Priority

### 2. Global state lock inconsistency

**Current state:** `file_tools.py` uses `_LAST_BRIDGE_CHANGE` with `threading.Lock()`, `config.py`
uses `_CONFIG` with `threading.RLock()`. No coordination.

**Risk:** Race condition potential under multi-session usage.

**Proposed solution:**
- Create a single central lock module (`src/claude_bridge/state.py`)
- All global mutable state managed through this module
- Or: document that single-threaded MCP stdio flow makes this a non-issue in practice

**Affected files:** `src/claude_bridge/tool_utils.py` or new `state.py`

### 3. server.py God Object tendency

**Current state:** `server.py` ~1060 lines, all MCP tool registration in a single file.

**Proposed solution:**
- Split tools by category: `file_server.py`, `shell_server.py`, `meta_server.py`, `workflow_server.py`
- Each module registers its own tools on the `mcp` instance
- `server.py` contains only `mcp = FastMCP(...)` and `run_mcp_server()`

**Affected files:** `src/claude_bridge/server.py`, `src/claude_bridge/mcp_server.py`

### 4. Disk cache size quota

**Current state:** `_prune_workflow_disk_cache` only limits file count (64), not total size.

**Proposed solution:**
- Add total size limit for cache files (e.g., 50MB)
- Clean oldest files when quota exceeded
- Check on every cache write

**Affected files:** `src/claude_bridge/workflow_tools.py`

### 5. client_managed_approval real client contract

**Current state:** Server tool path is tested for `client_managed_approval=True` mode for write/shell.
This mode assumes the MCP client actually implements an approval UI.

**Remaining risk:** Not all MCP clients implement approval semantics identically.

**Proposed solution:**
- Keep README/security docs clear that this is a client contract
- Add manual smoke guide for non-Claude Desktop clients

---

## Low Priority

### 6. test_protocol.py size

**Current state:** 2118 lines, all MCP tool tests in a single file.

**Proposed solution:**
- Split by category: `test_file_tools.py`, `test_shell_tools.py`, `test_meta_tools.py`, `test_workflow_tools.py`
- Shared fixtures in `conftest.py`

### 7. Parallel test isolation

**Current state:** Global state (`mcp_server.set_config`) causes issues with parallel testing (pytest-xdist).

**Proposed solution:**
- Fixtures reset state after each test
- Or: document no-xdist policy

---

## Resolved / Partially Resolved

- **power-user auto_approve risk** → Partially resolved with audit logging
- **Python 3.8 annotations** → Closed by moving minimum to Python 3.10+
- **Missing async test decorator** → `asyncio_mode = "auto"` in pyproject.toml, no issue
- **Shell blocklist bypass vectors** → basename/full-path/env normalization and extended shell list added
- **Output truncation semantic integrity** → `TRUNCATED:` marker added when shell output is cut

---

## References

- Claude Code review (2026-04-29)
- `archive/competitive-analysis-desktopcommander.md`
- `docs/product-vision.md`
