"""Smart utilities: token counting, encoding detection, tool intelligence."""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from claude_bridge.intent_engine import detect_undecided

DEFAULT_CONTEXT_BUDGET_TOKENS = 4000
_DetectEncodingBytes = Callable[[bytes], Any]

_tiktoken: Any | None = None
_TIKTOKEN_AVAILABLE = False
try:
    import tiktoken as _imported_tiktoken  # type: ignore[import-not-found]

    _tiktoken = _imported_tiktoken
    _TIKTOKEN_AVAILABLE = True
except ImportError:
    pass

_CHARSET_NORMALIZER_AVAILABLE = False
_detect_encoding_bytes: _DetectEncodingBytes | None = None
_PATH_TOKEN_RE = re.compile(r"^[\w./-]+\.[A-Za-z0-9]+$|^[\w./-]+/[\w./-]*$")
_WORD_RE = re.compile(r"[A-Za-z0-9_./-]+", re.UNICODE)
_STOPWORDS = {
    "a",
    "and",
    "for",
    "i",
    "in",
    "is",
    "it",
    "of",
    "or",
    "the",
    "to",
}
_MODE_HINTS = {
    "review": {"review", "critical", "shadow"},
    "optimize": {"optimize", "optimization", "performance", "speed"},
    "test": {"test", "pytest", "unit", "regression"},
    "explain": {"explain", "describe", "walkthrough"},
    "compact": {"compact", "summary", "cheap", "budget"},
    "platform": {"platform", "linux", "windows", "vscode", "visual", "studio"},
    "benchmark": {"benchmark", "latency", "startup", "profiling"},
    "fix": {"fix", "bug", "patch", "resolve"},
}


@dataclass
class ToolMetrics:
    token_efficiency_score: float
    context_savings_percent: float
    intelligence_confidence: float
    recommendation_reason: str


@lru_cache(maxsize=128)
def _cached_tokenEstimate(text_hash: int, text_len: int, model: str) -> int:
    return max(1, (text_len + 3) // 4)


def estimate_context_savings(
    original_tokens: int, compact_tokens: int, overhead_tokens: int
) -> dict[str, Any]:
    if original_tokens <= 0:
        return {"error": "original_tokens must be positive"}
    total_savings = original_tokens - compact_tokens - overhead_tokens
    savings_percent = (total_savings / original_tokens) * 100
    return {
        "original_tokens": original_tokens,
        "compact_tokens": compact_tokens,
        "overhead_tokens": overhead_tokens,
        "total_savings_tokens": max(0, total_savings),
        "savings_percent": round(max(0, savings_percent), 1),
        "efficiency_score": round(max(0, min(100, savings_percent)) / 100, 3),
    }


def get_tool_recommendation(
    query: str,
    available_tools: list[str],
    context_budget: int = DEFAULT_CONTEXT_BUDGET_TOKENS,
) -> dict[str, Any]:
    query_lower = query.lower()
    recommended: list[dict[str, Any]] = []
    scores: dict[str, float] = {tool: 0.0 for tool in available_tools}

    query_hints: dict[str, float] = {
        "count_file_tokens": 0.0,
        "context_fit": 0.0,
        "smart_status": 0.0,
        "batch_token_estimate": 0.0,
        "compact_intent": 0.0,
        "budget_metadata": 0.0,
    }

    file_mention = bool(_PATH_TOKEN_RE.search(query))
    if file_mention:
        query_hints["count_file_tokens"] += 0.8
        query_hints["batch_token_estimate"] += 0.6

    context_keywords = {"fit", "context", "limit", "token", "budget", "window", "overflow"}
    if any(kw in query_lower for kw in context_keywords):
        query_hints["context_fit"] += 0.9
        query_hints["budget_metadata"] += 0.5

    smart_keywords = {"available", "status", "feature", "smart", "tiktoken"}
    if any(kw in query_lower for kw in smart_keywords):
        query_hints["smart_status"] += 0.95

    compact_keywords = {"compact", "summary", "intent", "analyze", "understand", "query"}
    if any(kw in query_lower for kw in compact_keywords):
        query_hints["compact_intent"] += 0.85

    batch_keywords = {"batch", "multiple", "files", "estimate", "total"}
    if any(kw in query_lower for kw in batch_keywords):
        query_hints["batch_token_estimate"] += 0.7

    for tool, score in query_hints.items():
        if tool in scores:
            scores[tool] = score

    sorted_tools = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    for tool, score in sorted_tools:
        if score > 0:
            reason_map = {
                "count_file_tokens": "File path detected - token counting recommended",
                "batch_token_estimate": "Multiple files or batch operation suggested",
                "context_fit": "Context limit check needed",
                "smart_status": "Feature availability query detected",
                "compact_intent": "Intent analysis or query understanding requested",
                "budget_metadata": "Budget planning requested",
            }
            recommended.append(
                {"tool": tool, "score": round(score, 2), "reason": reason_map.get(tool, "")}
            )

    return {
        "query": query,
        "context_budget": context_budget,
        "recommendations": recommended,
        "primary_tool": recommended[0]["tool"] if recommended else None,
    }


try:
    from charset_normalizer import (  # type: ignore[import-not-found]
        from_bytes as _imported_detect_encoding_bytes,
    )

    _detect_encoding_bytes = _imported_detect_encoding_bytes
    _CHARSET_NORMALIZER_AVAILABLE = True
except ImportError:
    pass


def smart_available() -> dict[str, bool]:
    return {
        "tiktoken": _TIKTOKEN_AVAILABLE,
        "charset_normalizer": _CHARSET_NORMALIZER_AVAILABLE,
    }


def count_tokens(text: str, model: str = "gpt-4") -> int | None:
    if _tiktoken is None:
        return None
    try:
        enc = _tiktoken.encoding_for_model(model)
    except Exception:
        try:
            enc = _tiktoken.get_encoding("cl100k_base")
        except Exception:
            return None
    return len(enc.encode(text))


def estimate_token_count(text: str, model: str = "gpt-4") -> int:
    tokens = count_tokens(text, model)
    if tokens is not None:
        return tokens
    return max(1, (len(text) + 3) // 4)


def count_tokens_for_path(path: Path, model: str = "gpt-4") -> dict[str, Any]:
    if not path.is_file():
        return {"error": "not a file", "path": str(path)}
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return {"error": str(exc), "path": str(path)}

    if len(raw) > 1_000_000:
        return {"error": "file too large (max 1MB)", "path": str(path), "size": len(raw)}

    encoding = detect_file_encoding(raw)
    try:
        text = raw.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        text = raw.decode("utf-8", errors="replace")

    tokens = count_tokens(text, model)
    chars = len(text)
    lines = text.count("\n") + 1
    return {
        "path": str(path),
        "encoding": encoding,
        "chars": chars,
        "lines": lines,
        "tokens": tokens,
        "bytes": len(raw),
    }


def budget_metadata(
    *,
    estimated_tokens: int,
    budget_tokens: int = DEFAULT_CONTEXT_BUDGET_TOKENS,
    recommended_next_step: str,
) -> dict[str, Any]:
    safe_budget = max(1, int(budget_tokens))
    return {
        "context_budget_tokens": safe_budget,
        "estimated_tokens": estimated_tokens,
        "budget_spent": estimated_tokens,
        "budget_remaining": max(0, safe_budget - estimated_tokens),
        "within_budget": estimated_tokens <= safe_budget,
        "recommended_next_step": recommended_next_step,
        "budget_note": "estimated_tokens may exclude system prompt and tool overhead",
    }


def detect_file_encoding(raw: bytes) -> str:
    if not _CHARSET_NORMALIZER_AVAILABLE:
        if raw[:3] == b"\xef\xbb\xbf":
            return "utf-8-sig"
        return "utf-8"
    if not callable(_detect_encoding_bytes):
        return "utf-8"
    result = _detect_encoding_bytes(raw)
    if result:
        best = result.best()
        if best is not None and best.encoding is not None:
            return str(best.encoding)
    return "utf-8"


def context_fit_check(
    text: str,
    model: str = "gpt-4",
    context_limit: int = 200000,
) -> dict[str, Any]:
    tokens = count_tokens(text, model)
    if tokens is None:
        return {"tokens": None, "fit": None, "reason": "tiktoken not available"}
    ratio = tokens / context_limit
    return {
        "tokens": tokens,
        "context_limit": context_limit,
        "usage_percent": round(ratio * 100, 1),
        "fit": ratio <= 1.0,
        "remaining": max(0, context_limit - tokens),
    }


def batch_token_estimate(paths: list[Path], model: str = "gpt-4") -> dict[str, Any]:
    total_tokens = 0
    files: list[dict[str, Any]] = []
    for path in paths:
        if not path.is_file():
            continue
        info = count_tokens_for_path(path, model)
        if "error" in info:
            continue
        tokens = info.get("tokens") or 0
        total_tokens += tokens
        files.append(info)
    files.sort(key=lambda f: f.get("tokens", 0), reverse=True)
    return {
        "total_files": len(files),
        "total_tokens": total_tokens,
        "files": files,
    }


def compact_intent(
    text: str,
    *,
    max_keywords: int = 6,
    preserve_language: bool = True,
) -> dict[str, Any]:
    normalized = " ".join(text.split())
    words = [match.group(0) for match in _WORD_RE.finditer(normalized)]
    lowered_words = [word.lower() for word in words]
    keywords: list[str] = []
    seen_keywords: set[str] = set()
    path_hints: list[str] = []
    mode_scores: dict[str, int] = {mode: 0 for mode in _MODE_HINTS}

    for original, lowered in zip(words, lowered_words):
        if _PATH_TOKEN_RE.match(original):
            if original not in path_hints:
                path_hints.append(original)
        if len(lowered) >= 3 and lowered not in _STOPWORDS and lowered not in seen_keywords:
            seen_keywords.add(lowered)
            keywords.append(original)
        for mode, hints in _MODE_HINTS.items():
            if lowered in hints:
                mode_scores[mode] += 1

    inferred_mode = max(mode_scores, key=lambda mode: mode_scores[mode])
    if mode_scores[inferred_mode] == 0:
        inferred_mode = "general"

    constraints = [
        label
        for label, markers in (
            ("low_cost", {"token", "cheap", "compact", "budget"}),
            ("cross_platform", {"linux", "windows", "vscode", "platform"}),
            ("tests", {"test", "pytest", "regression"}),
        )
        if any(word in markers for word in lowered_words)
    ]
    compact_fields: dict[str, Any] = {
        "mode": inferred_mode,
        "target_hint": path_hints[0] if path_hints else None,
        "keywords": keywords[: max(1, max_keywords)],
        "constraints": constraints,
        "preserve_language": preserve_language,
    }
    compact_keywords = list(compact_fields["keywords"])
    compact_constraints = list(compact_fields["constraints"])
    compact_summary = (
        f"mode={compact_fields['mode']}; "
        f"target={compact_fields['target_hint'] or '.'}; "
        f"keywords={', '.join(compact_keywords) or 'none'}; "
        f"constraints={', '.join(compact_constraints) or 'none'}"
    )
    compact_prompt = (
        "Use the smallest useful context for this request.\n"
        f"Intent: {compact_summary}\n"
        f"Reply language: {'original language' if preserve_language else 'English'}\n"
        "Prefer narrow_context, targeted reads, and concise planning."
    )
    original_tokens = estimate_token_count(normalized)
    compact_summary_tokens = estimate_token_count(compact_summary)
    compact_tokens = estimate_token_count(compact_prompt)

    is_vague, vague_intent = detect_undecided(normalized)
    confidence = vague_intent.confidence if is_vague else 1.0 - (len(keywords) / 20)

    context_savings = estimate_context_savings(
        original_tokens, compact_summary_tokens, compact_tokens - compact_summary_tokens
    )
    token_efficiency = context_savings.get("efficiency_score", 0.0)

    intelligence_metrics = ToolMetrics(
        token_efficiency_score=token_efficiency,
        context_savings_percent=context_savings.get("savings_percent", 0.0),
        intelligence_confidence=round(max(0.0, min(1.0, confidence)), 3),
        recommendation_reason=(
            f"compact_intent reduces tokens by {context_savings.get('savings_percent', 0):.0f}%"
            if token_efficiency > 0.1
            else "minimal compression benefit detected"
        ),
    )

    result: dict[str, Any] = {
        "original_text": normalized,
        "canonical_intent": compact_fields,
        "compact_summary": compact_summary,
        "compact_prompt": compact_prompt,
        "estimated_original_tokens": original_tokens,
        "estimated_compact_summary_tokens": compact_summary_tokens,
        "estimated_compact_tokens": compact_tokens,
        "estimated_token_delta": compact_summary_tokens - original_tokens,
        "estimated_prompt_overhead_tokens": compact_tokens - compact_summary_tokens,
        "is_vague": is_vague,
        "intelligence_metrics": {
            "token_efficiency_score": intelligence_metrics.token_efficiency_score,
            "context_savings_percent": intelligence_metrics.context_savings_percent,
            "intelligence_confidence": intelligence_metrics.intelligence_confidence,
            "recommendation_reason": intelligence_metrics.recommendation_reason,
        },
        "recommended_usage": (
            "Use the canonical intent object for internal routing "
            "and keep original text only when nuance is needed."
        ),
    }

    if is_vague:
        result["vague_intent"] = {
            "intent_type": vague_intent.intent_type.value,
            "confidence": vague_intent.confidence,
            "suggested_actions": vague_intent.suggested_actions,
            "matched_patterns": vague_intent.matched_patterns,
        }
        result["recommended_usage"] = (
            "Vague input detected. Use advise_next_step or improve_request to clarify scope "
            "before planning."
        )

    return result
