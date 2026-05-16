"""
QA Agent - error analysis, functionality analysis, code quality analysis
"""
import delegate_task
from pathlib import Path

SRC_DIR = Path("/c/AIProjects/claude-bridge/src/claude_bridge")
TEST_DIR = Path("/c/AIProjects/claude-bridge/tests")


def spawn_qa_agent(context: dict) -> dict:
    impl_results = context.get("impl_results", {})
    files_changed = impl_results.get("files_changed", []) if isinstance(impl_results, dict) else []

    # Get list of all Python files in src
    src_files = list(SRC_DIR.rglob("*.py"))

    tasks = [
        {
            "goal": """You are QA Agent 1 - Error & Security Analysis.
Analyze claude-bridge for:
1. Runtime errors - use 'python -m py_compile' on all .py files
2. Type errors - run 'mypy src' and analyze output
3. Security vulnerabilities - look for injection points, path traversal, secret exposure
4. Race conditions - check global mutable state usage

Run these checks:
- Find files with syntax errors
- Find type annotation gaps
- Find potential security issues in shell_tools and file_tools

Return JSON:
{
  "syntax_errors": [{"file": path, "error": msg}],
  "type_errors": [{"file": path, "line": n, "error": msg}],
  "security_issues": [{"file": path, "issue": description, "severity": high/medium/low}],
  "race_conditions": [{"file": path, "issue": description}],
  "summary": "Overall health score X/10"
}
Output valid JSON only.""",
            "role": "leaf",
            "toolsets": ["terminal", "file"],
            "context": f"SRC_DIR={SRC_DIR}, TEST_DIR={TEST_DIR}",
        },
        {
            "goal": """You are QA Agent 2 - Functionality & Integration Analysis.
Analyze claude-bridge for:
1. Missing test coverage for new features
2. Broken imports or circular dependencies
3. Inconsistent error handling patterns
4. Tool registration issues
5. MCP protocol compliance

Run these checks:
- Check imports: python -c "import claude_bridge"
- List all registered tools
- Check test file count per module
- Find untested edge cases

Return JSON:
{
  "import_errors": [{"module": name, "error": msg}],
  "missing_tests": [{"module": name, "coverage": percent}],
  "inconsistent_patterns": [{"file": path, "pattern": description}],
  "tool_issues": [{"tool": name, "issue": description}],
  "summary": "Overall functionality score X/10"
}
Output valid JSON only.""",
            "role": "leaf",
            "toolsets": ["terminal", "file"],
            "context": f"SRC_DIR={SRC_DIR}, TEST_DIR={TEST_DIR}",
        },
        {
            "goal": """You are QA Agent 3 - Code Quality & Style Analysis.
Analyze claude-bridge for:
1. Code complexity - functions > 100 lines, classes > 500 lines
2. Style violations - run 'ruff check .' and 'black --check .'
3. Documentation gaps - missing docstrings on public APIs
4. Naming inconsistencies
5. Dead code detection

Run these checks:
- ruff check . --output-format=json > ruff.json
- black --check src/
- Find large functions/classes
- Find modules without __all__ exports

Return JSON:
{
  "complex_code": [{"file": path, "function": name, "lines": n, "reason": why_complex}],
  "style_violations": [{"file": path, "rule": id, "message": msg}],
  "undocumented": [{"file": path, "function": name}],
  "dead_code": [{"file": path, "name": name}],
  "summary": "Overall code quality score X/10"
}
Output valid JSON only.""",
            "role": "leaf",
            "toolsets": ["terminal", "file"],
            "context": f"SRC_DIR={SRC_DIR}, TEST_DIR={TEST_DIR}",
        },
        {
            "goal": """You are QA Agent 4 - Performance & Scalability Analysis.
Analyze claude-bridge for:
1. Indexing bottlenecks - full reindex, no incremental
2. Global lock contention in caching
3. ThreadPoolExecutor anti-pattern
4. Memory leaks in global caches
5. Process session limits

Check:
- indexing.py for _INDEX_CACHE locking
- relevance.py for _RELEVANCE_CACHE
- config.py for global _config locks
- workflow_engine.py for ParallelWorkflowExecutor
- _shell_run.py for process session management

Return JSON:
{
  "bottlenecks": [{"file": path, "issue": description, "impact": severity}],
  "lock_contention": [{"file": path, "lock": name}],
  "memory_issues": [{"file": path, "cache": name, "issue": description}],
  "scaling_limits": [{"limit": name, "current": n, "issue": description}],
  "summary": "Overall scalability score X/10"
}
Output valid JSON only.""",
            "role": "leaf",
            "toolsets": ["terminal", "file"],
            "context": f"SRC_DIR={SRC_DIR}, TEST_DIR={TEST_DIR}",
        },
    ]

    results = delegate_task(tasks=tasks, toolsets=["delegation"])

    combined = {
        "error_analysis": {},
        "functionality_analysis": {},
        "code_quality_analysis": {},
        "performance_analysis": {},
        "overall_scores": {},
    }

    if isinstance(results, list) and len(results) >= 4:
        combined["error_analysis"] = results[0]
        combined["functionality_analysis"] = results[1]
        combined["code_quality_analysis"] = results[2]
        combined["performance_analysis"] = results[3]

        # Calculate overall scores
        for key in ["error_analysis", "functionality_analysis", "code_quality_analysis", "performance_analysis"]:
            r = results[["error_analysis", "functionality_analysis", "code_quality_analysis", "performance_analysis"].index(key)]
            if isinstance(r, dict) and "summary" in r:
                # Extract score from summary like "score X/10"
                import re
                match = re.search(r"(\d+)/10", r["summary"])
                if match:
                    combined["overall_scores"][key] = int(match.group(1))

    # Calculate average
    if combined["overall_scores"]:
        avg = sum(combined["overall_scores"].values()) / len(combined["overall_scores"])
        combined["overall_scores"]["average"] = round(avg, 1)

    # Fix missing issues
    if "issues" not in combined:
        combined["issues"] = []

    return combined