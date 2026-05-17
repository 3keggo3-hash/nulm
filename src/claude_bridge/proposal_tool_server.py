"""Registration helpers for adaptive recommendation proposal MCP tools.

Provides tools for listing recommendations and recording accept/reject decisions.
"""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

from typing import Any, Callable

from claude_bridge._stream_events import get_broadcaster
from claude_bridge.adaptive_council import (
    ProposalStore,
    accept_proposal as _accept_proposal,
    reject_proposal as _reject_proposal,
)
from claude_bridge.tool_registration import ToolRegistrationContext


def register_proposal_tools(
    *,
    mcp: Any,
    tool_options: Callable[..., dict[str, Any]],
    audit_tool_call: Callable[..., str],
    json_response: Callable[..., str],
    enabled_names: set[str] | None = None,
) -> dict[str, Any]:
    """Register proposal management tools for adaptive recommendations."""
    ctx = ToolRegistrationContext(
        mcp=mcp,
        tool_options=tool_options,
        audit_tool_call=audit_tool_call,
        enabled_names=enabled_names,
    )

    if ctx.should_register("accept_proposal"):

        async def accept_proposal(proposal_id: str) -> str:
            started_at = ctx.now_ms()
            store = ProposalStore()
            ok, error = _accept_proposal(proposal_id, store)

            if not ok:
                result = json_response(
                    False,
                    f"Failed to accept proposal: {error}",
                    code="accept_proposal_failed",
                    details={"proposal_id": proposal_id},
                )
            else:
                broadcaster = get_broadcaster()
                broadcaster.publish(
                    "skill_proposal.accepted",
                    {"proposal_id": proposal_id},
                    correlation_id=proposal_id,
                )
                result = json_response(
                    True,
                    f"Proposal {proposal_id} accept decision recorded",
                    details={"proposal_id": proposal_id, "action": "accepted"},
                )

            return audit_tool_call(
                "accept_proposal",
                {"proposal_id": proposal_id},
                result,
                started_at=started_at,
            )

        ctx.register(
            "accept_proposal",
            "Record acceptance of a pending skill recommendation proposal.",
            accept_proposal,
        )

    if ctx.should_register("reject_proposal"):

        async def reject_proposal(proposal_id: str) -> str:
            started_at = ctx.now_ms()
            store = ProposalStore()
            ok, error = _reject_proposal(proposal_id, store)

            if not ok:
                result = json_response(
                    False,
                    f"Failed to reject proposal: {error}",
                    code="reject_proposal_failed",
                    details={"proposal_id": proposal_id},
                )
            else:
                broadcaster = get_broadcaster()
                broadcaster.publish(
                    "skill_proposal.rejected",
                    {"proposal_id": proposal_id},
                    correlation_id=proposal_id,
                )
                result = json_response(
                    True,
                    f"Proposal {proposal_id} reject decision recorded",
                    details={"proposal_id": proposal_id, "action": "rejected"},
                )

            return audit_tool_call(
                "reject_proposal",
                {"proposal_id": proposal_id},
                result,
                started_at=started_at,
            )

        ctx.register(
            "reject_proposal",
            "Record rejection of a pending skill recommendation proposal.",
            reject_proposal,
        )

    if ctx.should_register("list_pending_proposals"):

        async def list_pending_proposals() -> str:
            started_at = ctx.now_ms()
            store = ProposalStore()
            proposals = store.list_pending()

            result = json_response(
                True,
                f"Pending proposals: {len(proposals)}",
                details={
                    "schema_version": "pending_proposals.v1",
                    "count": len(proposals),
                    "proposals": [p.to_dict() for p in proposals],
                },
            )
            return audit_tool_call(
                "list_pending_proposals",
                {},
                result,
                started_at=started_at,
            )

        ctx.register(
            "list_pending_proposals",
            "List all pending skill recommendation proposals.",
            list_pending_proposals,
            read_only=True,
        )

    if ctx.should_register("get_proposal_details"):

        async def get_proposal_details(proposal_id: str) -> str:
            started_at = ctx.now_ms()
            store = ProposalStore()
            proposal = store.load(proposal_id)

            if proposal is None:
                result = json_response(
                    False,
                    f"Proposal {proposal_id} not found",
                    code="proposal_not_found",
                    details={"proposal_id": proposal_id},
                )
            else:
                result = json_response(
                    True,
                    f"Proposal details: {proposal_id}",
                    details={
                        "schema_version": "proposal_details.v1",
                        "proposal": proposal.to_dict(),
                        "formatted": proposal.format_for_user(),
                    },
                )

            return audit_tool_call(
                "get_proposal_details",
                {"proposal_id": proposal_id},
                result,
                started_at=started_at,
            )

        ctx.register(
            "get_proposal_details",
            "Get details of a specific proposal.",
            get_proposal_details,
            read_only=True,
        )

    return ctx.results
