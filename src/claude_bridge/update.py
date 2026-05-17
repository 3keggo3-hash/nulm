"""Check for nulm updates from PyPI."""
# Copyright (c) 2026 Claude Bridge Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import URLError

from importlib.metadata import PackageNotFoundError, version as _package_version

try:
    from packaging.version import parse as _parse_version
except ImportError:  # pragma: no cover - packaging is available in dev/test envs
    _parse_version = None  # type: ignore[assignment]

from claude_bridge.tool_utils import json_response


PACKAGE_NAME = "nulm"
CLI_NAME = "claude-bridge"
WHEEL_PREFIX = "nulm-"


def _history_dir() -> Path:
    pd = Path(os.environ.get("CLAUDE_BRIDGE_PROJECT_DIR", ".")).resolve()
    hist_dir = pd / ".claude-bridge" / "update_history"
    hist_dir.mkdir(parents=True, exist_ok=True)
    return hist_dir


def _save_update_record(record: dict[str, Any]) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = _history_dir() / f"update_{ts}.json"
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")


def _load_update_history() -> list[dict[str, Any]]:
    hist_dir = _history_dir()
    records: list[dict[str, Any]] = []
    if not hist_dir.is_dir():
        return records
    for f in sorted(hist_dir.iterdir()):
        if f.is_file() and f.suffix == ".json":
            try:
                records.append(json.loads(f.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                continue
    return records


def get_update_history() -> list[dict[str, Any]]:
    return _load_update_history()


@dataclass
class UpdateResult:
    ok: bool
    message: str
    from_version: str = "unknown"
    to_version: str = "unknown"
    rolled_back: bool = False
    backup_path: str | None = None
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "message": self.message,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "rolled_back": self.rolled_back,
            "backup_path": self.backup_path,
            "error": self.error,
            "details": self.details,
        }


def check_update() -> str:
    """Return a JSON string with update status info.

    Keys: ok, message, details with current_version, latest_version,
    up_to_date (bool), install_command.
    """
    try:
        current_version = _package_version(PACKAGE_NAME)
    except PackageNotFoundError:
        current_version = "unknown"

    latest_version = _fetch_latest_version_with_retry()
    up_to_date = current_version != "unknown" and _versions_compatible(
        current_version, latest_version
    )

    if current_version == "unknown":
        ok = True
        message = "Could not determine installed version"
    elif latest_version == "unknown":
        ok = True
        message = "Could not determine latest version from PyPI"
    elif up_to_date:
        ok = True
        message = f"{CLI_NAME} is up to date (v{current_version})"
    else:
        ok = True
        message = f"Update available: v{current_version} → v{latest_version}"

    details: dict[str, Any] = {
        "current_version": current_version,
        "latest_version": latest_version,
        "up_to_date": up_to_date,
        "install_command": f"pip install --upgrade {PACKAGE_NAME}",
    }

    return json_response(ok, message, details=details)


def _versions_compatible(current: str, latest: str) -> bool:
    if current == latest:
        return True
    if _parse_version is None:
        return current == latest
    try:
        cur = _parse_version(current)
        lat = _parse_version(latest)
        return cur >= lat
    except (ValueError, TypeError):
        return current == latest


def _fetch_latest_version_with_retry(max_retries: int = 3, initial_delay: float = 0.5) -> str:
    delay = initial_delay
    for attempt in range(max_retries):
        version = _fetch_latest_version()
        if version != "unknown":
            return version
        if attempt < max_retries - 1:
            time.sleep(delay)
            delay *= 2
    return "unknown"


def _fetch_latest_version() -> str:
    """Fetch the latest nulm version from PyPI JSON API."""
    url = f"https://pypi.org/pypi/{PACKAGE_NAME}/json"
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read(65536).decode("utf-8"))
        return str(data.get("info", {}).get("version", "unknown"))
    except (URLError, OSError, ValueError, KeyError):
        return "unknown"


def _get_package_info() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["pip", "show", PACKAGE_NAME],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            info: dict[str, Any] = {}
            for line in result.stdout.splitlines():
                if ":" in line:
                    key, _, value = line.partition(":")
                    info[key.strip().lower().replace("-", "_")] = value.strip()
            return info
    except (subprocess.TimeoutExpired, OSError):
        pass
    return {}


def perform_update() -> UpdateResult:
    current_version = "unknown"
    try:
        current_version = _package_version(PACKAGE_NAME)
    except PackageNotFoundError:
        return UpdateResult(
            ok=False,
            message="Could not determine installed version",
            error="package_not_found",
        )

    latest_version = _fetch_latest_version_with_retry()
    if latest_version == "unknown":
        return UpdateResult(
            ok=False,
            message="Could not fetch latest version from PyPI",
            from_version=current_version,
            to_version="unknown",
            error="fetch_failed",
        )

    if _versions_compatible(current_version, latest_version):
        return UpdateResult(
            ok=True,
            message=f"Already at latest version v{current_version}",
            from_version=current_version,
            to_version=latest_version,
        )

    backup_path = _backup_current_package()
    if not backup_path:
        return UpdateResult(
            ok=False,
            message="Failed to create backup before update",
            from_version=current_version,
            to_version=latest_version,
            error="backup_failed",
        )

    try:
        result = subprocess.run(
            ["pip", "install", "--upgrade", PACKAGE_NAME],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            _rollback_install(backup_path, current_version)
            return UpdateResult(
                ok=False,
                message="Update failed, rolled back to previous version",
                from_version=current_version,
                to_version=latest_version,
                rolled_back=True,
                backup_path=str(backup_path),
                error=f"install_failed: {result.stderr[:200]}",
            )
    except subprocess.TimeoutExpired:
        _rollback_install(backup_path, current_version)
        return UpdateResult(
            ok=False,
            message="Update timed out, rolled back to previous version",
            from_version=current_version,
            to_version=latest_version,
            rolled_back=True,
            backup_path=str(backup_path),
            error="timeout",
        )
    except OSError:
        return UpdateResult(
            ok=False,
            message="pip not available for update",
            from_version=current_version,
            to_version=latest_version,
            backup_path=str(backup_path),
            error="pip_not_available",
        )

    if not _verify_installed_version(latest_version):
        _rollback_install(backup_path, current_version)
        return UpdateResult(
            ok=False,
            message="Update installed but version mismatch, rolled back",
            from_version=current_version,
            to_version=latest_version,
            rolled_back=True,
            backup_path=str(backup_path),
            error="version_mismatch",
        )

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": "update",
        "from_version": current_version,
        "to_version": latest_version,
        "success": True,
        "backup_path": str(backup_path),
    }
    _save_update_record(record)

    return UpdateResult(
        ok=True,
        message=f"Successfully updated from v{current_version} to v{latest_version}",
        from_version=current_version,
        to_version=latest_version,
        backup_path=str(backup_path),
    )


def rollback_update(target_version: str | None = None) -> UpdateResult:
    history = _load_update_history()
    rollback_record: dict[str, Any] | None = None

    if target_version:
        for record in reversed(history):
            if record.get("action") == "update" and record.get("success"):
                if record.get("to_version") == target_version:
                    rollback_record = record
                    break
    else:
        for record in reversed(history):
            if record.get("action") == "update" and record.get("success"):
                rollback_record = record
                break

    if not rollback_record:
        return UpdateResult(
            ok=False,
            message="No successful update found to rollback",
            error="no_update_to_rollback",
        )

    backup_path_str = rollback_record.get("backup_path", "")
    if not backup_path_str or not Path(backup_path_str).is_file():
        return UpdateResult(
            ok=False,
            message="Backup file not found for rollback",
            error="backup_not_found",
        )

    from_version = rollback_record.get("from_version", "unknown")
    to_version = rollback_record.get("to_version", "unknown")

    if not _rollback_install(Path(backup_path_str), from_version):
        return UpdateResult(
            ok=False,
            message="Rollback failed - could not restore package",
            from_version=to_version,
            to_version=from_version,
            error="rollback_failed",
        )

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": "rollback",
        "from_version": to_version,
        "to_version": from_version,
        "success": True,
    }
    _save_update_record(record)

    return UpdateResult(
        ok=True,
        message=f"Rolled back from v{to_version} to v{from_version}",
        from_version=to_version,
        to_version=from_version,
        rolled_back=True,
    )


def _backup_current_package() -> Path | None:
    try:
        result = subprocess.run(
            ["pip", "download", "--no-deps", "--dest", str(_history_dir()), PACKAGE_NAME],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            backup_files = list(_history_dir().glob(f"{WHEEL_PREFIX}*.whl"))
            if backup_files:
                return backup_files[0]
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def _rollback_install(backup_path: Path, target_version: str) -> bool:
    try:
        result = subprocess.run(
            ["pip", "install", "--force-reinstall", "--no-deps", str(backup_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            if _verify_installed_version(target_version):
                return True
    except (subprocess.TimeoutExpired, OSError):
        pass
    return False


def _verify_installed_version(expected: str) -> bool:
    try:
        installed = _package_version(PACKAGE_NAME)
        return _versions_compatible(expected, installed)
    except PackageNotFoundError:
        return False
