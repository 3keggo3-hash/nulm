"""Skill marketplace for import/export of skill packages."""

from __future__ import annotations

import json
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from claude_bridge.skill_registry import SKILLS_DIR, get_registry
from claude_bridge.skill_schema import load_skill_json, validate_skill_json


MANIFEST_FILE = "skill.json"
SKILL_CODE_FILE = "skill.py"
PACKAGE_VERSION = "1.0"


def export_skill(name: str, dest_path: Path) -> tuple[bool, list[str]]:
    """Export a skill to a tar.gz package.

    Package format: skill.json + skill.py in tar.gz archive.
    Returns (success, error_messages).
    """
    registry = get_registry()
    meta = registry.get_meta(name)
    if meta is None:
        return False, [f"Skill '{name}' not found in registry"]

    skill_files = list(SKILLS_DIR.glob(f"{name}.v*.json"))
    if not skill_files:
        return False, [f"Skill '{name}' JSON file not found"]

    skill_file = skill_files[0]
    code_file = SKILLS_DIR / f"{name}.py"

    if not code_file.exists():
        return False, [f"Skill '{name}' code file not found"]

    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        with tarfile.open(dest_path, "w:gz") as tar:
            skill_data, errors = load_skill_json(skill_file)
            if errors:
                return False, errors

            code_content = code_file.read_text(encoding="utf-8")

            skill_data["code"] = code_content

            manifest_bytes = json.dumps(
                skill_data,
                indent=2,
                ensure_ascii=False,
            ).encode("utf-8")

            with tempfile.NamedTemporaryFile(delete=False) as mf:
                mf.write(manifest_bytes)
                manifest_path = mf.name

            tar.add(manifest_path, arcname=MANIFEST_FILE)
            Path(manifest_path).unlink(missing_ok=True)

            code_bytes = code_content.encode("utf-8")
            with tempfile.NamedTemporaryFile(delete=False) as cf:
                cf.write(code_bytes)
                code_path = cf.name

            tar.add(code_path, arcname=SKILL_CODE_FILE)
            Path(code_path).unlink(missing_ok=True)

        return True, []
    except OSError as e:
        return False, [f"Failed to create package: {e}"]
    except tarfile.TarError as e:
        return False, [f"Failed to create tar archive: {e}"]


def import_skill(package_path: Path) -> tuple[bool, list[str]]:
    """Import a skill from a tar.gz package.

    Package must contain skill.json and skill.py.
    Returns (success, error_messages).
    """
    if not package_path.exists():
        return False, [f"Package not found: {package_path}"]

    try:
        with tarfile.open(package_path, "r:gz") as tar:
            members = {m.name for m in tar.getmembers()}
            if MANIFEST_FILE not in members:
                return False, [f"Package missing '{MANIFEST_FILE}'"]
            if SKILL_CODE_FILE not in members:
                return False, [f"Package missing '{SKILL_CODE_FILE}'"]

            manifest_file = tar.extractfile(MANIFEST_FILE)
            if manifest_file is None:
                return False, [f"Failed to extract {MANIFEST_FILE}"]
            manifest_data = json.loads(manifest_file.read().decode("utf-8"))

            is_valid, errors = validate_skill_json(manifest_data)
            if not is_valid:
                return False, [f"Invalid skill JSON: {', '.join(errors)}"]

            code_file = tar.extractfile(SKILL_CODE_FILE)
            if code_file is None:
                return False, [f"Failed to extract {SKILL_CODE_FILE}"]
            code_content = code_file.read().decode("utf-8")

        name = manifest_data["name"]

        registry = get_registry()
        meta = registry.get_meta(name)
        if meta is not None:
            return False, [f"Skill '{name}' already registered (version {meta.version})"]

        from claude_bridge.skill_schema import SkillMeta

        meta = SkillMeta.from_dict(manifest_data)
        success, errors = registry.register(name, meta, code_content)
        return success, errors

    except (OSError, json.JSONDecodeError) as e:
        return False, [f"Failed to read package: {e}"]
    except tarfile.TarError as e:
        return False, [f"Failed to extract package: {e}"]


def list_exported_skills(package_dir: Path) -> list[dict[str, Any]]:
    """List all skill packages in a directory.

    Returns list of package info dicts.
    """
    if not package_dir.exists():
        return []

    results: list[dict[str, Any]] = []
    for pkg in package_dir.glob("*.tar.gz"):
        try:
            with tarfile.open(pkg, "r:gz") as tar:
                manifest_file = tar.extractfile(MANIFEST_FILE)
                if manifest_file is not None:
                    data = json.loads(manifest_file.read().decode("utf-8"))
                    results.append(
                        {
                            "name": data.get("name", "unknown"),
                            "version": data.get("version", "unknown"),
                            "file": pkg.name,
                            "size": pkg.stat().st_size,
                        }
                    )
        except Exception:
            continue

    return results