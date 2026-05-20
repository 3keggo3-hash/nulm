# Feature Surface Pruning Table

Based on read-only analysis of council, adaptive proposals, skills, meta-agent tools, shared memory, messaging, workflow engine, verification agent, and model routing modules.

Feature/module	Current public surface	Keep/Rework/Hide/Deprecate/Remove-later	Reason	Risk	Tests/docs affected
Council (council.py, council_tool_server.py)	run_council_session MCP tool (read-only)	Keep	Core advisory feature, bounded (2-8 agents, 1-3 rounds), read-only, approval-gated output. No autonomy or recursion.	Low	test_council.py; docs: multi-agent-architecture-audit.md
Adaptive Council (adaptive_council.py, proposal_engine.py, proposal_tool_server.py)	accept_proposal, reject_proposal, list_pending_proposals, get_proposal_details MCP tools	Rework	Approval-gated proposal store for skill deactivation. Records decisions only (does not mutate skills). Requires real comparison evidence from skill-comparison layer. Could be simplified - proposal_engine.py has stub _create_comparison_report returning None.	Low	test_adaptive_council.py; docs: multi-agent-architecture-audit.md
Skills - Core (skill_registry.py, skill_schema.py, skill_tool_server.py)	list_skills, inspect_skill, recommend_skills, inspect_skill_package MCP tools	Keep	Skill discovery and inspection are read-only, well-tested. recommend_skills uses deterministic scoring with telemetry boost. Safe surface.	Low	test_skill_registry.py, test_skill_schema.py, test_skill_tool_server.py; docs: skill-discovery.md
Skills - Execution (skill_executor.py, skill_builder.py, skill_marketplace.py, skill_comparison.py)	run_skill MCP tool (destructive, policy-gated)	Rework	run_skill has policy gates via rules_engine.evaluate_runtime_policy_chain and approval checks. However, skill execution layer is complex with multiple modules. Could consolidate skill_builder/marketplace/comparison which have lighter test coverage.	Medium	test_skill_executor.py, test_skill_builder.py, test_skill_marketplace.py, test_skill_comparison.py
Meta-Agent Tools (meta_agent_server.py)	create_plan, execute_step, get_plan_status, explore_approaches, execute_approach, compare_approaches, self_critique, create_checkpoint, restore_checkpoint, list_checkpoints, reflect_on_recent_work, meta_review MCP tools	Rework	12 tools for P6 meta-agent orchestration. Checkpoint tools have approval gates. Surface is large but bounded (no recursion). Some overlap with workflow engine. Could consolidate checkpoint/plan/step tools.	Medium	test_agents/test_workflow_engine.py; docs: multi-agent-architecture-audit.md, multi-agent-execution-roadmap.md
Meta Tools (meta_tool_server.py)	nulm_assist, advise_next_step, improve_request, plan_quality_review, suggest_bridge_config, review_result_quality, apply_bridge_config_change, plus autocomplete, config, insights, smart, git, notes tools (~30+ tools total)	Rework	Massive surface (1888 lines). Mix of advisory (read-only) and config (destructive but approval-gated). Many tools overlap in purpose (advise_next_step, improve_request, plan_quality_review, review_result_quality). Autocomplete is decorative. Needs consolidation.	Medium	Tests scattered across test suite; docs: agent-quality-layer-plan.md, agent-quality-chat-flows.md
Shared Memory (memory.py, _memory_store.py, agents/shared_memory.py)	No direct MCP tools (internal infrastructure)	Keep	Three-layer encrypted memory (user profile, project memory, lessons learned). Internal infrastructure, no public MCP surface. Core runtime module.	Low	test_memory.py, test_agents/test_shared_memory.py
Messaging (agents/messaging.py)	No direct MCP tools (internal infrastructure)	Keep	In-memory pub/sub message bus for agent communication. Internal infrastructure, no public MCP surface. Core runtime module for agent coordination.	Low	No dedicated tests (used internally by agents)
Workflow Engine (workflow_engine.py, workflow_tool_server.py, workflow_agent_loop.py, workflow_runner.py, workflow_presets.py)	run_agent_loop_step, build_context_pack, narrow_context, suggest_validation_commands, run_agent_loop_session, run_workflow MCP tools	Keep	State machine for Plan->Approve->Apply->Test->Report flow. Well-tested, bounded execution. run_agent_loop_step and run_agent_loop_session are destructive but bounded (max_iterations). Core workflow orchestration.	Low	test_workflow_engine.py, test_workflow_tools.py, test_parallel_workflow.py, test_workflow_cache.py, e2e/test_full_workflow.py, integration/test_workflow_skills.py; docs: policy-pr-workflow.md
Verification Agent (agents/sub/verification_agent.py)	No direct MCP tools (internal agent)	Keep	Pre/post-change validation with dangerous pattern detection. Internal agent, no public MCP surface. Core safety module.	Low	No dedicated tests (used internally)
Model Routing (ai_router.py)	No direct MCP tools (internal infrastructure)	Keep	AI provider routing for advisory workflows. Internal infrastructure, no public MCP surface. Supports council and advisor tools. Core runtime module.	Low	test_ai_router.py
Summary
Keep (6 modules): Council, Skills-Core, Shared Memory, Messaging, Workflow Engine, Verification Agent, Model Routing

Rework (4 modules):

Adaptive Council: Simplify proposal_engine (stub comparison report)
Skills-Execution: Consolidate skill_builder/marketplace/comparison
Meta-Agent Tools: Consolidate checkpoint/plan/step tools (12 → ~6)
Meta Tools: Massive surface consolidation (~30 tools → ~10-12), remove decorative autocomplete
Hide (0 modules): None identified

Deprecate (0 modules): None identified

Remove-later (0 modules): None identified

Key Findings
No unsafe autonomy or recursion found - All features are bounded, approval-gated, or read-only
Core safety/runtime modules intact - Shared memory, messaging, verification, model routing are internal infrastructure
Meta tools surface is largest concern - 30+ tools in one file, significant overlap in advisory functions
Skills execution layer could consolidate - Multiple modules for builder/marketplace/comparison with lighter test coverage
Council and workflow engine are well-bounded - Read-only or approval-gated with clear limits
Recommended Action Plan
Phase 1 (Low risk): Rework meta_tool_server.py - consolidate overlapping advisory tools (advise_next_step, improve_request, plan_quality_review, review_result_quality), remove decorative autocomplete
Phase 2 (Low risk): Rework adaptive_council/proposal_engine - complete stub _create_comparison_report or simplify if not needed
Phase 3 (Medium risk): Consolidate skills execution layer - merge skill_builder/marketplace/comparison into tighter module
Phase 4 (Medium risk): Consolidate meta-agent tools - merge checkpoint/plan/step tools, reduce from 12 to ~6 tools
All changes should be test-backed and preserve existing MCP tool names (no renaming).
