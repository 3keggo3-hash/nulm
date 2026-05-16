"""Git-based checkpointing - delegates to snapshot.py module-level functions."""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

from claude_bridge.snapshot import (
    create_checkpoint,
    list_checkpoints,
    restore_checkpoint,
)

__all__ = ["create_checkpoint", "restore_checkpoint", "list_checkpoints"]
