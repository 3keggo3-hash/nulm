# Test Baseline Inventory Analysis

**Tarih:** 20 Mayıs 2026  
**Proje:** claude-bridge  
**Durum:** Tamamlandi

---

## Test File Categorization

| Category | Test Files | Count |
|---|---|---|
| Agent-related | tests/test_agents/test_base.py, test_debug_agent.py, test_dispatcher.py, test_git_agent.py, test_integration.py, test_orchestrator.py, test_permissions.py, test_research_agent.py, test_result.py, test_review_agent.py, test_security_agent.py, test_shared_memory.py, test_workflow_engine.py, tests/test_agent_advisor.py, tests/test_adaptive_council.py | 15 |
| Control-plane | tests/test_control_plane.py | 1 |
| Workflow | tests/test_workflow_engine.py, tests/test_parallel_workflow.py, tests/test_workflow_tools.py, tests/test_workflow_cache.py | 4 |
| Router | tests/test_ai_router.py | 1 |
| Benchmark | tests/test_benchmarking.py | 1 |
| Integration | tests/integration/test_credential_scopes.py, test_observability.py, test_observability_otel.py, test_prompt_injection.py, test_resilience.py, test_shell_velocity.py, test_tool_sanitization.py, test_workflow_skills.py | 8 |
| E2E | tests/e2e/test_full_workflow.py, tests/e2e/test_observability_e2e.py | 2 |

**Toplam test dosyasi sayisi:** 42

---

## Slow / Integration-Heavy / Flaky Tests

| Test File | Characteristics | Risk Level |
|---|---|---|
| tests/integration/test_shell_velocity.py | Threading tests, time.sleep() calls, rate limiting with timing windows | High (timing-dependent) |
| tests/integration/test_resilience.py | Async retry logic, circuit breaker with time.sleep(), distributed cache (Redis) | Medium (async timing) |
| tests/integration/test_credential_scopes.py | Threading tests, time.sleep() for TTL expiry, concurrent registration | Medium (timing-dependent) |
| tests/integration/test_observability_otel.py | Threading tests, concurrent span recording, singleton pattern | Medium (thread-safety) |
| tests/e2e/test_full_workflow.py | Full workflow with temp projects, async agent loop, concurrent operations | High (integration complexity) |
| tests/e2e/test_observability_e2e.py | E2E with audit trail setup | Medium (state setup) |
| tests/integration/test_prompt_injection.py | Large test file (413 lines), many regex patterns | Low (unit-like but large) |

---

## Test Gaps for New Components

| Component | Current Coverage | Gap Description |
|---|---|---|
| AgentRunRecord | Indirect via test_dispatcher.py (uses compact_run_summary) | No direct unit tests for AgentRunRecord dataclass, finish(), to_dict(), field validation, serialization edge cases |
| TaskSpec | Partial via test_dispatcher.py (2 tests: legacy adapter, typed spec acceptance) | Missing tests for TaskBudget.from_raw(), TaskPermissions.from_raw(), EvidenceRef, AgentArtifact, coerce_task_spec(), frozen dataclass immutability |
| ToolBroker | None (component not found in src) | Component does not exist yet - needs full test suite when implemented |
| ContextManifest | None (component not found in src) | Component does not exist yet - needs full test suite when implemented |

---

## Suggested Minimum Regression Commands (Phase 1-4)

| Phase | Command | Rationale |
|---|---|---|
| Phase 1 | pytest tests/test_agents/test_base.py tests/test_agents/test_dispatcher.py tests/test_agents/test_orchestrator.py -v | Core agent layer: base, dispatcher, orchestrator |
| Phase 1 | pytest tests/test_control_plane.py -v | Control-plane state management |
| Phase 2 | pytest tests/test_workflow_engine.py tests/test_parallel_workflow.py -v | Workflow execution engine |
| Phase 2 | pytest tests/test_ai_router.py tests/test_benchmarking.py -v | Router and benchmarking infrastructure |
| Phase 3 | pytest tests/integration/test_observability.py tests/integration/test_resilience.py -v | Core integration: observability, resilience patterns |
| Phase 3 | pytest tests/integration/test_shell_velocity.py -v | Rate limiting and velocity checks |
| Phase 4 | pytest tests/integration/ -m integration --timeout=300 | Full integration suite (with timeout) |
| Phase 4 | pytest tests/e2e/ -m e2e --timeout=300 | E2E workflows (with timeout) |

---

## Summary

- **Toplam test dosyasi:** 42 (32 agent/control-plane/workflow/router/benchmark + 10 integration/e2e)
- **Yuksek riskli testler:** 2 (shell_velocity, full_workflow e2e)
- **Orta riskli testler:** 4 (resilience, credential_scopes, observability_otel, observability_e2e)
- **Kritik test bosluklari:** ToolBroker ve ContextManifest mevcut degil; AgentRunRecord ve TaskSpec icin sadece dolayli test kapsami mevcut