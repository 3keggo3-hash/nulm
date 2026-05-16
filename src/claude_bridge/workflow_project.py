"""Project type detection, file helpers and validation suggestions."""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from claude_bridge.tool_utils import path_outside_project_details


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
            "Entrypoint and settings interactions often matter as much as the target module.",
        ],
        "node": [
            "Scripts and tooling behavior may be driven by package.json over source files.",
        ],
        "vite": [
            "Frontend runtime and build behavior can depend on vite.config and tsconfig details.",
        ],
        "nextjs": [
            "Routing, build output, boundaries may depend on next.config and structure.",
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
