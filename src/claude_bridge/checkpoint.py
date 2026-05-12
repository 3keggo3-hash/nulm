"""Git-based checkpointing wrapper - delegates to snapshot.py."""

from __future__ import annotations

from claude_bridge.snapshot import SnapshotManager

_manager = SnapshotManager()

create_checkpoint = _manager.create_git_checkpoint
restore_checkpoint = _manager.restore_git_checkpoint
list_checkpoints = _manager.list_git_checkpoints