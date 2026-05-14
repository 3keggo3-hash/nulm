"""Intent Engine - Vague input detection and intent parsing for Claude Bridge."""

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
        "çalışmıyor",
        "hata",
        "crash",
        "broken",
        "olmuyor",
        "başarısız",
        "fail",
        "error",
        "exception",
        "traceback",
        "segfault",
        "panik",
        "kilitlen",
        "çökme",
        "not responding",
        "ölü",
        "deprecated",
    ],
    "performance_concern": [
        "yavaş",
        "slow",
        "performance",
        "hız",
        "optimizasyon",
        "gecikmeli",
        "timeout",
        "ağır",
        "gecikm",
        "fps",
        "memory leak",
        "ram",
        "cpu",
        "latency",
        "yavaşlat",
    ],
    "security_concern": [
        "güvenli mi",
        "secure",
        "risk",
        "güvenlik",
        "güvensiz",
        "hack",
        "salary",
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
        "injection",
    ],
    "missing_feature": [
        "eksik",
        "missing",
        "yok",
        "bulamadım",
        "找不到",
        "mevcut değil",
        "destination",
        "namoed",
        "bulunamadı",
        "gerçekleştirilemiyor",
    ],
    "refactoring_concern": [
        "refactor",
        "yeniden yapılandır",
        "temizle",
        "cleanup",
        "düzenle",
        "restructure",
        "code smell",
        "tech debt",
        "technical debt",
        "karışık",
        "bağımlılık",
        "coupling",
        "modular",
        "extract",
        "inheritance",
    ],
    "test_creation": [
        "test",
        "pytest",
        "unit test",
        "integration test",
        "e2e",
        "coverage",
        "test coverage",
        "birim test",
        "senaryo",
        "assertion",
        "mock",
        "fixture",
        "spec",
        "tap",
    ],
    "documentation_request": [
        "dokümantasyon",
        "docs",
        "documentation",
        "readme",
        "comment",
        "yorum",
        "açıklama",
        "explain",
        "wiki",
        "changelog",
        "version",
        "nasıl",
        "how to",
        "tutorial",
        "guide",
    ],
    "vague_indicators": [
        "biraz karışık",
        "nasıl yapacağımı bilmiyorum",
        "ne yapacağımı bilmiyorum",
        "hmm",
        "şey",
        "karışık",
        "anlamadım",
        "belki",
        "fikrim yok",
        "tahminden",
        "acaba",
        "orada bir",
        "birisine",
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

    vague_indicators = INTENT_PATTERNS.get("vague_indicators", [])
    for pattern in vague_indicators:
        if pattern in normalized:
            matched.append(pattern)
            confidence = max(confidence, 0.7)

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

    is_vague = confidence >= 0.7 and (
        len(matched) >= 2
        or any(vi in normalized for vi in vague_indicators)
        or intent_type == IntentType.VAGUE
    )

    if is_vague and not suggested_actions:
        suggested_actions = [
            "Analyze project structure",
            "Identify potential approaches",
            "Present ranked options",
        ]

    if confidence < 0.7 and intent_type == IntentType.VAGUE:
        confidence = 0.0
        suggested_actions = []

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
