"""Workflow state machine for Plan -> Onay -> Uygula -> Test -> Rapor flow."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Awaitable

from claude_bridge._shell_analysis import risk_score_category
from claude_bridge.checkpoint import create_checkpoint, restore_checkpoint
from claude_bridge.agent_advisor import ResultQualityReviewRequest, review_result_quality
from claude_bridge.agents.result import AgentResult
from claude_bridge.skill_builder import (
    WorkflowResult,
    propose_skill_creation as propose_skill_creation_async,
)
from claude_bridge.tool_utils import request_approval


class WorkflowState(Enum):
    """Workflow state enumeration matching Phase 2 requirements."""

    IDLE = "idle"
    PLANNING = "planning"
    APPROVAL_PENDING = "approval_pending"
    APPLYING = "applying"
    TESTING = "testing"
    REPORTING = "reporting"
    DONE = "done"
    REJECTED = "rejected"


@dataclass
class WorkflowStep:
    """Single step in a workflow plan."""

    action: str
    files_affected: list[str] = field(default_factory=list)
    risk_score: int = 0
    rollback_plan: str = ""
    status: str = "pending"
    result: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "files_affected": self.files_affected,
            "risk_score": self.risk_score,
            "rollback_plan": self.rollback_plan,
            "status": self.status,
            "result": self.result,
        }


class OrchestratorExecutor:
    """Wrapper for executing orchestrator tasks within a workflow."""

    def __init__(self, orchestrator: Any) -> None:
        self.orchestrator = orchestrator

    async def execute_workflow_task(
        self,
        task: str,
        agents: list[Any],
    ) -> dict[str, Any]:
        result = await self.orchestrator.orchestrate(task, agents)
        if isinstance(result, AgentResult):
            return result.to_dict()
        if isinstance(result, dict):
            return {"ok": True, **result}
        return {"ok": True, "result": str(result)}


class WorkflowEngine:
    """State machine for mandatory workflow execution.

    States: IDLE -> PLANNING -> APPROVAL_PENDING -> APPLYING -> TESTING
            -> REPORTING -> DONE (or REJECTED)

    Each step includes: action, files affected, risk score, rollback plan.
    """

    def __init__(self) -> None:
        self.state = WorkflowState.IDLE
        self.steps: list[WorkflowStep] = []
        self.current_step = 0
        self.task: str = ""
        self.checkpoint_name: str | None = None
        self.execution_log: list[dict[str, Any]] = []

    def create_plan(self, task: str) -> list[WorkflowStep]:
        """Decompose task into steps using LLM-based analysis."""
        self.task = task
        self.transition_to(WorkflowState.PLANNING)
        self.steps = self._decompose_task(task)
        self.current_step = 0
        self._log_event("plan_created", {"task": task, "step_count": len(self.steps)})
        return self.steps

    def _decompose_task(self, task: str) -> list[WorkflowStep]:
        """Break down task into workflow steps with risk assessment."""
        task_lower = task.lower()
        steps: list[WorkflowStep] = []

        # Analyze overall task risk
        if any(kw in task_lower for kw in ["create", "new", "add", "implement"]):
            steps.append(
                WorkflowStep(
                    action="Analyze requirements and identify target files",
                    files_affected=[],
                    risk_score=10,
                    rollback_plan="No changes made yet",
                )
            )
            steps.append(
                WorkflowStep(
                    action="Read existing code in target area",
                    files_affected=[],
                    risk_score=5,
                    rollback_plan="No changes made yet",
                )
            )
            steps.append(
                WorkflowStep(
                    action="Implement the requested feature",
                    files_affected=[],
                    risk_score=25,
                    rollback_plan="Revert to previous checkpoint",
                )
            )
            steps.append(
                WorkflowStep(
                    action="Run tests to validate implementation",
                    files_affected=[],
                    risk_score=10,
                    rollback_plan="Revert implementation changes",
                )
            )

        elif any(kw in task_lower for kw in ["fix", "bug", "error", "repair"]):
            steps.append(
                WorkflowStep(
                    action="Identify the failing component",
                    files_affected=[],
                    risk_score=5,
                    rollback_plan="No changes made yet",
                )
            )
            steps.append(
                WorkflowStep(
                    action="Analyze root cause of the issue",
                    files_affected=[],
                    risk_score=5,
                    rollback_plan="No changes made yet",
                )
            )
            steps.append(
                WorkflowStep(
                    action="Apply the fix",
                    files_affected=[],
                    risk_score=20,
                    rollback_plan="Revert to previous checkpoint",
                )
            )
            steps.append(
                WorkflowStep(
                    action="Run tests to confirm fix",
                    files_affected=[],
                    risk_score=10,
                    rollback_plan="Revert fix if tests fail",
                )
            )

        elif any(kw in task_lower for kw in ["refactor", "restructure", "cleanup"]):
            steps.append(
                WorkflowStep(
                    action="Identify files to refactor",
                    files_affected=[],
                    risk_score=5,
                    rollback_plan="No changes made yet",
                )
            )
            steps.append(
                WorkflowStep(
                    action="Create checkpoint before changes",
                    files_affected=[],
                    risk_score=15,
                    rollback_plan="Restore checkpoint",
                )
            )
            steps.append(
                WorkflowStep(
                    action="Perform refactoring",
                    files_affected=[],
                    risk_score=35,
                    rollback_plan="Restore from checkpoint",
                )
            )
            steps.append(
                WorkflowStep(
                    action="Run tests and validation",
                    files_affected=[],
                    risk_score=10,
                    rollback_plan="Restore from checkpoint",
                )
            )

        else:
            steps.append(
                WorkflowStep(
                    action="Analyze task and identify files",
                    files_affected=[],
                    risk_score=10,
                    rollback_plan="No changes made yet",
                )
            )
            steps.append(
                WorkflowStep(
                    action="Plan implementation approach",
                    files_affected=[],
                    risk_score=5,
                    rollback_plan="No changes made yet",
                )
            )
            steps.append(
                WorkflowStep(
                    action="Execute the task",
                    files_affected=[],
                    risk_score=25,
                    rollback_plan="Revert to previous state",
                )
            )
            steps.append(
                WorkflowStep(
                    action="Validate results with tests",
                    files_affected=[],
                    risk_score=10,
                    rollback_plan="Revert changes if validation fails",
                )
            )

        return steps

    async def execute_step(
        self,
        step: WorkflowStep,
        execute_fn: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    ) -> bool:
        """Execute a single step with checkpoint before modifications."""
        if step.risk_score >= 60:
            checkpoint_name = f"pre_step_{uuid.uuid4().hex[:8]}"
            cp_result = create_checkpoint(checkpoint_name)
            if cp_result.get("ok"):
                step.rollback_plan = f"Restore checkpoint: {checkpoint_name}"
                self.checkpoint_name = checkpoint_name
                self._log_event("checkpoint_created", {"checkpoint": checkpoint_name})

        # Execute the step function if provided
        if execute_fn is not None:
            result = await execute_fn(step)
            step.result = result
            step.status = "completed" if result.get("ok", False) else "failed"
            self._log_event("step_executed", {"action": step.action, "result": result})
            return bool(result.get("ok", False))

        step.status = "completed"
        self._log_event("step_completed", {"action": step.action})
        return True

    def transition_to(self, new_state: WorkflowState) -> None:
        """Transition to a new state with validation."""
        valid_transitions: dict[WorkflowState, set[WorkflowState]] = {
            WorkflowState.IDLE: {WorkflowState.PLANNING},
            WorkflowState.PLANNING: {WorkflowState.APPROVAL_PENDING, WorkflowState.IDLE},
            WorkflowState.APPROVAL_PENDING: {
                WorkflowState.APPLYING,
                WorkflowState.REJECTED,
                WorkflowState.IDLE,
            },
            WorkflowState.APPLYING: {WorkflowState.TESTING, WorkflowState.REJECTED},
            WorkflowState.TESTING: {WorkflowState.REPORTING, WorkflowState.REJECTED},
            WorkflowState.REPORTING: {WorkflowState.DONE},
            WorkflowState.DONE: {WorkflowState.IDLE},
            WorkflowState.REJECTED: {WorkflowState.IDLE},
        }

        allowed = valid_transitions.get(self.state, set())
        if new_state not in allowed:
            raise ValueError(f"Invalid transition: {self.state.value} -> {new_state.value}")

        old_state = self.state
        self.state = new_state
        self._log_event(
            "state_transition",
            {
                "from": old_state.value,
                "to": new_state.value,
            },
        )

    async def request_approval_for_plan(
        self,
        request_approval_fn: Callable[[str, dict[str, Any]], Awaitable[bool]] = request_approval,
    ) -> bool:
        """Request user approval for the workflow plan."""
        self.transition_to(WorkflowState.APPROVAL_PENDING)
        params = {
            "task": self.task,
            "steps": [s.to_dict() for s in self.steps],
            "total_risk": sum(s.risk_score for s in self.steps),
            "step_count": len(self.steps),
        }
        approved = await request_approval_fn("workflow_approve", params)
        if approved:
            self.transition_to(WorkflowState.APPLYING)
            return True
        self.transition_to(WorkflowState.REJECTED)
        return False

    def format_plan_for_user(self, plan: list[WorkflowStep] | None = None) -> str:
        """Generate human-readable plan display with risk scores."""
        steps_to_show = plan if plan is not None else self.steps
        if not steps_to_show:
            return "No plan available."

        total_risk = sum(s.risk_score for s in steps_to_show)
        lines = [
            "┌─────────────────────────────────────────┐",
            "│ 📋 Plan Review                          │",
            "├─────────────────────────────────────────┤",
        ]

        for i, step in enumerate(steps_to_show, 1):
            risk_emoji = self._risk_emoji_for_score(step.risk_score)
            lines.append(f"│ Step {i}: {step.action[:30]:<30} │")
            lines.append(f"│         Risk: {step.risk_score}/100 {risk_emoji:<8} │")
            if step.files_affected:
                files_str = ", ".join(step.files_affected[:2])
                if len(step.files_affected) > 2:
                    files_str += "..."
                lines.append(f"│         Files: {files_str:<28} │")
            if step.rollback_plan:
                rollback_short = step.rollback_plan[:35]
                lines.append(f"│         Rollback: {rollback_short:<24} │")
            lines.append("├─────────────────────────────────────────┤")

        lines.append(f"│ Total Risk: {total_risk}/100{' ' * 18} │")
        lines.append("├─────────────────────────────────────────┤")
        lines.append("│ [Approve] [Modify] [Cancel]             │")
        lines.append("└─────────────────────────────────────────┘")
        return "\n".join(lines)

    def _risk_emoji_for_score(self, score: int) -> str:
        """Return emoji for risk score."""
        category, _ = risk_score_category(score)
        emoji_map = {
            "Safe": "🔒",
            "Low Risk": "🔓",
            "Medium": "⚠️",
            "High": "🚨",
            "Critical": "🚨",
            "Blocked": "🚫",
        }
        return emoji_map.get(category, "⚠️")

    def _log_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Log workflow event with timestamp."""
        self.execution_log.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": event_type,
                "state": self.state.value,
                **data,
            }
        )

    def get_status(self) -> dict[str, Any]:
        """Return current workflow status."""
        return {
            "state": self.state.value,
            "task": self.task,
            "current_step": self.current_step,
            "total_steps": len(self.steps),
            "steps": [s.to_dict() for s in self.steps],
            "execution_log": self.execution_log,
            "checkpoint_name": self.checkpoint_name,
        }

    async def _run_self_review(self) -> dict[str, Any]:
        """Run self-critique before moving to REPORTING.

        Returns dict with status (pass/fail), warnings, and errors.
        """
        changed_files = self._get_changed_files()
        test_results = self._get_test_results()

        request = ResultQualityReviewRequest(
            goal=self.task,
            result_summary=f"Workflow completed with {len(self.steps)} steps",
            changed_files=changed_files,
            validation=test_results,
        )
        review = review_result_quality(request)

        verdict = review.verdict
        strengths = review.strengths or []
        warnings_list = [s for s in strengths if "note" in s.lower()]
        errors_list: list[str] = []
        if verdict in ("needs_followup", "needs_clarification"):
            errors_list.append(review.summary)
            status = "fail"
        else:
            status = "pass"

        result: dict[str, Any] = {
            "status": status,
            "verdict": verdict,
            "summary": review.summary,
            "warnings": warnings_list,
            "errors": errors_list,
        }
        return result

    def _get_changed_files(self) -> list[str]:
        """Extract list of files modified during workflow."""
        files: list[str] = []
        for step in self.steps:
            if step.files_affected:
                files.extend(step.files_affected)
        return list(set(files))

    def _get_test_results(self) -> dict[str, Any]:
        """Get test results from execution log."""
        completed_steps = sum(1 for s in self.steps if s.status == "completed")
        failed_steps = sum(1 for s in self.steps if s.status == "failed")

        if failed_steps > 0:
            return {"passed": False, "steps_tested": completed_steps}

        for log in reversed(self.execution_log):
            if log.get("event") == "step_completed" and "test" in log.get("action", "").lower():
                return {"passed": log.get("status") == "completed", "steps_tested": completed_steps}

        return {"passed": True, "steps_tested": completed_steps}

    async def transition_to_reporting(self) -> dict[str, Any]:
        """Transition from TESTING to REPORTING after self-review.

        Runs self-critique and only transitions if review passes or user approves.
        Returns dict with transition result and review info.
        """
        if self.state != WorkflowState.TESTING:
            raise ValueError(f"Cannot transition from {self.state.value}, expected TESTING")

        review_result = await self._run_self_review()

        if review_result["status"] == "fail":
            self._log_event("self_review_failed", review_result)
            return {"ok": False, "review": review_result}

        if review_result["warnings"]:
            self._log_event("self_review_warnings", {"warnings": review_result["warnings"]})

        self.transition_to(WorkflowState.REPORTING)
        self._log_event("transition_to_reporting", {"review": review_result})
        return {"ok": True, "review": review_result}

    def rollback(self) -> dict[str, Any]:
        """Rollback to the last checkpoint."""
        if self.checkpoint_name:
            result = restore_checkpoint(self.checkpoint_name)
            self._log_event("rollback", {"checkpoint": self.checkpoint_name})
            return result
        return {"ok": False, "error": "No checkpoint available for rollback"}

    def reset(self) -> None:
        """Reset workflow to IDLE state."""
        self.state = WorkflowState.IDLE
        self.steps = []
        self.current_step = 0
        self.task = ""
        self.checkpoint_name = None
        self._log_event("reset", {})

    def check_and_propose_skill(
        self,
        request_approval_fn: Any = None,
    ) -> tuple[bool, str | None]:
        """Propose skill creation if workflow result is suitable."""
        if self.state != WorkflowState.DONE:
            return False, None

        workflow_result = WorkflowResult(
            task=self.task,
            steps=[s.to_dict() for s in self.steps],
            outcome="success",
            artifacts={},
        )
        import asyncio

        async def run_proposal() -> tuple[bool, str | None]:
            proposal = await propose_skill_creation_async(workflow_result)
            if proposal is None:
                return False, None
            return True, proposal.skill_name

        return asyncio.get_event_loop().run_until_complete(run_proposal())
