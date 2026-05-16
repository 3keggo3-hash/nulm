"""
Spawn 3 Feature Brainstorm Agents in parallel + refinement agents
"""
import delegate_task


def _make_brainstorm_tasks(context: dict, round_num: int):
    research = context.get("research_results", {})
    competitor_features = research.get("competitor_analysis", {}).get("competitors", [])
    security_patterns = research.get("security_analysis", {}).get("security_patterns", [])
    agent_patterns = research.get("autonomy_analysis", {}).get("agent_patterns", [])
    top_from_prev = context.get("top_features", [])

    prev_features_str = ""
    if top_from_prev:
        prev_features_str = "\nPreviously proposed features to refine:\n"
        for f in top_from_prev:
            prev_features_str += f"- {f.get('name', 'unknown')}: {f.get('description', '')}\n"

    return [
        {
            "goal": f"""You are Brainstorm Agent 1 - Security & Safety Focus.
You create innovative features for claude-bridge MCP server.
Based on research:
- Competitors: {str(competitor_features[:3])}
- Security patterns: {str(security_patterns[:3])}

Previous round features to refine (if any):{prev_features_str}

Create 5-7 unique security/safety features. Each feature must have:
- name: short descriptive name
- description: what it does and why it matters
- inspiration: which competitor or research inspired it
- difficulty: easy/medium/hard
- impact: low/medium/high

Return as JSON array of feature objects. Output valid JSON only.""",
            "role": "leaf",
            "toolsets": ["web", "terminal", "file"],
        },
        {
            "goal": f"""You are Brainstorm Agent 2 - Autonomy & Intelligence Focus.
You create innovative features for claude-bridge MCP server.
Based on research:
- Agent patterns: {str(agent_patterns[:3])}
- Autonomy approaches: {str(agent_patterns)}

Previous round features to refine (if any):{prev_features_str}

Create 5-7 unique autonomous intelligence features. Each feature must have:
- name: short descriptive name
- description: what it does and why it matters
- inspiration: which competitor or research inspired it
- difficulty: easy/medium/hard
- impact: low/medium/high

Return as JSON array of feature objects. Output valid JSON only.""",
            "role": "leaf",
            "toolsets": ["web", "terminal", "file"],
        },
        {
            "goal": f"""You are Brainstorm Agent 3 - Developer Experience & Performance Focus.
You create innovative features for claude-bridge MCP server.
Based on research:
- Competitor strengths: {str([c.get('strengths', []) for c in competitor_features[:3]])}

Previous round features to refine (if any):{prev_features_str}

Create 5-7 unique developer experience or performance features. Each feature must have:
- name: short descriptive name
- description: what it does and why it matters
- inspiration: which competitor or research inspired it
- difficulty: easy/medium/hard
- impact: low/medium/high

Return as JSON array of feature objects. Output valid JSON only.""",
            "role": "leaf",
            "toolsets": ["web", "terminal", "file"],
        },
    ]


def spawn_brainstorm_agents(context: dict, round_num: int) -> list:
    tasks = _make_brainstorm_tasks(context, round_num)
    results = delegate_task(tasks=tasks, toolsets=["delegation"])

    all_features = []
    for r in results:
        if isinstance(r, list):
            all_features.extend(r)
        elif isinstance(r, dict) and "features" in r:
            all_features.extend(r["features"])

    # Deduplicate by name
    seen = set()
    unique = []
    for f in all_features:
        name = f.get("name", "")
        if name and name not in seen:
            seen.add(name)
            unique.append(f)

    return unique


def spawn_refinement_agents(context: dict, round_num: int) -> list:
    top = context.get("top_features", [])
    if not top:
        return spawn_brainstorm_agents(context, round_num)

    tasks = [
        {
            "goal": f"""You are Refinement Agent focusing on the TOP features from previous rounds.
Top features to refine and improve:
{str(top[:5])}

For each feature:
1. Analyze its strengths and weaknesses
2. Suggest specific improvements
3. Consider implementation complexity
4. Think about interaction with other features

Return refined versions as JSON array with original + refined fields.
Output valid JSON only.""",
            "role": "leaf",
            "toolsets": ["web", "terminal", "file"],
        },
        {
            "goal": f"""You are Creative Refinement Agent - think of NEW related features.
Previous top features:
{str(top[:5])}

Think creatively about what ADDITIONAL features would complement these.
Consider: integration possibilities, pain points not addressed, next-level capabilities.
Suggest 3-5 NEW features that synergize with the top features.

Return as JSON array of feature objects. Output valid JSON only.""",
            "role": "leaf",
            "toolsets": ["web", "terminal", "file"],
        },
    ]

    results = delegate_task(tasks=tasks, toolsets=["delegation"])

    all_features = []
    for r in results:
        if isinstance(r, list):
            all_features.extend(r)
        elif isinstance(r, dict):
            if "features" in r:
                all_features.extend(r["features"])
            elif "refined" in r:
                all_features.extend(r["refined"])

    return all_features