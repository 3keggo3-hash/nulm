"""Static workflow presets and prompt helpers for Claude Bridge."""

from __future__ import annotations

from typing import Any

SUPPORTED_WORKFLOW_MODES = {
    "review",
    "shadow",
    "optimize",
    "orchestrate",
    "agent_loop",
    "quality",
    "test",
    "todo",
    "explain",
    "commit",
    "refactor",
    "debug",
    "document",
    "security",
}

PROMPT_SHORTCUTS = [
    {
        "name": "compact",
        "category": "low-cost",
        "description": "Shrink the working context and continue with a tighter budget-aware plan.",
        "token_strategy": "Use when the session is getting expensive and you want a smaller working set.",
        "chat_fallback": '/compact target="src/" goal="continue with lower token cost"',
    },
    {
        "name": "review",
        "category": "workflow",
        "description": "Review code for bugs and missing tests.",
        "token_strategy": "Prefer MCP prompt UI or slash menu instead of typing a long request.",
        "chat_fallback": '/review target="src/" focus="bugs and missing tests"',
    },
    {
        "name": "shadow",
        "category": "critical-review",
        "description": "Re-review a target skeptically and challenge prior assumptions before accepting conclusions.",
        "token_strategy": "Use as a prompt entrypoint when you want a fresh, critical pass with minimal chat overhead.",
        "chat_fallback": '/shadow target="src/" focus="challenge prior assumptions"',
    },
    {
        "name": "optimize",
        "category": "workflow",
        "description": "Optimize code for performance and maintainability.",
        "token_strategy": "Use the prompt entrypoint to avoid spending a separate planning turn.",
        "chat_fallback": '/optimize target="src/" focus="performance and readability"',
    },
    {
        "name": "orchestrate",
        "category": "workflow",
        "description": "Split a large task into workstreams and integration gates.",
        "token_strategy": "Useful when the client exposes MCP prompts directly.",
        "chat_fallback": '/orchestrate target="src/" focus="split by modules"',
    },
    {
        "name": "agent_loop",
        "category": "workflow",
        "description": "Design a bounded inspect-patch-validate loop.",
        "token_strategy": "Cheaper than re-explaining the loop each time in chat.",
        "chat_fallback": '/agent_loop target="src/" goal="fix the failing behavior"',
    },
    {
        "name": "quality",
        "category": "workflow",
        "description": "Evaluate shipping quality and regression safety.",
        "token_strategy": "Start from the prompt catalog entry to reduce prompt repetition.",
        "chat_fallback": '/quality target="src/" focus="correctness and regression safety"',
    },
    {
        "name": "test",
        "category": "workflow",
        "description": "Design or improve regression tests.",
        "token_strategy": "Saves one reasoning turn versus typing the full framing every time.",
        "chat_fallback": '/test target="src/" test_style="regression tests"',
    },
    {
        "name": "todo",
        "category": "workflow",
        "description": "Scan and prioritize TODO-style markers.",
        "token_strategy": "Better as a direct prompt entrypoint than a natural-language request.",
        "chat_fallback": '/todo target="." keywords="TODO, FIXME"',
    },
    {
        "name": "explain",
        "category": "workflow",
        "description": "Explain code for a chosen audience.",
        "token_strategy": "Avoids re-sending the audience and style framing each time.",
        "chat_fallback": '/explain target="src/..." audience="junior developer"',
    },
    {
        "name": "commit",
        "category": "workflow",
        "description": "Summarize changes and suggest a commit message.",
        "token_strategy": "Small but useful saving when repeated often.",
        "chat_fallback": '/commit target="." style="short imperative"',
    },
    {
        "name": "benchmark",
        "category": "ops",
        "description": "Ask for a benchmark-oriented investigation plan before running heavier checks.",
        "token_strategy": "Use prompt entrypoint first, then run the benchmark tool only if needed.",
        "chat_fallback": '/benchmark target="src/" focus="startup and relevance latency"',
    },
    {
        "name": "platform",
        "category": "ops",
        "description": "Audit Linux, Windows, and editor compatibility gaps.",
        "token_strategy": "Keeps platform-review framing concise and reusable.",
        "chat_fallback": '/platform target="." focus="Linux, Windows, VS Code"',
    },
    {
        "name": "refactor",
        "category": "workflow",
        "description": "Restructure code without changing external behavior.",
        "token_strategy": "Keeps the refactoring scope disciplined and avoids mixing in feature changes.",
        "chat_fallback": '/refactor target="src/" focus="improve structure and reduce duplication"',
    },
    {
        "name": "debug",
        "category": "workflow",
        "description": "Debug a known issue step by step with root-cause analysis.",
        "token_strategy": "Avoids spending turns re-framing the debugging approach.",
        "chat_fallback": '/debug target="src/" focus="trace the failing code path with evidence"',
    },
    {
        "name": "document",
        "category": "workflow",
        "description": "Generate or improve documentation for the target code.",
        "token_strategy": "Saves re-specifying doc format and audience each time.",
        "chat_fallback": '/document target="src/" style="module-level docstrings and README"',
    },
    {
        "name": "security",
        "category": "workflow",
        "description": "Audit the target for security vulnerabilities and risky patterns.",
        "token_strategy": "Pre-wires the security mindset so the model doesn't need to re-derive the checklist.",
        "chat_fallback": '/security target="src/" focus="injection, path traversal, and secrets handling"',
    },
]

CLIENT_SIDE_ONLY_SHORTCUTS = [
    {
        "name": "/model",
        "reason": "Model switching belongs to the MCP client or host app, not the Claude Bridge server.",
    },
    {
        "name": "/clear",
        "reason": "Conversation clearing is controlled by the client conversation UI.",
    },
]


def _build_compact_message(target: str, goal: str, language: str = "Turkish") -> str:
    return (
        "Shrink the active context before doing more work.\n"
        f"Target: {target}\n"
        f"Goal: {goal}\n"
        f"Response language: {language}\n"
        "Prefer the smallest useful set of files, the narrowest read windows,"
        " and the cheapest next step.\n"
        "Call out what can be deferred until later if it does not fit"
        " the current budget."
    )


def _build_shadow_message(target: str, focus: str, language: str = "Turkish") -> str:
    return (
        workflow_prompt("shadow", target, focus, language)
        + "\nTreat earlier assumptions as untrusted until the files confirm them.\n"
        + "Prefer a cold, critical reread over agreement-seeking."
    )


def _build_benchmark_message(target: str, focus: str, language: str = "Turkish") -> str:
    return (
        "Prepare a benchmark-first investigation plan.\n"
        f"Target: {target}\n"
        f"Focus: {focus}\n"
        f"Response language: {language}\n"
        "Start with the cheapest signals first. Use `claude-bridge benchmark` CLI when a full"
        " measurement run is justified.\n"
        "Separate measurement from interpretation.\n"
        "Call out what can be learned without spending a full benchmark run yet."
    )


def _build_platform_message(target: str, focus: str, language: str = "Turkish") -> str:
    return (
        "Audit cross-platform and editor compatibility.\n"
        f"Target: {target}\n"
        f"Focus: {focus}\n"
        f"Response language: {language}\n"
        "List platform assumptions, packaging risks, path issues, shell differences,"
        " and client integration gaps.\n"
        "Prefer a matrix of concrete risks and verifications over vague advice."
    )


# Arguments for each registered prompt, keyed by PROMPT_SHORTCUTS name.
PROMPT_ARGUMENTS: dict[str, list[dict[str, Any]]] = {
    "review": [
        {"name": "target", "description": "File or directory to review", "required": False},
        {"name": "focus", "description": "Specific review focus", "required": False},
        {
            "name": "language",
            "description": "Response language (e.g. Turkish, English)",
            "required": False,
        },
    ],
    "optimize": [
        {"name": "target", "description": "File or directory to optimize", "required": False},
        {"name": "focus", "description": "Optimization focus", "required": False},
        {
            "name": "language",
            "description": "Response language (e.g. Turkish, English)",
            "required": False,
        },
    ],
    "orchestrate": [
        {"name": "target", "description": "File or directory to orchestrate", "required": False},
        {"name": "focus", "description": "How to split the work", "required": False},
        {
            "name": "language",
            "description": "Response language (e.g. Turkish, English)",
            "required": False,
        },
    ],
    "agent_loop": [
        {"name": "target", "description": "File or directory for the loop", "required": False},
        {"name": "goal", "description": "What the loop should accomplish", "required": False},
        {
            "name": "max_iterations",
            "description": "Maximum number of inspect-patch-validate iterations",
            "required": False,
        },
        {
            "name": "language",
            "description": "Response language (e.g. Turkish, English)",
            "required": False,
        },
    ],
    "quality": [
        {"name": "target", "description": "File or directory to evaluate", "required": False},
        {"name": "focus", "description": "Specific quality focus", "required": False},
        {
            "name": "language",
            "description": "Response language (e.g. Turkish, English)",
            "required": False,
        },
    ],
    "test": [
        {"name": "target", "description": "File or directory to test", "required": False},
        {"name": "test_style", "description": "Preferred testing style", "required": False},
        {
            "name": "language",
            "description": "Response language (e.g. Turkish, English)",
            "required": False,
        },
    ],
    "todo": [
        {"name": "target", "description": "File or directory to scan", "required": False},
        {"name": "keywords", "description": "Keywords to search for", "required": False},
        {
            "name": "language",
            "description": "Response language (e.g. Turkish, English)",
            "required": False,
        },
    ],
    "explain": [
        {"name": "target", "description": "File or directory to explain", "required": False},
        {"name": "audience", "description": "Audience level", "required": False},
        {"name": "language", "description": "Response language", "required": False},
    ],
    "commit": [
        {"name": "target", "description": "File or directory to summarize", "required": False},
        {"name": "style", "description": "Preferred commit message style", "required": False},
        {
            "name": "language",
            "description": "Response language (e.g. Turkish, English)",
            "required": False,
        },
    ],
    "compact": [
        {"name": "target", "description": "File or directory to narrow", "required": False},
        {"name": "goal", "description": "What to preserve while compacting", "required": False},
        {
            "name": "language",
            "description": "Response language (e.g. Turkish, English)",
            "required": False,
        },
    ],
    "shadow": [
        {"name": "target", "description": "File or directory to re-review", "required": False},
        {"name": "focus", "description": "Critical review focus", "required": False},
        {
            "name": "language",
            "description": "Response language (e.g. Turkish, English)",
            "required": False,
        },
    ],
    "benchmark": [
        {"name": "target", "description": "File or directory to assess", "required": False},
        {"name": "focus", "description": "Benchmark focus", "required": False},
        {
            "name": "language",
            "description": "Response language (e.g. Turkish, English)",
            "required": False,
        },
    ],
    "platform": [
        {"name": "target", "description": "File or directory to assess", "required": False},
        {"name": "focus", "description": "Platform or client focus", "required": False},
        {
            "name": "language",
            "description": "Response language (e.g. Turkish, English)",
            "required": False,
        },
    ],
    "refactor": [
        {"name": "target", "description": "File or directory to refactor", "required": False},
        {
            "name": "focus",
            "description": "Refactoring focus (structure, duplication, naming, etc.)",
            "required": False,
        },
        {
            "name": "language",
            "description": "Response language (e.g. Turkish, English)",
            "required": False,
        },
    ],
    "debug": [
        {"name": "target", "description": "File or directory to debug", "required": False},
        {
            "name": "focus",
            "description": "Debugging focus (specific symptom or code path)",
            "required": False,
        },
        {
            "name": "language",
            "description": "Response language (e.g. Turkish, English)",
            "required": False,
        },
    ],
    "document": [
        {"name": "target", "description": "File or directory to document", "required": False},
        {
            "name": "style",
            "description": "Documentation style (docstrings, README, API docs)",
            "required": False,
        },
        {
            "name": "language",
            "description": "Response language (e.g. Turkish, English)",
            "required": False,
        },
    ],
    "security": [
        {"name": "target", "description": "File or directory to audit", "required": False},
        {
            "name": "focus",
            "description": "Security focus (injection, path traversal, secrets, etc.)",
            "required": False,
        },
        {
            "name": "language",
            "description": "Response language (e.g. Turkish, English)",
            "required": False,
        },
    ],
}

# Maps prompt name → which arg fills the {focus} placeholder in WORKFLOW_PROMPT_TEMPLATES.
# Prompts not listed here use custom message builders.
_PROMPT_FOCUS_ARG: dict[str, str] = {
    "review": "focus",
    "optimize": "focus",
    "orchestrate": "focus",
    "agent_loop": "goal",
    "quality": "focus",
    "test": "test_style",
    "todo": "keywords",
    "explain": "audience",
    "commit": "style",
    "refactor": "focus",
    "debug": "focus",
    "document": "style",
    "security": "focus",
}

# Maps prompt name to a custom message builder (compact/shadow/benchmark/platform).
# Prompts not listed here use the standard workflow template path.
_PROMPT_CUSTOM_BUILDERS: dict[str, Any] = {
    "compact": _build_compact_message,
    "shadow": _build_shadow_message,
    "benchmark": _build_benchmark_message,
    "platform": _build_platform_message,
}

_CUSTOM_PROMPT_DEFAULTS: dict[str, str] = {
    "compact": "continue the task with a smaller, cheaper working context",
    "shadow": "challenge prior assumptions, verify from files, and be skeptical of earlier conclusions",
    "benchmark": "startup cost, relevance latency, token efficiency, and cache behavior",
    "platform": "Linux, Windows, WSL, VS Code, and other MCP client compatibility",
}


WORKFLOW_PROMPT_TEMPLATES = {
    "review": (
        "Review the target for bugs, regressions, edge cases, and missing tests.\n"
        "Target: {target}\n"
        "Focus: {focus}\n"
        "Response language: {language}\n"
        "Start by exploring the relevant files before proposing changes.\n"
        "Do not stop after finding a single matching constant or comment.\n"
        "Cross-check related config, entrypoint, scene, and export files"
        " before concluding behavior is final."
    ),
    "shadow": (
        "Re-review the target with a skeptical, critical eye."
        " Challenge prior assumptions.\n"
        "Target: {target}\n"
        "Focus: {focus}\n"
        "Response language: {language}\n"
        "Treat earlier conclusions as untrusted until the files confirm them.\n"
        "Prefer a cold, critical reread over agreement-seeking.\n"
        "Cross-check related config, entrypoint, scene, and export files"
        " before accepting any earlier conclusion."
    ),
    "optimize": (
        "Analyze the target for performance, readability, and"
        " maintainability improvements.\n"
        "Target: {target}\n"
        "Focus: {focus}\n"
        "Response language: {language}\n"
        "Prefer concrete, low-risk improvements.\n"
        "Verify that proposed simplifications do not ignore framework-level"
        " overrides or nearby configuration files."
    ),
    "orchestrate": (
        "Break the target into an agentic implementation plan.\n"
        "Target: {target}\n"
        "Focus: {focus}\n"
        "Response language: {language}\n"
        "Split the work into parallelizable tracks when possible.\n"
        "For each track, define ownership boundaries, dependencies, risks,"
        " and validation.\n"
        "Then define an integration pass where a main agent reviews, merges,"
        " retests, and resolves conflicts."
    ),
    "agent_loop": (
        "Design a controlled mini agent loop for the target.\n"
        "Target: {target}\n"
        "Goal: {focus}\n"
        "Response language: {language}\n"
        "Use a small iterative loop: inspect -> patch -> validate -> decide"
        " whether to continue.\n"
        "Always define an iteration cap, allowed command set, rollback/snapshot"
        " rule, and final quality gate.\n"
        "Prefer safe, low-blast-radius edits and stop when evidence is insufficient."
    ),
    "quality": (
        "Evaluate the target against a practical shipping-quality bar.\n"
        "Target: {target}\n"
        "Focus: {focus}\n"
        "Response language: {language}\n"
        "Do not stop at the first plausible explanation.\n"
        "Cross-check related implementation, config, scene, and build/export"
        " files before judging quality complete.\n"
        "Call out where the code is acceptable, where it is fragile, and what"
        " evidence is still missing."
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
        "Use the `todo_scan` tool first for a fast automated pass,"
        " then read the flagged files manually.\n"
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
    "refactor": (
        "Restructure the target code without changing its external behavior.\n"
        "Target: {target}\n"
        "Focus: {focus}\n"
        "Response language: {language}\n"
        "Identify structural issues: duplication, unclear naming, deep nesting,"
        " god modules, tight coupling.\n"
        "Propose incremental refactors that can be validated with existing tests.\n"
        "Do not mix behavioral changes or new features into the refactoring plan."
    ),
    "debug": (
        "Debug the target step by step with root-cause analysis.\n"
        "Target: {target}\n"
        "Focus: {focus}\n"
        "Response language: {language}\n"
        "Form a hypothesis, read the relevant code paths, and trace execution flow.\n"
        "Use evidence from the files — not assumptions — to narrow the cause.\n"
        "When you find the root cause, explain it clearly and propose a minimal fix."
    ),
    "document": (
        "Generate or improve documentation for the target code.\n"
        "Target: {target}\n"
        "Preferred style: {focus}\n"
        "Response language: {language}\n"
        "Read the target files first, then produce documentation that matches"
        " the actual code.\n"
        "Prefer concrete usage examples and clear module/function-level descriptions."
    ),
    "security": (
        "Audit the target for security vulnerabilities and risky patterns.\n"
        "Target: {target}\n"
        "Focus: {focus}\n"
        "Response language: {language}\n"
        "Check for: injection vectors, path traversal, hardcoded secrets,"
        " unsafe deserialization,\n"
        "missing input validation, insecure defaults, and privilege escalation paths.\n"
        "Rank findings by severity and provide concrete remediation steps."
    ),
}

WORKFLOW_DEFAULT_FOCUS = {
    "review": "bugs, regressions, and missing tests",
    "shadow": "challenge prior assumptions, verify from files,"
    " and be skeptical of earlier conclusions",
    "optimize": "performance and readability",
    "orchestrate": "decompose the task into independent workstreams with clear ownership",
    "agent_loop": "inspect, patch, validate, and stop within a bounded number of iterations",
    "quality": "correctness, regression safety, readability, tests, and verification depth",
    "test": "regression tests",
    "todo": "TODO, FIXME, HACK, XXX",
    "explain": "a junior developer",
    "commit": "short imperative commit message with a concise summary",
    "refactor": "improve structure, reduce duplication, and clarify naming"
    " without behavioral changes",
    "debug": "trace the failing code path with evidence and isolate the root cause",
    "document": "module-level docstrings and README",
    "security": "injection, path traversal, secrets handling, and input validation",
}

WORKFLOW_STEPS = {
    "review": [
        "List the target to understand its structure.",
        "Read the most relevant files.",
        "Identify bugs, regressions, and missing tests before editing.",
    ],
    "shadow": [
        "List the target structure for a fresh orientation.",
        "Re-read the key files without trusting earlier summaries.",
        "Challenge each prior conclusion with file evidence before accepting it.",
    ],
    "optimize": [
        "Inspect the structure and current hotspots.",
        "Read the implementation details that matter most.",
        "Propose low-risk improvements with measurable benefit.",
    ],
    "orchestrate": [
        "Inspect the target structure and identify natural module boundaries.",
        "Split the task into independent workstreams with explicit file or"
        " responsibility ownership.",
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
        "Judge correctness, regression safety, readability, and test depth before"
        " suggesting changes.",
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
    "refactor": [
        "Inspect the target structure and identify structural hotspots.",
        "Read the implementation focusing on duplication, coupling, and naming.",
        "Propose incremental refactors with a rollback plan and test validation.",
    ],
    "debug": [
        "Inspect the target and note the reported symptom.",
        "Read the code path with a hypothesis in mind, tracing execution flow.",
        "Narrow the cause with file evidence and propose a minimal, verifiable fix.",
    ],
    "document": [
        "Inspect the target layout and public API surface.",
        "Read the implementation to understand intent and edge cases.",
        "Write documentation that matches the actual code with concrete examples.",
    ],
    "security": [
        "Inspect the target structure and identify trust boundaries.",
        "Read the implementation checking for injection, path traversal,"
        " secrets, and validation gaps.",
        "Rank findings by severity and provide concrete, actionable remediation steps.",
    ],
}

WORKFLOW_EXAMPLES = {
    "review": [
        'run_workflow(mode="review", target="src/")',
        'run_workflow(mode="review", target="src/", option="bugs and missing tests")',
    ],
    "shadow": [
        'run_workflow(mode="shadow", target="src/")',
        'run_workflow(mode="shadow", target="src/", option="challenge prior assumptions")',
    ],
    "optimize": [
        'run_workflow(mode="optimize", target="src/")',
        'run_workflow(mode="optimize", target="src/", option="performance and readability")',
    ],
    "orchestrate": [
        'run_workflow(mode="orchestrate", target="src/")',
        'run_workflow(mode="orchestrate", target="src/",'
        ' option="split by modules and define integration gates")',
    ],
    "agent_loop": [
        'run_workflow(mode="agent_loop", target="src/",'
        ' option="fix the failing behavior with bounded iterations",'
        " max_iterations=3)",
        'run_workflow(mode="agent_loop", target="src/",'
        ' option="stabilize tests before broader refactors",'
        " max_iterations=4)",
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
        'run_workflow(mode="explain", target="src/claude_bridge/server.py",'
        ' option="a junior Python developer", language="English")',
    ],
    "commit": [
        'run_workflow(mode="commit", target=".")',
        'run_workflow(mode="commit", target=".", option="short imperative message")',
    ],
    "refactor": [
        'run_workflow(mode="refactor", target="src/")',
        'run_workflow(mode="refactor", target="src/",'
        ' option="improve structure and reduce duplication")',
    ],
    "debug": [
        'run_workflow(mode="debug", target="src/")',
        'run_workflow(mode="debug", target="src/",'
        ' option="trace the failing code path with evidence")',
    ],
    "document": [
        'run_workflow(mode="document", target="src/")',
        'run_workflow(mode="document", target="src/", option="module-level docstrings and README")',
    ],
    "security": [
        'run_workflow(mode="security", target="src/")',
        'run_workflow(mode="security", target="src/",'
        ' option="injection, path traversal, and secrets handling")',
    ],
}

WORKFLOW_DISCOVERY_TERMS = {
    "review": "bugs tests regressions",
    "shadow": "skeptical reread challenge assumptions critical review",
    "optimize": "performance readability maintainability",
    "orchestrate": "modules boundaries dependencies integration tests",
    "agent_loop": "failing behavior tests validation patch smallest fix",
    "quality": "correctness regressions readability tests config entrypoint",
    "test": "tests edge cases regression",
    "todo": "todo fixme hack xxx",
    "explain": "entrypoint flow usage",
    "commit": "changes summary impact",
    "refactor": "structure duplication naming coupling",
    "debug": "bug root cause trace hypothesis fix",
    "document": "docstrings readme api docs documentation",
    "security": "injection path traversal secrets validation vulnerability",
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
    template = WORKFLOW_PROMPT_TEMPLATES.get(mode)
    if template is None:
        return f"Workflow mode '{mode}' is not supported."
    return template.format(
        target=target,
        focus=option or WORKFLOW_DEFAULT_FOCUS.get(mode, "general"),
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
        "rollback_policy": (
            "take a git snapshot before risky edits when possible;"
            " otherwise keep patches small and reversible"
        ),
        "quality_gate": [
            "correctness improved",
            "no obvious regression introduced",
            "tests or validation command executed when useful",
            "remaining risks explicitly called out",
        ],
    }


def prompt_shortcut_catalog() -> dict[str, Any]:
    return {
        "shortcuts": [dict(item) for item in PROMPT_SHORTCUTS],
        "client_side_only": [dict(item) for item in CLIENT_SIDE_ONLY_SHORTCUTS],
        "notes": [
            "Lowest-token path is a client-native MCP prompt or slash UI,"
            " if the client exposes it.",
            "Typing a natural-language request into chat still consumes a model"
            " turn before tools run.",
            "Claude Bridge can provide prompt entrypoints, but it cannot force"
            " the client to skip chat routing.",
        ],
    }
