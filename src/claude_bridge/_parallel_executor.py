"""Parallel workflow execution with aggregation modes and risk scoring."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

from claude_bridge.workflow_engine import WorkflowStep


class AggregationMode(Enum):
    """How to aggregate results from parallel step execution.

    - ALL_MUST_SUCCEED: All steps must succeed, otherwise the group fails.
    - ANY_CAN_FAIL: Any step can fail without failing the group.
    - BEST_EFFORT: Complete as many as possible, aggregate risk scores.
    """

    ALL_MUST_SUCCEED = "all_must_succeed"
    ANY_CAN_FAIL = "any_can_fail"
    BEST_EFFORT = "best_effort"


@dataclass
class ParallelStepGroup:
    """A group of workflow steps that can execute in parallel.

    Attributes:
        steps: List of WorkflowSteps in this parallel group.
        max_workers: Maximum number of concurrent workers.
        aggregation_mode: How to aggregate results from individual steps.
        group_id: Unique identifier for this parallel group.
    """

    steps: list[WorkflowStep] = field(default_factory=list)
    max_workers: int = 4
    aggregation_mode: AggregationMode = AggregationMode.BEST_EFFORT
    group_id: str | None = None

    def __post_init__(self) -> None:
        if self.group_id is None and self.steps:
            import uuid

            self.group_id = f"parallel_{uuid.uuid4().hex[:8]}"

    @property
    def max_risk_score(self) -> int:
        """Return the maximum risk score among all steps in the group."""
        if not self.steps:
            return 0
        return max(step.risk_score for step in self.steps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "step_count": len(self.steps),
            "max_workers": self.max_workers,
            "aggregation_mode": self.aggregation_mode.value,
            "max_risk_score": self.max_risk_score,
            "steps": [s.to_dict() for s in self.steps],
        }


def aggregate_risk_scores(step_results: list[WorkflowStep]) -> int:
    """Aggregate risk scores from multiple steps using max aggregation.

    This takes the maximum risk score across all steps, representing
    the worst-case risk of the parallel execution.

    Args:
        step_results: List of WorkflowSteps with risk scores.

    Returns:
        Maximum risk score across all steps (0-100 scale).
    """
    if not step_results:
        return 0
    return max(step.risk_score for step in step_results)


async def execute_parallel_steps(
    steps: list[WorkflowStep],
    max_workers: int = 4,
    aggregation: str = "best_effort",
    execute_fn: Callable[..., Awaitable[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Execute multiple workflow steps in parallel using ThreadPoolExecutor.

    Args:
        steps: List of WorkflowSteps to execute in parallel.
        max_workers: Maximum number of concurrent workers.
        aggregation: Aggregation mode string ("all_must_succeed", "any_can_fail",
                    "best_effort").
        execute_fn: Optional async function to execute for each step.

    Returns:
        Dictionary with 'completed', 'failed', 'errors' lists and aggregated
        risk score.
    """
    try:
        agg_mode = AggregationMode(aggregation)
    except ValueError:
        agg_mode = AggregationMode.BEST_EFFORT

    completed: list[WorkflowStep] = []
    failed: list[WorkflowStep] = []
    errors: dict[str, str] = {}

    def run_step_sync(step: WorkflowStep) -> tuple[WorkflowStep, dict[str, Any] | None, str | None]:
        try:
            import asyncio

            result = asyncio.run(execute_fn(step)) if execute_fn is not None else None
            if result is None:
                step.status = "completed"
                result = {"ok": True}
            return (step, result, None)
        except Exception as e:
            return (step, None, str(e))

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(run_step_sync, step): step for step in steps}
        for future in as_completed(futures):
            step = futures[future]
            try:
                executed_step, result, error = future.result()
                if error:
                    executed_step.status = "failed"
                    failed.append(executed_step)
                    errors[executed_step.action] = error
                elif result:
                    executed_step.result = result
                    executed_step.status = "completed" if result.get("ok", False) else "failed"
                    if executed_step.status == "failed":
                        failed.append(executed_step)
                        errors[executed_step.action] = result.get("error", "unknown error")
                    else:
                        completed.append(executed_step)
                else:
                    executed_step.status = "failed"
                    failed.append(executed_step)
                    errors[executed_step.action] = "no result returned"
            except Exception as e:
                step.status = "failed"
                failed.append(step)
                errors[step.action] = str(e)

    # Determine overall success based on aggregation mode
    if agg_mode == AggregationMode.ALL_MUST_SUCCEED:
        overall_ok = len(failed) == 0
    elif agg_mode == AggregationMode.ANY_CAN_FAIL:
        overall_ok = len(completed) > 0
    else:  # BEST_EFFORT
        overall_ok = True

    return {
        "completed": completed,
        "failed": failed,
        "errors": errors,
        "overall_ok": overall_ok,
        "aggregated_risk": aggregate_risk_scores(completed + failed),
    }


def plan_parallel_groups(
    workflow_plan: list[WorkflowStep],
) -> list[ParallelStepGroup]:
    """Analyze workflow steps and group those that can run in parallel.

    Dependency analysis identifies independent steps (no shared files_affected)
    and groups them for parallel execution. Validation-type steps without
    file conflicts are prioritized for parallel grouping.

    Args:
        workflow_plan: List of WorkflowSteps to analyze.

    Returns:
        List of ParallelStepGroup, each containing steps that can run together.
    """
    if not workflow_plan:
        return []

    validation_keywords = [
        "lint",
        "type check",
        "typecheck",
        "test",
        "format",
        "validate",
        "check",
        "ruff",
        "mypy",
        "pytest",
        "black",
    ]

    independent: list[WorkflowStep] = []
    dependent: list[WorkflowStep] = []

    for step in workflow_plan:
        if step.status != "pending":
            continue

        action_lower = step.action.lower()
        has_validation_keyword = any(kw in action_lower for kw in validation_keywords)
        has_no_file_conflicts = not step.files_affected

        if has_validation_keyword and has_no_file_conflicts:
            independent.append(step)
        else:
            dependent.append(step)

    groups: list[ParallelStepGroup] = []

    if independent:
        groups.append(
            ParallelStepGroup(
                steps=independent,
                max_workers=min(4, len(independent)),
                aggregation_mode=AggregationMode.BEST_EFFORT,
            )
        )

    for step in dependent:
        groups.append(
            ParallelStepGroup(
                steps=[step],
                max_workers=1,
                aggregation_mode=AggregationMode.ALL_MUST_SUCCEED,
            )
        )

    return groups


def check_atomic_permissions(
    step: WorkflowStep,
    allowed_roots: list[str],
    project_dir: str,
) -> tuple[bool, str]:
    """Check if a step has atomic permissions to execute.

    This is an immediate permission check at execution time, not planning time.
    Validates that the step's affected files are within allowed boundaries.

    Args:
        step: WorkflowStep to check permissions for.
        allowed_roots: List of allowed project root directories.
        project_dir: Current project directory.

    Returns:
        Tuple of (has_permission, error_message).
    """
    if not step.files_affected:
        return True, ""

    from claude_bridge.tool_utils import path_outside_project_details

    for file_path in step.files_affected:
        details = path_outside_project_details(file_path)
        path_allowed_roots = details.get("allowed_roots", [])
        # Check if any allowed root covers this file
        is_outside = True
        for root in path_allowed_roots:
            # Check if file_path starts with the allowed root
            import os

            normalized_path = os.path.normpath(file_path).replace("\\", "/")
            normalized_root = os.path.normpath(root).replace("\\", "/")
            if (
                normalized_path.startswith(normalized_root + "/")
                or normalized_path == normalized_root
            ):
                is_outside = False
                break
        if is_outside:
            return False, f"Permission denied: {file_path} is outside allowed roots"

    return True, ""
