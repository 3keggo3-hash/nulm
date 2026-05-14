"""Performance helpers for large-repo indexing and relevance checks."""

from __future__ import annotations

import gc
import time
import json
import statistics
from pathlib import Path
from typing import Any

from claude_bridge.indexing import build_index, public_index_payload
from claude_bridge.relevance import rank_indexed_files
from claude_bridge.tool_utils import infer_project_root, is_within_root, resolve_path


def load_benchmark_profile(profile_path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read benchmark profile: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("Benchmark profile must be a JSON object")
    return raw


def _get_memory_mb() -> float:
    try:
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    except Exception:
        return 0.0


def run_index_and_relevance_benchmark(
    *,
    project_dir: Path,
    path: str = ".",
    query: str,
    limit: int = 5,
    repeats: int = 3,
    warmup_repeats: int = 1,
    clear_cache: bool = False,
) -> dict[str, Any]:
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    if limit < 1:
        raise ValueError("limit must be at least 1")
    if warmup_repeats < 0:
        raise ValueError("warmup_repeats must be non-negative")

    resolved_project_dir = project_dir.resolve()
    benchmark_path = (
        str((resolved_project_dir / path).resolve()) if path != "." else str(resolved_project_dir)
    )

    if clear_cache:
        from claude_bridge.indexing import _INDEX_CACHE, _INDEX_CACHE_LOCK

        with _INDEX_CACHE_LOCK:
            _INDEX_CACHE.clear()
        gc.collect()

    mem_before_mb = _get_memory_mb()
    started = time.perf_counter()
    raw_index_payload = build_index(
        benchmark_path,
        resolve_path=resolve_path,
        infer_project_root=infer_project_root,
        is_within_root=is_within_root,
    )
    index_duration_ms = (time.perf_counter() - started) * 1000
    mem_after_index_mb = _get_memory_mb()

    for _ in range(warmup_repeats):
        rank_indexed_files(raw_index_payload, query=query, limit=limit)

    query_durations_ms: list[float] = []
    ranked_payload: dict[str, Any] | None = None
    for _ in range(repeats):
        started = time.perf_counter()
        ranked_payload = rank_indexed_files(raw_index_payload, query=query, limit=limit)
        query_durations_ms.append((time.perf_counter() - started) * 1000)

    if ranked_payload is None:
        raise RuntimeError("rank_indexed_files returned None")

    mem_after_query_mb = _get_memory_mb()
    public_payload = public_index_payload(raw_index_payload)

    query_avg = sum(query_durations_ms) / len(query_durations_ms)
    query_stdev = statistics.stdev(query_durations_ms) if len(query_durations_ms) > 1 else 0.0

    return {
        "project_dir": str(resolved_project_dir),
        "path": path,
        "query": query,
        "limit": limit,
        "repeats": repeats,
        "warmup_repeats": warmup_repeats,
        "clear_cache": clear_cache,
        "index_duration_ms": round(index_duration_ms, 3),
        "index_memory_delta_mb": round(mem_after_index_mb - mem_before_mb, 2),
        "query_durations_ms": [round(duration, 3) for duration in query_durations_ms],
        "query_avg_duration_ms": round(query_avg, 3),
        "query_stddev_ms": round(query_stdev, 3),
        "query_best_duration_ms": round(min(query_durations_ms), 3),
        "query_worst_duration_ms": round(max(query_durations_ms), 3),
        "query_memory_delta_mb": round(mem_after_query_mb - mem_after_index_mb, 2),
        "index_summary": {
            "root": public_payload["root"],
            "source_files": public_payload["source_files"],
            "python_files": public_payload["python_files"],
            "parser_backends": public_payload["parser_backends"],
            "cached": public_payload["cached"],
        },
        "top_results": ranked_payload["results"],
    }


def run_multi_query_benchmark(
    *,
    project_dir: Path,
    path: str = ".",
    queries: list[str],
    limit: int = 5,
    repeats_per_query: int = 3,
    warmup_repeats: int = 1,
    clear_cache_before_each: bool = False,
) -> dict[str, Any]:
    if not queries:
        raise ValueError("queries list cannot be empty")
    for q in queries:
        if not q.strip():
            raise ValueError("query cannot be empty or whitespace only")

    resolved_project_dir = project_dir.resolve()
    benchmark_path = (
        str((resolved_project_dir / path).resolve()) if path != "." else str(resolved_project_dir)
    )

    from claude_bridge.indexing import _INDEX_CACHE, _INDEX_CACHE_LOCK

    index_started = time.perf_counter()
    raw_index_payload = build_index(
        benchmark_path,
        resolve_path=resolve_path,
        infer_project_root=infer_project_root,
        is_within_root=is_within_root,
    )
    index_duration_ms = (time.perf_counter() - index_started) * 1000
    public_payload = public_index_payload(raw_index_payload)

    results: list[dict[str, Any]] = []
    for query in queries:
        if clear_cache_before_each:
            with _INDEX_CACHE_LOCK:
                _INDEX_CACHE.clear()
            gc.collect()

        for _ in range(warmup_repeats):
            rank_indexed_files(raw_index_payload, query=query, limit=limit)

        durations_ms: list[float] = []
        for _ in range(repeats_per_query):
            started = time.perf_counter()
            ranked = rank_indexed_files(raw_index_payload, query=query, limit=limit)
            durations_ms.append((time.perf_counter() - started) * 1000)

        avg = sum(durations_ms) / len(durations_ms)
        stdev = statistics.stdev(durations_ms) if len(durations_ms) > 1 else 0.0
        results.append(
            {
                "query": query,
                "query_avg_duration_ms": round(avg, 3),
                "query_stddev_ms": round(stdev, 3),
                "query_best_duration_ms": round(min(durations_ms), 3),
                "query_worst_duration_ms": round(max(durations_ms), 3),
                "top_results": ranked["results"] if ranked else [],
            }
        )

    total_query_ms = sum(r["query_avg_duration_ms"] for r in results) * repeats_per_query
    return {
        "project_dir": str(resolved_project_dir),
        "path": path,
        "queries": queries,
        "limit": limit,
        "repeats_per_query": repeats_per_query,
        "warmup_repeats": warmup_repeats,
        "index_duration_ms": round(index_duration_ms, 3),
        "total_query_duration_ms": round(total_query_ms, 3),
        "index_summary": {
            "root": public_payload["root"],
            "source_files": public_payload["source_files"],
            "python_files": public_payload["python_files"],
            "parser_backends": public_payload["parser_backends"],
            "cached": public_payload["cached"],
        },
        "per_query_results": results,
    }


def compare_benchmark_to_baseline(
    current: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    if baseline.get("status", "ready") != "ready":
        return {
            "ok": False,
            "failures": ["baseline is not marked ready for enforcement"],
            "baseline_name": baseline.get("name"),
        }
    max_index_duration_ms = baseline.get("max_index_duration_ms")
    max_query_avg_duration_ms = baseline.get("max_query_avg_duration_ms")
    max_query_stddev_ms = baseline.get("max_query_stddev_ms")
    min_source_files = baseline.get("min_source_files")
    expected_top_paths = baseline.get("expected_top_paths", [])
    if (
        max_index_duration_ms is None
        and max_query_avg_duration_ms is None
        and max_query_stddev_ms is None
        and min_source_files is None
        and not expected_top_paths
    ):
        return {
            "ok": False,
            "failures": ["baseline has no enforceable thresholds"],
            "baseline_name": baseline.get("name"),
        }

    failures: list[str] = []
    if min_source_files is not None and current["index_summary"]["source_files"] < min_source_files:
        failures.append(
            f"source_files {current['index_summary']['source_files']} < expected minimum {min_source_files}"
        )
    if max_index_duration_ms is not None and current["index_duration_ms"] > max_index_duration_ms:
        failures.append(
            f"index_duration_ms {current['index_duration_ms']} > baseline {max_index_duration_ms}"
        )
    if (
        max_query_avg_duration_ms is not None
        and current["query_avg_duration_ms"] > max_query_avg_duration_ms
    ):
        failures.append(
            "query_avg_duration_ms "
            f"{current['query_avg_duration_ms']} > baseline {max_query_avg_duration_ms}"
        )
    if max_query_stddev_ms is not None and current.get("query_stddev_ms", 0) > max_query_stddev_ms:
        failures.append(
            f"query_stddev_ms {current.get('query_stddev_ms', 0)} > baseline {max_query_stddev_ms}"
        )
    if expected_top_paths:
        current_top_paths = [
            item["path"] for item in current["top_results"][: len(expected_top_paths)]
        ]
        if current_top_paths != expected_top_paths:
            failures.append(f"top_results {current_top_paths} != expected {expected_top_paths}")

    return {
        "ok": not failures,
        "failures": failures,
        "baseline_name": baseline.get("name"),
    }
