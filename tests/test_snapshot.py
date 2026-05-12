"""Tests for snapshot.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_bridge.snapshot import SnapshotManager, SnapshotType, _safe_filename


@pytest.fixture
def temp_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".claude-bridge").mkdir()
    return project


@pytest.fixture
def snapshot_manager(temp_project: Path, monkeypatch: pytest.MonkeyPatch) -> SnapshotManager:
    monkeypatch.setenv("CLAUDE_BRIDGE_PROJECT_DIR", str(temp_project))
    from claude_bridge import config
    config._CONFIG["project_dir"] = temp_project
    config._CONFIG["allowed_roots"] = [temp_project]
    return SnapshotManager()


class TestSafeFilename:
    def test_safe_filename_preserves_valid_chars(self) -> None:
        assert _safe_filename("valid_name-123") == "valid_name-123"

    def test_safe_filename_sanitizes_invalid_chars(self) -> None:
        assert _safe_filename("name with spaces!") == "name_with_spaces"

    def test_safe_filename_strips_leading_underscores(self) -> None:
        assert _safe_filename("___name___") == "name"

    def test_safe_filename_returns_unnamed_for_empty(self) -> None:
        assert _safe_filename("!!!") == "unnamed"


class TestSnapshotManager:
    def test_create_pre_session_snapshot(
        self, snapshot_manager: SnapshotManager, temp_project: Path
    ) -> None:
        test_file = temp_project / "test.txt"
        test_file.write_text("content")

        snapshot = snapshot_manager.create("test", SnapshotType.PRE_SESSION)
        assert snapshot.name == "test"
        assert snapshot.type == SnapshotType.PRE_SESSION
        assert len(snapshot.files) >= 1
        assert snapshot.path.exists()

    def test_create_named_snapshot_with_files(
        self, snapshot_manager: SnapshotManager, temp_project: Path
    ) -> None:
        test_file = temp_project / "test.txt"
        test_file.write_text("content")

        snapshot = snapshot_manager.create("named", SnapshotType.NAMED, files=["test.txt"])
        assert snapshot.name == "named"
        assert "test.txt" in snapshot.files

    def test_list_snapshots(
        self, snapshot_manager: SnapshotManager, temp_project: Path
    ) -> None:
        test_file = temp_project / "test.txt"
        test_file.write_text("content")

        snapshot_manager.create("first", SnapshotType.PRE_TASK)
        snapshot_manager.create("second", SnapshotType.PRE_SESSION)

        snapshots = snapshot_manager.list()
        assert len(snapshots) >= 2
        names = [s.name for s in snapshots]
        assert "first" in names
        assert "second" in names

    def test_restore_snapshot(
        self, snapshot_manager: SnapshotManager, temp_project: Path
    ) -> None:
        test_file = temp_project / "test.txt"
        test_file.write_text("original")

        snapshot_manager.create("backup", SnapshotType.PRE_SESSION, files=["test.txt"])
        test_file.write_text("modified")

        result = snapshot_manager.restore("backup")
        assert result is True
        assert test_file.read_text() == "original"

    def test_delete_snapshot(
        self, snapshot_manager: SnapshotManager, temp_project: Path
    ) -> None:
        test_file = temp_project / "test.txt"
        test_file.write_text("content")

        snapshot_manager.create("todelete", SnapshotType.NAMED)
        result = snapshot_manager.delete("todelete")
        assert result is True

        snapshots = snapshot_manager.list()
        assert not any(s.name == "todelete" for s in snapshots)

    def test_delete_snapshot_not_found(self, snapshot_manager: SnapshotManager) -> None:
        result = snapshot_manager.delete("nonexistent")
        assert result is False

    def test_get_snapshot_path(
        self, snapshot_manager: SnapshotManager, temp_project: Path
    ) -> None:
        test_file = temp_project / "test.txt"
        test_file.write_text("content")

        snapshot_manager.create("path_test", SnapshotType.PRE_SESSION, files=["test.txt"])
        path = snapshot_manager.get_snapshot_path("path_test")
        assert path is not None
        assert path.exists()

    def test_get_snapshot_path_not_found(self, snapshot_manager: SnapshotManager) -> None:
        path = snapshot_manager.get_snapshot_path("nonexistent")
        assert path is None


class TestGitCheckpointIntegration:
    def test_create_git_checkpoint_returns_ok_when_no_git_repo(
        self, snapshot_manager: SnapshotManager
    ) -> None:
        result = snapshot_manager.create_git_checkpoint("test_checkpoint")
        assert result.get("ok") is False
        assert result.get("step") == "add"

    def test_list_git_checkpoints_returns_empty_dict(
        self, snapshot_manager: SnapshotManager
    ) -> None:
        result = snapshot_manager.list_git_checkpoints()
        assert result.get("ok") is True
        assert result.get("count", -1) == 0