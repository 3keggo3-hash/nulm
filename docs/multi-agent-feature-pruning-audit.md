# Multi-Agent Feature Surface Pruning Audit

Date: 2026-05-20
Status: Phase 0.5 audit

This audit classifies the current multi-agent and agent-adjacent feature surface before runtime
expansion. Phase 0.5 does not delete implementation code. Items may be hidden from the default
profile, kept in `full`, deprecated with a removal window, or carried as deferred work until
observability and compatibility data exist.

## Classification Rules

| Class | Meaning |
|---|---|
| Keep | Directly serves the multi-agent runtime target and is safe enough for the current surface |
| Rework | The idea is useful, but contracts, safety, routing, or implementation need tightening |
| Hide | Too experimental, noisy, costly, or broad for the default profile |
| Deprecate | Public/API impact requires documentation and a compatibility window before removal |
| Remove later | Candidate for deletion only after measurement and compatibility evidence |

## Decision Table

| Surface | Classification | Default profile action | Rationale | Follow-up phase |
|---|---|---|---|---|
| `run_council_session` | Keep, gated | Hidden from `standard`; available in `full` | Useful as an advisory decision gate, but high-noise and not part of the default execution path | Phase 3 route telemetry, later explicit gates |
| Adaptive proposals | Rework/Hide | Keep proposal-only and full-profile scoped | Should stay shadow/advisory; no automatic behavior until benchmarks and traces exist | Phase 6 gates |
| `run_skill` | Hide | Keep in `full` only | Skill execution is powerful and should not become default runtime behavior | Phase 4 broker and later policy envelope |
| `meta_agent_server` | Hide/Rework | Keep out of `standard` | Broad behavior overlaps future typed runtime without strong contracts | Phase 2 contracts |
| `agents/messaging.py` | Rework/Hide | Treat as experimental/test-only | In-memory, short-TTL messaging is not durable enough for runtime coordination | Phase 7 durable records |
| `agents/shared_memory.py` | Rework/Remove later | Keep compatibility, plan replacement | Flat shared memory should evolve into context manifests and a typed blackboard | Phase 5 context manifest |
| `workflow_engine.py` | Keep/Rework | Preserve compatibility facade | Existing workflow behavior should not be deleted while durable DAG records are designed | Phase 7 compatibility |
| `VerificationAgent` | Keep/Rework | Preserve implementation | Current checks are shallow, but the role maps directly to verifier nodes | Phase 9 verifier MVP |
| URL and multi-format readers | Hide candidate | No code change in this pass | Useful but optional and token-heavy; defer standard-profile decision to compatibility review | Phase 0.5 follow-up |
| Git commit mutation | Hide | Keep in `full` | Mutation path should remain opt-in until broker and verifier gates exist | Phase 4 and Phase 9 |

## Deferred List

Keep these visible and out of scope until benchmark, trace, and safety gates are in place:

- Learned model router.
- Recursive delegation.
- Always-on council/debate.
- Autonomous skill installation/execution.
- Self-modifying prompts.
- Full A2A implementation.
- Remote SaaS control plane.
- Docker sandbox by default.
- Cross-project automatic memory sharing.
- Marketplace/auction routing.

## Phase 0.5 Exit Criteria

- Keep/Rework/Hide/Deprecate/Remove-later table exists: this document.
- Deferred list is visible and preserved.
- Default surface decision is explicit for the first high-noise item:
  `run_council_session` remains available in `full` and is no longer registered by `standard`.
