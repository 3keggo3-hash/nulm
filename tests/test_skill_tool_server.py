"""Tests for skill MCP tools."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
from pathlib import Path

from claude_bridge import server as mcp_server
from claude_bridge import skill_registry
from claude_bridge.skill_schema import SkillMeta


async def test_recommend_skills_returns_schema(temp_project: Path, monkeypatch) -> None:
    monkeypatch.chdir(temp_project)
    skill_registry._registry = None
    registry = skill_registry.get_registry()
    registry.register(
        "docs",
        SkillMeta(name="docs", version="1.0", trigger_phrases=["release notes"]),
        "def run(ctx): return None",
    )

    payload = json.loads(await mcp_server.recommend_skills("write release notes"))

    assert payload["ok"] is True
    assert payload["details"]["schema_version"] == "skill_recommendations.v1"
    assert payload["details"]["matches"][0]["name"] == "docs"


async def test_list_skills_returns_metadata_only(temp_project: Path, monkeypatch) -> None:
    monkeypatch.chdir(temp_project)
    skill_registry._registry = None
    registry = skill_registry.get_registry()
    registry.register(
        "secretive",
        SkillMeta(name="secretive", version="1.0", trigger_phrases=["secretive"]),
        "SECRET = 'do-not-list'",
    )

    payload = json.loads(await mcp_server.list_skills())

    assert payload["ok"] is True
    assert payload["details"]["skills"][0]["meta"]["name"] == "secretive"
    assert "code" not in payload["details"]["skills"][0]


async def test_skill_tools_use_project_scoped_registry(temp_project: Path, tmp_path: Path) -> None:
    skill_registry.get_registry(temp_project).register(
        "project-skill",
        SkillMeta(name="project-skill", version="1.0", trigger_phrases=["project"]),
        "def run(ctx): return None",
    )
    skill_registry.get_registry(tmp_path).register(
        "other-skill",
        SkillMeta(name="other-skill", version="1.0", trigger_phrases=["other"]),
        "def run(ctx): return None",
    )

    payload = json.loads(await mcp_server.list_skills())

    names = {item["meta"]["name"] for item in payload["details"]["skills"]}
    assert "project-skill" in names
    assert "other-skill" not in names


async def test_inspect_skill_package_reports_errors(temp_project: Path) -> None:
    payload = json.loads(
        await mcp_server.inspect_skill_package(str(temp_project / "missing.tar.gz"))
    )

    assert payload["ok"] is False
    assert payload["code"] == "skill_package_invalid"
    assert payload["details"]["errors"]


async def test_inspect_skill_package_enforces_allowed_roots(
    temp_project: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.tar.gz"
    outside.write_bytes(b"not a real tar")

    payload = json.loads(await mcp_server.inspect_skill_package(str(outside)))

    assert payload["ok"] is False
    assert payload["code"] == "path_denied"


async def test_run_skill_returns_executor_result(temp_project: Path, monkeypatch) -> None:
    monkeypatch.chdir(temp_project)
    skill_registry._registry = None
    registry = skill_registry.get_registry()
    registry.register(
        "hello",
        SkillMeta(name="hello", version="1.0", trigger_phrases=["hello"]),
        "def run(ctx): return {'message': ctx.get('task')}",
    )

    payload = json.loads(await mcp_server.run_skill("hello", '{"task": "hi"}'))

    assert payload["ok"] is True
    assert payload["details"]["schema_version"] == "skill_run.v1"
    assert payload["details"]["result"]["status"] == "success"


async def test_run_skill_requires_approval(temp_project: Path, monkeypatch) -> None:
    monkeypatch.chdir(temp_project)
    skill_registry._registry = None
    mcp_server.set_config(project_dir=temp_project, auto_approve=False)
    registry = skill_registry.get_registry()
    registry.register(
        "hello",
        SkillMeta(name="hello", version="1.0", trigger_phrases=["hello"]),
        "def run(ctx): return {'message': 'hi'}",
    )

    payload = json.loads(await mcp_server.run_skill("hello", "{}"))

    assert payload["ok"] is False
    assert payload["code"] == "approval_rejected"
