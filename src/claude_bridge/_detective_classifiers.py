"""Error classification patterns for Bridge Detective."""

from __future__ import annotations

import re
from typing import Final

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
        (r"No module named ['\"]", 9),
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

    best_type = max(scores, key=scores.get)
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
