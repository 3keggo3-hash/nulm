"""Static workflow presets and prompt helpers for Claude Bridge."""

from __future__ import annotations

from typing import Any

SUPPORTED_WORKFLOW_MODES = {
    "review",
    "optimize",
    "orchestrate",
    "agent_loop",
    "quality",
    "test",
    "todo",
    "explain",
    "commit",
}

WORKFLOW_PROMPT_TEMPLATES = {
    "review": (
        "Review the target for bugs, regressions, edge cases, and missing tests.\n"
        "Target: {target}\n"
        "Focus: {focus}\n"
        "Response language: {language}\n"
        "Start by exploring the relevant files before proposing changes.\n"
        "Do not stop after finding a single matching constant or comment.\n"
        "Cross-check related config, entrypoint, scene, and export files before concluding behavior is final."
    ),
    "optimize": (
        "Analyze the target for performance, readability, and maintainability improvements.\n"
        "Target: {target}\n"
        "Focus: {focus}\n"
        "Response language: {language}\n"
        "Prefer concrete, low-risk improvements.\n"
        "Verify that proposed simplifications do not ignore framework-level overrides or nearby configuration files."
    ),
    "orchestrate": (
        "Break the target into an agentic implementation plan.\n"
        "Target: {target}\n"
        "Focus: {focus}\n"
        "Response language: {language}\n"
        "Split the work into parallelizable tracks when possible.\n"
        "For each track, define ownership boundaries, dependencies, risks, and validation.\n"
        "Then define an integration pass where a main agent reviews, merges, retests, and resolves conflicts."
    ),
    "agent_loop": (
        "Design a controlled mini agent loop for the target.\n"
        "Target: {target}\n"
        "Goal: {focus}\n"
        "Response language: {language}\n"
        "Use a small iterative loop: inspect -> patch -> validate -> decide whether to continue.\n"
        "Always define an iteration cap, allowed command set, rollback/snapshot rule, and final quality gate.\n"
        "Prefer safe, low-blast-radius edits and stop when evidence is insufficient."
    ),
    "quality": (
        "Evaluate the target against a practical shipping-quality bar.\n"
        "Target: {target}\n"
        "Focus: {focus}\n"
        "Response language: {language}\n"
        "Do not stop at the first plausible explanation.\n"
        "Cross-check related implementation, config, scene, and build/export files before judging quality complete.\n"
        "Call out where the code is acceptable, where it is fragile, and what evidence is still missing."
    ),
    "test": (
        "Design or improve tests for the target.\n"
        "Target: {target}\n"
        "Preferred test style: {focus}\n"
        "Response language: {language}\n"
        "Call out risky gaps before writing new tests."
    ),
    "todo": (
        "Scan the target for implementation markers and prioritize them.\n"
        "Target: {target}\n"
        "Keywords to scan: {focus}\n"
        "Response language: {language}\n"
        "Group findings by urgency and likely impact."
    ),
    "explain": (
        "Explain the target clearly and incrementally.\n"
        "Target: {target}\n"
        "Audience: {focus}\n"
        "Response language: {language}\n"
        "Reference the important files and code paths first."
    ),
    "commit": (
        "Summarize the current changes and propose a commit message.\n"
        "Target: {target}\n"
        "Preferred style: {focus}\n"
        "Response language: {language}\n"
        "Mention user-visible impact and risky areas."
    ),
}

WORKFLOW_DEFAULT_FOCUS = {
    "review": "bugs, regressions, and missing tests",
    "optimize": "performance and readability",
    "orchestrate": "decompose the task into independent workstreams with clear ownership",
    "agent_loop": "inspect, patch, validate, and stop within a bounded number of iterations",
    "quality": "correctness, regression safety, readability, tests, and verification depth",
    "test": "regression tests",
    "todo": "TODO, FIXME, HACK, XXX",
    "explain": "a junior developer",
    "commit": "short imperative commit message with a concise summary",
}

WORKFLOW_STEPS = {
    "review": [
        "List the target to understand its structure.",
        "Read the most relevant files.",
        "Identify bugs, regressions, and missing tests before editing.",
    ],
    "optimize": [
        "Inspect the structure and current hotspots.",
        "Read the implementation details that matter most.",
        "Propose low-risk improvements with measurable benefit.",
    ],
    "orchestrate": [
        "Inspect the target structure and identify natural module boundaries.",
        "Split the task into independent workstreams with explicit file or responsibility ownership.",
        "Define the integration pass, validation gates, and merge risks before coding starts.",
    ],
    "agent_loop": [
        "Inspect the target and define the smallest useful first change.",
        "Patch only the current hypothesis and validate it immediately.",
        "Repeat only while the evidence improves and the iteration budget allows.",
    ],
    "quality": [
        "Inspect the target structure and likely execution path.",
        "Read the implementation together with nearby config or runtime override files.",
        "Judge correctness, regression safety, readability, and test depth before suggesting changes.",
    ],
    "test": [
        "Inspect the current test surface.",
        "Read the implementation and existing tests.",
        "Add regression coverage for the riskiest behavior.",
    ],
    "todo": [
        "Inspect the target layout.",
        "Search for TODO-style markers.",
        "Prioritize the findings by impact and effort.",
    ],
    "explain": [
        "Inspect the target layout.",
        "Read the key implementation files.",
        "Explain the flow from high level to detail.",
    ],
    "commit": [
        "Inspect the changed area.",
        "Read the current implementation context.",
        "Summarize the intent and propose a clean commit message.",
    ],
}

WORKFLOW_EXAMPLES = {
    "review": [
        'run_workflow(mode="review", target="src/")',
        'run_workflow(mode="review", target="src/", option="bugs and missing tests")',
    ],
    "optimize": [
        'run_workflow(mode="optimize", target="src/")',
        'run_workflow(mode="optimize", target="src/", option="performance and readability")',
    ],
    "orchestrate": [
        'run_workflow(mode="orchestrate", target="src/")',
        'run_workflow(mode="orchestrate", target="src/", option="split by modules and define integration gates")',
    ],
    "agent_loop": [
        'run_workflow(mode="agent_loop", target="src/", option="fix the failing behavior with bounded iterations", max_iterations=3)',
        'run_workflow(mode="agent_loop", target="src/", option="stabilize tests before broader refactors", max_iterations=4)',
    ],
    "quality": [
        'run_workflow(mode="quality", target="src/")',
        'run_workflow(mode="quality", target="src/", option="correctness and regression safety")',
    ],
    "test": [
        'run_workflow(mode="test", target="tests/")',
        'run_workflow(mode="test", target="src/", option="regression tests")',
    ],
    "todo": [
        'run_workflow(mode="todo", target=".")',
        'run_workflow(mode="todo", target=".", option="TODO, FIXME")',
    ],
    "explain": [
        'run_workflow(mode="explain", target="src/claude_bridge/server.py")',
        'run_workflow(mode="explain", target="src/claude_bridge/server.py", option="a junior Python developer", language="English")',
    ],
    "commit": [
        'run_workflow(mode="commit", target=".")',
        'run_workflow(mode="commit", target=".", option="short imperative message")',
    ],
}

WORKFLOW_DISCOVERY_TERMS = {
    "review": "bugs tests regressions",
    "optimize": "performance readability maintainability",
    "orchestrate": "modules boundaries dependencies integration tests",
    "agent_loop": "failing behavior tests validation patch smallest fix",
    "quality": "correctness regressions readability tests config entrypoint",
    "test": "tests edge cases regression",
    "todo": "todo fixme hack xxx",
    "explain": "entrypoint flow usage",
    "commit": "changes summary impact",
}

WORKFLOW_WARNINGS = [
    "execute=true only performs a safe first read/list step.",
    "This tool does not automatically patch files or run risky shell commands.",
]

WORKFLOW_QUALITY_BAR = [
    "correctness",
    "regression safety",
    "readability",
    "test coverage",
    "verification depth",
]

WORKFLOW_ORCHESTRATION_RULES = [
    "split only along clear ownership boundaries",
    "keep overlapping write scopes minimal",
    "define validation per workstream",
    "require a main-agent integration pass",
    "run a final end-to-end quality check after merging",
]


def workflow_prompt(mode: str, target: str, option: str | None, language: str) -> str:
    return WORKFLOW_PROMPT_TEMPLATES[mode].format(
        target=target,
        focus=option or WORKFLOW_DEFAULT_FOCUS[mode],
        language=language,
    )


def build_agent_loop_policy(max_iterations: int) -> dict[str, Any]:
    return {
        "max_iterations": max_iterations,
        "loop_shape": ["inspect", "patch", "validate", "decide"],
        "allowed_tools": ["read_file", "list_directory", "patch_file", "run_shell"],
        "allowed_shell_examples": ["pytest", "python3 -m pytest", "git diff", "git status"],
        "stop_conditions": [
            "validation passes",
            "iteration budget exhausted",
            "evidence becomes ambiguous",
            "blast radius grows beyond the current target",
        ],
        "rollback_policy": "take a git snapshot before risky edits when possible; otherwise keep patches small and reversible",
        "quality_gate": [
            "correctness improved",
            "no obvious regression introduced",
            "tests or validation command executed when useful",
            "remaining risks explicitly called out",
        ],
    }
