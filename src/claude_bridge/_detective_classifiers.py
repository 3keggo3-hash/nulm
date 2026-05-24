"""Error classification patterns for Bridge Detective."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import base64
import re
from typing import Final, Tuple

UNICODE_TRAPS: Final[list[tuple[str, str, str]]] = [
    (r"\u202E", "RLO", "Right-to-Left Override"),
    (r"\u202D", "LRO", "Left-to-Right Override"),
    (r"\u202C", "PDF", "Pop Directional Formatting"),
    (r"\u200B", "ZWSP", "Zero-Width Space"),
    (r"\u200C", "ZWNJ", "Zero-Width Non-Joiner"),
    (r"\u200D", "ZWJ", "Zero-Width Joiner"),
    (r"\uFEFF", "BOM", "Byte Order Mark"),
]

B64_PATTERNS: Final[list[tuple[str, float]]] = [
    (r"^[A-Za-z0-9+/]{20,}={0,2}$", 0.6),
    (r"(?:[A-Za-z0-9+/]{4}){5,}", 0.5),
]

INDIRECT_INJECTION: Final[list[tuple[str, float]]] = [
    (r"(?i)ignore\s+all\s+previous\s+instructions", 1.0),
    (r"(?i)disregard\s+all\s+previous", 0.9),
    (r"(?i)forget\s+everything\s+above", 0.9),
    (r"(?i)switch\s+to\s+\w+\s+mode", 0.8),
    (r"(?i)you\s+are\s+now\s+a", 0.7),
    (r"(?i)act\s+as\s+if\s+you\s+are", 0.7),
    (r"(?i)pretend\s+you\s+are", 0.6),
    (r"(?i)new\s+system:\s*", 0.8),
    (r"(?i)system prompt:", 0.8),
    (r"<\|im_start\|>", 0.7),
    (r"<\|im_end\|>", 0.7),
]

SHELL_INJECTION_PATTERNS: Final[list[tuple[str, float]]] = [
    (r"`[^`]+`", 0.8),
    (r"\$\([^)]+\)", 0.8),
    (r"\|\s*bash", 0.9),
    (r"\|\s*sh\s*", 0.8),
    (r";\s*rm\s+", 0.9),
    (r";\s*wget\s+", 0.9),
    (r";\s*curl\s+", 0.9),
    (r">\s*/dev/null", 0.6),
    (r"2>&1", 0.5),
    (r"&&\s*curl\s+", 0.9),
    (r"&&\s*wget\s+", 0.9),
]

HOMOGLYPHS: Final[dict[str, str]] = {
    "а": "a",
    "е": "e",
    "о": "o",
    "р": "p",
    "с": "c",
    "х": "x",
    "ү": "y",
    "і": "i",
    "ј": "j",
    "ѕ": "s",
    "ԁ": "d",
    "ɡ": "g",
    "һ": "h",
    "ӄ": "k",
    "Ӏ": "l",
    "ո": "n",
    "г": "r",
    "ѵ": "v",
    "ᴍ": "M",
    "Ғ": "F",
    "Т": "T",
    "А": "A",
    "Е": "E",
    "О": "O",
    "Р": "P",
    "С": "C",
    "Х": "X",
}


class PromptInjectionClassifier:
    _instance: PromptInjectionClassifier | None = None

    def __init__(self, threshold: float = 0.5) -> None:
        self.threshold = threshold
        self.unicode_traps = UNICODE_TRAPS
        self.b64_patterns = B64_PATTERNS
        self.indirect_injection = INDIRECT_INJECTION
        self.shell_injection = SHELL_INJECTION_PATTERNS
        self.homoglyphs = HOMOGLYPHS
        self._unicode_re = re.compile("|".join(f"({p})" for p, _, _ in UNICODE_TRAPS))
        self._b64_re = re.compile("|".join(f"({p})" for p, _ in B64_PATTERNS))
        self._indirect_re = re.compile(
            "|".join(f"(?i:{p[4:]})" for p, _ in INDIRECT_INJECTION),
            re.IGNORECASE,
        )
        self._shell_re = re.compile("|".join(f"({p})" for p, _ in SHELL_INJECTION_PATTERNS))

    def classify(self, text: str) -> Tuple[bool, str, float]:
        if not text:
            return False, "", 0.0
        score = 0.0
        reasons: list[str] = []
        for pattern, weight in self.indirect_injection:
            if re.search(pattern, text, re.IGNORECASE):
                score += weight
                reasons.append(f"indirect_prompt_injection:{pattern}")
        for pattern, weight in self.shell_injection:
            if re.search(pattern, text):
                score += weight
                reasons.append(f"shell_injection_pattern:{pattern}")
        if self._unicode_re.search(text):
            matches = len(self._unicode_re.findall(text))
            score += 2.5 * matches
            reasons.append(f"unicode_control_chars:{matches}")
        if self._b64_re.search(text):
            b64_match = True
            try:
                decoded = base64.b64decode(text).decode("utf-8", errors="ignore")
                if decoded.strip():
                    if self._indirect_re.search(decoded):
                        b64_match = False
                    if b64_match:
                        score += 0.5
                        reasons.append("base64_payload")
            except Exception:
                pass
        homoglyph_chars = set(text) & set(self.homoglyphs.keys())
        if homoglyph_chars:
            score += 0.4
            reasons.append(f"homoglyphs:{len(homoglyph_chars)}")
        is_suspicious = score >= self.threshold
        reason = "; ".join(reasons) if reasons else ""
        return is_suspicious, reason, min(score, 1.0)

    def sanitize(self, text: str) -> str:
        sanitized = self._unicode_re.sub("", text)
        for char, replacement in self.homoglyphs.items():
            sanitized = sanitized.replace(char, replacement)
        return sanitized.strip()


def get_prompt_injection_classifier() -> PromptInjectionClassifier:
    if PromptInjectionClassifier._instance is None:
        PromptInjectionClassifier._instance = PromptInjectionClassifier()
    return PromptInjectionClassifier._instance


_ERROR_PATTERNS: Final[dict[str, list[tuple[str, int]]]] = {
    "SYNTAX_ERROR": [
        (r"SyntaxError", 10),
        (r"IndentationError", 10),
        (r"TabError", 10),
        (r"unexpected EOF", 8),
        (r"invalid syntax", 7),
        (r"closing parenthesis", 5),
        (r"EOL while scanning string literal", 8),
        (r"EOF in multi-line", 7),
    ],
    "RUNTIME_ERROR": [
        (r"Traceback \(most recent call last\)", 10),
        (r'^\s*File ".+?", line \d+', 6),
        (r"AttributeError", 9),
        (r"TypeError", 8),
        (r"ValueError", 7),
        (r"KeyError", 8),
        (r"IndexError", 8),
        (r"NameError", 8),
        (r"ZeroDivisionError", 10),
        (r"ImportError", 8),
        (r"ModuleNotFoundError", 10),
        (r"No module named", 9),
        (r"PermissionError", 9),
        (r"FileNotFoundError", 9),
        (r"AssertionError", 8),
        (r"NotImplementedError", 8),
        (r"RuntimeError", 7),
        (r"RecursionError", 10),
        (r"MemoryError", 10),
        (r"TimeoutError", 7),
        (r"ConnectionError", 8),
        (r"BrokenPipeError", 9),
        (r"CursorDisconnectedError", 10),
    ],
    "SECURITY_ERROR": [
        (r"SecurityError", 10),
        (r"PermissionError", 6),
        (r"Access denied", 8),
        (r"Unauthorized", 7),
        (r"forbidden", 5),
        (r"SQL injection", 10),
        (r"XSS", 10),
        (r"path traversal", 9),
        (r"shell injection", 10),
        (r"code injection", 10),
    ],
    "NETWORK_ERROR": [
        (r"ConnectionError", 9),
        (r"TimeoutError", 8),
        (r"NetworkError", 10),
        (r"HTTPError", 8),
        (r"URLError", 9),
        (r"Connection refused", 9),
        (r"Connection reset", 9),
        (r"name or service not known", 9),
        (r"Name or service not known", 9),
        (r"Network is unreachable", 10),
        (r"Connection timed out", 9),
    ],
}

_CONFIDENCE_THRESHOLD = 7


def classify_error(error_output: str) -> str:
    """Classify an error string into an ErrorType with confidence scoring."""
    scores: dict[str, int] = {}
    for error_type, patterns in _ERROR_PATTERNS.items():
        score = 0
        for pattern, weight in patterns:
            if re.search(pattern, error_output, re.IGNORECASE | re.MULTILINE):
                score += weight
        if score > 0:
            scores[error_type] = score

    if not scores:
        return "UNKNOWN"

    best_type = max(scores, key=lambda key: scores[key])
    if scores[best_type] < _CONFIDENCE_THRESHOLD:
        return "UNKNOWN"

    return best_type


def extract_error_location(error_output: str) -> dict[str, str]:
    """Extract file location and line number from error output."""
    file_line_re = re.compile(r'^\s*File "(.+?)", line (\d+)', re.MULTILINE)
    match = file_line_re.search(error_output)
    if match:
        return {"file": match.group(1), "line": match.group(2)}

    python_runner_re = re.compile(r"/[^\s]+python[0-9]*[^\s]*: (.+?): (.+), line (\d+)")
    match = python_runner_re.search(error_output)
    if match:
        return {"file": match.group(2), "line": match.group(3)}

    arrow_re = re.compile(r"line (\d+)", re.IGNORECASE)
    match = arrow_re.search(error_output)
    if match:
        return {"file": "", "line": match.group(1)}
    return {"file": "", "line": ""}
