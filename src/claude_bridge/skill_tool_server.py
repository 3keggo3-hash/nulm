"""Registration helpers for skill governance MCP tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from claude_bridge.config import active_role, active_user
from claude_bridge.guard_policy import DecisionAction, ToolRequestContext
from claude_bridge.rules_engine import evaluate_runtime_policy_chain
from claude_bridge.tool_registration import ToolRegistrationContext
from claude_bridge.tool_utils import require_approval


def register_skill_tools(
    *,
    mcp: Any,
    tool_options: Callable[..., dict[str, Any]],
    audit_tool_call: Callable[..., str],
    json_response: Callable[..., str],
    resolve_path: Callable[[str], Path],
    project_dir: Callable[[], Path],
    enabled_names: set[str] | None = None,
) -> dict[str, Any]:
    """Register skill discovery, inspection, recommendation, and execution tools."""
    ctx = ToolRegistrationContext(
        mcp=mcp,
        tool_options=tool_options,
        audit_tool_call=audit_tool_call,
        enabled_names=enabled_names,
    )

    if ctx.should_register("list_skills"):

        async def list_skills() -> str:
            from claude_bridge.skill_registry import get_registry

            started_at = ctx.now_ms()
            skills = get_registry(project_dir()).list_skill_metadata()
            result = json_response(
                True,
                f"Skills listed: {len(skills)}",
                details={"schema_version": "skill_list.v1", "skills": skills},
            )
            return audit_tool_call("list_skills", {}, result, started_at=started_at)

        ctx.register("list_skills", "List registered skills.", list_skills, read_only=True)

    if ctx.should_register("inspect_skill"):

        async def inspect_skill(name: str) -> str:
            from claude_bridge.skill_registry import get_registry

            started_at = ctx.now_ms()
            loaded = get_registry(project_dir()).inspect_skill(name)
            if loaded is None:
                result = json_response(
                    False,
                    f"Skill '{name}' not found",
                    code="skill_not_found",
                    details={"name": name},
                )
            else:
                result = json_response(
                    True,
                    f"Skill inspected: {name}",
                    details={
                        "schema_version": "skill_inspect.v1",
                        "skill": loaded.metadata_dict(),
                    },
                )
            return audit_tool_call("inspect_skill", {"name": name}, result, started_at=started_at)

        ctx.register("inspect_skill", "Inspect a registered skill.", inspect_skill, read_only=True)

    if ctx.should_register("recommend_skills"):

        async def recommend_skills(
            query: str,
            context_json: str | None = None,
            limit: int = 5,
        ) -> str:
            from claude_bridge.skill_registry import get_registry

            started_at = ctx.now_ms()
            context, error = _parse_context_json(context_json)
            if error is not None:
                result = json_response(False, error, code="invalid_context_json", details={})
                return audit_tool_call(
                    "recommend_skills",
                    {"query": query, "context_json": context_json, "limit": limit},
                    result,
                    started_at=started_at,
                )
            matches = get_registry(project_dir()).recommend(query, context=context, limit=limit)
            result = json_response(
                True,
                f"Skill recommendations: {len(matches)}",
                details={
                    "schema_version": "skill_recommendations.v1",
                    "query": query,
                    "matches": [match.to_dict() for match in matches],
                },
            )
            return audit_tool_call(
                "recommend_skills",
                {"query": query, "context_json": context_json, "limit": limit},
                result,
                started_at=started_at,
            )

        ctx.register(
            "recommend_skills",
            "Recommend registered skills for a task.",
            recommend_skills,
            read_only=True,
        )

    if ctx.should_register("inspect_skill_package"):

        async def inspect_skill_package(package_path: str) -> str:
            from claude_bridge.skill_marketplace import inspect_package

            started_at = ctx.now_ms()
            try:
                resolved_package = resolve_path(package_path)
            except (OSError, PermissionError) as exc:
                result = json_response(
                    False,
                    str(exc),
                    code="path_denied",
                    details={"package_path": package_path},
                )
                return audit_tool_call(
                    "inspect_skill_package",
                    {"package_path": package_path},
                    result,
                    started_at=started_at,
                )
            inspection, errors = inspect_package(resolved_package, registry_root=project_dir())
            if errors:
                result = json_response(
                    False,
                    "Package inspection failed",
                    code="skill_package_invalid",
                    details={"errors": errors},
                )
            else:
                result = json_response(
                    True,
                    "Package inspected",
                    details={
                        "schema_version": "skill_package_inspect.v1",
                        "inspection": inspection,
                    },
                )
            return audit_tool_call(
                "inspect_skill_package",
                {"package_path": package_path},
                result,
                started_at=started_at,
            )

        ctx.register(
            "inspect_skill_package",
            "Inspect a local skill package without importing it.",
            inspect_skill_package,
            read_only=True,
        )

    if ctx.should_register("run_skill"):

        async def run_skill(name: str, context_json: str | None = None) -> str:
            from claude_bridge.skill_executor import get_executor

            started_at = ctx.now_ms()
            context, error = _parse_object_json(context_json)
            if error is not None:
                result = json_response(False, error, code="invalid_context_json", details={})
                return audit_tool_call(
                    "run_skill",
                    {"name": name, "context_json": context_json},
                    result,
                    started_at=started_at,
                )
            policy_params = {"name": name, "context_json": context_json}
            policy_context = ToolRequestContext(
                tool_name="run_skill",
                params=policy_params,
                project_dir=str(project_dir()),
                role=active_role(),
                user=active_user(),
            )
            rule_decision = evaluate_runtime_policy_chain(policy_context)
            if rule_decision is not None and rule_decision.action == DecisionAction.DENY:
                result = json_response(
                    False,
                    rule_decision.reason,
                    code="policy_denied",
                    details={"name": name},
                    decision=rule_decision,
                    decision_in_details=True,
                )
                return audit_tool_call(
                    "run_skill",
                    policy_params,
                    result,
                    started_at=started_at,
                )
            if rule_decision is None or rule_decision.action == DecisionAction.ASK:
                rejection = await require_approval(
                    "run_skill",
                    policy_params,
                    rejection_message=(
                        rule_decision.reason
                        if rule_decision is not None
                        else "Skill execution rejected by user"
                    ),
                    rejection_details={"name": name},
                )
                if rejection is not None:
                    if rule_decision is not None:
                        result = json_response(
                            False,
                            rule_decision.reason,
                            code="approval_rejected",
                            details={"name": name},
                            decision=rule_decision,
                            decision_in_details=True,
                        )
                    else:
                        result = rejection
                    return audit_tool_call(
                        "run_skill",
                        policy_params,
                        result,
                        started_at=started_at,
                    )
            skill_result = get_executor().run_skill(
                name,
                context=context,
                registry_root=project_dir(),
            )
            ok = skill_result.status == "success"
            result = json_response(
                ok,
                f"Skill finished with status: {skill_result.status}",
                code=None if ok else "skill_execution_failed",
                details={"schema_version": "skill_run.v1", "result": skill_result.to_dict()},
            )
            return audit_tool_call(
                "run_skill",
                {"name": name, "context_json": context_json},
                result,
                started_at=started_at,
            )

        ctx.register("run_skill", "Run a registered skill.", run_skill, destructive=True)

    return ctx.results


def _parse_context_json(raw: str | None) -> tuple[list[str], str | None]:
    if raw is None or raw == "":
        return [], None
    raw_json = raw
    try:
        value = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        return [], f"Invalid JSON: {exc}"
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return [], "context_json must be a JSON string array"
    return value, None


def _parse_object_json(raw: str | None) -> tuple[dict[str, Any], str | None]:
    if raw is None or raw == "":
        return {}, None
    raw_json = raw
    try:
        value = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        return {}, f"Invalid JSON: {exc}"
    if not isinstance(value, dict):
        return {}, "context_json must be a JSON object"
    return value, None
