"""Shared relevance scoring helpers for indexed code search."""

from __future__ import annotations

import re
import threading
from collections import OrderedDict
from typing import Any

_TOKEN_SPLIT_PATTERN = re.compile(r"[^a-zA-Z0-9]+")
_CAMEL_CASE_PATTERN = re.compile(r"(?<!^)(?=[A-Z])")
_MAX_RELEVANCE_CACHE_ENTRIES = 128
_RELEVANCE_CACHE: OrderedDict[tuple[str, str], dict[str, Any]] = OrderedDict()
_RELEVANCE_CACHE_LOCK = threading.RLock()


def query_terms(query: str) -> list[str]:
    return [term.lower() for term in query.strip().split() if term]


def _tokenize_text(value: str) -> set[str]:
    stripped = value.strip()
    if not stripped:
        return set()
    segmented = _CAMEL_CASE_PATTERN.sub(" ", stripped)
    direct_tokens = {token.lower() for token in _TOKEN_SPLIT_PATTERN.split(segmented) if token}
    expanded_tokens = set(direct_tokens)
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
    if cached is not None:
        cached_results = cached["results"] if limit is None else cached["results"][:limit]
        return {
            "query": query,
            "terms": list(cached["terms"]),
            "results": cached_results,
            "total_results": cached["total_results"],
            "cached": True,
        }

    terms = query_terms(query)
    results: list[dict[str, Any]] = []

    for item in index_payload["files"]:
        functions = item["functions"]
        classes = item["classes"]
        imports = item["imports"]
        parser_backend = item.get("parser_backend", "fallback")
        function_tokens = _tokenize_names(functions)
        class_tokens = _tokenize_names(classes)
        import_tokens = _tokenize_names(imports)
        path_tokens = _tokenize_text(item["path"])
        content_tokens = _tokenize_text(item["content"])
        haystacks = {
            "path": item["path"].lower(),
            "functions": " ".join(name.lower() for name in functions),
            "classes": " ".join(name.lower() for name in classes),
            "imports": " ".join(name.lower() for name in imports),
            "content": item["content"].lower(),
        }
        matched_terms: list[str] = []
        score = 0
        matched_fields: set[str] = set()

        for term in terms:
            term_score = 0
            symbol_match = False
            token_match = False

            if term in haystacks["path"]:
                term_score += 5
                matched_fields.add("path")
            if term in path_tokens:
                term_score += 2
                matched_fields.add("path")

            if term in haystacks["functions"]:
                term_score += 4
                symbol_match = True
                matched_fields.add("functions")
            if term in function_tokens:
                term_score += 3
                symbol_match = True
                token_match = True
                matched_fields.add("functions")

            if term in haystacks["classes"]:
                term_score += 4
                symbol_match = True
                matched_fields.add("classes")
            if term in class_tokens:
                term_score += 3
                symbol_match = True
                token_match = True
                matched_fields.add("classes")

            if term in haystacks["imports"]:
                term_score += 2
                symbol_match = True
                matched_fields.add("imports")
            if term in import_tokens:
                term_score += 2
                symbol_match = True
                token_match = True
                matched_fields.add("imports")

            if term in haystacks["content"]:
                term_score += 1
                matched_fields.add("content")
            if term in content_tokens:
                term_score += 1
                matched_fields.add("content")

            if symbol_match and parser_backend == "tree_sitter":
                term_score += 2
            if token_match:
                term_score += 1
            if term_score:
                matched_terms.append(term)
                score += term_score

        if score:
            if len(matched_terms) > 1:
                score += len(matched_terms)
            if len(matched_fields) > 1:
                score += len(matched_fields)
            results.append(
                {
                    "path": item["path"],
                    "score": score,
                    "matched_terms": matched_terms,
                    "matched_fields": sorted(matched_fields),
                    "parser_backend": parser_backend,
                }
            )

    results.sort(key=lambda entry: (-entry["score"], entry["path"]))
    payload = {
        "query": query,
        "terms": terms,
        "results": results if limit is None else results[:limit],
        "total_results": len(results),
        "cached": False,
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
