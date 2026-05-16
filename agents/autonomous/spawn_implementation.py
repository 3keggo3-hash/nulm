"""
Implementation Agent - implements top features into the codebase
"""
import delegate_task
from pathlib import Path

SRC_DIR = Path("/c/AIProjects/claude-bridge/src/claude_bridge")


def spawn_implementation_agent(context: dict) -> dict:
    top_features = context.get("top_features", [])
    research = context.get("research_results", {})

    if not top_features:
        return {"status": "no_features", "implemented": []}

    features_to_impl = top_features[:5]  # Implement top 5

    # Read current key files for context
    current_state = {}
    key_files = {
        "config": SRC_DIR / "config.py",
        "server": SRC_DIR / "server.py",
        "shell_run": SRC_DIR / "_shell_run.py",
        "indexing": SRC_DIR / "indexing.py",
        "workflow_engine": SRC_DIR / "workflow_engine.py",
    }

    for name, path in key_files.items():
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    lines = f.readlines()
                    current_state[name] = {
                        "path": str(path),
                        "lines": len(lines),
                        "preview": "".join(lines[:50])
                    }
            except Exception:
                current_state[name] = {"path": str(path), "error": "could not read"}

    tasks = [
        {
            "goal": f"""You are Implementation Agent - Security Enhancements.
Implement these features in claude-bridge:
{str(features_to_impl[:2])}

Research context:
- Security patterns: {str(research.get('security_analysis', {}).get('security_patterns', [])[:3])}

Your task:
1. Read the relevant source files
2. Implement the feature following existing code patterns
3. Add tests for the new feature
4. Ensure mypy type hints and black formatting
5. Do NOT break existing functionality

Key files:
- Security: _shell_safety.py, _shell_run.py, guard_policy.py
- Config: config.py
- Server: server.py

Report what you implemented, what files changed, and any issues.
Return JSON: {{"implemented": [list of features], "files_changed": [paths], "tests_added": [paths], "issues": []}}""",
            "role": "leaf",
            "toolsets": ["terminal", "file"],
            "context": f"Source directory: {SRC_DIR}\nCurrent files: {str(current_state)}",
        },
        {
            "goal": f"""You are Implementation Agent - Autonomy & Performance.
Implement these features in claude-bridge:
{str(features_to_impl[2:4])}

Research context:
- Agent patterns: {str(research.get('autonomy_analysis', {}).get('agent_patterns', [])[:3])}

Your task:
1. Read the relevant source files
2. Implement the feature following existing code patterns
3. Add tests for the new feature
4. Ensure mypy type hints and black formatting
5. Do NOT break existing functionality

Key files:
- Workflow: workflow_engine.py, workflow_agent_loop.py
- Indexing: indexing.py, relevance.py
- Agents: agents/orchestrator.py, agents/dispatcher.py
- Config: config.py

Report what you implemented, what files changed, and any issues.
Return JSON: {{"implemented": [list of features], "files_changed": [paths], "tests_added": [paths], "issues": []}}""",
            "role": "leaf",
            "toolsets": ["terminal", "file"],
            "context": f"Source directory: {SRC_DIR}\nCurrent files: {str(current_state)}",
        },
        {
            "goal": f"""You are Implementation Agent - Developer Experience.
Implement these features in claude-bridge:
{str(features_to_impl[4:])}

Your task:
1. Read the relevant source files
2. Implement the feature following existing code patterns
3. Add tests for the new feature
4. Ensure mypy type hints and black formatting
5. Do NOT break existing functionality

Key files:
- CLI: cli.py
- Meta tools: meta_tool_server.py
- Tools: file_tools/, shell_tool_server.py
- Skills: skills/

Report what you implemented, what files changed, and any issues.
Return JSON: {{"implemented": [list of features], "files_changed": [paths], "tests_added": [paths], "issues": []}}""",
            "role": "leaf",
            "toolsets": ["terminal", "file"],
            "context": f"Source directory: {SRC_DIR}\nCurrent files: {str(current_state)}",
        },
    ]

    results = delegate_task(tasks=tasks, toolsets=["delegation"])

    combined = {
        "implemented_features": [],
        "files_changed": set(),
        "tests_added": [],
        "issues": [],
    }

    for r in results:
        if isinstance(r, dict):
            combined["implemented_features"].extend(r.get("implemented", []))
            combined["files_changed"].update(r.get("files_changed", []))
            combined["tests_added"].extend(r.get("tests_added", []))
            combined["issues"].extend(r.get("issues", []))

    combined["files_changed"] = list(combined["files_changed"])

    return combined