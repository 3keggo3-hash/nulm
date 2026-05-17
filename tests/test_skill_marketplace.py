"""Tests for skill marketplace package inspection and reviewed import."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest

from claude_bridge import skill_registry
from claude_bridge.skill_marketplace import (
    import_skill_reviewed,
    inspect_package,
    score_package_risk,
    search_packages,
)


@pytest.fixture
def temp_skills_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    skills_dir = tmp_path / ".claude-bridge" / "skills"
    skills_dir.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    skill_registry._registry = None
    return skills_dir


def _package(
    path: Path,
    *,
    manifest: dict[str, object] | None = None,
    code: str = "def run(ctx): return {'ok': True}",
    code_name: str = "skill.py",
    manifest_name: str = "skill.json",
    symlink_code: bool = False,
) -> Path:
    manifest = manifest or {
        "name": "example",
        "version": "1.0",
        "trigger_phrases": ["example"],
        "description": "Example skill",
        "tags": ["example"],
    }
    with tarfile.open(path, "w:gz") as tar:
        manifest_bytes = json.dumps(manifest).encode("utf-8")
        manifest_info = tarfile.TarInfo(manifest_name)
        manifest_info.size = len(manifest_bytes)
        tar.addfile(manifest_info, io.BytesIO(manifest_bytes))

        if symlink_code:
            link_info = tarfile.TarInfo(code_name)
            link_info.type = tarfile.SYMTYPE
            link_info.linkname = "/tmp/skill.py"
            tar.addfile(link_info)
        else:
            code_bytes = code.encode("utf-8")
            code_info = tarfile.TarInfo(code_name)
            code_info.size = len(code_bytes)
            tar.addfile(code_info, io.BytesIO(code_bytes))
    return path


def test_inspect_package_returns_manifest_and_risk(
    temp_skills_dir: Path,
    tmp_path: Path,
) -> None:
    package = _package(tmp_path / "example.tar.gz")

    inspection, errors = inspect_package(package)

    assert errors == []
    assert inspection is not None
    assert inspection["manifest"]["name"] == "example"
    assert inspection["code_length"] > 0
    assert inspection["risk"]["risk_level"] == "low"
    assert inspection["install_eligible"] is True
    assert inspection["trust_level"] == "unverified"


def test_inspect_package_with_trust_metadata(
    temp_skills_dir: Path,
    tmp_path: Path,
) -> None:
    package = _package(
        tmp_path / "official.tar.gz",
        manifest={
            "name": "official-skill",
            "version": "1.0",
            "trigger_phrases": ["official"],
            "description": "An official skill",
            "tags": ["official"],
            "trust_level": "official",
            "signature": "sig_abc123",
        },
    )

    inspection, errors = inspect_package(package)

    assert errors == []
    assert inspection is not None
    assert inspection["manifest"]["trust_level"] == "official"
    assert inspection["manifest"]["signature"] == "sig_abc123"
    assert inspection["trust_level"] == "official"


def test_inspect_package_rejects_unsafe_tar_member(
    temp_skills_dir: Path,
    tmp_path: Path,
) -> None:
    package = _package(tmp_path / "bad.tar.gz", code_name="../skill.py")

    inspection, errors = inspect_package(package)

    assert inspection is None
    assert any("unsafe path" in error for error in errors)


def test_inspect_package_rejects_link_member(
    temp_skills_dir: Path,
    tmp_path: Path,
) -> None:
    package = _package(tmp_path / "link.tar.gz", symlink_code=True)

    inspection, errors = inspect_package(package)

    assert inspection is None
    assert any("link member" in error for error in errors)


def test_high_risk_package_requires_explicit_allow(
    temp_skills_dir: Path,
    tmp_path: Path,
) -> None:
    package = _package(
        tmp_path / "risky.tar.gz",
        manifest={
            "name": "risky",
            "version": "1.0",
            "trigger_phrases": ["risky"],
            "permissions": ["execute"],
            "trust_level": "community",
        },
        code="import subprocess\n\ndef run(ctx): subprocess.run(['true'])",
    )

    success, errors = import_skill_reviewed(package)
    assert success is False
    assert any("High-risk" in error for error in errors)

    success, errors = import_skill_reviewed(package, allow_high_risk=True)
    assert success is True
    assert errors == []


def test_score_package_risk_flags_static_markers() -> None:
    risk = score_package_risk(
        {"name": "net", "version": "1.0", "trigger_phrases": ["net"]},
        "import socket\nexec('print(1)')",
    )

    assert risk["risk_level"] == "high"
    assert "uses socket/network primitives" in risk["reasons"]
    assert "uses exec" in risk["reasons"]


def test_search_packages_matches_metadata(
    temp_skills_dir: Path,
    tmp_path: Path,
) -> None:
    package_dir = tmp_path / "packages"
    package_dir.mkdir()
    _package(
        package_dir / "docs.tar.gz",
        manifest={
            "name": "docs",
            "version": "1.0",
            "trigger_phrases": ["document"],
            "description": "Write release notes",
            "tags": ["docs"],
        },
    )

    results = search_packages(package_dir, "release")

    assert len(results) == 1
    assert results[0]["name"] == "docs"


def test_unverified_skill_requires_approval(
    temp_skills_dir: Path,
    tmp_path: Path,
) -> None:
    package = _package(
        tmp_path / "unverified.tar.gz",
        manifest={
            "name": "unverified-skill",
            "version": "1.0",
            "trigger_phrases": ["unverified"],
            "description": "An unverified skill",
            "tags": ["test"],
            "trust_level": "unverified",
        },
    )

    success, errors = import_skill_reviewed(package, skip_unverified_approval=False)
    assert success is False
    assert any("Unverified skill requires explicit approval" in error for error in errors)

    success, errors = import_skill_reviewed(package, skip_unverified_approval=True)
    assert success is True


def test_community_skill_no_approval_required(
    temp_skills_dir: Path,
    tmp_path: Path,
) -> None:
    package = _package(
        tmp_path / "community.tar.gz",
        manifest={
            "name": "community-skill",
            "version": "1.0",
            "trigger_phrases": ["community"],
            "description": "A community skill",
            "tags": ["test"],
            "trust_level": "community",
        },
    )

    success, errors = import_skill_reviewed(package, skip_unverified_approval=False)
    assert success is True
    assert errors == []
