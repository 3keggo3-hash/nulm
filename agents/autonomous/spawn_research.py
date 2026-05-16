"""
Spawn 3 Research Agents in parallel - competitor analysis
"""
import delegate_task


def spawn_research_agents(context: dict) -> dict:
    tasks = [
        {
            "goal": """You are Research Agent 1 - Competitor Analysis Specialist.
Research MCP server competitors and local AI agent tools. Find:
1. Top 5 competitors (Zed, Cline, Goose, Aider, etc.)
2. Their unique features
3. What makes them successful
4. Gaps they have

Focus on: Claude Code, Zed, Cline, Aider, Goose, Llmon, Tabby, Sourcegraph Cody.
Return a JSON with keys: competitors (list of {name, features, strengths, gaps}), trends, inspiration.
Output as valid JSON only, no markdown.""",
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
Return a JSON with keys: security_patterns (list of {pattern, how_it_works, effectiveness}), audit_approaches, inspiration.
Output as valid JSON only, no markdown.""",
            "role": "leaf",
            "toolsets": ["web", "terminal"],
        },
        {
            "goal": """You are Research Agent 3 - Autonomy & Agent Systems Specialist.
Research autonomous agent architectures and multi-agent systems. Find:
1. How do LangChain/LlamaIndex agents work?
2. What makes Hermes agent effective?
3. Multi-agent orchestration patterns
4. Memory and context management

Focus on: autonomous agents, multi-agent loops, memory systems, tool synthesis, self-improvement.
Return a JSON with keys: agent_patterns (list of {pattern, description, pros, cons}), memory_approaches, orchestration_models.
Output as valid JSON only, no markdown.""",
            "role": "leaf",
            "toolsets": ["web", "terminal"],
        },
    ]

    results = delegate_task(tasks=tasks, toolsets=["delegation"])
    combined = {
        "competitor_analysis": results[0],
        "security_analysis": results[1],
        "autonomy_analysis": results[2],
    }
    return combined