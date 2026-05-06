"""Context pack building for workflow tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from claude_bridge.smart import budget_metadata
from claude_bridge.smart import count_tokens_for_path as smart_count_tokens_for_path
from claude_bridge.tool_utils import path_outside_project_details
from claude_bridge.workflow_cache import (
    _CONTEXT_PACK_CACHE,
    _WORKFLOW_CACHE_LOCK,
    _load_disk_cached_response,
    _safe_cached_json_payload,
    _store_cache_entry,
    _touch_cache_entry,
    _write_disk_cached_response,
)
from claude_bridge.workflow_project import (
    _config_file_paths,
    _display_path,
    _risk_notes_for_project_type,
    _safe_json_response_load,
    _test_file_score,
    _workflow_state_signature,
    detect_project_type,
    suggest_validation_commands,
)


def _build_context_pack_error(
    *,
    target: str,
    message: str,
    code: str,
    json_response: Callable[..., str],
    details: dict[str, Any] | None = None,
) -> str:
    return json_response(False, message, code=code, details=details or {"path": target})


def _dedupe_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def _selected_file_budget(
    selected_files: list[str],
    *,
    budget_tokens: int,
    resolve_path: Callable[[str], Path],
) -> dict[str, Any]:
    file_estimates: list[dict[str, Any]] = []
    total_tokens = 0
    for selected in selected_files:
        try:
            resolved = resolve_path(selected)
        except PermissionError:
            continue
        if not resolved.exists() or not resolved.is_file():
            continue
        info = smart_count_tokens_for_path(resolved)
        estimated_tokens = int(info.get("tokens") or max(1, int(info.get("chars", 0)) // 4 or 1))
        total_tokens += estimated_tokens
        file_estimates.append(
            {
                "path": selected,
                "estimated_tokens": estimated_tokens,
            }
        )
    return {
        "file_estimates": file_estimates,
        **budget_metadata(
            estimated_tokens=total_tokens,
            budget_tokens=budget_tokens,
            recommended_next_step="Read only the highest-signal files first, or lower max_files to stay within budget.",
        ),
    }


def _select_context_candidates(
    *,
    target: str,
    goal: str,
    max_files: int,
    resolved: Path,
    active_project_dir: Path,
    project_root: Path,
    path_from_active_root: Callable[[Path], str],
    find_relevant_files: Callable[..., Awaitable[str]],
    json_response: Callable[..., str],
) -> Awaitable[tuple[list[str], str | None]]:
    async def _inner() -> tuple[list[str], str | None]:
        selected_files: list[str] = []
        if resolved.is_file():
            if target not in {"", "."}:
                selected_files.append(target)
            else:
                selected_files.append(
                    _display_path(
                        resolved,
                        active_project_dir=active_project_dir,
                        project_root=project_root,
                        path_from_active_root=path_from_active_root,
                    )
                )
            return selected_files, None

        relevant_raw = await find_relevant_files(query=goal, path=target, limit=max_files)
        relevant_payload, parse_error = _safe_json_response_load(
            relevant_raw,
            json_response=json_response,
            tool_name="find_relevant_files",
        )
        if parse_error is not None or relevant_payload is None:
            return [], parse_error
        if not relevant_payload.get("ok", False):
            return [], json_response(
                False,
                relevant_payload["message"],
                code=relevant_payload.get("code"),
                details=relevant_payload.get("details", {}),
            )
        for item in relevant_payload.get("details", {}).get("results", []):
            best_match = item["path"]
            read_target = (
                f"{target.rstrip('/')}/{best_match}" if target not in {".", ""} else best_match
            )
            selected_files.append(read_target)
        return selected_files, None

    return _inner()


def _collect_test_files(
    *,
    include_tests: bool,
    resolved: Path,
    project_root: Path,
    project_type: str,
    active_project_dir: Path,
    path_from_active_root: Callable[[Path], str],
    iter_searchable_files: Callable[[Path, Path, str | None], list[Path]],
) -> list[str]:
    if not include_tests:
        return []
    candidates = iter_searchable_files(project_root, project_root, None)
    relative_target_root = (
        resolved.relative_to(project_root)
        if resolved.is_dir()
        else resolved.parent.relative_to(project_root)
    )
    scored = sorted(
        (
            (
                candidate,
                _test_file_score(
                    candidate.relative_to(project_root),
                    project_type=project_type,
                    target_root=relative_target_root,
                ),
            )
            for candidate in candidates
        ),
        key=lambda item: (-item[1], item[0].as_posix()),
    )
    test_files: list[str] = []
    for candidate, score in scored:
        if score <= 0:
            continue
        test_files.append(
            _display_path(
                candidate,
                active_project_dir=active_project_dir,
                project_root=project_root,
                path_from_active_root=path_from_active_root,
            )
        )
        if len(test_files) >= 3:
            break
    return test_files


def build_context_pack(
    *,
    target: str,
    goal: str,
    max_files: int,
    include_tests: bool,
    include_git_diff: bool,
    include_docs: bool,
    budget_tokens: int,
    resolve_path: Callable[[str], Path],
    find_relevant_files: Callable[..., Awaitable[str]],
    path_from_active_root: Callable[[Path], str],
    project_dir: Callable[[], Path],
    infer_project_root: Callable[[Path], Path],
    iter_searchable_files: Callable[[Path, Path, str | None], list[Path]],
    git_status_snapshot: Callable[[Path], dict[str, Any]],
    json_response: Callable[..., str],
) -> Awaitable[str]:
    async def _inner() -> str:
        if max_files < 1:
            return _build_context_pack_error(
                target=target,
                message="max_files must be at least 1",
                code="invalid_max_files",
                json_response=json_response,
                details={"max_files": max_files},
            )

        try:
            resolved = resolve_path(target)
        except PermissionError as exc:
            return json_response(
                False,
                str(exc),
                code="path_outside_project",
                details=path_outside_project_details(target),
            )
        if not resolved.exists():
            return _build_context_pack_error(
                target=target,
                message=f"Path not found: {target}",
                code="path_not_found",
                json_response=json_response,
            )
        active_project_dir = project_dir()
        project_root = infer_project_root(resolved)
        project_type = detect_project_type(resolved, project_root)
        validation_commands = suggest_validation_commands(resolved, project_root)
        state_signature = _workflow_state_signature(resolved, project_root)
        cache_key = (
            str(project_root.resolve()),
            str(resolved.resolve()),
            target,
            goal,
            str(max_files),
            str(include_tests),
            str(include_git_diff),
            str(include_docs),
            str(budget_tokens),
            state_signature,
        )
        with _WORKFLOW_CACHE_LOCK:
            cached_payload = _touch_cache_entry(_CONTEXT_PACK_CACHE, cache_key)
            if cached_payload is None:
                cached_payload = _load_disk_cached_response("context-pack", cache_key)
                if cached_payload is not None:
                    _store_cache_entry(_CONTEXT_PACK_CACHE, cache_key, cached_payload)
        if cached_payload is not None:
            cached = _safe_cached_json_payload(cached_payload)
            if cached is not None and isinstance(cached.get("details"), dict):
                cached["details"]["cached"] = True
                return json.dumps(cached, ensure_ascii=False)

        config_paths = [
            _display_path(
                Path(path),
                active_project_dir=active_project_dir,
                project_root=project_root,
                path_from_active_root=path_from_active_root,
            )
            for path in _config_file_paths(resolved, project_root)
        ]

        selected_files, selection_error = await _select_context_candidates(
            target=target,
            goal=goal,
            max_files=max_files,
            resolved=resolved,
            active_project_dir=active_project_dir,
            project_root=project_root,
            path_from_active_root=path_from_active_root,
            find_relevant_files=find_relevant_files,
            json_response=json_response,
        )
        if selection_error is not None:
            return selection_error

        if include_docs:
            for doc_name in ("README.md", "README.rst"):
                doc_path = project_root / doc_name
                if doc_path.exists():
                    selected_files.append(
                        _display_path(
                            doc_path,
                            active_project_dir=active_project_dir,
                            project_root=project_root,
                            path_from_active_root=path_from_active_root,
                        )
                    )
                    break

        test_files = _collect_test_files(
            include_tests=include_tests,
            resolved=resolved,
            project_root=project_root,
            project_type=project_type,
            active_project_dir=active_project_dir,
            path_from_active_root=path_from_active_root,
            iter_searchable_files=iter_searchable_files,
        )

        selected_files.extend(config_paths)
        if include_tests:
            selected_files.extend(test_files)
        selected_files = _dedupe_paths(selected_files)[:max_files]

        git_status = git_status_snapshot(project_root) if include_git_diff else None
        budget_info = _selected_file_budget(
            selected_files,
            budget_tokens=budget_tokens,
            resolve_path=resolve_path,
        )
        if not budget_info.get("within_budget", True):
            within_budget: list[str] = []
            running = 0
            for est in budget_info["file_estimates"]:
                if running + est["estimated_tokens"] > budget_tokens:
                    break
                within_budget.append(est["path"])
                running += est["estimated_tokens"]
            if within_budget:
                selected_files = within_budget
                budget_info = _selected_file_budget(
                    selected_files,
                    budget_tokens=budget_tokens,
                    resolve_path=resolve_path,
                )
        details: dict[str, Any] = {
            "target": target,
            "goal": goal,
            "project_type": project_type,
            "selected_files": selected_files,
            "test_files": test_files,
            "config_files": config_paths,
            "validation_commands": validation_commands,
            "risk_notes": _risk_notes_for_project_type(project_type),
            "next_recommended_tools": ["read_file", "run_workflow", "find_relevant_files"],
            "file_estimates": budget_info["file_estimates"],
        }
        if git_status is not None:
            details["git_status"] = git_status
        details["cached"] = False
        details.update(
            {key: value for key, value in budget_info.items() if key != "file_estimates"}
        )
        response = json_response(True, f"Built context pack for {target}", details=details)
        with _WORKFLOW_CACHE_LOCK:
            _store_cache_entry(_CONTEXT_PACK_CACHE, cache_key, response)
            try:
                _write_disk_cached_response("context-pack", cache_key, response)
            except OSError:
                pass
        return response

    return _inner()
