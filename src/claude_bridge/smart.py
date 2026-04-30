"""Smart utilities: token counting, encoding detection."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

DEFAULT_CONTEXT_BUDGET_TOKENS = 4000

_tiktoken: Any | None = None
_TIKTOKEN_AVAILABLE = False
try:
    import tiktoken as _imported_tiktoken  # type: ignore[import-not-found]

    _tiktoken = _imported_tiktoken
    _TIKTOKEN_AVAILABLE = True
except ImportError:
    pass

_CHARSET_NORMALIZER_AVAILABLE = False
_detect_encoding_bytes: Any | None = None
_PATH_TOKEN_RE = re.compile(r"^[\w./-]+\.[A-Za-z0-9]+$|^[\w./-]+/[\w./-]*$")
_WORD_RE = re.compile(r"[A-Za-z0-9_./-]+", re.UNICODE)
_STOPWORDS = {
    "a",
    "and",
    "bir",
    "bu",
    "da",
    "de",
    "daha",
    "for",
    "gibi",
    "i",
    "ile",
    "için",
    "in",
    "is",
    "it",
    "mi",
    "ne",
    "of",
    "or",
    "the",
    "to",
    "ve",
    "ya",
}
_MODE_HINTS = {
    "review": {"review", "incele", "kritik", "shadow"},
    "optimize": {"optimize", "optimization", "performans", "hiz", "speed"},
    "test": {"test", "pytest", "unit", "regression"},
    "explain": {"explain", "acikla", "açıkla", "anlat"},
    "compact": {"compact", "daralt", "özet", "ozet", "cheap", "ucuz"},
    "platform": {"platform", "linux", "windows", "vscode", "visual", "studio"},
    "benchmark": {"benchmark", "latency", "startup", "profiling"},
    "fix": {"fix", "bug", "hata", "duzelt", "düzelt"},
}
try:
    from charset_normalizer import from_bytes as _detect_encoding_bytes

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
            ("low_cost", {"token", "ucuz", "cheap", "compact", "budget"}),
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
    return {
        "original_text": normalized,
        "canonical_intent": compact_fields,
        "compact_summary": compact_summary,
        "compact_prompt": compact_prompt,
        "estimated_original_tokens": original_tokens,
        "estimated_compact_summary_tokens": compact_summary_tokens,
        "estimated_compact_tokens": compact_tokens,
        "estimated_token_delta": compact_summary_tokens - original_tokens,
        "estimated_prompt_overhead_tokens": compact_tokens - compact_summary_tokens,
        "recommended_usage": (
            "Use the canonical intent object for internal routing and keep the original text only when nuance is needed."
        ),
    }
