# Feature Implementation Plans — Claude Bridge

Generated via 5-agent debate teams. Each plan is consensus across security, implementation, UX, and scope experts.

---

## Plan 1: Shell Hard-Deny Bypass Gap Fix

**Status:** READY FOR IMPLEMENTATION
**Priority:** HIGH (security)

### Problem Statement
Skill execution via `exec(compile(code))` in `skill_executor.py:192` bypasses all shell hard-deny patterns (`_BLOCKED_DIRECT_COMMANDS`, `_BLOCKED_PIPE_TARGETS`) defined in `_shell_safety.py:398-414`. A skill with `permissions=["execute"]` can call `os.system("sudo rm -rf /")` with no interception.

### Agreed Solution Approach

1. **Pre-execution static scan**: Add `check_skill_code_safety()` using existing `blocked_command_reason()` pattern-matching — scan skill code before `exec()` runs, block hard-deny shell patterns
2. **Layered defense**: Keep `_RISKY_CODE_MARKERS` (import-time warnings in `skill_marketplace.py:18-28`) + new hard-deny enforcement at execution time — different moments, complementary
3. **Natural chokepoint**: Execution wrapper at `skill_executor.py:175-200` is the call site — scan after `skill_code = loaded.code` (around line 112), before writing temp file
4. **Preserve trust model**: Skills with `execute` permission can still run arbitrary Python; only shell hard-deny patterns (`sudo`, `chmod`, `rm -rf`, etc.) are blocked — closes bypass without changing permission model
5. **Clear error + audit**: Blocked skills return `status="denied"` with reason referencing the exact pattern category; logged in audit trail

### New Function Location
- `src/claude_bridge/_shell_safety.py` — add `_check_skill_code_blocked()` near existing `_BLOCKED_MATCHERS`
- Calls `_BLOCKED_DIRECT_COMMANDS` and `_BLOCKED_PIPE_TARGETS` from `_shell_constants.py`

### Integration Point
- `src/claude_bridge/skill_executor.py` — call after `skill_code = loaded.code` (~line 112), before `exec()`

### New Test Cases
| Test | Purpose |
|------|---------|
| `test_skill_hard_deny_blocks_sudo_subprocess` | `subprocess.run(["sudo", "rm", "-rf", "/"])` blocked at execution |
| `test_skill_hard_deny_blocks_os_system` | `os.system("sudo rm -rf /")` blocked at execution |
| `test_skill_hard_deny_blocks_chmod` | `subprocess.run(["chmod", "777", "/etc"])` blocked |
| `test_skill_hard_deny_allows_safe_subprocess` | `subprocess.run(["git", "status"])` runs successfully |
| `test_skill_execute_permission_preserved` | Skill with `execute` permission but no dangerous calls works normally |
| `test_skill_hard_deny_returns_clear_error` | Blocked skill returns status="denied" with reason |
| `test_skill_hard_deny_audit_logged` | Blocked attempt appears in audit log |

### Backward Compatibility
- Skills that run safe Python (no hard-deny shell patterns) are unaffected
- `skill_marketplace.py` import-time risk scoring already flags `subprocess` + `execute` as medium/high risk — no behavior change there
- Hard-denied patterns apply only at execution time; skill metadata/schema unchanged

### Deferred Items
- Runtime OS-level sandboxing (containers, seccomp, ulimit) — future work, not v1 scope
- Override path for legitimate privileged commands — `approve --temporary` CLI — deferred to v1.1

---

## Plan 2: Skill Recommendation Telemetry

**Status:** READY FOR IMPLEMENTATION
**Priority:** MEDIUM

### Problem Statement
Skill `recommend()` ranks by static text matching only (trigger=10pts, tag=3pts, description=1-5pts). No account for actual usage success, recency, or acceptance rate — recommendations don't improve based on empirical performance.

### Agreed Solution Approach

1. **Telemetry fields in LoadedSkill** (not SkillMeta — persists per-install, not in published JSON schema): `acceptance_count` (int, default 0), `rejection_count` (int, default 0), `last_accepted` (str | None, default None)
2. **Scoring formula** in `skill_registry.py:recommend()` — additive boost (not multiplicative to avoid popularity dominance): `base_score + telemetry_boost`
3. **Recency decay**: exponential window (last 30 days); skills with <3 total hits get no boost (cold-start guard)
4. **No automatic scoring until 3+ data points** — preserves current behavior for new/skipped skills
5. **Persistence**: telemetry written to `index.json` alongside metadata on `record_hit()` — single write, no separate store

### New Fields (in LoadedSkill / index.json)

| Field | Type | Default |
|-------|------|---------|
| `acceptance_count` | `int` | `0` |
| `rejection_count` | `int` | `0` |
| `last_accepted` | `str \| None` | `None` |

Existing fields already present: `hit_count`, `last_used`

### Implementation Locations

| Change | File | Approx Line |
|--------|------|-------------|
| New fields in `LoadedSkill.__init__` | `skill_registry.py` | ~25 |
| `record_outcome(skill_name, accepted)` method | `skill_registry.py` | ~312 (new method) |
| `telemetry_boost()` private method | `skill_registry.py` | ~265 (new method) |
| Scoring integration in `recommend()` | `skill_registry.py` | ~218 |
| Persistence on record_hit/update | `skill_registry.py` | `_save_index` ~96 |

### Scoring Formula Detail
```python
def _telemetry_boost(self, meta: LoadedSkill) -> tuple[int, list[str]]:
    total = meta.acceptance_count + meta.rejection_count
    if total < 3:
        return 0, []
    acceptance_rate = meta.acceptance_count / total
    recency = self._recency_factor(meta.last_accepted)  # 0.0-1.0
    boost = int(acceptance_rate * 5) + int(recency * 3)  # max ~8 pts
    reasons = [f"acceptance_rate={acceptance_rate:.0%}", f"recency={recency:.1f}"]
    return min(boost, 8), reasons
```

### New Test Cases
| Test | Purpose |
|------|---------|
| `test_telemetry_boost_applied_when_enough_data` | Skill with 3+ hits and acceptance rate gets boosted above text-matched rival |
| `test_telemetry_no_boost_cold_start` | Skill with 2 hits gets no boost even if acceptance 100% |
| `test_telemetry_rejection_penalty` | Skill with 50% acceptance gets smaller boost than 90% acceptance |
| `test_telemetry_recency_decay` | Old accepted skill without recent activity gets minimal/no boost |
| `test_telemetry_backward_compat` | Existing skill JSON without new fields loads and scores correctly |
| `test_telemetry_record_outcome` | Recording accept/reject updates counters correctly |
| `test_telemetry_last_accepted` | last_accepted timestamp updated on acceptance |

### Backward Compatibility
- Existing skill JSON files do not need migration — missing telemetry fields default to 0/None
- `recommend()` checks `hit_count < 3` before applying any telemetry boost — pure deterministic behavior for new/skills without history
- `index.json` schema is additive — old entries readable, new fields ignored if absent

### Deferred Items
- `avg_latency_ms`, `context_affinity` heat map — deferred to v1.2
- Cross-device sync of telemetry — explicitly out of scope (local-only by design)
- Interactive exploration mode — v2 discussion

---

## Plan 3: Workflow Preview

**Status:** READY FOR IMPLEMENTATION
**Priority:** MEDIUM

### Problem Statement
Users running `claude-bridge workflow` have no way to see the rendered prompt before committing to execution — trial-and-error runs waste time and token budget.

### Agreed Solution Approach

1. **New `preview_workflow()` function in `workflow_presets.py`** — returns dict with resolved prompt + metadata; read-only, no execution
2. **New CLI command**: `claude-bridge workflow preview --mode <mode> --target <path> [--option <str>] [--language <str>]`
3. **V1 scope**: resolved prompt text + token estimate only; context/file list and validation commands deferred to v1.5
4. **Rich terminal output** using existing Rich library — mode, target, focus, resolved prompt, token estimate in visual hierarchy
5. **Integration**: CLI wraps `preview_workflow()` directly; MCP tool wraps same function for programmatic access

### New CLI Command Signature
```bash
claude-bridge workflow preview --mode <mode> --target <path> [--option <str>] [--language <str>] [--json]
```

### New Function Location
- `src/claude_bridge/workflow_presets.py` — add `preview_workflow()` function near existing `workflow_prompt()`

### V1 vs Deferred
| Feature | V1? |
|---------|-----|
| Resolved prompt text | YES |
| Token estimate | YES |
| Steps summary | YES |
| Context file list | NO (deferred v1.5) |
| Validation command list | NO (deferred v1.5) |
| Interactive parameter editing | NO (deferred v2) |
| Adjacent mode hints | NO (deferred v2) |

### New Test Cases
| Test | Purpose |
|------|---------|
| `test_workflow_preview_renders_prompt` | Preview returns resolved prompt text |
| `test_workflow_preview_token_estimate` | Token estimate is reasonable (word_count * 1.3 ± 20%) |
| `test_workflow_preview_invalid_mode` | Invalid mode returns error with valid modes listed |
| `test_workflow_preview_json_flag` | `--json` flag returns machine-readable output |

### Backward Compatibility
- No existing behavior changed — `workflow_preview` is net-new functionality
- No changes to `run_workflow`, `workflow_engine`, or any existing tool schema

---

## Implementation Order Recommendation

1. **Plan 1 (Shell Hard-Deny Fix)** — SECURITY — implement first, standalone
2. **Plan 3 (Workflow Preview)** — LOW RISK, HIGH VISIBILITY — implement second, no dependencies
3. **Plan 2 (Skill Telemetry)** — MEDIUM COMPLEXITY — implement third

No cross-feature dependencies. Each plan is self-contained.

---

## Agent Teams Used

| Feature | Architect | Impl | Skeptic | UX/Scope | Facilitator |
|---------|-----------|------|---------|----------|-------------|
| Shell Gap Fix | Security Architect | Implementation Engineer | Skeptic | UX/Policy Expert | Facilitator |
| Skill Telemetry | Product Architect | Implementation Engineer | Skeptic | Data Model Expert | Facilitator |
| Workflow Preview | Product Architect | Implementation Engineer | Scope Expert | UX Expert | Facilitator |

All 15 agents reached mediated consensus. No unresolved conflicts.