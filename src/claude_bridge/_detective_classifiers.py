"""Error classification patterns for Bridge Detective."""

from __future__ import annotations

import re
from typing import Final

_ERROR_PATTERNS: Final[dict[str, list[str]]] = {
    "SYNTAX_ERROR": [
        r"SyntaxError",
        r"IndentationError",
        r"TabError",
        r"Unexpected EOF",
        r"invalid syntax",
        r"closing parenthesis",
    ],
    "RUNTIME_ERROR": [
        r"Traceback \(most recent call last\)",
        r"^\s*File \"(.+?)\", line \d+",
        r"AttributeError",
        r"TypeError",
        r"ValueError",
        r"KeyError",
        r"IndexError",
        r"NameError",
        r"ZeroDivisionError",
        r"ImportError",
        r"ModuleNotFoundError",
    ],
    "SECURITY_ERROR": [
        r"SecurityError",
        r"PermissionError",
        r"Access denied",
        r"Unauthorized",
        r"forbidden",
        r"SQL injection",
        r"XSS",
        r"path traversal",
    ],
    "NETWORK_ERROR": [
        r"ConnectionError",
        r"TimeoutError",
        r"NetworkError",
        r"HTTPError",
        r"URLError",
        r"Connection refused",
        r"Connection reset",
        r"name or service not known",
    ],
}


def classify_error(error_output: str) -> str:
    """Classify an error string into an ErrorType."""
    for error_type, patterns in _ERROR_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, error_output, re.IGNORECASE | re.MULTILINE):
                return error_type
    return "UNKNOWN"


def extract_error_location(error_output: str) -> dict[str, str]:
    """Extract file location and line number from error output."""
    file_line_re = re.compile(r'^\s*File "(.+?)", line (\d+)', re.MULTILINE)
    match = file_line_re.search(error_output)
    if match:
        return {"file": match.group(1), "line": match.group(2)}

    arrow_re = re.compile(r"line (\d+)", re.IGNORECASE)
    match = arrow_re.search(error_output)
    if match:
        return {"file": "", "line": match.group(1)}
    return {"file": "", "line": ""}
