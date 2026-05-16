"""Registration helpers for git-oriented MCP tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from claude_bridge.tool_registration import ToolRegistrationContext


def register_git_tools(
    *,
    mcp: Any,
    tool_options: Callable[..., dict[str, Any]],
    audit_tool_call: Callable[..., str],
    json_response: Callable[..., str],
    project_dir: Callable[[], Path],
    enabled_names: set[str] | None = None,
) -> dict[str, Any]:
    ctx = ToolRegistrationContext(
        mcp=mcp,
        tool_options=tool_options,
        audit_tool_call=audit_tool_call,
        enabled_names=enabled_names,
    )

    if ctx.should_register("commit_changes"):

        async def commit_changes(message: str) -> str:
            from claude_bridge.config import active_role, active_user
            from claude_bridge.git_ops import commit_changes as _commit_changes
            from claude_bridge.guard_policy import DecisionAction, ToolRequestContext
            from claude_bridge.rules_engine import evaluate_runtime_policy_chain
            from claude_bridge.tool_utils import require_approval

            started_at = ctx.now_ms()
            if not message.strip():
                result = json_response(
                    False,
                    "Commit message cannot be empty",
                    code="empty_message",
                    details={},
                )
                return audit_tool_call(
                    "commit_changes",
                    {"message": message},
                    result,
                    started_at=started_at,
                )
            policy_context = ToolRequestContext(
                tool_name="commit_changes",
                params={"message": message},
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
                    details={},
                    decision=rule_decision,
                    decision_in_details=True,
                )
                return audit_tool_call(
                    "commit_changes", {"message": message}, result, started_at=started_at
                )
            if rule_decision is None or rule_decision.action == DecisionAction.ASK:
                rejection = await require_approval(
                    "commit_changes",
                    {"message": message},
                    rejection_message=(
                        rule_decision.reason
                        if rule_decision is not None
                        else "Commit rejected by user"
                    ),
                    rejection_details={},
                )
                if rejection is not None:
                    if rule_decision is not None:
                        result = json_response(
                            False,
                            rule_decision.reason,
                            code="approval_rejected",
                            details={},
                            decision=rule_decision,
                            decision_in_details=True,
                        )
                    else:
                        result = rejection
                    return audit_tool_call(
                        "commit_changes", {"message": message}, result, started_at=started_at
                    )

            payload = _commit_changes(message, project_dir=project_dir())
            result = json_response(
                payload["commit"],
                "Changes committed" if payload["commit"] else "Commit failed",
                details=payload,
            )
            return audit_tool_call(
                "commit_changes",
                {"message": message},
                result,
                started_at=started_at,
            )

        ctx.register(
            "commit_changes",
            "Commit all staged and unstaged changes in the current project with a message. "
            "Use this for batch commits when auto_commit is set to False on individual "
            "write_file / patch_file calls.",
            commit_changes,
            destructive=True,
        )

    if ctx.should_register("git_branch_list"):

        async def git_branch_list() -> str:
            from claude_bridge.git_ops import git_branch_list as _git_branch_list

            started_at = ctx.now_ms()
            payload = _git_branch_list(project_dir=project_dir())
            result = json_response(
                payload.get("ok", False),
                "Branches listed" if payload.get("ok") else "Failed to list branches",
                details=payload,
            )
            return audit_tool_call("git_branch_list", {}, result, started_at=started_at)

        ctx.register(
            "git_branch_list",
            "List all local git branches with current HEAD indicator and tracking info.",
            git_branch_list,
            destructive=False,
        )

    if ctx.should_register("git_branch_create"):

        async def git_branch_create(name: str, base_branch: str | None = None) -> str:
            from claude_bridge.git_ops import git_branch_create as _git_branch_create

            started_at = ctx.now_ms()
            if not name.strip():
                result = json_response(
                    False, "Branch name cannot be empty", code="empty_name", details={}
                )
                return audit_tool_call(
                    "git_branch_create", {"name": name}, result, started_at=started_at
                )

            payload = _git_branch_create(name, project_dir=project_dir(), base_branch=base_branch)
            result = json_response(
                payload.get("ok", False),
                "Branch created" if payload.get("ok") else "Failed to create branch",
                details=payload,
            )
            return audit_tool_call(
                "git_branch_create",
                {"name": name, "base_branch": base_branch},
                result,
                started_at=started_at,
            )

        ctx.register(
            "git_branch_create",
            "Create a new git branch with optional base branch.",
            git_branch_create,
            destructive=True,
        )

    if ctx.should_register("git_merge"):

        async def git_merge(
            target: str,
            no_fast_forward: bool = False,
            squash: bool = False,
        ) -> str:
            from claude_bridge.git_ops import git_merge as _git_merge

            started_at = ctx.now_ms()
            if not target.strip():
                result = json_response(
                    False, "Merge target branch required", code="empty_target", details={}
                )
                return audit_tool_call(
                    "git_merge", {"target": target}, result, started_at=started_at
                )

            payload = _git_merge(
                target,
                project_dir=project_dir(),
                no_fast_forward=no_fast_forward,
                squash=squash,
            )
            result = json_response(
                payload.get("ok", False),
                "Merge completed" if payload.get("ok") else "Merge failed",
                details=payload,
            )
            return audit_tool_call(
                "git_merge",
                {"target": target, "no_fast_forward": no_fast_forward, "squash": squash},
                result,
                started_at=started_at,
            )

        ctx.register(
            "git_merge",
            "Merge a branch into the current branch. Returns conflict information if any.",
            git_merge,
            destructive=True,
        )

    if ctx.should_register("git_stash"):

        async def git_stash(message: str | None = None, include_untracked: bool = True) -> str:
            from claude_bridge.git_ops import git_stash as _git_stash

            started_at = ctx.now_ms()
            payload = _git_stash(
                project_dir=project_dir(), message=message, include_untracked=include_untracked
            )
            result = json_response(
                payload.get("ok", False),
                "Changes stashed" if payload.get("ok") else "Failed to stash",
                details=payload,
            )
            return audit_tool_call(
                "git_stash",
                {"message": message, "include_untracked": include_untracked},
                result,
                started_at=started_at,
            )

        ctx.register(
            "git_stash",
            "Stash working directory changes to preserve work-in-progress before risky operations. "
            "Use git_stash_pop to restore stashed changes.",
            git_stash,
            destructive=True,
        )

    if ctx.should_register("git_stash_pop"):

        async def git_stash_pop(restore_conflicts: bool = False) -> str:
            from claude_bridge.git_ops import git_stash_pop as _git_stash_pop

            started_at = ctx.now_ms()
            payload = _git_stash_pop(project_dir=project_dir(), restore_conflicts=restore_conflicts)
            result = json_response(
                payload.get("ok", False),
                "Stash restored" if payload.get("ok") else "Failed to restore stash",
                details=payload,
            )
            return audit_tool_call(
                "git_stash_pop",
                {"restore_conflicts": restore_conflicts},
                result,
                started_at=started_at,
            )

        ctx.register(
            "git_stash_pop",
            "Pop the most recent stash to restore stashed changes.",
            git_stash_pop,
            destructive=True,
        )

    return ctx.results
