"""
Spawn 2 Evaluation Agents - vote and select top features
"""
import delegate_task


def spawn_evaluation_agents(context: dict, round_num: int) -> tuple:
    all_features = context.get("all_features", [])
    top_from_prev = context.get("top_features", [])

    # Combine features to evaluate
    features_to_eval = list(all_features)
    if top_from_prev:
        # Include previous top features for re-evaluation
        for f in top_from_prev:
            if f not in features_to_eval:
                features_to_eval.append(f)

    if not features_to_eval:
        return {}, []

    features_str = str(features_to_eval[:20])  # Limit to 20 for practicality

    tasks = [
        {
            "goal": f"""You are Evaluation Agent 1 - Security & Safety Analyst.
Evaluate these features for claude-bridge. Score each 1-10 on:
- Security improvement
- Implementation difficulty
- User impact
- Innovation

Features to evaluate:
{features_str}

Return a JSON object with keys:
- scores: list of {{name, security_score, difficulty, impact, innovation, total}}
- reasoning: brief explanation of top choice
- recommended_implementation_order: ordered list of feature names

Output valid JSON only.""",
            "role": "leaf",
            "toolsets": ["web", "terminal", "file"],
        },
        {
            "goal": f"""You are Evaluation Agent 2 - Architecture & Developer Experience Analyst.
Evaluate these features for claude-bridge. Score each 1-10 on:
- Code quality improvement
- Performance impact
- Maintainability
- Developer experience

Features to evaluate:
{features_str}

Return a JSON object with keys:
- scores: list of {{name, quality_score, performance, maintainability, dx, total}}
- reasoning: brief explanation of top choice
- risks: potential issues with top features

Output valid JSON only.""",
            "role": "leaf",
            "toolsets": ["web", "terminal", "file"],
        },
    ]

    results = delegate_task(tasks=tasks, toolsets=["delegation"])

    # Combine votes
    all_votes = {}
    for r in results:
        if isinstance(r, dict):
            if "scores" in r:
                for score in r["scores"]:
                    name = score.get("name", "unknown")
                    if name not in all_votes:
                        all_votes[name] = {"votes": [], "total": 0}
                    all_votes[name]["votes"].append(score)
                    all_votes[name]["total"] += score.get("total", 0)

    # Compute top features
    ranked = sorted(all_votes.items(), key=lambda x: x[1]["total"], reverse=True)
    top_features = []
    for name, data in ranked[:10]:
        # Reconstruct full feature object
        for f in features_to_eval:
            if f.get("name") == name:
                top_features.append(f)
                break

    return all_votes, top_features