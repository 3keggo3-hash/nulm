"""Lessons learned storage for Bridge Detective."""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from claude_bridge.config import project_dir

_LESSONS_FILE = ".claude-bridge/lessons_learned.json"


def _lessons_path() -> Path:
    pd = project_dir()
    path = pd / _LESSONS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_lessons() -> list[dict[str, Any]]:
    """Load lessons learned from storage."""
    path = _lessons_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def save_lessons(lessons: list[dict[str, Any]]) -> None:
    """Save lessons learned to storage."""
    path = _lessons_path()
    path.write_text(json.dumps(lessons, indent=2), encoding="utf-8")


def add_lesson(pattern: str, solution: str, error_type: str, file_path: str = "") -> None:
    """Add a new lesson to storage."""
    lessons = load_lessons()
    existing = next((i for i, lesson in enumerate(lessons) if lesson.get("pattern") == pattern), -1)

    entry: dict[str, Any] = {
        "pattern": pattern,
        "solution": solution,
        "error_type": error_type,
        "file": file_path,
        "hits": 1,
    }

    if existing >= 0:
        lessons[existing]["hits"] = lessons[existing].get("hits", 0) + 1
        if solution and solution != lessons[existing].get("solution", ""):
            lessons[existing]["solution"] = solution
    else:
        lessons.append(entry)

    save_lessons(lessons)


def find_similar_lesson(error_output: str) -> dict[str, Any] | None:
    """Find a lesson matching the error output pattern.

    Uses word-boundary matching to reduce false positives.
    """
    lessons = load_lessons()
    error_lower = error_output.lower()

    best: dict[str, Any] | None = None
    best_score = 0

    for lesson in lessons:
        pattern = lesson.get("pattern", "")
        if not pattern:
            continue
        pattern_lower = pattern.lower()

        if pattern_lower in error_lower:
            score = lesson.get("hits", 1)

            word_boundary_bonus = 0
            for word in pattern_lower.split():
                if len(word) >= 4:
                    if re.search(rf"\b{re.escape(word)}\b", error_lower):
                        word_boundary_bonus += 2
            score += word_boundary_bonus

            if score > best_score:
                best_score = score
                best = lesson

    return best
