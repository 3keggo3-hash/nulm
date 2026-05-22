"""Append-only JSONL store for durable agent DAG records."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, TypeVar, cast

from claude_bridge.agents.dag_records import (
    AgentDagArtifactRecord,
    AgentDagConflictRecord,
    AgentDagNodeRecord,
    AgentDagRunRecord,
)

_RecordT = TypeVar("_RecordT")


@dataclass(frozen=True)
class AgentDagRunView:
    """Materialized view reconstructed from append-only DAG records."""

    run: AgentDagRunRecord
    nodes: tuple[AgentDagNodeRecord, ...]
    artifacts: tuple[AgentDagArtifactRecord, ...]
    conflicts: tuple[AgentDagConflictRecord, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run": self.run.to_dict(),
            "nodes": [node.to_dict() for node in self.nodes],
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "conflicts": [conflict.to_dict() for conflict in self.conflicts],
        }


class AgentDagStore:
    """Small explicit-path JSONL store for DAG reconstruction records."""

    def __init__(self, base_path: str | Path) -> None:
        self.base_path = Path(base_path).expanduser().resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)
        _chmod_if_possible(self.base_path, 0o700)

    @property
    def runs_path(self) -> Path:
        return self.base_path / "runs.jsonl"

    @property
    def nodes_path(self) -> Path:
        return self.base_path / "nodes.jsonl"

    @property
    def artifacts_path(self) -> Path:
        return self.base_path / "artifacts.jsonl"

    @property
    def conflicts_path(self) -> Path:
        return self.base_path / "conflicts.jsonl"

    def append_run(self, record: AgentDagRunRecord) -> None:
        _append_record(self.runs_path, record.to_dict())

    def append_node(self, record: AgentDagNodeRecord) -> None:
        _append_record(self.nodes_path, record.to_dict())

    def append_artifact(self, record: AgentDagArtifactRecord) -> None:
        _append_record(self.artifacts_path, record.to_dict())

    def append_conflict(self, record: AgentDagConflictRecord) -> None:
        _append_record(self.conflicts_path, record.to_dict())

    def load_runs(self) -> list[AgentDagRunRecord]:
        records = _read_records(self.runs_path, AgentDagRunRecord.from_dict)
        return _latest_by_id(records, lambda record: record.run_id)

    def load_nodes(self, run_id: str | None = None) -> list[AgentDagNodeRecord]:
        records = _read_records(self.nodes_path, AgentDagNodeRecord.from_dict)
        latest = _latest_by_id(records, lambda record: record.node_id)
        return _filter_run(latest, run_id)

    def load_artifacts(self, run_id: str | None = None) -> list[AgentDagArtifactRecord]:
        records = _read_records(self.artifacts_path, AgentDagArtifactRecord.from_dict)
        latest = _latest_by_id(records, lambda record: record.artifact_id)
        return _filter_run(latest, run_id)

    def load_conflicts(self, run_id: str | None = None) -> list[AgentDagConflictRecord]:
        records = _read_records(self.conflicts_path, AgentDagConflictRecord.from_dict)
        latest = _latest_by_id(records, lambda record: record.conflict_id)
        return _filter_run(latest, run_id)

    def reconstruct_run(self, run_id: str) -> AgentDagRunView:
        run = next((record for record in self.load_runs() if record.run_id == run_id), None)
        if run is None:
            raise ValueError(f"DAG run {run_id!r} not found")
        return AgentDagRunView(
            run=run,
            nodes=tuple(self.load_nodes(run_id=run_id)),
            artifacts=tuple(self.load_artifacts(run_id=run_id)),
            conflicts=tuple(self.load_conflicts(run_id=run_id)),
        )


def _append_record(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _chmod_if_possible(path.parent, 0o700)
    is_new = not path.exists()
    if is_new:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
    _chmod_if_possible(path, 0o600)


def _read_records(path: Path, factory: Callable[[dict[str, Any]], _RecordT]) -> list[_RecordT]:
    if not path.exists():
        return []
    records: list[_RecordT] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            raw = json.loads(line)
            if not isinstance(raw, dict):
                raise ValueError(f"invalid JSONL record in {path}")
            records.append(factory(cast(dict[str, Any], raw)))
    return records


def _latest_by_id(records: list[_RecordT], key_fn: Callable[[_RecordT], str]) -> list[_RecordT]:
    latest: dict[str, _RecordT] = {}
    order: list[str] = []
    for record in records:
        record_id = key_fn(record)
        if record_id not in latest:
            order.append(record_id)
        latest[record_id] = record
    return [latest[record_id] for record_id in order]


def _filter_run(records: list[_RecordT], run_id: str | None) -> list[_RecordT]:
    if run_id is None:
        return records
    return [record for record in records if getattr(record, "run_id") == run_id]


def _chmod_if_possible(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        return
