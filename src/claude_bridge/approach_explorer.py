"""Template-based approach explorer for programming problem alternatives."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from claude_bridge.config import project_dir

_KEYWORD_APPROACHES: dict[str, list[dict[str, Any]]] = {
    "sort": [
        {
            "name": "Quicksort",
            "description": "Divide-and-conquer in-place sorting with pivot selection.",
            "pros": ["Average O(n log n)", "In-place", "Good cache locality"],
            "cons": ["Worst-case O(n²)", "Not stable", "Pivot choice critical"],
            "complexity": "medium",
        },
        {
            "name": "Mergesort",
            "description": "Stable divide-and-conquer sort with guaranteed O(n log n).",
            "pros": ["Stable", "Guaranteed O(n log n)", "Parallelizable"],
            "cons": ["O(n) extra space", "Slower constant factors", "Recursive overhead"],
            "complexity": "medium",
        },
        {
            "name": "Heapsort",
            "description": "In-place comparison sort using a binary heap data structure.",
            "pros": ["Guaranteed O(n log n)", "In-place", "No recursion"],
            "cons": ["Not stable", "Poor cache locality", "Slower than quicksort in practice"],
            "complexity": "medium",
        },
    ],
    "search": [
        {
            "name": "Linear Search",
            "description": "Sequentially scan each element until the target is found.",
            "pros": ["Works on unsorted data", "Simple implementation", "No preprocessing"],
            "cons": ["O(n) time complexity", "Inefficient for large datasets"],
            "complexity": "low",
        },
        {
            "name": "Binary Search",
            "description": "Repeatedly divide sorted data in half to narrow search range.",
            "pros": ["O(log n) time", "Minimal memory overhead", "Well understood"],
            "cons": ["Requires sorted data", "Array-based only", "Insertions are costly"],
            "complexity": "low",
        },
        {
            "name": "Hash-Based Lookup",
            "description": "Use a hash table for O(1) average-case key-based retrieval.",
            "pros": ["O(1) average lookup", "Flexible key types", "Widely supported"],
            "cons": ["Worst-case O(n)", "Extra memory for table", "Hash collisions"],
            "complexity": "low",
        },
    ],
    "cache": [
        {
            "name": "LRU Cache",
            "description": "Least Recently Used eviction policy with bounded capacity.",
            "pros": ["Simple pattern", "Predictable memory", "Good for recency workloads"],
            "cons": ["No frequency tracking", "Adversarial patterns defeat it"],
            "complexity": "low",
        },
        {
            "name": "Distributed Cache",
            "description": "Shared cache layer across multiple service instances.",
            "pros": ["Uniform view", "Scalable capacity", "Decouples from compute"],
            "cons": ["Network latency", "Consistency concerns", "Operational complexity"],
            "complexity": "high",
        },
        {
            "name": "Write-Through Cache",
            "description": "Writes go to both cache and backing store synchronously.",
            "pros": ["Strong consistency", "Data never stale", "Reads always fast"],
            "cons": ["Higher write latency", "Cache must fit working set"],
            "complexity": "low",
        },
    ],
    "auth": [
        {
            "name": "JWT Authentication",
            "description": "Stateless token-based auth using signed JSON payloads.",
            "pros": ["Stateless", "Decentralized verification", "Compact"],
            "cons": ["Token revocation is hard", "Payload is readable", "Key management needed"],
            "complexity": "medium",
        },
        {
            "name": "OAuth 2.0 / OIDC",
            "description": "Delegated authorization framework with identity provider integration.",
            "pros": ["Industry standard", "Delegated access", "Rich ecosystem"],
            "cons": ["Complex flows", "Redirect URI management", "Many grant types"],
            "complexity": "high",
        },
        {
            "name": "Session-Based Auth",
            "description": "Server-side sessions with opaque cookie tokens.",
            "pros": ["Easy revocation", "Simple to implement", "Well understood"],
            "cons": ["Server state required", "Not RESTful by default", "CSRF risk"],
            "complexity": "low",
        },
    ],
    "api": [
        {
            "name": "REST API",
            "description": "Resource-oriented HTTP endpoints with standard verbs and status codes.",
            "pros": ["Universal tooling", "Cacheable responses", "Stateless design"],
            "cons": ["Over/under-fetching", "Chatty for complex views", "Versioning overhead"],
            "complexity": "low",
        },
        {
            "name": "GraphQL API",
            "description": "Query language allowing clients to request exactly the data they need.",
            "pros": ["Flexible queries", "Single endpoint", "Strong typing"],
            "cons": ["Query complexity risk", "Caching harder", "File upload tricky"],
            "complexity": "medium",
        },
        {
            "name": "gRPC API",
            "description": "High-performance RPC framework using Protocol Buffers and HTTP/2.",
            "pros": ["Fast binary protocol", "Streaming support", "Strong contracts"],
            "cons": ["Browser support limited", "Requires proto compiler", "Debugging harder"],
            "complexity": "medium",
        },
    ],
    "database": [
        {
            "name": "Relational (SQL)",
            "description": "Structured schema with ACID transactions and declarative queries.",
            "pros": ["ACID guarantees", "Mature ecosystem", "Powerful joins"],
            "cons": ["Schema rigidity", "Horizontal scaling hard", "Impedance mismatch"],
            "complexity": "medium",
        },
        {
            "name": "NoSQL Document Store",
            "description": "Schema-flexible document storage with eventual consistency options.",
            "pros": ["Flexible schema", "Horizontal scaling", "Fast writes"],
            "cons": ["Limited joins", "Eventual consistency", "Query capabilities vary"],
            "complexity": "medium",
        },
        {
            "name": "In-Memory Database",
            "description": "Data stored primarily in RAM for ultra-low latency access.",
            "pros": ["Sub-millisecond latency", "Simplest model", "No disk I/O"],
            "cons": ["Data loss risk", "Capacity limited by RAM", "Persistence add-on needed"],
            "complexity": "low",
        },
    ],
    "parser": [
        {
            "name": "Regex-Based Parser",
            "description": "Pattern matching with regular expressions for simple grammars.",
            "pros": ["Quick to write", "No dependencies", "Good for simple formats"],
            "cons": ["Unmaintainable beyond trivial", "No error recovery", "No nesting"],
            "complexity": "low",
        },
        {
            "name": "Recursive Descent Parser",
            "description": "Hand-written parser with one function per grammar rule.",
            "pros": ["Intuitive mapping", "Full control", "Good error messages"],
            "cons": ["Left-recursion issues", "Verbose for large grammars", "Manual labor"],
            "complexity": "medium",
        },
        {
            "name": "Parser Combinator",
            "description": "Composable higher-order functions that build parsers.",
            "pros": ["Highly composable", "Readable grammar", "Easy to extend"],
            "cons": ["Performance overhead", "Error messages tricky", "Learning curve"],
            "complexity": "medium",
        },
    ],
    "compiler": [
        {
            "name": "Single-Pass Compiler",
            "description": "Emit target code while parsing the source in one forward pass.",
            "pros": ["Fast compilation", "Low memory footprint", "Simple architecture"],
            "cons": ["Limited optimizations", "Forward declarations needed", "Less flexible"],
            "complexity": "medium",
        },
        {
            "name": "Multi-Pass Compiler",
            "description": "Separate lexing, parsing, analysis, and codegen in distinct passes.",
            "pros": ["Rich optimizations", "Clean separation", "Extensible"],
            "cons": ["Slower compile times", "Higher memory use", "More complex"],
            "complexity": "high",
        },
        {
            "name": "JIT Compiler",
            "description": "Just-In-Time compilation at runtime with adaptive optimization.",
            "pros": ["Peak performance", "Adaptive optimization", "Cross-platform"],
            "cons": ["Warm-up overhead", "Complex implementation", "Memory pressure"],
            "complexity": "high",
        },
    ],
    "test": [
        {
            "name": "Unit Testing",
            "description": "Isolated tests for individual functions and modules.",
            "pros": ["Fast feedback", "Pinpoints failures", "Documents behavior"],
            "cons": ["Limited coverage of integration", "Mock maintenance", "False confidence"],
            "complexity": "low",
        },
        {
            "name": "Integration Testing",
            "description": "Tests across module boundaries with real dependencies.",
            "pros": ["Catches interface bugs", "Realistic scenarios", "Confidence in wiring"],
            "cons": ["Slower execution", "Harder to debug", "Environment setup required"],
            "complexity": "medium",
        },
        {
            "name": "End-to-End Testing",
            "description": "Full-system tests simulating real user workflows end to end.",
            "pros": ["Validates real flows", "Business assurance", "Non-regression"],
            "cons": ["Flaky by nature", "Very slow", "Expensive to maintain"],
            "complexity": "high",
        },
    ],
    "deploy": [
        {
            "name": "Container-Based Deploy",
            "description": "Package application as OCI containers with orchestration.",
            "pros": ["Consistent environments", "Reproducible", "Ecosystem maturity"],
            "cons": ["Image size management", "Orchestrator complexity", "Cold starts"],
            "complexity": "medium",
        },
        {
            "name": "Serverless Deploy",
            "description": "Function-as-a-Service with automatic scaling and pay-per-use billing.",
            "pros": ["Zero ops at low scale", "Auto-scaling", "Cost efficient for spiky"],
            "cons": ["Vendor lock-in", "Cold starts", "Timeout limits"],
            "complexity": "medium",
        },
        {
            "name": "VM-Based Deploy",
            "description": "Traditional deployment on virtual machine instances.",
            "pros": ["Full OS control", "Long-running workloads", "Predictable performance"],
            "cons": ["Manual scaling", "OS maintenance", "Slower provisioning"],
            "complexity": "low",
        },
    ],
    "build": [
        {
            "name": "Make-Based Build",
            "description": "Dependency-driven build with makefile rules and incremental rebuilds.",
            "pros": ["Ubiquitous", "Incremental builds", "Simple model"],
            "cons": ["Portability issues", "Complex macros", "Recursive make pitfalls"],
            "complexity": "low",
        },
        {
            "name": "CMake / Modern Build System",
            "description": "Cross-platform build generation with a modular, declarative DSL.",
            "pros": ["Cross-platform", "IDE integration", "Package management"],
            "cons": ["Steep learning curve", "Slow generation", "Debugging configure"],
            "complexity": "medium",
        },
        {
            "name": "Incremental / Watch Build",
            "description": "File-watcher-driven rebuilds that recompile only changed artifacts.",
            "pros": ["Instant feedback", "Low cognitive overhead", "Great DX"],
            "cons": ["Resource-hungry watcher", "May miss transitive changes"],
            "complexity": "low",
        },
    ],
    "async": [
        {
            "name": "Thread Pool",
            "description": "Pre-allocated OS threads managed by a work-stealing executor.",
            "pros": ["True parallelism", "Mature tooling", "Simple mental model"],
            "cons": ["Context-switch overhead", "Memory per thread", "Synchronization bugs"],
            "complexity": "medium",
        },
        {
            "name": "Async/Await Coroutines",
            "description": "Cooperative concurrency with language-level suspend/resume points.",
            "pros": ["Low overhead", "High concurrency", "Readable sequential style"],
            "cons": ["Function coloring", "Library ecosystem split", "Debugging harder"],
            "complexity": "medium",
        },
        {
            "name": "Event Loop / Reactor",
            "description": "Single-threaded loop dispatching I/O events to callbacks.",
            "pros": ["Minimal overhead", "No synchronization needed", "Deterministic"],
            "cons": ["Callback nesting", "CPU-bound tasks block", "Stack traces harder"],
            "complexity": "medium",
        },
    ],
    "optimize": [
        {
            "name": "Caching Optimization",
            "description": "Add memoization, result caches, or precomputed lookup tables.",
            "pros": ["Large speed wins", "Easy to retrofit", "Measurable impact"],
            "cons": ["Staleness risk", "Memory consumption", "Cache invalidation"],
            "complexity": "low",
        },
        {
            "name": "Algorithmic Improvement",
            "description": "Replace O(n²) approaches with O(n log n) or better algorithms.",
            "pros": ["Asymptotic gains", "Scales better", "Often simpler code"],
            "cons": ["May need data restructure", "Harder to verify", "Not always available"],
            "complexity": "medium",
        },
        {
            "name": "Parallel / Vectorized",
            "description": "Leverage multiple cores or SIMD instructions for data-parallel work.",
            "pros": ["Near-linear scaling", "Hardware utilization", "Latency reduction"],
            "cons": ["Amdahl's law limits", "Synchronization overhead", "Debugging hard"],
            "complexity": "high",
        },
    ],
    "refactor": [
        {
            "name": "Incremental Refactor",
            "description": "Gradual restructuring behind abstractions with dual-run validation.",
            "pros": ["Low risk per step", "Reversible easily", "Continuous delivery safe"],
            "cons": ["Slow overall", "Temporary complexity", "Requires discipline"],
            "complexity": "medium",
        },
        {
            "name": "Big Bang Rewrite",
            "description": "Replace the entire component in one coordinated cut-over.",
            "pros": ["Clean break", "No legacy cruft", "Full redesign freedom"],
            "cons": ["High risk", "Long feature freeze", "Regression surface large"],
            "complexity": "high",
        },
        {
            "name": "Strangler Fig Pattern",
            "description": "Wrap legacy with proxy that gradually redirects calls to new system.",
            "pros": ["No big-bang risk", "Incremental migration", "Fallback always available"],
            "cons": ["Proxy overhead", "Dual maintenance period", "Routing complexity"],
            "complexity": "medium",
        },
    ],
    "security": [
        {
            "name": "Input Validation & Sanitization",
            "description": "Validate and sanitize all external inputs at system boundaries.",
            "pros": ["Defense-in-depth foundation", "Prevents injection", "Easy to audit"],
            "cons": ["Must cover every boundary", "Schema maintenance", "Performance overhead"],
            "complexity": "low",
        },
        {
            "name": "Encryption at Rest & Transit",
            "description": "TLS for data in motion and AES/disk encryption for stored data.",
            "pros": ["Broad protection", "Compliance ready", "Transparent to app"],
            "cons": ["Key management", "Performance impact", "Operational burden"],
            "complexity": "medium",
        },
        {
            "name": "Zero Trust Architecture",
            "description": "Never trust — verify every request regardless of origin.",
            "pros": ["Strongest posture", "Lateral movement prevention", "Audit ready"],
            "cons": ["Significant overhead", "Every service must adapt", "Complex rollout"],
            "complexity": "high",
        },
    ],
}

_SYNONYM_MAP: dict[str, str] = {
    "sorting": "sort",
    "sorted": "sort",
    "sorts": "sort",
    "arrange": "sort",
    "organization": "sort",
    "finding": "search",
    "find": "search",
    "lookup": "search",
    "locate": "search",
    "retrieve": "search",
    "memo": "cache",
    "memorize": "cache",
    "speed": "optimize",
    "performance": "optimize",
    "slow": "optimize",
    "bottleneck": "optimize",
    "compile": "compiler",
    "parsing": "parser",
    "parse": "parser",
    "grammar": "parser",
    "containerize": "deploy",
    "container": "deploy",
    "docker": "deploy",
    "kubernetes": "deploy",
    "k8s": "deploy",
}

_INTENT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(faster|speed up|improve performance|optimize)\b"), "optimize"),
    (re.compile(r"\b(slow|sluggish|bottleneck|slow down)\b"), "optimize"),
    (re.compile(r"\b(legacy|old system|migrate|refactor)\b"), "refactor"),
    (re.compile(r"\b(replace|rewrite|big bang|rebuild)\b"), "refactor"),
    (re.compile(r"\b(multithread|parallel|concurrent|async|multithreading)\b"), "async"),
    (re.compile(r"\b(thread|process|core|cpu)\b"), "async"),
]

_STORE_DIR_CACHE: Path | None = None


def _approach_store_dir() -> Path:
    global _STORE_DIR_CACHE
    if _STORE_DIR_CACHE is None:
        store = project_dir() / ".claude-bridge" / "approaches"
        store.mkdir(parents=True, exist_ok=True)
        _STORE_DIR_CACHE = store
    return _STORE_DIR_CACHE


def invalidate_store_dir_cache() -> None:
    global _STORE_DIR_CACHE
    _STORE_DIR_CACHE = None


def _valid_approach_id(approach_id: str) -> bool:
    return re.fullmatch(r"[0-9a-f]{32}", approach_id) is not None


def _detect_keywords(problem: str) -> list[str]:
    lowered = problem.lower()
    keywords: set[str] = set()
    for kw in _KEYWORD_APPROACHES:
        if kw in lowered:
            keywords.add(kw)
    for syn, canonical in _SYNONYM_MAP.items():
        if syn in lowered and canonical in _KEYWORD_APPROACHES:
            keywords.add(canonical)
    for pattern, kw in _INTENT_PATTERNS:
        if pattern.search(problem) and kw in _KEYWORD_APPROACHES:
            keywords.add(kw)
    return sorted(keywords)


def _score_keyword_match(problem: str, keyword: str) -> float:
    """Score how strongly a keyword matches the problem (0.0 to 1.0)."""
    lowered = problem.lower()
    count = lowered.count(keyword)
    if count >= 3:
        return 1.0
    elif count == 2:
        return 0.8
    elif count == 1:
        return 0.6
    return 0.0


def explore_approaches(
    problem: str, count: int = 3, include_low_relevance: bool = False
) -> dict[str, Any]:
    """Generate N alternative approaches based on keyword analysis of the problem.

    Each approach is stored as a JSON file under .claude-bridge/approaches/.
    Relevance scoring ranks approaches by how well they match the problem domain.
    """
    if count <= 0:
        return {"ok": False, "message": "count must be positive.", "approaches": []}
    if count > 20:
        return {"ok": False, "message": "count cannot exceed 20.", "approaches": []}
    keywords = _detect_keywords(problem)
    if not keywords:
        return {
            "ok": False,
            "message": "No relevant keywords found in problem description.",
            "approaches": [],
        }

    candidates: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for kw in keywords:
        relevance = _score_keyword_match(problem, kw)
        for tmpl in _KEYWORD_APPROACHES[kw]:
            if tmpl["name"] not in seen_names:
                candidate = dict(tmpl)
                candidate["keyword"] = kw
                candidate["relevance_score"] = relevance
                candidates.append(candidate)
                seen_names.add(tmpl["name"])

    complexity_rank = {"low": 0, "medium": 1, "high": 2}

    def _weighted_score(a: dict[str, Any]) -> float:
        relevance = float(a.get("relevance_score", 0.5))
        complexity = complexity_rank.get(a.get("complexity", "medium"), 1)
        return relevance * 0.7 + (1.0 - complexity / 2.0) * 0.3

    candidates.sort(key=_weighted_score, reverse=True)

    if not include_low_relevance:
        candidates = [c for c in candidates if c.get("relevance_score", 0) >= 0.4]

    selected = candidates[:count]
    store_dir = _approach_store_dir()
    for tmpl in selected:
        approach_id = uuid.uuid4().hex
        tmpl["id"] = approach_id
        file_path = store_dir / f"{approach_id}.json"
        file_path.write_text(json.dumps(tmpl, indent=2, sort_keys=True))

    return {
        "ok": True,
        "message": f"Generated {len(selected)} approach(es).",
        "approaches": selected,
        "keywords_matched": keywords,
    }


def execute_approach(approach_id: str) -> dict[str, Any]:
    """Load an approach file, mark it as executed, and return with metadata."""
    if not _valid_approach_id(approach_id):
        return {"ok": False, "message": "Invalid approach_id."}
    file_path = _approach_store_dir() / f"{approach_id}.json"
    if not file_path.exists():
        return {"ok": False, "message": f"Approach '{approach_id}' not found."}

    try:
        data = json.loads(file_path.read_text())
    except json.JSONDecodeError:
        return {"ok": False, "message": f"Approach '{approach_id}' has invalid JSON."}

    data["executed"] = True
    data["executed_at"] = time.time()
    file_path.write_text(json.dumps(data, indent=2, sort_keys=True))

    return {
        "ok": True,
        "message": f"Approach '{data.get('name', approach_id)}' executed.",
        "approach": data,
    }


def compare_approaches(approach_ids: list[str]) -> dict[str, Any]:
    """Load and compare multiple approaches, recommending the one with lowest complexity."""
    store_dir = _approach_store_dir()
    approaches: list[dict[str, Any]] = []
    missing: list[str] = []

    for aid in approach_ids:
        if not isinstance(aid, str) or not _valid_approach_id(aid):
            missing.append(str(aid))
            continue
        file_path = store_dir / f"{aid}.json"
        if file_path.exists():
            try:
                approaches.append(json.loads(file_path.read_text()))
            except json.JSONDecodeError:
                missing.append(aid)
        else:
            missing.append(aid)

    if not approaches:
        return {
            "ok": False,
            "message": "None of the requested approaches were found.",
            "approaches": [],
            "missing": missing,
        }

    complexity_rank = {"low": 0, "medium": 1, "high": 2}

    def _score(a: dict[str, Any]) -> int:
        return complexity_rank.get(a.get("complexity", "medium"), 1)

    sorted_approaches = sorted(approaches, key=_score)
    best = sorted_approaches[0]

    comparison: dict[str, Any] = {
        "compared_approaches": approaches,
        "complexity_levels": {
            a.get("name", a.get("id", "?")): a.get("complexity") for a in approaches
        },
        "best_recommendation": {
            "id": best.get("id"),
            "name": best.get("name"),
            "complexity": best.get("complexity"),
            "reason": f"{best.get('name')} has the lowest complexity ({best.get('complexity')}) "
            f"among the {len(approaches)} compared approach(es).",
        },
    }
    if missing:
        comparison["missing"] = missing

    return {
        "ok": True,
        "message": f"Compared {len(approaches)} approach(es). Best: {best.get('name')}.",
        "comparison": comparison,
    }
