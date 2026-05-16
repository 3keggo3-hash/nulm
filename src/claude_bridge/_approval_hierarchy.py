"""Hierarchical Approval System for Claude Bridge.

Provides multi-tier approval chains with risk-based level assignment,
timeout handling, and approval recording for audit purposes.
"""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from enum import Enum
from typing import Any

from claude_bridge.guard_policy import RiskLevel


class ApprovalStatus(str, Enum):
    """Possible outcomes for an approval chain evaluation."""

    APPROVED = "approved"
    DENIED = "denied"
    PENDING = "pending"
    TIMEOUT = "timeout"


@dataclass
class ApprovalLevel:
    """A single tier in an approval chain.

    Attributes:
        name: Unique identifier for this level (e.g. "auto_approve", "user_prompt").
        threshold_risk: The minimum risk level that requires approval at this tier.
        approver_role: The role required to approve at this level (e.g. "user",
            "security_admin", "admin"). Empty string means any approver or auto.
        timeout_seconds: How long to wait for approval before falling back.
    """

    name: str
    threshold_risk: str  # RiskLevel value as string for serialization compatibility
    approver_role: str = ""
    timeout_seconds: int = 300

    @property
    def risk_enum(self) -> RiskLevel | None:
        """Parse threshold_risk as RiskLevel enum."""
        try:
            return RiskLevel(self.threshold_risk)
        except ValueError:
            return None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return {
            "name": self.name,
            "threshold_risk": self.threshold_risk,
            "approver_role": self.approver_role,
            "timeout_seconds": self.timeout_seconds,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApprovalLevel":
        """Deserialize from dict."""
        return cls(
            name=str(data.get("name", "")),
            threshold_risk=str(data.get("threshold_risk", "low")),
            approver_role=str(data.get("approver_role", "")),
            timeout_seconds=int(data.get("timeout_seconds", 300)),
        )


@dataclass
class ApprovalChain:
    """A named approval chain with ordered levels.

    Attributes:
        name: Unique identifier for this chain (e.g. "default", "restricted").
        levels: Ordered list of ApprovalLevel (evaluated from index 0 upward).
        default_fallback: Action to take when all levels timeout
            ("allow", "deny", "ask"). Defaults to "deny".
    """

    name: str
    levels: list[ApprovalLevel] = dc_field(default_factory=list)
    default_fallback: str = "deny"

    def get_level_for_risk(self, risk_level: RiskLevel) -> ApprovalLevel | None:
        """Find the approval level for a given risk level using escalation logic.

        The approval chain levels are ordered from lowest to highest risk.
        Each level's threshold represents the MINIMUM risk level that triggers
        that level's approval requirement.

        Algorithm: Find the first level whose threshold value is >= risk value.
        This represents the minimum level required for the given risk.

        Example with thresholds [low=1, medium=2, high=3, critical=4]:
        - risk=low(1):     first level where threshold >= 1 -> auto_approve(1)
        - risk=medium(2):  first level where threshold >= 2 -> user_prompt(2)
        - risk=high(3):    first level where threshold >= 3 -> security_admin(3)
        - risk=critical(4): first level where threshold >= 4 -> critical_block(4)

        Returns the matching level, or None if no levels defined.
        """
        if not self.levels:
            return None

        # Get numeric index for proper comparison (enum comparison uses name order, not value)
        risk_order = list(RiskLevel)
        try:
            risk_index = risk_order.index(risk_level)
        except ValueError:
            risk_index = 1  # Default to medium

        # Find the first level whose threshold is >= risk value
        for level in self.levels:
            level_risk = level.risk_enum
            if level_risk is not None:
                try:
                    threshold_index = risk_order.index(level_risk)
                    if threshold_index >= risk_index:
                        return level
                except ValueError:
                    continue

        return None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dict."""
        return {
            "name": self.name,
            "levels": [level.to_dict() for level in self.levels],
            "default_fallback": self.default_fallback,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApprovalChain":
        """Deserialize from dict."""
        levels_data = data.get("levels", [])
        if not isinstance(levels_data, list):
            levels_data = []
        levels = [
            (
                ApprovalLevel.from_dict(lvl)
                if isinstance(lvl, dict)
                else ApprovalLevel(name="", threshold_risk="low")
            )
            for lvl in levels_data
        ]
        return cls(
            name=str(data.get("name", "")),
            levels=levels,
            default_fallback=str(data.get("default_fallback", "deny")),
        )


# -----------------------------------------------------------------------------
# Approval Records Store (in-memory, thread-safe)
# -----------------------------------------------------------------------------

_approval_records: dict[str, dict[str, Any]] = {}
_approval_records_lock = threading.RLock()


def _generate_approval_id() -> str:
    """Generate a unique approval ID."""
    return f"apr_{uuid.uuid4().hex[:16]}"


# -----------------------------------------------------------------------------
# Default Approval Chain Preset
# -----------------------------------------------------------------------------

# Level 1: Auto-approve for LOW risk operations
_AUTO_APPROVE_LEVEL = ApprovalLevel(
    name="auto_approve",
    threshold_risk="low",
    approver_role="",
    timeout_seconds=0,  # No timeout needed for auto-approve
)

# Level 2: User prompt for MEDIUM risk, 5 minute timeout
_USER_PROMPT_LEVEL = ApprovalLevel(
    name="user_prompt",
    threshold_risk="medium",
    approver_role="user",
    timeout_seconds=300,  # 5 minutes
)

# Level 3: Security admin for HIGH risk, 30 minute timeout
_SECURITY_ADMIN_LEVEL = ApprovalLevel(
    name="security_admin",
    threshold_risk="high",
    approver_role="security_admin",
    timeout_seconds=1800,  # 30 minutes
)

# Level 4: Block CRITICAL risk by default
_CRITICAL_BLOCK_LEVEL = ApprovalLevel(
    name="critical_block",
    threshold_risk="critical",
    approver_role="admin",
    timeout_seconds=600,  # 10 minutes
)


DEFAULT_APPROVAL_CHAIN = ApprovalChain(
    name="default",
    levels=[
        _AUTO_APPROVE_LEVEL,
        _USER_PROMPT_LEVEL,
        _SECURITY_ADMIN_LEVEL,
        _CRITICAL_BLOCK_LEVEL,
    ],
    default_fallback="deny",
)


# -----------------------------------------------------------------------------
# Core Functions
# -----------------------------------------------------------------------------


def get_required_approval_level(
    risk_level: str,
    chain: ApprovalChain | None = None,
) -> ApprovalLevel | None:
    """Determine which approval level is required for a given risk level.

    Args:
        risk_level: String risk level ("low", "medium", "high", "critical").
        chain: The approval chain to use. Defaults to DEFAULT_APPROVAL_CHAIN.

    Returns:
        The required ApprovalLevel if approval is needed, None if auto-approved.
    """
    if chain is None:
        chain = DEFAULT_APPROVAL_CHAIN

    try:
        risk_enum = RiskLevel(risk_level)
    except ValueError:
        risk_enum = RiskLevel.MEDIUM  # Treat unknown as medium risk

    return chain.get_level_for_risk(risk_enum)


def evaluate_approval_chain(
    context: dict[str, Any],
    chain: ApprovalChain | None = None,
) -> str:
    """Evaluate the approval chain for a tool request context.

    This function determines the appropriate approval outcome based on
    the risk level and configured chain. It handles auto-approval for
    low-risk operations and delegates to the appropriate approval level.

    Args:
        context: Dictionary containing at minimum:
            - tool_name: str - name of the tool being invoked
            - risk_level: str - risk assessment ("low", "medium", "high", "critical")
            - params: dict - tool parameters
            - Optional: role, user for additional context

        chain: The approval chain to use. Defaults to DEFAULT_APPROVAL_CHAIN.

    Returns:
        One of: "approved", "denied", "pending", "timeout"
    """
    if chain is None:
        chain = DEFAULT_APPROVAL_CHAIN

    risk_level_str = context.get("risk_level", "low")
    required_level = get_required_approval_level(risk_level_str, chain)

    # If no level is required (risk is below all thresholds), auto-approve
    if required_level is None:
        return ApprovalStatus.APPROVED.value

    # Auto-approve levels have no approver role and timeout_seconds == 0
    if required_level.approver_role == "" and required_level.timeout_seconds == 0:
        return ApprovalStatus.APPROVED.value

    # For user prompt levels, we return pending and let the caller handle
    # the actual user interaction via request_approval
    if required_level.name == "user_prompt":
        # The actual user interaction is handled by request_approval in tool_utils
        return ApprovalStatus.PENDING.value

    # For security_admin and higher, we return pending - these require
    # role-based approval that must be handled by the caller
    if required_level.approver_role in ("security_admin", "admin"):
        return ApprovalStatus.PENDING.value

    # Critical block - default deny unless explicitly approved
    if required_level.name == "critical_block":
        # Check if there's a pre-approved status in context
        pre_approved = context.get("_pre_approved", False)
        if pre_approved:
            return ApprovalStatus.APPROVED.value
        return ApprovalStatus.DENIED.value

    # Default: pending for unhandled cases
    return ApprovalStatus.PENDING.value


def record_approval(
    approval_id: str,
    level_name: str,
    decision: str,
    approver: str,
    reason: str,
    *,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record an approval decision for audit purposes.

    Args:
        approval_id: Unique identifier for this approval (generated or provided).
        level_name: Which approval level this decision applies to.
        decision: "approved" or "denied".
        approver: Who made the decision (role, user identifier, or "system").
        reason: Explanation for the decision.
        context: Optional context dict with tool_name, params, risk_level, etc.

    Returns:
        The recorded approval dict with timestamp and ID.
    """
    global _approval_records

    if not approval_id:
        approval_id = _generate_approval_id()

    record = {
        "approval_id": approval_id,
        "level_name": level_name,
        "decision": decision,
        "approver": approver,
        "reason": reason,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "context": context or {},
    }

    with _approval_records_lock:
        _approval_records[approval_id] = record

    return record


def get_approval_record(approval_id: str) -> dict[str, Any] | None:
    """Retrieve a previously recorded approval by ID."""
    with _approval_records_lock:
        return (
            dict(_approval_records.get(approval_id)) if approval_id in _approval_records else None
        )


def list_approvals(
    *,
    limit: int = 100,
    level_name: str | None = None,
    decision: str | None = None,
) -> list[dict[str, Any]]:
    """List recorded approvals, optionally filtered.

    Args:
        limit: Maximum number of records to return (oldest first).
        level_name: Filter by approval level name.
        decision: Filter by decision ("approved", "denied").

    Returns:
        List of approval records.
    """
    with _approval_records_lock:
        records = list(_approval_records.values())

    if level_name:
        records = [r for r in records if r.get("level_name") == level_name]
    if decision:
        records = [r for r in records if r.get("decision") == decision]

    # Return most recent first, limited
    records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return records[:limit]


def clear_approval_records() -> None:
    """Clear all recorded approvals (mainly for testing)."""
    global _approval_records
    with _approval_records_lock:
        _approval_records.clear()
