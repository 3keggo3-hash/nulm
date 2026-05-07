"""Check for claude-bridge updates from PyPI."""

from __future__ import annotations

import json
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import URLError

from importlib.metadata import PackageNotFoundError, version as _package_version

from claude_bridge.tool_utils import json_response


def check_update() -> str:
    """Return a JSON string with update status info.

    Keys: ok, message, details with current_version, latest_version,
    up_to_date (bool), install_command.
    """
    try:
        current_version = _package_version("claude-bridge")
    except PackageNotFoundError:
        current_version = "unknown"

    latest_version = _fetch_latest_version()
    up_to_date = current_version != "unknown" and current_version == latest_version

    if current_version == "unknown":
        ok = True
        message = "Could not determine installed version"
    elif latest_version == "unknown":
        ok = True
        message = "Could not determine latest version from PyPI"
    elif up_to_date:
        ok = True
        message = f"claude-bridge is up to date (v{current_version})"
    else:
        ok = True
        message = f"Update available: v{current_version} → v{latest_version}"

    details: dict[str, Any] = {
        "current_version": current_version,
        "latest_version": latest_version,
        "up_to_date": up_to_date,
        "install_command": "pip install --upgrade claude-bridge",
    }

    return json_response(ok, message, details=details)


def _fetch_latest_version() -> str:
    """Fetch the latest claude-bridge version from PyPI JSON API."""
    url = "https://pypi.org/pypi/claude-bridge/json"
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read(65536).decode("utf-8"))
        return str(data.get("info", {}).get("version", "unknown"))
    except (URLError, OSError, ValueError, KeyError):
        return "unknown"
