"""Workflow and bounded agent-loop helpers for Claude Bridge."""

from __future__ import annotations

import json
import os
import threading
from collections import OrderedDict
from hashlib import sha256
from pathlib import Path
from typing import Any, Awaitable, Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts.base import Message, Prompt, PromptArgument
from claude_bridge.smart import budget_metadata
from claude_bridge.smart import count_tokens_for_path as smart_count_tokens_for_path
from claude_bridge.tool_utils import path_outside_project_details
from claude_bridge.workflow_presets import (
    prompt_shortcut_catalog,
    SUPPORTED_WORKFLOW_MODES,
    WORKFLOW_DISCOVERY_TERMS,
    WORKFLOW_EXAMPLES,
    WORKFLOW_ORCHESTRATION_RULES,
    WORKFLOW_QUALITY_BAR,
    WORKFLOW_STEPS,
    WORKFLOW_WARNINGS,
    build_agent_loop_policy,
    workflow_prompt,
)

_WORKFLOW_CACHE_LOCK = threading.RLock()
_MAX_WORKFLOW_CACHE_ENTRIES = 128
_WORKFLOW_CACHE_VERSION = 1
_MAX_WORKFLOW_DISK_CACHE_FILES = 64
_CONTEXT_PACK_CACHE: OrderedDict[tuple[str, ...], str] = OrderedDict()
_WORKFLOW_PLAN_CACHE: OrderedDict[tuple[str, ...], str] = OrderedDict()


def _touch_cache_entry(
    cache: OrderedDict[tuple[str, ...], str], key: tuple[str, ...]
) -> str | None:
    value = cache.get(key)
    if value is not None:
        cache.move_to_end(key)
    return value


def _store_cache_entry(
    cache: OrderedDict[tuple[str, ...], str],
    key: tuple[str, ...],
    value: str,
) -> None:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > _MAX_WORKFLOW_CACHE_ENTRIES:
        cache.popitem(last=False)


def _workflow_cache_dir() -> Path:
    raw = os.environ.get("CLAUDE_BRIDGE_CACHE_DIR", "").strip()
    if raw:
        return (Path(raw).expanduser().resolve() / "workflow").resolve()
    xdg = os.environ.get("XDG_CACHE_HOME", "").strip()
    if xdg:
        return (Path(xdg).expanduser() / "claude-bridge" / "workflow").resolve()
    return (Path.home() / ".cache" / "claude-bridge" / "workflow").resolve()


def _workflow_cache_file(prefix: str, key: tuple[str, ...]) -> Path:
    digest = sha256("|".join(key).encode("utf-8")).hexdigest()
    return _workflow_cache_dir() / f"{prefix}-v{_WORKFLOW_CACHE_VERSION}-{digest}.json"


def _load_disk_cached_response(prefix: str, key: tuple[str, ...]) -> str | None:
    cache_file = _workflow_cache_file(prefix, key)
    if not cache_file.exists():
        return None
    try:
        raw = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("version") != _WORKFLOW_CACHE_VERSION:
        return None
    payload = raw.get("response")
    return payload if isinstance(payload, str) else None


def _prune_workflow_disk_cache() -> None:
    cache_dir = _workflow_cache_dir()
    try:
        entries = sorted(
            [path for path in cache_dir.glob("*.json") if path.is_file()],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return
    if len(entries) <= _MAX_WORKFLOW_DISK_CACHE_FILES:
        return
    for path in entries[_MAX_WORKFLOW_DISK_CACHE_FILES:]:
        try:
            path.unlink()
        except OSError:
            pass


def _write_disk_cached_response(prefix: str, key: tuple[str, ...], response: str) -> None:
    cache_file = _workflow_cache_file(prefix, key)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps({"version": _WORKFLOW_CACHE_VERSION, "response": response}, ensure_ascii=False),
        encoding="utf-8",
    )
    _prune_workflow_disk_cache()


def _workflow_recipe(
    *,
    mode: str,
    project_type: str,
    execute: bool,
    max_iterations: int,
) -> dict[str, Any]:
    recipe = {
        "mode": mode,
        "project_type": project_type,
        "shape": ["discover", "read", "analyze"],
        "execute_first_step": execute,
    }
    if mode == "agent_loop":
        recipe["shape"] = ["discover", "inspect", "patch", "validate", "decide"]
        recipe["iteration_budget"] = max_iterations
    elif mode == "orchestrate":
        recipe["shape"] = ["discover", "split_workstreams", "define_validation", "integrate"]
    elif mode == "test":
        recipe["shape"] = ["discover", "inspect_existing_tests", "design_regressions"]
    elif mode == "commit":
        recipe["shape"] = ["discover", "read_changes", "summarize_impact"]
    return recipe


def _dedupe_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        unique.append(path)
    return unique


def _build_context_pack_error(
    *,
    target: str,
    message: str,
    code: str,
    json_response: Callable[..., str],
    details: dict[str, Any] | None = None,
) -> str:
    return json_response(False, message, code=code, details=details or {"path": target})


def _safe_json_response_load(
    raw: str,
    *,
    json_response: Callable[..., str],
    tool_name: str,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, json_response(
            False,
            f"{tool_name} returned invalid JSON",
            code="invalid_tool_payload",
            details={"tool": tool_name, "error": str(exc)},
        )
    if not isinstance(payload, dict):
        return None, json_response(
            False,
            f"{tool_name} returned a non-object payload",
            code="invalid_tool_payload",
            details={"tool": tool_name, "payload_type": type(payload).__name__},
        )
    return payload, None


def _display_path(
    path: Path,
    *,
    active_project_dir: Path,
    project_root: Path,
    path_from_active_root: Callable[[Path], str],
) -> str:
    if project_root == active_project_dir:
        return path_from_active_root(path)
    return str(path)


def _path_signature(path: Path) -> str:
    try:
        stat = path.stat()
    except OSError:
        return f"{path.resolve()}:missing"
    return f"{path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}"


def _workflow_state_signature(resolved: Path, project_root: Path) -> str:
    signatures = [_path_signature(resolved)]
    for extra in supplemental_review_targets(resolved, project_root):
        signatures.append(_path_signature(extra))
    for doc_name in (
        "README.md",
        "README.rst",
        "pyproject.toml",
        "package.json",
        "Cargo.toml",
        "go.mod",
    ):
        candidate = project_root / doc_name
        if candidate.exists():
            signatures.append(_path_signature(candidate))
    return "|".join(signatures)


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


async def _execute_workflow_first_step(
    *,
    mode: str,
    target: str,
    option: str | None,
    max_iterations: int,
    resolved: Path,
    active_project_dir: Path,
    project_root: Path,
    path_from_active_root: Callable[[Path], str],
    read_file: Callable[[str], Awaitable[str]],
    list_directory: Callable[[str], Awaitable[str]],
    find_relevant_files: Callable[..., Awaitable[str]],
    json_response: Callable[..., str],
) -> tuple[dict[str, Any] | None, str | None]:
    read_targets_for_plan: list[str] = []
    if resolved.is_file():
        performed = ["read_file"]
        read_raw = await read_file(target)
        read_payload, parse_error = _safe_json_response_load(
            read_raw,
            json_response=json_response,
            tool_name="read_file",
        )
        if parse_error is not None or read_payload is None:
            return None, parse_error
        results = [read_payload]
        read_targets_for_plan.append(target)
        extra_targets = supplemental_review_targets(resolved, project_root)
        for extra in extra_targets:
            performed.append("read_file")
            extra_target = _display_path(
                extra,
                active_project_dir=active_project_dir,
                project_root=project_root,
                path_from_active_root=path_from_active_root,
            )
            read_targets_for_plan.append(extra_target)
            extra_read_raw = await read_file(extra_target)
            extra_read_payload, parse_error = _safe_json_response_load(
                extra_read_raw,
                json_response=json_response,
                tool_name="read_file",
            )
            if parse_error is not None or extra_read_payload is None:
                return None, parse_error
            results.append(extra_read_payload)
        execution: dict[str, Any] = {"performed_actions": performed, "results": results}
        if mode == "agent_loop":
            execution["loop_plan"] = build_agent_loop_execution_plan(
                target=target,
                resolved=resolved,
                max_iterations=max_iterations,
                read_targets=read_targets_for_plan,
                project_root=project_root,
            )
        return execution, None

    performed = ["list_directory", "find_relevant_files"]
    list_raw = await list_directory(target)
    list_payload, parse_error = _safe_json_response_load(
        list_raw,
        json_response=json_response,
        tool_name="list_directory",
    )
    if parse_error is not None or list_payload is None:
        return None, parse_error
    results = [list_payload]
    relevant_raw = await find_relevant_files(
        query=option or WORKFLOW_DISCOVERY_TERMS[mode],
        path=target,
        limit=max(max_iterations, 3),
    )
    relevant_payload, parse_error = _safe_json_response_load(
        relevant_raw,
        json_response=json_response,
        tool_name="find_relevant_files",
    )
    if parse_error is not None or relevant_payload is None:
        return None, parse_error
    results.append(relevant_payload)
    if not relevant_payload.get("ok", False):
        return {"performed_actions": performed, "results": results}, json_response(
            False,
            relevant_payload["message"],
            code=relevant_payload.get("code"),
            details=relevant_payload.get("details", {}),
        )
    read_targets: list[str] = []
    for item in relevant_payload["details"].get("results", [])[: max(max_iterations, 3)]:
        best_match = item["path"]
        read_target = (
            f"{target.rstrip('/')}/{best_match}" if target not in {".", ""} else best_match
        )
        if read_target not in read_targets:
            read_targets.append(read_target)
    for extra in supplemental_review_targets(resolved, project_root):
        extra_target = _display_path(
            extra,
            active_project_dir=active_project_dir,
            project_root=project_root,
            path_from_active_root=path_from_active_root,
        )
        if extra_target not in read_targets:
            read_targets.append(extra_target)
    if read_targets:
        read_targets_for_plan.extend(read_targets)
        performed.append("read_file")
        results.append(
            {"ok": True, "message": "Planned read targets", "details": {"targets": read_targets}}
        )
        for read_target in read_targets:
            performed.append("read_file")
            read_raw = await read_file(read_target)
            read_payload, parse_error = _safe_json_response_load(
                read_raw,
                json_response=json_response,
                tool_name="read_file",
            )
            if parse_error is not None or read_payload is None:
                return None, parse_error
            results.append(read_payload)
    execution = {"performed_actions": performed, "results": results}
    if mode == "agent_loop":
        execution["loop_plan"] = build_agent_loop_execution_plan(
            target=target,
            resolved=resolved,
            max_iterations=max_iterations,
            read_targets=read_targets_for_plan,
            project_root=project_root,
        )
    return execution, None


def detect_project_type(path: Path, project_root: Path) -> str:
    target = path if path.exists() else project_root

    if target.suffix == ".gd" or (project_root / "project.godot").exists():
        return "godot"
    if (project_root / "manage.py").exists():
        return "django"
    if (project_root / "package.json").exists():
        if (project_root / "vite.config.ts").exists() or (project_root / "vite.config.js").exists():
            return "vite"
        if (project_root / "next.config.js").exists() or (
            project_root / "next.config.mjs"
        ).exists():
            return "nextjs"
        return "node"
    if (project_root / "Cargo.toml").exists():
        return "rust"
    if (project_root / "go.mod").exists():
        return "go"
    if any(
        (project_root / name).exists()
        for name in ("pyproject.toml", "requirements.txt", "setup.py")
    ):
        return "python"
    return "unknown"


def supplemental_review_targets(target: Path, project_root: Path) -> list[Path]:
    project_type = detect_project_type(target, project_root)
    candidates: list[Path] = []

    framework_candidates: dict[str, list[Path]] = {
        "godot": [
            project_root / "project.godot",
            project_root / "export_presets.cfg",
        ],
        "python": [
            project_root / "pyproject.toml",
            project_root / "requirements.txt",
            project_root / "pytest.ini",
        ],
        "django": [
            project_root / "manage.py",
            project_root / "pyproject.toml",
            project_root / "requirements.txt",
        ],
        "node": [
            project_root / "package.json",
            project_root / "tsconfig.json",
        ],
        "vite": [
            project_root / "package.json",
            project_root / "vite.config.ts",
            project_root / "vite.config.js",
            project_root / "tsconfig.json",
        ],
        "nextjs": [
            project_root / "package.json",
            project_root / "next.config.js",
            project_root / "next.config.mjs",
            project_root / "tsconfig.json",
        ],
        "rust": [
            project_root / "Cargo.toml",
            project_root / "Cargo.lock",
        ],
        "go": [
            project_root / "go.mod",
            project_root / "go.sum",
        ],
    }

    for candidate in framework_candidates.get(project_type, []):
        if candidate.exists() and candidate not in candidates:
            candidates.append(candidate)

    if project_type == "godot" and (project_root / "scenes").is_dir():
        scene_files = sorted((project_root / "scenes").rglob("*.tscn"))
        if scene_files and scene_files[0] not in candidates:
            candidates.append(scene_files[0])

    if target.is_file():
        candidates = [candidate for candidate in candidates if candidate != target]

    return candidates[:3]


def _config_file_paths(target: Path, project_root: Path) -> list[str]:
    return [str(path) for path in supplemental_review_targets(target, project_root)]


def _language_suffixes_for_project_type(project_type: str) -> set[str]:
    mapping = {
        "python": {".py"},
        "django": {".py"},
        "node": {".js", ".jsx", ".ts", ".tsx"},
        "vite": {".js", ".jsx", ".ts", ".tsx"},
        "nextjs": {".js", ".jsx", ".ts", ".tsx"},
        "rust": {".rs"},
        "go": {".go"},
        "godot": {".gd"},
    }
    return mapping.get(project_type, set())


def _test_file_score(path: Path, *, project_type: str, target_root: Path) -> int:
    lowered = path.as_posix().lower()
    score = 0
    if "/tests/" in lowered or lowered.startswith("tests/"):
        score += 3
    if "/test/" in lowered or lowered.startswith("test/"):
        score += 2
    if any(token in path.name.lower() for token in ("test", "spec")):
        score += 2
    if path.suffix in _language_suffixes_for_project_type(project_type):
        score += 2
    if target_root != Path(".") and target_root in path.parents:
        score += 2
    if path.name.lower().startswith("test_") or path.name.lower().endswith("_test.go"):
        score += 1
    return score


def _risk_notes_for_project_type(project_type: str) -> list[str]:
    notes = {
        "godot": [
            "Runtime behavior may depend on scene files and project.godot settings.",
            "Export presets can affect shipped behavior even when script code looks correct.",
        ],
        "python": [
            "Environment and test runner configuration may live in pyproject.toml or pytest.ini.",
        ],
        "django": [
            "Entrypoint and settings interactions often matter as much as the target module itself.",
        ],
        "node": [
            "Scripts and tooling behavior may be driven by package.json rather than source files alone.",
        ],
        "vite": [
            "Frontend runtime and build behavior can depend on vite.config and tsconfig details.",
        ],
        "nextjs": [
            "Routing, build output, and server/client boundaries may depend on next.config and app structure.",
        ],
        "rust": [
            "Cargo.toml features and workspace layout can change build and test behavior.",
        ],
        "go": [
            "Module boundaries and package tests can affect behavior outside the current folder.",
        ],
    }
    return notes.get(
        project_type,
        ["Cross-check config, tests, and entrypoints before assuming the target is isolated."],
    )


def suggest_validation_commands(resolved: Path, project_root: Path) -> list[str]:
    commands: list[str] = []
    project_type = detect_project_type(resolved, project_root)

    if project_type in {"python", "django"}:
        commands.append("python3 -m pytest")
    elif project_type in {"node", "vite", "nextjs"}:
        commands.extend(["npm test", "git diff"])
    elif project_type == "rust":
        commands.extend(["cargo test", "git diff"])
    elif project_type == "go":
        commands.extend(["go test ./...", "git diff"])
    elif project_type == "godot":
        commands.append("git diff")
    elif resolved.is_dir() and any((resolved / name).exists() for name in {"tests", "test"}):
        commands.append("python3 -m pytest")
    elif any((project_root / name).exists() for name in {"tests", "test"}):
        commands.append("python3 -m pytest")

    if "git diff" not in commands:
        commands.append("git diff")
    return list(dict.fromkeys(commands))


async def build_validation_suggestions(
    *,
    target: str,
    resolve_path: Callable[[str], Path],
    infer_project_root: Callable[[Path], Path],
    json_response: Callable[..., str],
) -> str:
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
        return json_response(
            False,
            f"Path not found: {target}",
            code="path_not_found",
            details={"path": target},
        )

    project_root = infer_project_root(resolved)
    project_type = detect_project_type(resolved, project_root)
    commands = suggest_validation_commands(resolved, project_root)
    return json_response(
        True,
        f"Suggested validation commands for {target}",
        details={
            "target": target,
            "resolved_path": str(resolved),
            "project_type": project_type,
            "validation_commands": commands,
            "risk_notes": _risk_notes_for_project_type(project_type),
        },
    )


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
            cached = json.loads(cached_payload)
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


def build_agent_loop_execution_plan(
    *,
    target: str,
    resolved: Path,
    max_iterations: int,
    read_targets: list[str],
    project_root: Path,
) -> dict[str, Any]:
    validation_commands = suggest_validation_commands(resolved, project_root)
    focus_target = read_targets[0] if read_targets else target
    return {
        "iteration_budget": max_iterations,
        "current_iteration": 1,
        "project_type": detect_project_type(resolved, project_root),
        "focus_target": focus_target,
        "inspect_targets": read_targets,
        "proposed_patch_strategy": "make the smallest reversible change that tests the current hypothesis",
        "validation_commands": validation_commands,
        "decision_rule": "continue only if validation yields clearer evidence or a narrower fix",
        "stop_if": [
            "the first validation passes",
            "the next patch would broaden scope beyond the current target",
            "the evidence stays ambiguous after the current iteration",
        ],
    }


async def run_agent_loop_step(
    *,
    file: str,
    search: str,
    replace: str,
    validation_command: str,
    iteration: int,
    max_iterations: int,
    patch_file: Callable[..., Awaitable[str]],
    run_shell: Callable[[str], Awaitable[str]],
    json_response: Callable[..., str],
) -> str:
    if iteration < 1:
        return json_response(
            False,
            "iteration must be at least 1",
            code="invalid_iteration",
            details={"iteration": iteration},
        )
    if max_iterations < 1:
        return json_response(
            False,
            "max_iterations must be at least 1",
            code="invalid_max_iterations",
            details={"max_iterations": max_iterations},
        )
    if iteration > max_iterations:
        return json_response(
            False,
            "iteration cannot exceed max_iterations",
            code="invalid_iteration_budget",
            details={"iteration": iteration, "max_iterations": max_iterations},
        )

    try:
        patch_payload = json.loads(await patch_file(file=file, search=search, replace=replace))
    except (json.JSONDecodeError, TypeError):
        return json_response(
            False,
            "Agent loop step failed: patch_file returned invalid JSON",
            code="agent_loop_patch_failed",
            details={"iteration": iteration, "max_iterations": max_iterations, "decision": "stop"},
        )
    if not isinstance(patch_payload, dict) or not patch_payload.get("ok"):
        return json_response(
            False,
            "Agent loop step failed during patch phase",
            code="agent_loop_patch_failed",
            details={
                "iteration": iteration,
                "max_iterations": max_iterations,
                "patch_result": patch_payload,
                "decision": "stop",
            },
        )

    try:
        validation_payload = json.loads(await run_shell(validation_command))
    except (json.JSONDecodeError, TypeError):
        validation_ok = False
        validation_payload = {"ok": False}
    else:
        validation_ok = bool(validation_payload.get("ok", False))
    decision = (
        "stop_success"
        if validation_ok
        else ("continue" if iteration < max_iterations else "stop_failure")
    )

    return json_response(
        True,
        "Agent loop step executed",
        details={
            "iteration": iteration,
            "max_iterations": max_iterations,
            "patch_result": patch_payload,
            "validation_result": validation_payload,
            "decision": decision,
            "next_action": (
                "stop"
                if decision == "stop_success"
                else "inspect validation output and prepare the next smallest patch"
            ),
        },
    )


def build_agent_loop_session_summary(
    session_results: list[dict[str, Any]],
    *,
    max_iterations: int,
    final_decision: str,
    results_compacted: bool = False,
    compacted_steps: int = 0,
    retained_recent_steps: int = 0,
) -> dict[str, Any]:
    files_touched: list[str] = []
    last_successful_file: str | None = None
    last_validation_command: str | None = None
    last_validation_ok: bool | None = None

    for result in session_results:
        details = result.get("details", {})
        patch_result = details.get("patch_result", {})
        validation_result = details.get("validation_result", {})
        patch_details = patch_result.get("details", {})
        validation_details = validation_result.get("details", {})

        path = patch_details.get("path")
        if isinstance(path, str):
            if path not in files_touched:
                files_touched.append(path)
            if patch_result.get("ok"):
                last_successful_file = path

        command = validation_details.get("command")
        if isinstance(command, str):
            last_validation_command = command

        if isinstance(validation_result.get("ok"), bool):
            last_validation_ok = validation_result["ok"]

    remaining_budget = max(max_iterations - len(session_results), 0)
    if final_decision == "stop_success":
        next_recommended_action = "stop"
    elif final_decision == "stop_failure":
        next_recommended_action = (
            "inspect the last validation failure before planning another session"
        )
    else:
        next_recommended_action = "prepare the next smallest reversible patch"

    validation_label = (
        "passed" if last_validation_ok else ("failed" if last_validation_ok is False else "not run")
    )
    handoff_summary = (
        f"Executed {len(session_results)} step(s); final decision: {final_decision}. "
        f"Files touched: {', '.join(files_touched) if files_touched else 'none'}. "
        f"Last validation {validation_label}"
        f"{f' via {last_validation_command}' if last_validation_command else ''}. "
        f"Next action: {next_recommended_action}."
    )

    return {
        "executed_steps": len(session_results),
        "final_decision": final_decision,
        "files_touched": files_touched,
        "last_successful_file": last_successful_file,
        "last_validation_ok": last_validation_ok,
        "last_validation_command": last_validation_command,
        "remaining_budget": remaining_budget,
        "next_recommended_action": next_recommended_action,
        "results_compacted": results_compacted,
        "compacted_steps": compacted_steps,
        "retained_recent_steps": retained_recent_steps,
        "handoff_summary": handoff_summary,
    }


def compact_agent_loop_result(result: dict[str, Any]) -> dict[str, Any]:
    details = result.get("details", {})
    patch_result = details.get("patch_result", {})
    validation_result = details.get("validation_result", {})
    patch_details = patch_result.get("details", {})
    validation_details = validation_result.get("details", {})
    return {
        "iteration": details.get("iteration"),
        "decision": details.get("decision"),
        "file": patch_details.get("path"),
        "validation_ok": validation_result.get("ok"),
        "validation_command": validation_details.get("command"),
        "message": result.get("message"),
    }


def compact_agent_loop_session_results(
    session_results: list[dict[str, Any]],
    *,
    compact_threshold: int,
    keep_recent_results: int,
) -> tuple[bool, list[dict[str, Any]], list[dict[str, Any]], int]:
    if len(session_results) <= compact_threshold:
        return False, [], session_results, len(session_results)

    if keep_recent_results >= len(session_results):
        return False, [], session_results, len(session_results)

    older_results = session_results[:-keep_recent_results]
    recent_results = session_results[-keep_recent_results:]
    compacted_history = [compact_agent_loop_result(result) for result in older_results]
    return True, compacted_history, recent_results, len(recent_results)


async def run_agent_loop_session(
    *,
    steps_json: str | None,
    steps: list[dict[str, Any]] | None,
    max_iterations: int,
    compact_threshold: int,
    keep_recent_results: int,
    run_agent_loop_step: Callable[..., Awaitable[str]],
    json_response: Callable[..., str],
) -> str:
    if max_iterations < 1:
        return json_response(
            False,
            "max_iterations must be at least 1",
            code="invalid_max_iterations",
            details={"max_iterations": max_iterations},
        )
    if compact_threshold < 1:
        return json_response(
            False,
            "compact_threshold must be at least 1",
            code="invalid_compact_threshold",
            details={"compact_threshold": compact_threshold},
        )
    if keep_recent_results < 1:
        return json_response(
            False,
            "keep_recent_results must be at least 1",
            code="invalid_keep_recent_results",
            details={"keep_recent_results": keep_recent_results},
        )

    planned_input = steps
    if planned_input is None:
        if steps_json is None:
            return json_response(
                False,
                "Either steps or steps_json must be provided",
                code="missing_steps",
                details={},
            )
        try:
            planned_input = json.loads(steps_json)
        except json.JSONDecodeError as exc:
            return json_response(
                False,
                f"Invalid steps_json: {exc}",
                code="invalid_steps_json",
                details={"steps_json": steps_json},
            )

    if not isinstance(planned_input, list) or not planned_input:
        return json_response(
            False,
            "steps must be a non-empty list",
            code="invalid_steps_payload",
            details={"steps_json": steps_json, "steps": planned_input},
        )

    planned_steps = planned_input[:max_iterations]
    session_results: list[dict[str, Any]] = []
    final_decision = "stop_failure"

    for iteration, step in enumerate(planned_steps, start=1):
        if not isinstance(step, dict):
            return json_response(
                False,
                "Each step must be an object",
                code="invalid_step_entry",
                details={"step": step, "iteration": iteration},
            )

        required = {"file", "search", "replace", "validation_command"}
        missing = sorted(required - set(step))
        if missing:
            return json_response(
                False,
                "Step is missing required fields",
                code="invalid_step_fields",
                details={"iteration": iteration, "missing_fields": missing},
            )

        step_result = json.loads(
            await run_agent_loop_step(
                file=step["file"],
                search=step["search"],
                replace=step["replace"],
                validation_command=step["validation_command"],
                iteration=iteration,
                max_iterations=max_iterations,
            )
        )
        session_results.append(step_result)

        if not step_result["ok"]:
            final_decision = "stop_failure"
            break

        final_decision = step_result["details"]["decision"]
        if final_decision in {"stop_success", "stop_failure"}:
            break

    results_compacted, compacted_history, visible_results, retained_recent_steps = (
        compact_agent_loop_session_results(
            session_results,
            compact_threshold=compact_threshold,
            keep_recent_results=keep_recent_results,
        )
    )
    session_summary = build_agent_loop_session_summary(
        session_results,
        max_iterations=max_iterations,
        final_decision=final_decision,
        results_compacted=results_compacted,
        compacted_steps=len(compacted_history),
        retained_recent_steps=retained_recent_steps,
    )

    return json_response(
        True,
        "Agent loop session executed",
        details={
            "max_iterations": max_iterations,
            "compact_threshold": compact_threshold,
            "keep_recent_results": keep_recent_results,
            "executed_steps": len(session_results),
            "final_decision": final_decision,
            "results_compacted": results_compacted,
            "compacted_steps": len(compacted_history),
            "compacted_history": compacted_history,
            "session_summary": session_summary,
            "results": visible_results,
        },
    )


async def run_workflow(
    *,
    mode: str,
    target: str,
    option: str | None,
    language: str,
    execute: bool,
    max_iterations: int,
    resolve_path: Callable[[str], Path],
    read_file: Callable[[str], Awaitable[str]],
    list_directory: Callable[[str], Awaitable[str]],
    find_relevant_files: Callable[..., Awaitable[str]],
    path_from_active_root: Callable[[Path], str],
    project_dir: Callable[[], Path],
    infer_project_root: Callable[[Path], Path],
    json_response: Callable[..., str],
) -> str:
    if mode not in SUPPORTED_WORKFLOW_MODES:
        return json_response(
            False,
            f"Unsupported workflow mode: {mode}",
            code="unknown_workflow_mode",
            details={"mode": mode},
        )
    if max_iterations < 1:
        return json_response(
            False,
            "max_iterations must be at least 1",
            code="invalid_max_iterations",
            details={"max_iterations": max_iterations},
        )

    prompt = workflow_prompt(mode, target, option, language)
    try:
        resolved_for_type = resolve_path(target)
    except PermissionError as exc:
        return json_response(
            False,
            str(exc),
            code="path_outside_project",
            details=path_outside_project_details(target),
        )
    active_project_dir = project_dir()
    project_root = infer_project_root(resolved_for_type)
    project_type = detect_project_type(resolved_for_type, project_root)
    state_signature = _workflow_state_signature(resolved_for_type, project_root)
    cache_key = (
        mode,
        target,
        option or "",
        language,
        str(max_iterations),
        str(project_root.resolve()),
        str(resolved_for_type.resolve()),
        state_signature,
    )
    if not execute:
        with _WORKFLOW_CACHE_LOCK:
            cached_payload = _touch_cache_entry(_WORKFLOW_PLAN_CACHE, cache_key)
            if cached_payload is None:
                cached_payload = _load_disk_cached_response("workflow-plan", cache_key)
                if cached_payload is not None:
                    _store_cache_entry(_WORKFLOW_PLAN_CACHE, cache_key, cached_payload)
        if cached_payload is not None:
            cached = json.loads(cached_payload)
            cached["details"]["cached"] = True
            return json.dumps(cached, ensure_ascii=False)
    recommended_tools = ["list_directory", "read_file"]
    if mode == "todo":
        recommended_tools.append("run_shell")
    steps = WORKFLOW_STEPS[mode]
    examples = WORKFLOW_EXAMPLES[mode]
    warnings = WORKFLOW_WARNINGS
    quality_bar = WORKFLOW_QUALITY_BAR
    orchestration_rules = WORKFLOW_ORCHESTRATION_RULES
    agent_loop_policy = build_agent_loop_policy(max_iterations)

    execution: dict[str, Any] | None = None
    if execute:
        execution, execution_error = await _execute_workflow_first_step(
            mode=mode,
            target=target,
            option=option,
            max_iterations=max_iterations,
            resolved=resolved_for_type,
            active_project_dir=active_project_dir,
            project_root=project_root,
            path_from_active_root=path_from_active_root,
            read_file=read_file,
            list_directory=list_directory,
            find_relevant_files=find_relevant_files,
            json_response=json_response,
        )
        if execution_error is not None:
            error_details: dict[str, Any] = {
                "mode": mode,
                "target": target,
                "project_type": project_type,
                "prompt": prompt,
                "recommended_tools": recommended_tools,
                "steps": steps,
                "examples": examples,
                "warnings": warnings,
                "quality_bar": quality_bar,
                "orchestration_rules": orchestration_rules,
                "agent_loop_policy": agent_loop_policy,
                "execute": execute,
                "max_iterations": max_iterations,
                "execution": execution,
            }
            error_payload = json.loads(execution_error)
            return json_response(
                False,
                error_payload["message"],
                code=error_payload.get("code"),
                details=error_details,
            )

    details: dict[str, Any] = {
        "mode": mode,
        "target": target,
        "project_type": project_type,
        "prompt": prompt,
        "recommended_tools": recommended_tools,
        "steps": steps,
        "examples": examples,
        "warnings": warnings,
        "quality_bar": quality_bar,
        "orchestration_rules": orchestration_rules,
        "agent_loop_policy": agent_loop_policy,
        "execute": execute,
        "max_iterations": max_iterations,
        "cached": False,
        "recipe": _workflow_recipe(
            mode=mode,
            project_type=project_type,
            execute=execute,
            max_iterations=max_iterations,
        ),
    }
    if execution is not None:
        details["execution"] = execution

    response = json_response(True, f"Workflow prepared for mode: {mode}", details=details)
    if not execute:
        with _WORKFLOW_CACHE_LOCK:
            _store_cache_entry(_WORKFLOW_PLAN_CACHE, cache_key, response)
            try:
                _write_disk_cached_response("workflow-plan", cache_key, response)
            except OSError:
                pass
    return response


def register_prompts(mcp: FastMCP) -> None:
    def review_prompt(target: str = ".", focus: str = "bugs and missing tests") -> Message:
        return Message(workflow_prompt("review", target, focus, "Turkish"), role="user")

    def optimize_prompt(target: str = ".", focus: str = "performance and readability") -> Message:
        return Message(workflow_prompt("optimize", target, focus, "Turkish"), role="user")

    def orchestrate_prompt(
        target: str = ".",
        focus: str = "decompose into independent workstreams with clear ownership",
    ) -> Message:
        return Message(workflow_prompt("orchestrate", target, focus, "Turkish"), role="user")

    def agent_loop_prompt(
        target: str = ".",
        goal: str = "fix the current issue with small validated steps",
    ) -> Message:
        return Message(workflow_prompt("agent_loop", target, goal, "Turkish"), role="user")

    def quality_prompt(
        target: str = ".",
        focus: str = "correctness, regression safety, readability, tests, and verification depth",
    ) -> Message:
        return Message(workflow_prompt("quality", target, focus, "Turkish"), role="user")

    def test_prompt(target: str = ".", test_style: str = "regression tests") -> Message:
        return Message(workflow_prompt("test", target, test_style, "Turkish"), role="user")

    def todo_prompt(target: str = ".", keywords: str = "TODO, FIXME, HACK, XXX") -> Message:
        return Message(workflow_prompt("todo", target, keywords, "Turkish"), role="user")

    def explain_prompt(
        target: str = ".",
        audience: str = "a junior developer",
        language: str = "Turkish",
    ) -> Message:
        return Message(workflow_prompt("explain", target, audience, language), role="user")

    def commit_prompt(
        target: str = ".",
        style: str = "short imperative commit message with a concise summary",
    ) -> Message:
        return Message(workflow_prompt("commit", target, style, "Turkish"), role="user")

    def shadow_prompt(
        target: str = ".",
        focus: str = "challenge prior assumptions, verify from files, and be skeptical of earlier conclusions",
    ) -> Message:
        return Message(
            workflow_prompt("review", target, focus, "Turkish")
            + "\nTreat earlier assumptions as untrusted until the files confirm them.\n"
            + "Prefer a cold, critical reread over agreement-seeking.",
            role="user",
        )

    def benchmark_prompt(
        target: str = ".",
        focus: str = "startup cost, relevance latency, token efficiency, and cache behavior",
    ) -> Message:
        return Message(
            "Prepare a benchmark-first investigation plan.\n"
            f"Target: {target}\n"
            f"Focus: {focus}\n"
            "Response language: Turkish\n"
            "Start with the cheapest signals first.\n"
            "Separate measurement from interpretation.\n"
            "Call out what can be learned without spending a full benchmark run yet.",
            role="user",
        )

    def platform_prompt(
        target: str = ".",
        focus: str = "Linux, Windows, WSL, VS Code, and other MCP client compatibility",
    ) -> Message:
        return Message(
            "Audit cross-platform and editor compatibility.\n"
            f"Target: {target}\n"
            f"Focus: {focus}\n"
            "Response language: Turkish\n"
            "List platform assumptions, packaging risks, path issues, shell differences, and client integration gaps.\n"
            "Prefer a matrix of concrete risks and verifications over vague advice.",
            role="user",
        )

    def compact_prompt(
        target: str = ".",
        goal: str = "continue the task with a smaller, cheaper working context",
    ) -> Message:
        return Message(
            "Shrink the active context before doing more work.\n"
            f"Target: {target}\n"
            f"Goal: {goal}\n"
            "Response language: Turkish\n"
            "Prefer the smallest useful set of files, the narrowest read windows, and the cheapest next step.\n"
            "Call out what can be deferred until later if it does not fit the current budget.",
            role="user",
        )

    prompt_specs = [
        (
            "review",
            "Review code for bugs and missing tests.",
            [
                PromptArgument(
                    name="target", description="File or directory to review", required=False
                ),
                PromptArgument(name="focus", description="Specific review focus", required=False),
            ],
            review_prompt,
        ),
        (
            "optimize",
            "Optimize code for performance and maintainability.",
            [
                PromptArgument(
                    name="target", description="File or directory to optimize", required=False
                ),
                PromptArgument(name="focus", description="Optimization focus", required=False),
            ],
            optimize_prompt,
        ),
        (
            "orchestrate",
            "Turn a larger task into parallel workstreams plus an integration plan.",
            [
                PromptArgument(
                    name="target", description="File or directory to orchestrate", required=False
                ),
                PromptArgument(name="focus", description="How to split the work", required=False),
            ],
            orchestrate_prompt,
        ),
        (
            "agent_loop",
            "Plan a bounded inspect-patch-validate loop for a focused coding task.",
            [
                PromptArgument(
                    name="target", description="File or directory for the loop", required=False
                ),
                PromptArgument(
                    name="goal", description="What the loop should accomplish", required=False
                ),
            ],
            agent_loop_prompt,
        ),
        (
            "quality",
            "Evaluate code quality against a practical shipping standard.",
            [
                PromptArgument(
                    name="target", description="File or directory to evaluate", required=False
                ),
                PromptArgument(name="focus", description="Specific quality focus", required=False),
            ],
            quality_prompt,
        ),
        (
            "test",
            "Plan tests for the selected target.",
            [
                PromptArgument(
                    name="target", description="File or directory to test", required=False
                ),
                PromptArgument(
                    name="test_style", description="Preferred testing style", required=False
                ),
            ],
            test_prompt,
        ),
        (
            "todo",
            "Scan for TODO-style markers and prioritize them.",
            [
                PromptArgument(
                    name="target", description="File or directory to scan", required=False
                ),
                PromptArgument(
                    name="keywords", description="Keywords to search for", required=False
                ),
            ],
            todo_prompt,
        ),
        (
            "explain",
            "Explain how a piece of code works.",
            [
                PromptArgument(
                    name="target", description="File or directory to explain", required=False
                ),
                PromptArgument(name="audience", description="Audience level", required=False),
                PromptArgument(name="language", description="Response language", required=False),
            ],
            explain_prompt,
        ),
        (
            "commit",
            "Summarize changes and suggest a commit message.",
            [
                PromptArgument(
                    name="target", description="File or directory to summarize", required=False
                ),
                PromptArgument(
                    name="style", description="Preferred commit message style", required=False
                ),
            ],
            commit_prompt,
        ),
        (
            "compact",
            "Shrink the active context and continue with a lower-cost plan.",
            [
                PromptArgument(
                    name="target", description="File or directory to narrow", required=False
                ),
                PromptArgument(
                    name="goal", description="What to preserve while compacting", required=False
                ),
            ],
            compact_prompt,
        ),
        (
            "shadow",
            "Re-review a target skeptically and challenge prior assumptions.",
            [
                PromptArgument(
                    name="target", description="File or directory to re-review", required=False
                ),
                PromptArgument(name="focus", description="Critical review focus", required=False),
            ],
            shadow_prompt,
        ),
        (
            "benchmark",
            "Prepare a benchmark-first investigation plan.",
            [
                PromptArgument(
                    name="target", description="File or directory to assess", required=False
                ),
                PromptArgument(name="focus", description="Benchmark focus", required=False),
            ],
            benchmark_prompt,
        ),
        (
            "platform",
            "Audit cross-platform and editor compatibility gaps.",
            [
                PromptArgument(
                    name="target", description="File or directory to assess", required=False
                ),
                PromptArgument(
                    name="focus", description="Platform or client focus", required=False
                ),
            ],
            platform_prompt,
        ),
    ]

    for name, description, arguments, fn in prompt_specs:
        mcp.add_prompt(
            Prompt(
                name=name,
                title=description,
                description=description,
                arguments=arguments,
                fn=fn,
                context_kwarg=None,
            )
        )


def build_prompt_catalog_payload() -> dict[str, Any]:
    catalog = prompt_shortcut_catalog()
    return {
        "shortcuts": catalog["shortcuts"],
        "client_side_only": catalog["client_side_only"],
        "notes": catalog["notes"],
        "recommended_path": "Use an MCP prompt or slash UI when the client exposes it; fall back to run_workflow or a natural-language request only when necessary.",
    }
