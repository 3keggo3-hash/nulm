"""Intent Engine - Vague input detection and intent parsing for Nulm."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

IntentType = Enum(
    "IntentType",
    [
        ("ERROR_COMPLAINT", "ERROR_COMPLAINT"),
        ("PERFORMANCE_CONCERN", "PERFORMANCE_CONCERN"),
        ("SECURITY_CONCERN", "SECURITY_CONCERN"),
        ("MISSING_FEATURE", "MISSING_FEATURE"),
        ("REFACTORING_CONCERN", "REFACTORING_CONCERN"),
        ("TEST_CREATION", "TEST_CREATION"),
        ("DOCUMENTATION_REQUEST", "DOCUMENTATION_REQUEST"),
        ("VAGUE", "VAGUE"),
    ],
)

INTENT_PATTERNS: dict[str, list[str]] = {
    "error_complaint": [
        "crash",
        "broken",
        "fail",
        "error",
        "exception",
        "traceback",
        "segfault",
        "not responding",
        "deprecated",
    ],
    "performance_concern": [
        "slow",
        "performance",
        "timeout",
        "memory leak",
        "cpu",
        "latency",
    ],
    "security_concern": [
        "secure",
        "risk",
        "hack",
        "password",
        "secret",
        "api_key",
        "token",
        "credential",
        "exploit",
        "vulnerability",
        "cve",
        "xss",
        "sql injection",
    ],
    "missing_feature": [
        "missing",
        "not found",
        "doesn't exist",
        "cannot find",
        "unable to locate",
    ],
    "refactoring_concern": [
        "refactor",
        "cleanup",
        "restructure",
        "code smell",
        "tech debt",
        "technical debt",
        "coupling",
        "modular",
    ],
    "test_creation": [
        "test",
        "pytest",
        "unit test",
        "integration test",
        "e2e",
        "coverage",
        "mock",
        "fixture",
    ],
    "documentation_request": [
        "docs",
        "documentation",
        "readme",
        "comment",
        "explain",
        "wiki",
        "changelog",
        "how to",
        "tutorial",
        "guide",
    ],
}


@dataclass
class VagueIntent:
    intent_type: IntentType
    confidence: float
    suggested_actions: list[str]
    raw_input: str
    matched_patterns: list[str]


def detect_undecided(user_input: str) -> tuple[bool, VagueIntent]:
    normalized = " ".join(user_input.lower().split())
    matched: list[str] = []
    intent_type = IntentType.VAGUE
    confidence = 0.0
    suggested_actions: list[str] = []

    for pattern_list in INTENT_PATTERNS.values():
        for pattern in pattern_list:
            if pattern in normalized:
                if pattern not in matched:
                    matched.append(pattern)

    intent_weights: dict[str, tuple[IntentType, float, list[str]]] = {
        "error_complaint": (
            IntentType.ERROR_COMPLAINT,
            0.85,
            ["Run diagnostics", "Check recent changes", "Analyze error patterns"],
        ),
        "performance_concern": (
            IntentType.PERFORMANCE_CONCERN,
            0.8,
            ["Profile performance hotspots", "Analyze resource usage", "Check database queries"],
        ),
        "security_concern": (
            IntentType.SECURITY_CONCERN,
            0.9,
            ["Run security audit", "Check dependencies", "Verify permissions"],
        ),
        "missing_feature": (
            IntentType.MISSING_FEATURE,
            0.75,
            ["Verify dependencies", "Check configuration", "Search for alternatives"],
        ),
        "refactoring_concern": (
            IntentType.REFACTORING_CONCERN,
            0.7,
            ["Analyze code structure", "Identify refactoring targets", "Plan extraction strategy"],
        ),
        "test_creation": (
            IntentType.TEST_CREATION,
            0.8,
            ["Identify test targets", "Write unit tests", "Verify coverage"],
        ),
        "documentation_request": (
            IntentType.DOCUMENTATION_REQUEST,
            0.7,
            ["Review existing docs", "Identify gaps", "Draft documentation"],
        ),
    }

    for pattern_key, (intent, conf, actions) in intent_weights.items():
        patterns = INTENT_PATTERNS.get(pattern_key, [])
        if any(p in normalized for p in patterns):
            if conf > confidence:
                intent_type = intent
                confidence = conf
                suggested_actions = actions

    is_vague = len(matched) >= 3 and confidence < 0.7

    if is_vague and not suggested_actions:
        suggested_actions = [
            "Analyze project structure",
            "Identify potential approaches",
            "Present ranked options",
        ]

    vague_intent = VagueIntent(
        intent_type=intent_type,
        confidence=confidence,
        suggested_actions=suggested_actions,
        raw_input=user_input,
        matched_patterns=matched,
    )

    return is_vague, vague_intent


def parse_intent(user_input: str) -> dict[str, Any]:
    is_vague, vague_intent = detect_undecided(user_input)

    return {
        "is_vague": is_vague,
        "intent_type": vague_intent.intent_type.value,
        "confidence": vague_intent.confidence,
        "suggested_actions": vague_intent.suggested_actions,
        "matched_patterns": vague_intent.matched_patterns,
        "raw_input": vague_intent.raw_input,
    }


def has_clear_success_criteria(text: str) -> bool:
    indicators = [
        r"src/.*\.py",
        r"test.*\.py",
        r"--flag",
        r"--option",
        r"function\s+\w+",
        r"class\s+\w+",
        r"\d+\s*(files?|lines?)",
        r"\w+\s*should\s+\w+",
        r"error\s+is\s+",
        r"line\s+\d+",
    ]
    normalized = " ".join(text.lower().split())
    for pattern in indicators:
        if re.search(pattern, normalized, re.IGNORECASE):
            return True
    return False


def has_specific_files(text: str) -> bool:
    path_pattern = r"[\w./-]+\.[A-Za-z0-9]+|src/[\w./-]+"
    return bool(re.search(path_pattern, text))
