"""File-oriented tool implementations for Claude Bridge."""

# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from claude_bridge.file_tools._helpers import (
    _estimate_patch_risk,
    _last_bridge_change,
    _last_bridge_change_snapshot,
    _line_ending_for_content,
    _normalize_line_endings,
    _paginate_text_preview,
    _remember_bridge_change,
    _slice_text_lines,
    _write_text_exact,
    clear_last_bridge_change,
)
from claude_bridge.file_tools._meta import mkdir, path_exists, stat_file
from claude_bridge.file_tools._move import copy_path, move_file
from claude_bridge.file_tools._patch import patch_file, preview_patch, undo_last_patch
from claude_bridge.file_tools._read import list_directory, read_file, read_multiple_files
from claude_bridge.file_tools._search import append_to_file, diff_files, find_files, search_in_files
from claude_bridge.file_tools._write import write_file

__all__ = [
    "_estimate_patch_risk",
    "_last_bridge_change",
    "_last_bridge_change_snapshot",
    "_line_ending_for_content",
    "_normalize_line_endings",
    "_paginate_text_preview",
    "_remember_bridge_change",
    "_slice_text_lines",
    "_write_text_exact",
    "append_to_file",
    "clear_last_bridge_change",
    "copy_path",
    "diff_files",
    "find_files",
    "list_directory",
    "mkdir",
    "move_file",
    "patch_file",
    "path_exists",
    "preview_patch",
    "read_file",
    "read_multiple_files",
    "search_in_files",
    "stat_file",
    "undo_last_patch",
    "write_file",
]
