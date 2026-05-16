"""
Orchestrator - runs directly in agent context with full tool access.
Spawns parallel subagents and manages iteration loop.
"""
import json
import time
import re
from datetime import datetime
from pathlib import Path
from typing import Any

OUTPUT_DIR = Path("/c/AIProjects/claude-bridge/output")
AGENTS_DIR = Path("/c/AIProjects/claude-bridge/agents/autonomous")
SRC_DIR = Path("/c/AIProjects/claude-bridge/src/claude_bridge")

DEADLINE_HOUR = 6
DEADLINE_MIN = 30


def get_deadline_seconds() -> int:
    now = datetime.now()
    deadline = now.replace(hour=DEADLINE_HOUR, minute=DEADLINE_MIN, second=0, microsecond=0)
    if deadline <= now:
        deadline = deadline.replace(day=deadline.day + 1)
    return int((deadline - now).total_seconds())


def save_output(name: str, data: Any):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = OUTPUT_DIR / f"{name}_{int(time.time())}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return filepath


def parse_json_safe(text: str) -> Any:
    """Extract JSON from text that may contain markdown or other content."""
    # Try to find JSON in the text
    json_match = re.search(r'\{[\s\S]*\}|\[[\s\S]*\]', text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def main():
    print(f"[Orchestrator] Starting at {datetime.now().strftime('%H:%M:%S')}")
    print(f"[Orchestrator] Deadline: {DEADLINE_HOUR}:{DEADLINE_MIN:02d} AM")
    remaining = get_deadline_seconds()
    print(f"[Orchestrator] Time remaining: {remaining // 3600}h {(remaining % 3600) // 60}m")

    context = {
        "round": 0,
        "all_features": [],
        "top_features": [],
        "research_results": {},
        "votes": {},
    }

    # === ROUND 1 ===
    print("\n[Orchestrator] === ROUND 1: Research & Brainstorm ===")
    context["round"] = 1

    # Phase 1a: Research (parallel 3 agents)
    print("\n[Orchestrator] Phase 1a: Spawning 3 research agents...")
    research_tasks = [
        {
            "goal": """You are Research Agent 1 - Competitor Analysis Specialist.
Research MCP server competitors and local AI agent tools. Find:
1. Top 5 competitors (Claude Code, Cline, Goose, Aider, Zed, etc.)
2. Their unique features
3. What makes them successful
4. Gaps they have

Focus on: Claude Code, Zed, Cline, Aider, Goose, Llmon, Tabby, Sourcegraph Cody.
Return a JSON object with keys: competitors (list of {name, features, strengths, gaps}), trends, inspiration.
Output as valid JSON only, no markdown code blocks.""",
            "role": "leaf",
            "toolsets": ["web", "terminal"],
        },
        {
            "goal": """You are Research Agent 2 - Security & Architecture Specialist.
Research security models in AI coding agents and MCP servers. Find:
1. How do top tools handle approval flows?
2. What security patterns work best?
3. How do they handle dangerous commands?
4. What audit approaches exist?

Focus on: permission systems, guardrails, approval gates, audit logging best practices.
Return a JSON object with keys: security_patterns (list of {pattern, how_it_works, effectiveness}), audit_approaches, inspiration.
Output as valid JSON only, no markdown code blocks.""",
            "role": "leaf",
            "toolsets": ["web", "terminal"],
        },
        {
            "goal": """You are Research Agent 3 - Autonomy & Agent Systems Specialist.
Research autonomous agent architectures and multi-agent systems. Find:
1. How do LangChain/LlamaIndex agents work?
2. What makes multi-agent orchestration effective?
3. Multi-agent orchestration patterns
4. Memory and context management approaches

Focus on: autonomous agents, multi-agent loops, memory systems, tool synthesis, self-improvement.
Return a JSON object with keys: agent_patterns (list of {pattern, description, pros, cons}), memory_approaches, orchestration_models.
Output as valid JSON only, no markdown code blocks.""",
            "role": "leaf",
            "toolsets": ["web", "terminal"],
        },
    ]

    research_results = delegate_task(tasks=research_tasks, toolsets=["delegation"])
    combined = {}
    for r in research_results:
        if isinstance(r, dict):
            if "competitors" in r:
                combined["competitor_analysis"] = r
            elif "security_patterns" in r:
                combined["security_analysis"] = r
            elif "agent_patterns" in r:
                combined["autonomy_analysis"] = r

    context["research_results"] = combined
    save_output("round_1_research", combined)
    print(f"[Orchestrator] Research complete: {len(combined)} sources")

    # Phase 1b: Feature brainstorm (parallel 3 agents)
    print("\n[Orchestrator] Phase 1b: Spawning 3 brainstorm agents...")

    competitor_features = combined.get("competitor_analysis", {}).get("competitors", [])
    security_patterns = combined.get("security_analysis", {}).get("security_patterns", [])
    agent_patterns = combined.get("autonomy_analysis", {}).get("agent_patterns", [])

    brainstorm_tasks = [
        {
            "goal": f"""You are Brainstorm Agent 1 - Security & Safety Focus.
Create 5-7 unique security/safety features for claude-bridge MCP server.
Base your ideas on: {str(competitor_features[:2])}
Security patterns inspiration: {str(security_patterns[:2])}

Each feature needs: name, description, inspiration, difficulty (easy/medium/hard), impact (low/medium/high).
Return as JSON array of feature objects. Output valid JSON only, no markdown.""",
            "role": "leaf",
            "toolsets": ["web", "terminal", "file"],
        },
        {
            "goal": f"""You are Brainstorm Agent 2 - Autonomy & Intelligence Focus.
Create 5-7 unique autonomous intelligence features for claude-bridge MCP server.
Agent patterns inspiration: {str(agent_patterns[:2])}

Each feature needs: name, description, inspiration, difficulty (easy/medium/hard), impact (low/medium/high).
Return as JSON array of feature objects. Output valid JSON only, no markdown.""",
            "role": "leaf",
            "toolsets": ["web", "terminal", "file"],
        },
        {
            "goal": f"""You are Brainstorm Agent 3 - Developer Experience & Performance Focus.
Create 5-7 unique developer experience or performance features for claude-bridge.
Competitor strengths: {str([c.get('strengths', []) for c in competitor_features[:2]])}

Each feature needs: name, description, inspiration, difficulty (easy/medium/hard), impact (low/medium/high).
Return as JSON array of feature objects. Output valid JSON only, no markdown.""",
            "role": "leaf",
            "toolsets": ["web", "terminal", "file"],
        },
    ]

    brainstorm_results = delegate_task(tasks=brainstorm_tasks, toolsets=["delegation"])
    all_features = []
    for r in brainstorm_results:
        if isinstance(r, list):
            all_features.extend(r)
        elif isinstance(r, dict) and "features" in r:
            all_features.extend(r["features"])

    # Deduplicate
    seen = set()
    unique_features = []
    for f in all_features:
        name = f.get("name", "") if isinstance(f, dict) else ""
        if name and name not in seen:
            seen.add(name)
            unique_features.append(f)

    for i, feat in enumerate(unique_features[:10]):
        save_output(f"round_1_features_agent{i+1}", feat)

    context["all_features"] = unique_features
    print(f"[Orchestrator] Generated {len(unique_features)} feature ideas")

    # Phase 1c: Evaluation (parallel 2 agents)
    print("\n[Orchestrator] Phase 1c: Spawning 2 evaluation agents...")

    features_str = str(unique_features[:15])
    eval_tasks = [
        {
            "goal": f"""You are Evaluation Agent 1 - Security & Safety Analyst.
Evaluate these features for claude-bridge. Score each 1-10 on:
- Security improvement
- Implementation difficulty (inverse: higher = easier)
- User impact
- Innovation

Features:
{features_str}

Return JSON with: scores (list of {{name, security, difficulty, impact, innovation, total}}), reasoning, recommended_order.
Output valid JSON only.""",
            "role": "leaf",
            "toolsets": ["web", "terminal", "file"],
        },
        {
            "goal": f"""You are Evaluation Agent 2 - Architecture & DX Analyst.
Evaluate these features for claude-bridge. Score each 1-10 on:
- Code quality improvement
- Performance impact
- Maintainability
- Developer experience

Features:
{features_str}

Return JSON with: scores (list of {{name, quality, performance, maintainability, dx, total}}), reasoning, risks.
Output valid JSON only.""",
            "role": "leaf",
            "toolsets": ["web", "terminal", "file"],
        },
    ]

    eval_results = delegate_task(tasks=eval_tasks, toolsets=["delegation"])

    all_votes = {}
    for r in eval_results:
        if isinstance(r, dict) and "scores" in r:
            for score in r["scores"]:
                name = score.get("name", "unknown")
                if name not in all_votes:
                    all_votes[name] = {"votes": [], "total": 0}
                all_votes[name]["votes"].append(score)
                all_votes[name]["total"] += score.get("total", 0)

    ranked = sorted(all_votes.items(), key=lambda x: x[1]["total"], reverse=True)
    top_features = []
    for name, _ in ranked[:10]:
        for f in unique_features:
            if isinstance(f, dict) and f.get("name") == name:
                top_features.append(f)
                break

    save_output("round_1_votes", {"votes": all_votes, "top": top_features})
    context["votes"].update(all_votes)
    context["top_features"] = top_features
    print(f"[Orchestrator] Top {len(top_features)} features from round 1")

    # === ROUND 2 ===
    print("\n[Orchestrator] === ROUND 2: Refinement ===")
    context["round"] = 2
    remaining = get_deadline_seconds()
    print(f"[Orchestrator] Time remaining: {remaining // 3600}h {(remaining % 3600) // 60}m")

    refine_tasks = [
        {
            "goal": f"""You are Refinement Agent 1.
Top features from previous round: {str(top_features[:5])}

For each feature: analyze strengths/weaknesses, suggest improvements, consider complexity.
Return refined versions as JSON array with original + refined fields.
Output valid JSON only.""",
            "role": "leaf",
            "toolsets": ["web", "terminal", "file"],
        },
        {
            "goal": f"""You are Creative Refinement Agent 2.
Top features: {str(top_features[:5])}

Think creatively about what ADDITIONAL features would complement these.
Consider: integration possibilities, pain points not addressed, next-level capabilities.
Suggest 3-5 NEW features that synergize with the top features.
Return as JSON array. Output valid JSON only.""",
            "role": "leaf",
            "toolsets": ["web", "terminal", "file"],
        },
    ]

    refine_results = delegate_task(tasks=refine_tasks, toolsets=["delegation"])
    refined_features = []
    for r in refine_results:
        if isinstance(r, list):
            refined_features.extend(r)
        elif isinstance(r, dict):
            if "features" in r:
                refined_features.extend(r["features"])
            elif "refined" in r:
                refined_features.extend(r["refined"])

    for f in refined_features:
        name = f.get("name", "") if isinstance(f, dict) else ""
        if name and name not in seen:
            seen.add(name)
            context["all_features"].append(f)

    for i, feat in enumerate(refined_features):
        save_output(f"round_2_refined_{i}", feat)
    print(f"[Orchestrator] Refined/generated {len(refined_features)} features")

    # Re-evaluate
    eval_tasks_r2 = [
        {
            "goal": f"""Re-evaluate all features. Score {str(context['all_features'][:15])} on security, difficulty, impact, innovation (1-10).
Return JSON: scores list with totals, top 5 recommendations.
Output valid JSON only.""",
            "role": "leaf",
            "toolsets": ["web", "terminal", "file"],
        },
        {
            "goal": f"""Re-evaluate all features. Score {str(context['all_features'][:15])} on quality, performance, maintainability, DX (1-10).
Return JSON: scores list with totals, top 5 recommendations.
Output valid JSON only.""",
            "role": "leaf",
            "toolsets": ["web", "terminal", "file"],
        },
    ]

    eval_r2 = delegate_task(tasks=eval_tasks_r2, toolsets=["delegation"])
    all_votes_r2 = {}
    for r in eval_r2:
        if isinstance(r, dict) and "scores" in r:
            for score in r["scores"]:
                name = score.get("name", "unknown")
                if name not in all_votes_r2:
                    all_votes_r2[name] = {"votes": [], "total": 0}
                all_votes_r2[name]["votes"].append(score)
                all_votes_r2[name]["total"] += score.get("total", 0)

    ranked_r2 = sorted(all_votes_r2.items(), key=lambda x: x[1]["total"], reverse=True)
    top_r2 = []
    for name, _ in ranked_r2[:8]:
        for f in context["all_features"]:
            if isinstance(f, dict) and f.get("name") == name:
                top_r2.append(f)
                break

    context["top_features"] = top_r2
    save_output("round_2_votes", {"votes": all_votes_r2, "top": top_r2})
    print(f"[Orchestrator] Top {len(top_r2)} features from round 2")

    # === ROUND 3: Final Polish ===
    print("\n[Orchestrator] === ROUND 3: Final Polish ===")
    context["round"] = 3
    remaining = get_deadline_seconds()
    print(f"[Orchestrator] Time remaining: {remaining // 3600}h {(remaining % 3600) // 60}m")

    final_tasks = [
        {
            "goal": f"""Final refinement pass on: {str(top_r2[:6])}
Add concrete implementation details, edge cases, API designs.
Return enhanced feature specs as JSON array.
Output valid JSON only.""",
            "role": "leaf",
            "toolsets": ["web", "terminal", "file"],
        },
    ]

    final_r = delegate_task(tasks=final_tasks, toolsets=["delegation"])
    for r in final_r:
        if isinstance(r, list):
            for f in r:
                name = f.get("name", "") if isinstance(f, dict) else ""
                if name and name not in seen:
                    seen.add(name)
                    context["all_features"].append(f)

    # Final vote
    final_eval = delegate_task(tasks=[{
        "goal": f"""Final vote on: {str(context['all_features'][:12])}
Score all on overall suitability (1-10).
Return JSON: scores list, final top 5 ordered by total.
Output valid JSON only.""",
        "role": "leaf",
        "toolsets": ["web", "terminal", "file"],
    }], toolsets=["delegation"])

    all_final_votes = {}
    for r in final_eval:
        if isinstance(r, dict) and "scores" in r:
            for score in r["scores"]:
                name = score.get("name", "unknown")
                if name not in all_final_votes:
                    all_final_votes[name] = 0
                all_final_votes[name] += score.get("total", 0)

    final_ranked = sorted(all_final_votes.items(), key=lambda x: x[1], reverse=True)
    final_top = []
    for name, _ in final_ranked[:5]:
        for f in context["all_features"]:
            if isinstance(f, dict) and f.get("name") == name:
                final_top.append(f)
                break

    context["top_features"] = final_top
    save_output("round_3_final_votes", {"votes": all_final_votes, "top": final_top})
    print(f"[Orchestrator] Final top {len(final_top)} features ready for implementation")

    # === QA PHASE ===
    print("\n[Orchestrator] === QA: Analysis ===")
    remaining = get_deadline_seconds()
    print(f"[Orchestrator] Time remaining: {remaining // 3600}h {(remaining % 3600) // 60}m")

    qa_tasks = [
        {
            "goal": """Analyze claude-bridge for errors and security issues.

Run these checks on /c/AIProjects/claude-bridge/src/claude_bridge:
1. Find syntax errors: python -m py_compile on key .py files
2. Find type errors: run 'mypy src' if available
3. Find security issues: look for injection points, path traversal risks
4. Find race conditions: check global mutable state

Return JSON: {syntax_errors: [], type_errors: [], security_issues: [], race_conditions: [], summary: "score X/10"}
Output valid JSON only.""",
            "role": "leaf",
            "toolsets": ["terminal", "file"],
        },
        {
            "goal": """Analyze claude-bridge for functionality and integration issues.

Check:
1. Import errors: python -c "import claude_bridge"
2. Inconsistent error handling patterns
3. Tool registration completeness
4. Test coverage gaps

Look in: /c/AIProjects/claude-bridge/src/claude_bridge and /c/AIProjects/claude-bridge/tests

Return JSON: {import_errors: [], inconsistent_patterns: [], tool_issues: [], missing_tests: [], summary: "score X/10"}
Output valid JSON only.""",
            "role": "leaf",
            "toolsets": ["terminal", "file"],
        },
        {
            "goal": """Analyze claude-bridge for code quality issues.

Check:
1. Run: ruff check src/ --output-format=json
2. Check for large functions (>100 lines) in server.py, cli.py, meta_tool_server.py
3. Find undocumented public APIs
4. Find dead code

Return JSON: {style_violations: [], complex_code: [], undocumented: [], dead_code: [], summary: "score X/10"}
Output valid JSON only.""",
            "role": "leaf",
            "toolsets": ["terminal", "file"],
        },
        {
            "goal": """Analyze claude-bridge for performance and scalability issues.

Check these files for bottlenecks:
- indexing.py: _INDEX_CACHE locking
- relevance.py: _RELEVANCE_CACHE
- config.py: global _config locks
- workflow_engine.py: ParallelWorkflowExecutor
- _shell_run.py: process session limits

Return JSON: {bottlenecks: [], lock_contention: [], memory_issues: [], scaling_limits: [], summary: "score X/10"}
Output valid JSON only.""",
            "role": "leaf",
            "toolsets": ["terminal", "file"],
        },
    ]

    qa_results = delegate_task(tasks=qa_tasks, toolsets=["delegation"])
    combined_qa = {
        "error_analysis": qa_results[0] if len(qa_results) > 0 else {},
        "functionality_analysis": qa_results[1] if len(qa_results) > 1 else {},
        "code_quality_analysis": qa_results[2] if len(qa_results) > 2 else {},
        "performance_analysis": qa_results[3] if len(qa_results) > 3 else {},
    }
    save_output("qa_results", combined_qa)
    print(f"[Orchestrator] QA complete")

    # === FINAL REPORT ===
    print("\n[Orchestrator] === FINAL REPORT ===")

    final_report = {
        "timestamp": datetime.now().isoformat(),
        "rounds_completed": context["round"],
        "all_features_generated": len(context["all_features"]),
        "top_features": final_top,
        "qa_results": combined_qa,
        "research_summary": combined,
    }
    save_output("final_report", final_report)

    print(f"\n[Orchestrator] ALL DONE at {datetime.now().strftime('%H:%M:%S')}")
    print(f"[Orchestrator] Output saved to {OUTPUT_DIR}")
    print(f"\n=== SUMMARY ===")
    print(f"Features generated: {len(context['all_features'])}")
    print(f"Top features: {len(final_top)}")
    for i, f in enumerate(final_top[:5], 1):
        name = f.get("name", "unknown") if isinstance(f, dict) else str(f)
        print(f"  {i}. {name}")

    return final_report


if __name__ == "__main__":
    main()