"""Deterministic conflict detection for agent DAG records."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from claude_bridge.agents.dag_records import (
    AgentDagConflictRecord,
    AgentDagNodeRecord,
    make_agent_dag_id,
)


@dataclass(frozen=True)
class PatchHunk:
    """Normalized patch range for deterministic overlap checks."""

    node_id: str
    file_path: str
    start_line: int
    end_line: int

    def __post_init__(self) -> None:
        if self.start_line <= 0:
            raise ValueError("start_line must be positive")
        if self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line")


class ConflictDetector:
    """Detect first-class DAG conflicts without adjudicating them."""

    def detect_write_set_conflicts(
        self,
        nodes: tuple[AgentDagNodeRecord, ...],
        *,
        now: float | None = None,
    ) -> tuple[AgentDagConflictRecord, ...]:
        timestamp = time.time() if now is None else now
        conflicts: list[AgentDagConflictRecord] = []
        for index, left in enumerate(nodes):
            for right in nodes[index + 1 :]:
                if left.run_id != right.run_id:
                    continue
                overlap = path_overlap(left.write_set, right.write_set)
                if not overlap:
                    continue
                conflicts.append(
                    _conflict_record(
                        run_id=left.run_id,
                        node_ids=(left.node_id, right.node_id),
                        conflict_type="overlapping_write_set",
                        files=overlap,
                        signal="declared write_set overlap",
                        created_at=timestamp,
                    )
                )
        return tuple(conflicts)

    def detect_patch_conflicts(
        self,
        run_id: str,
        hunks: tuple[PatchHunk, ...],
        *,
        now: float | None = None,
    ) -> tuple[AgentDagConflictRecord, ...]:
        timestamp = time.time() if now is None else now
        conflicts: list[AgentDagConflictRecord] = []
        for index, left in enumerate(hunks):
            for right in hunks[index + 1 :]:
                if left.node_id == right.node_id:
                    continue
                if _normalize_path(left.file_path) != _normalize_path(right.file_path):
                    continue
                if not _ranges_overlap(left, right):
                    continue
                conflicts.append(
                    _conflict_record(
                        run_id=run_id,
                        node_ids=(left.node_id, right.node_id),
                        conflict_type="overlapping_patch",
                        files=(_normalize_path(left.file_path),),
                        signal="patch hunks overlap",
                        created_at=timestamp,
                        metadata={
                            "left_range": [left.start_line, left.end_line],
                            "right_range": [right.start_line, right.end_line],
                        },
                    )
                )
        return tuple(conflicts)

    def detect_task_boundary_conflicts(
        self,
        nodes: tuple[AgentDagNodeRecord, ...],
        *,
        now: float | None = None,
    ) -> tuple[AgentDagConflictRecord, ...]:
        timestamp = time.time() if now is None else now
        conflicts: list[AgentDagConflictRecord] = []
        for index, left in enumerate(nodes):
            for right in nodes[index + 1 :]:
                if left.run_id != right.run_id:
                    continue
                overlap = path_overlap(left.write_set, right.write_set)
                if not overlap:
                    continue
                left_goal = _goal(left)
                right_goal = _goal(right)
                if not left_goal or not right_goal or left_goal == right_goal:
                    continue
                conflicts.append(
                    _conflict_record(
                        run_id=left.run_id,
                        node_ids=(left.node_id, right.node_id),
                        conflict_type="task_boundary_ambiguity",
                        files=overlap,
                        signal="different goals claim same file",
                        created_at=timestamp,
                        metadata={"left_goal": left_goal, "right_goal": right_goal},
                    )
                )
        return tuple(conflicts)


def path_overlap(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
    """Return normalized path overlap."""
    left_paths = {_normalize_path(path) for path in left if path}
    right_paths = {_normalize_path(path) for path in right if path}
    return tuple(sorted(left_paths & right_paths))


def conflict_rate(conflicts: tuple[AgentDagConflictRecord, ...], *, node_count: int) -> float:
    """Return conflicts per node for simple runtime reporting."""
    if node_count <= 0:
        return 0.0
    return len(conflicts) / node_count


def _conflict_record(
    *,
    run_id: str,
    node_ids: tuple[str, str],
    conflict_type: str,
    files: tuple[str, ...],
    signal: str,
    created_at: float,
    metadata: dict[str, Any] | None = None,
) -> AgentDagConflictRecord:
    sorted_node_ids = tuple(sorted(node_ids))
    conflict_id = make_agent_dag_id(
        "conflict",
        {
            "files": list(files),
            "node_ids": list(sorted_node_ids),
            "run_id": run_id,
            "type": conflict_type,
        },
    )
    return AgentDagConflictRecord(
        conflict_id=conflict_id,
        run_id=run_id,
        node_ids=sorted_node_ids,
        type=conflict_type,
        files=files,
        signal=signal,
        created_at=created_at,
        metadata=metadata or {},
    )


def _ranges_overlap(left: PatchHunk, right: PatchHunk) -> bool:
    return left.start_line <= right.end_line and right.start_line <= left.end_line


def _normalize_path(path: str) -> str:
    return path.rstrip("/")


def _goal(node: AgentDagNodeRecord) -> str:
    for key in ("goal", "task", "task_goal"):
        raw = node.metadata.get(key)
        if isinstance(raw, str):
            return raw
    return ""
