"""Verification agent for pre/post change validation."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import re
from typing import Any

from claude_bridge._event_bus import EventType, get_event_bus
from claude_bridge.agents.base import BaseAgent
from claude_bridge.agents.result import AgentResult, AgentStatus


class VerificationAgent(BaseAgent):
    DANGEROUS_PATTERNS = [
        r"rm\s+-rf\s+",
        r"sudo\s+",
        r"curl\s+\|",
        r"wget\s+\|",
        r"--dangerous",
        r"format\s+drive",
        r"drop\s+database",
        r"delete\s+all\s+files",
    ]

    def __init__(self) -> None:
        super().__init__("verification_agent")

    async def execute(self, task: str, context: dict[str, Any]) -> AgentResult:
        task_lower = task.lower()
        changes = context.get("changes", [])
        result = context.get("result", {})

        if "pre" in task_lower or "change" in task_lower:
            return await self.pre_commit_validation(changes)
        if "post" in task_lower or "result" in task_lower:
            return await self.post_change_verification(result)
        return await self.pre_commit_validation(changes)

    async def pre_commit_validation(self, changes: list[dict[str, Any]]) -> AgentResult:
        reasons: list[str] = []
        artifacts: dict[str, Any] = {"checked_changes": len(changes), "dangerous_found": []}

        for change in changes:
            action = str(change.get("action", ""))

            for pattern in self.DANGEROUS_PATTERNS:
                if re.search(pattern, action, re.IGNORECASE):
                    reasons.append(f"Dangerous operation detected: {action[:50]}")
                    artifacts["dangerous_found"].append({"pattern": pattern, "action": action})

            if "rm" in action.lower() and "-rf" in action:
                reasons.append(f"Recursive delete detected: {action[:50]}")

        if reasons:
            get_event_bus().publish(EventType.VERIFICATION_FAIL, {"reasons": reasons, "changes": changes})
            return AgentResult(
                status=AgentStatus.FAILURE,
                findings=["Verification failed: dangerous operations detected"],
                artifacts=artifacts,
                agent_name=self.name,
                error="; ".join(reasons),
            )

        get_event_bus().publish(EventType.VERIFICATION_PASS, {"changes": changes})
        return AgentResult(
            status=AgentStatus.SUCCESS,
            findings=["Pre-commit validation passed"],
            artifacts=artifacts,
            agent_name=self.name,
        )

    async def post_change_verification(self, result: dict[str, Any]) -> AgentResult:
        reasons: list[str] = []
        artifacts: dict[str, Any] = {"verified_result": True}

        ok = result.get("ok", False)
        error = result.get("error", "")
        output = result.get("output", result.get("result", ""))

        if not ok:
            reasons.append(f"Execution failed: {error}")

        if isinstance(output, str):
            for pattern in self.DANGEROUS_PATTERNS:
                if re.search(pattern, output, re.IGNORECASE):
                    reasons.append(f"Dangerous pattern in output: {pattern}")

        if reasons:
            get_event_bus().publish(EventType.VERIFICATION_FAIL, {"reasons": reasons, "result": result})
            return AgentResult(
                status=AgentStatus.FAILURE,
                findings=["Post-change verification failed"],
                artifacts=artifacts,
                agent_name=self.name,
                error="; ".join(reasons),
            )

        get_event_bus().publish(EventType.VERIFICATION_PASS, {"result": result})
        return AgentResult(
            status=AgentStatus.SUCCESS,
            findings=["Post-change verification passed"],
            artifacts=artifacts,
            agent_name=self.name,
        )