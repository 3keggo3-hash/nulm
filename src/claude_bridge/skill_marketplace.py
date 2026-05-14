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
_MAX_PACKAGE_BYTES = 2_000_000
_RISKY_CODE_MARKERS = {
    "subprocess": "uses subprocess",
    "os.system": "uses os.system",
    "eval(": "uses eval",
    "exec(": "uses exec",
    "socket": "uses socket/network primitives",
    "urllib": "uses urllib/network access",
    "requests": "uses requests/network access",
    "shell=True": "uses shell=True",
    ".env": "references sensitive environment files",
}
_KNOWN_PERMISSIONS = {"read", "analyze", "write", "execute", "network"}


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
    _, inspection_errors = inspect_package(package_path)
    if inspection_errors:
        return False, inspection_errors

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


def inspect_package(
    package_path: Path,
    *,
    registry_root: Path | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Inspect a skill package without extracting or executing package code."""
    if not package_path.exists():
        return None, [f"Package not found: {package_path}"]
    if package_path.stat().st_size > _MAX_PACKAGE_BYTES:
        return None, [f"Package exceeds size limit of {_MAX_PACKAGE_BYTES} bytes"]

    try:
        with tarfile.open(package_path, "r:gz") as tar:
            members = tar.getmembers()
            safety_errors = _validate_members(members)
            if safety_errors:
                return None, safety_errors

            member_names = {member.name for member in members}
            if MANIFEST_FILE not in member_names:
                return None, [f"Package missing '{MANIFEST_FILE}'"]
            if SKILL_CODE_FILE not in member_names:
                return None, [f"Package missing '{SKILL_CODE_FILE}'"]

            manifest_file = tar.extractfile(MANIFEST_FILE)
            code_file = tar.extractfile(SKILL_CODE_FILE)
            if manifest_file is None:
                return None, [f"Failed to read {MANIFEST_FILE}"]
            if code_file is None:
                return None, [f"Failed to read {SKILL_CODE_FILE}"]

            manifest = json.loads(manifest_file.read().decode("utf-8"))
            if not isinstance(manifest, dict):
                return None, ["Skill manifest must be a JSON object"]
            is_valid, errors = validate_skill_json(manifest)
            if not is_valid:
                return None, [f"Invalid skill JSON: {', '.join(errors)}"]

            code = code_file.read().decode("utf-8")
    except (OSError, UnicodeError, json.JSONDecodeError) as e:
        return None, [f"Failed to read package: {e}"]
    except tarfile.TarError as e:
        return None, [f"Failed to inspect package: {e}"]

    registry = get_registry(registry_root)
    existing = registry.get_meta(str(manifest.get("name", "")))
    risk = score_package_risk(manifest, code)
    return {
        "manifest": manifest,
        "members": sorted(member_names),
        "code_length": len(code),
        "risk": risk,
        "duplicate": existing is not None,
        "existing_version": existing.version if existing is not None else None,
        "install_eligible": existing is None and risk["risk_level"] != "high",
    }, []


def score_package_risk(manifest: dict[str, Any], code: str) -> dict[str, Any]:
    """Score package risk from declared permissions and static code markers."""
    reasons: list[str] = []
    risk_score = 0
    permissions = [str(item) for item in manifest.get("permissions", [])]
    unknown_permissions = sorted(set(permissions) - _KNOWN_PERMISSIONS)

    if unknown_permissions:
        risk_score += 2
        reasons.append(f"unknown permissions: {', '.join(unknown_permissions)}")
    for permission in permissions:
        if permission in {"write", "execute", "network"}:
            risk_score += 2
            reasons.append(f"declares {permission} permission")
    if bool(manifest.get("auto_load", False)):
        risk_score += 3
        reasons.append("declares auto_load=true")
    for marker, reason in _RISKY_CODE_MARKERS.items():
        if marker in code:
            risk_score += 2
            reasons.append(reason)
    for key in ("description", "tags", "source"):
        if not manifest.get(key):
            reasons.append(f"missing optional metadata: {key}")

    if risk_score >= 4:
        risk_level = "high"
    elif risk_score >= 2:
        risk_level = "medium"
    else:
        risk_level = str(manifest.get("risk_level", "low"))

    return {
        "risk_level": risk_level,
        "reasons": reasons,
        "permissions": permissions,
        "unknown_permissions": unknown_permissions,
    }


def import_skill_reviewed(
    package_path: Path,
    *,
    allow_high_risk: bool = False,
) -> tuple[bool, list[str]]:
    """Import a package only after inspect-before-import risk checks."""
    inspection, errors = inspect_package(package_path)
    if errors:
        return False, errors
    assert inspection is not None
    risk = inspection["risk"]
    if inspection["duplicate"]:
        return False, ["Skill already registered; refusing to overwrite existing skill"]
    if risk["risk_level"] == "high" and not allow_high_risk:
        return False, ["High-risk skill package requires allow_high_risk=True"]
    return import_skill(package_path)


def search_packages(package_dir: Path, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search local skill packages by metadata without importing them."""
    if not package_dir.exists() or not package_dir.is_dir():
        return []
    query_lower = query.lower()
    results: list[dict[str, Any]] = []
    for package in sorted(package_dir.glob("*.tar.gz")):
        inspection, errors = inspect_package(package)
        if errors or inspection is None:
            continue
        manifest = inspection["manifest"]
        haystack = " ".join(
            [
                str(manifest.get("name", "")),
                str(manifest.get("description", "")),
                " ".join(str(item) for item in manifest.get("trigger_phrases", [])),
                " ".join(str(item) for item in manifest.get("tags", [])),
            ]
        ).lower()
        if query_lower and query_lower not in haystack:
            continue
        results.append(
            {
                "file": str(package),
                "name": manifest.get("name", "unknown"),
                "version": manifest.get("version", "unknown"),
                "risk": inspection["risk"],
                "duplicate": inspection["duplicate"],
            }
        )
        if len(results) >= max(1, limit):
            break
    return results


def _validate_members(members: list[tarfile.TarInfo]) -> list[str]:
    errors: list[str] = []
    names: set[str] = set()
    total_size = 0
    for member in members:
        name = member.name
        total_size += max(member.size, 0)
        path = Path(name)
        if name in names:
            errors.append(f"Package contains duplicate member: {name}")
        names.add(name)
        if path.is_absolute() or ".." in path.parts:
            errors.append(f"Package contains unsafe path: {name}")
        if member.issym() or member.islnk():
            errors.append(f"Package contains link member: {name}")
        if member.isdev():
            errors.append(f"Package contains device member: {name}")
        if not member.isfile():
            errors.append(f"Package contains unsupported member type: {name}")
    if total_size > _MAX_PACKAGE_BYTES:
        errors.append(f"Package contents exceed size limit of {_MAX_PACKAGE_BYTES} bytes")
    return errors


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
