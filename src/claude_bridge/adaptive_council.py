"""Approval-gated proposal store for skill recommendations.

Provides proposal creation and management based on comparison reports.
Accepting a proposal records the user's decision; it does not directly disable
or mutate skills.
"""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROPOSALS_DIR = Path(".claude-bridge/proposals")


@dataclass(frozen=True)
class DeactivationProposal:
    id: str
    skill_to_deactivate: str
    replacement: str
    reason: str
    stats: dict[str, Any]
    status: str
    created_at: str
    expires_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "skill_to_deactivate": self.skill_to_deactivate,
            "replacement": self.replacement,
            "reason": self.reason,
            "stats": self.stats,
            "status": self.status,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeactivationProposal:
        return cls(
            id=str(data.get("id", "")),
            skill_to_deactivate=str(data.get("skill_to_deactivate", "")),
            replacement=str(data.get("replacement", "")),
            reason=str(data.get("reason", "")),
            stats=dict(data.get("stats", {})),
            status=str(data.get("status", "pending")),
            created_at=str(data.get("created_at", "")),
            expires_at=str(data.get("expires_at", "")),
        )

    def is_expired(self) -> bool:
        try:
            expiry = datetime.strptime(self.expires_at, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            return datetime.now(timezone.utc) > expiry
        except ValueError:
            return True

    def format_for_user(self) -> str:
        skill_rate = self.stats.get("loser_rate", 0)
        replacement_rate = self.stats.get("winner_rate", 0)
        sample_size = self.stats.get("sample_size", "N/A")

        lines = [
            "---",
            "Skill Recommendation",
            f"Current: {self.skill_to_deactivate} (acceptance: {skill_rate:.0%})",
            f"Recommended: {self.replacement} (acceptance: {replacement_rate:.0%})",
            f"Reason: {self.reason}",
            f"Sample size: {sample_size} observations",
            "---",
            f'Record accept: accept_proposal("{self.id}")',
            f'Record reject: reject_proposal("{self.id}")',
        ]
        return "\n".join(lines)


class ProposalStore:
    def __init__(self, root: Path | None = None) -> None:
        self._root = (root or Path.cwd()).resolve()
        self._proposals_dir = self._root / PROPOSALS_DIR
        self._proposals_dir.mkdir(parents=True, exist_ok=True)

    def _proposal_path(self, proposal_id: str) -> Path:
        safe_id = proposal_id.replace("/", "_").replace("..", "_")
        return self._proposals_dir / f"{safe_id}.json"

    def save(self, proposal: DeactivationProposal) -> tuple[bool, str]:
        try:
            path = self._proposal_path(proposal.id)
            with path.open("w", encoding="utf-8") as f:
                json.dump(proposal.to_dict(), f, indent=2)
            return True, ""
        except OSError as e:
            return False, str(e)

    def load(self, proposal_id: str) -> DeactivationProposal | None:
        path = self._proposal_path(proposal_id)
        if not path.exists():
            return None

        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return DeactivationProposal.from_dict(data)
        except (OSError, json.JSONDecodeError):
            return None

    def list_pending(self) -> list[DeactivationProposal]:
        proposals: list[DeactivationProposal] = []

        for path in self._proposals_dir.glob("*.json"):
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                proposal = DeactivationProposal.from_dict(data)

                if proposal.status == "pending" and not proposal.is_expired():
                    proposals.append(proposal)
            except (OSError, json.JSONDecodeError):
                continue

        proposals.sort(key=lambda p: p.created_at, reverse=True)
        return proposals

    def update_status(self, proposal_id: str, new_status: str) -> DeactivationProposal | None:
        proposal = self.load(proposal_id)
        if proposal is None:
            return None

        updated_data = proposal.to_dict()
        updated_data["status"] = new_status

        new_proposal = DeactivationProposal.from_dict(updated_data)
        self.save(new_proposal)
        return new_proposal

    def delete(self, proposal_id: str) -> tuple[bool, str]:
        path = self._proposal_path(proposal_id)
        if not path.exists():
            return False, "not found"

        try:
            path.unlink()
            return True, ""
        except OSError as e:
            return False, str(e)


async def propose_deactivation(
    report: Any,
    store: ProposalStore | None = None,
) -> str | None:
    from claude_bridge.skill_comparison import ComparisonReport

    if not isinstance(report, ComparisonReport):
        return None

    if not report.deactivation_eligible:
        return None

    if report.winner == "insufficient_data" or report.winner == "none":
        return None

    if store is None:
        store = ProposalStore()

    proposal_id = f"deact_{uuid.uuid4().hex[:12]}"

    comparison = report.comparison
    winner_rate = max(comparison.skill_a_rate, comparison.skill_b_rate) if comparison else 0
    loser_rate = min(comparison.skill_a_rate, comparison.skill_b_rate) if comparison else 0
    stats = {
        "winner_rate": winner_rate,
        "loser_rate": loser_rate,
        "sample_size": 0,
        "significant": comparison.significant if comparison else False,
    }

    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=24)

    proposal = DeactivationProposal(
        id=proposal_id,
        skill_to_deactivate=report.loser,
        replacement=report.winner,
        reason=report.reason,
        stats=stats,
        status="pending",
        created_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        expires_at=expires.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    success, _ = store.save(proposal)
    if not success:
        return None

    return proposal_id


async def send_deactivation_proposal(
    proposal_id: str, store: ProposalStore | None = None
) -> str | None:
    if store is None:
        store = ProposalStore()

    proposal = store.load(proposal_id)
    if proposal is None:
        return None

    if proposal.is_expired():
        return None

    return proposal.format_for_user()


async def stream_proposal(proposal: DeactivationProposal) -> str:
    return proposal.format_for_user()


def accept_proposal(proposal_id: str, store: ProposalStore | None = None) -> tuple[bool, str]:
    if store is None:
        store = ProposalStore()

    proposal = store.load(proposal_id)
    if proposal is None:
        return False, "proposal not found"

    if proposal.is_expired():
        return False, "proposal expired"

    if proposal.status != "pending":
        return False, f"proposal already {proposal.status}"

    updated = store.update_status(proposal_id, "accepted")
    return updated is not None, ""


def reject_proposal(proposal_id: str, store: ProposalStore | None = None) -> tuple[bool, str]:
    if store is None:
        store = ProposalStore()

    proposal = store.load(proposal_id)
    if proposal is None:
        return False, "proposal not found"

    if proposal.is_expired():
        return False, "proposal expired"

    if proposal.status != "pending":
        return False, f"proposal already {proposal.status}"

    updated = store.update_status(proposal_id, "rejected")
    return updated is not None, ""


def get_current_proposals(store: ProposalStore | None = None) -> list[dict[str, Any]]:
    if store is None:
        store = ProposalStore()

    proposals = store.list_pending()
    return [p.to_dict() for p in proposals]
