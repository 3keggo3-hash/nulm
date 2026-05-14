"""Shared relevance scoring helpers for indexed code search."""

from __future__ import annotations

import re
import threading
from collections import OrderedDict
from typing import Any

_TOKEN_SPLIT_PATTERN = re.compile(r"[^a-zA-Z0-9]+")
_CAMEL_CASE_PATTERN = re.compile(r"(?<!^)(?=[A-Z])")
_PRESERVE_IDENTIFIER_PATTERN = re.compile(r"^[^a-zA-Z0-9_]+|[^a-zA-Z0-9_]+$")
_MAX_RELEVANCE_CACHE_ENTRIES = 128
_RELEVANCE_CACHE: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
_RELEVANCE_CACHE_LOCK = threading.RLock()
_SHORTLIST_MULTIPLIER = 3
_MIN_SHORTLIST_SIZE = 24

_FIELD_REASON_MAP: dict[str, str] = {
    "path": "path_match",
    "functions": "function_match",
    "classes": "class_match",
    "imports": "import_match",
    "content": "content_match",
}
_SUBTOKEN_INDEX: dict[str, set[str]] = {}
_SUBTOKEN_INDEX_LOCK = threading.Lock()
_MIN_SUBTOKEN_LEN = 3


def clear_relevance_cache() -> None:
    """Clear in-memory relevance ranking cache."""
    with _RELEVANCE_CACHE_LOCK:
        _RELEVANCE_CACHE.clear()


def query_terms(query: str) -> list[str]:
    return [term.lower() for term in query.strip().split() if term]


def _tokenize_text(value: str) -> set[str]:
    stripped = value.strip()
    if not stripped:
        return set()
    segmented = _CAMEL_CASE_PATTERN.sub(" ", stripped)
    direct_tokens = {token.lower() for token in _TOKEN_SPLIT_PATTERN.split(segmented) if token}
    expanded_tokens = set(direct_tokens)
    preserved_tokens = {
        cleaned.lower()
        for chunk in stripped.split()
        for cleaned in [_PRESERVE_IDENTIFIER_PATTERN.sub("", chunk)]
        if cleaned
    }
    expanded_tokens.update(preserved_tokens)
    for token in _TOKEN_SPLIT_PATTERN.split(stripped):
        if not token:
            continue
        camel_parts = [part.lower() for part in _CAMEL_CASE_PATTERN.split(token) if part]
        expanded_tokens.update(camel_parts)
    return expanded_tokens


def _tokenize_names(names: list[str]) -> set[str]:
    tokens: set[str] = set()
    for name in names:
        tokens.update(_tokenize_text(name))
    return tokens


def rank_indexed_files(
    index_payload: dict[str, Any],
    *,
    query: str,
    limit: int | None = None,
) -> dict[str, Any]:
    snapshot_key = str(index_payload.get("_snapshot_key", "no-snapshot"))
    cache_key = (snapshot_key, query.strip().lower())
    with _RELEVANCE_CACHE_LOCK:
        cached = _RELEVANCE_CACHE.get(cache_key)
        if cached is not None:
            _RELEVANCE_CACHE.move_to_end(cache_key)
            cached_terms = list(cached["terms"])
            cached_results_all = list(cached["results"])
            cached_total_results = int(cached["total_results"])
        else:
            cached_terms = []
            cached_results_all = []
            cached_total_results = 0
    if cached is not None:
        cached_results = cached_results_all if limit is None else cached_results_all[:limit]
        return {
            "query": query,
            "terms": cached_terms,
            "results": cached_results,
            "total_results": cached_total_results,
            "cached": True,
            "strategy": "two_phase_token_scoring",
        }

    terms = query_terms(query)
    if not terms:
        return {
            "query": query,
            "terms": [],
            "results": [],
            "total_results": 0,
            "cached": False,
            "strategy": "two_phase_token_scoring",
        }

    files = _candidate_files(index_payload, terms)
    candidates: list[dict[str, Any]] = []

    for item in files:
        functions = item.get("functions", [])
        classes = item.get("classes", [])
        imports = item.get("imports", [])
        parser_backend = item.get("parser_backend", "fallback")
        function_tokens = set(item.get("function_tokens", [])) or _tokenize_names(functions)
        class_tokens = set(item.get("class_tokens", [])) or _tokenize_names(classes)
        import_tokens = set(item.get("import_tokens", [])) or _tokenize_names(imports)
        path_tokens = set(item.get("path_tokens", [])) or _tokenize_text(item["path"])
        content_tokens = set(item.get("content_tokens", []))
        if not content_tokens:
            content_lower = item.get("content_lower", "")
            content_tokens = _tokenize_text(content_lower or str(item.get("content", "")))
        haystacks = {
            "path": item.get("path_lower", item["path"].lower()),
            "functions": " ".join(name.lower() for name in functions),
            "classes": " ".join(name.lower() for name in classes),
            "imports": " ".join(name.lower() for name in imports),
        }
        phase_one_score = 0
        phase_one_fields: set[str] = set()
        phase_one_matched_terms: set[str] = set()
        content_term_hits = 0
        content_matched_terms: set[str] = set()

        for term in terms:
            term_score = 0
            if term in haystacks["path"]:
                term_score += 5
                phase_one_fields.add("path")
            if term in path_tokens:
                term_score += 2
                phase_one_fields.add("path")

            if term in haystacks["functions"]:
                term_score += 4
                phase_one_fields.add("functions")
            if term in function_tokens:
                term_score += 4
                phase_one_fields.add("functions")

            if term in haystacks["classes"]:
                term_score += 4
                phase_one_fields.add("classes")
            if term in class_tokens:
                term_score += 4
                phase_one_fields.add("classes")

            if term in haystacks["imports"]:
                term_score += 2
                phase_one_fields.add("imports")
            if term in import_tokens:
                term_score += 3
                phase_one_fields.add("imports")
            if term in content_tokens:
                content_term_hits += 1
                content_matched_terms.add(term)
            if len(term) >= _MIN_SUBTOKEN_LEN:
                for i in range(len(term) - _MIN_SUBTOKEN_LEN + 1):
                    for length in range(_MIN_SUBTOKEN_LEN, len(term) - i + 1):
                        subtoken = term[i : i + length]
                        for field, haystack in haystacks.items():
                            if subtoken in haystack.lower():
                                term_score += 1
                                phase_one_fields.add(field)
                        for token_set, field in [
                            (function_tokens, "functions"),
                            (class_tokens, "classes"),
                            (import_tokens, "imports"),
                        ]:
                            if subtoken in {t.lower() for t in token_set}:
                                term_score += 1
                                phase_one_fields.add(field)
                        if subtoken in content_tokens:
                            content_term_hits += 1
                            content_matched_terms.add(subtoken)
            if term_score:
                if parser_backend == "tree_sitter":
                    term_score += 2
                phase_one_score += term_score
                phase_one_matched_terms.add(term)

        if phase_one_score or content_term_hits:
            candidates.append(
                {
                    "path": item["path"],
                    "parser_backend": parser_backend,
                    "phase_one_score": phase_one_score,
                    "phase_one_fields": sorted(phase_one_fields),
                    "phase_one_matched_terms": sorted(phase_one_matched_terms),
                    "content_term_hits": content_term_hits,
                    "content_matched_terms": sorted(content_matched_terms),
                }
            )

    shortlist_size = max(
        _MIN_SHORTLIST_SIZE, (limit or len(candidates) or 1) * _SHORTLIST_MULTIPLIER
    )
    candidates.sort(
        key=lambda entry: (
            -int(entry["phase_one_score"]),
            -int(entry["content_term_hits"]),
            str(entry["path"]),
        )
    )
    shortlisted = candidates[:shortlist_size]

    results: list[dict[str, Any]] = []
    for candidate in shortlisted:
        matched_fields = set(candidate["phase_one_fields"])
        matched_terms = set(candidate["phase_one_matched_terms"])
        score = int(candidate["phase_one_score"])
        if candidate["content_term_hits"]:
            score += int(candidate["content_term_hits"])
            matched_fields.add("content")
        matched_terms.update(candidate["content_matched_terms"])

        if score:
            unique_terms = sorted(matched_terms)
            if len(unique_terms) > 1:
                score += len(unique_terms)
            if len(matched_fields) > 1:
                score += len(matched_fields)
            if len(matched_fields) > 1:
                selection_reason = "combined"
            else:
                selection_reason = _FIELD_REASON_MAP.get(next(iter(matched_fields), ""), "combined")
            results.append(
                {
                    "path": candidate["path"],
                    "score": score,
                    "matched_terms": unique_terms,
                    "matched_fields": sorted(matched_fields),
                    "parser_backend": candidate["parser_backend"],
                    "selection_reason": selection_reason,
                }
            )

    results.sort(key=lambda entry: (-entry["score"], entry["path"]))
    payload = {
        "query": query,
        "terms": terms,
        "results": results if limit is None else results[:limit],
        "total_results": len(results),
        "cached": False,
        "strategy": "two_phase_token_scoring",
    }
    with _RELEVANCE_CACHE_LOCK:
        _RELEVANCE_CACHE[cache_key] = {
            "terms": list(terms),
            "results": list(results),
            "total_results": len(results),
        }
        _RELEVANCE_CACHE.move_to_end(cache_key)
        while len(_RELEVANCE_CACHE) > _MAX_RELEVANCE_CACHE_ENTRIES:
            _RELEVANCE_CACHE.popitem(last=False)
    return payload


def _subtoken_index_key(term: str) -> str:
    return term.lower()


def _build_subtoken_index(terms: list[str]) -> dict[str, list[str]]:
    subtoken_map: dict[str, list[str]] = {}
    for term in terms:
        key = _subtoken_index_key(term)
        subtoken_map[key] = []
        if len(term) >= _MIN_SUBTOKEN_LEN:
            for i in range(len(term) - _MIN_SUBTOKEN_LEN + 1):
                for length in range(_MIN_SUBTOKEN_LEN, len(term) - i + 1):
                    subtoken = term[i : i + length]
                    if len(subtoken) >= _MIN_SUBTOKEN_LEN:
                        subtoken_map[key].append(subtoken)
    return subtoken_map


def _candidate_files(index_payload: dict[str, Any], terms: list[str]) -> list[dict[str, Any]]:
    term_index = index_payload.get("_term_file_index")
    files = index_payload.get("files", [])
    if not isinstance(term_index, dict):
        return list(files)

    subtoken_map = _build_subtoken_index(terms)
    paths: set[str] = set()
    for term in terms:
        raw_paths = term_index.get(term, [])
        if isinstance(raw_paths, list):
            paths.update(str(path) for path in raw_paths)
    for term_key, subtokens in subtoken_map.items():
        for subtoken in subtokens:
            raw_paths = term_index.get(subtoken, [])
            if isinstance(raw_paths, list):
                paths.update(str(path) for path in raw_paths)
    for item in files:
        haystack = " ".join(
            [
                str(item.get("path_lower", item.get("path", ""))).lower(),
                " ".join(str(name).lower() for name in item.get("functions", [])),
                " ".join(str(name).lower() for name in item.get("classes", [])),
                " ".join(str(name).lower() for name in item.get("imports", [])),
            ]
        )
        haystack_lower = haystack.lower()
        if any(term in haystack for term in terms):
            paths.add(str(item.get("path")))
        else:
            term_matched = False
            for term in terms:
                key = _subtoken_index_key(term)
                if key in subtoken_map or len(term) >= _MIN_SUBTOKEN_LEN:
                    term_parts = set()
                    for i in range(len(term) - _MIN_SUBTOKEN_LEN + 1):
                        for length in range(_MIN_SUBTOKEN_LEN, len(term) - i + 1):
                            term_parts.add(term[i : i + length])
                    for part in term_parts:
                        if part in haystack_lower:
                            term_matched = True
                            break
                    if term_matched:
                        break
            if term_matched:
                paths.add(str(item.get("path")))
    if not paths:
        return list(files)

    by_path = {str(item.get("path")): item for item in files if isinstance(item, dict)}
    return [by_path[path] for path in sorted(paths) if path in by_path]
