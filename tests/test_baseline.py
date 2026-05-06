"""Tests for cross-session behavioral baseline helpers."""

from claude_bridge.baseline import (
    build_baseline_from_records,
    load_baseline,
    merge_baseline,
    save_baseline,
)


def test_build_baseline_extracts_tools_commands_paths_and_hours() -> None:
    records = [
        {
            "tool_name": "run_shell",
            "timestamp": "2026-05-06T10:00:00Z",
            "params": {"command": "python3 -m pytest tests", "path": "src/app.py"},
        },
        {
            "tool_name": "read_file",
            "timestamp": "2026-05-06T11:00:00Z",
            "params": {"file": "docs/readme.md"},
        },
    ]

    baseline = build_baseline_from_records(records)

    assert baseline["record_count"] == 2
    assert baseline["avg_records_per_session"] == 2
    assert baseline["tool_counts"] == {"run_shell": 1, "read_file": 1}
    assert "python3 -m pytest" in baseline["command_prefixes"]
    assert baseline["path_roots"] == ["docs", "src"]
    assert baseline["active_hours"] == [10, 11]


def test_merge_baseline_accumulates_counts_and_sets() -> None:
    existing = build_baseline_from_records(
        [
            {
                "tool_name": "run_shell",
                "params": {"command": "git status", "path": "src/a.py"},
            }
        ]
    )

    merged = merge_baseline(
        existing,
        [
            {
                "tool_name": "read_file",
                "params": {"file": "docs/guide.md"},
            }
        ],
    )

    assert merged["session_count"] == 2
    assert merged["record_count"] == 2
    assert merged["tool_counts"] == {"run_shell": 1, "read_file": 1}
    assert "git status" in merged["command_prefixes"]
    assert merged["path_roots"] == ["docs", "src"]


def test_save_and_load_baseline_round_trip(tmp_path) -> None:
    path = tmp_path / ".claude-bridge" / "baseline.json"
    baseline = build_baseline_from_records([{"tool_name": "read_file"}])

    save_baseline(path, baseline)

    assert load_baseline(path) == baseline


def test_load_baseline_returns_none_for_invalid_file(tmp_path) -> None:
    path = tmp_path / "baseline.json"
    path.write_text("not json", encoding="utf-8")

    assert load_baseline(path) is None
