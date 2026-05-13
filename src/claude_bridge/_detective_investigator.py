"""Diagnostic commands for Bridge Detective investigation phase."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

_DIAGNOSTIC_COMMANDS: dict[str, list[list[str]]] = {
    "SYNTAX_ERROR": [
        ["python", "-m", "py_compile"],
    ],
    "RUNTIME_ERROR": [
        ["python", "-m", "pytest", "--collect-only"],
        ["python", "-c", "import sys; print(sys.version)"],
    ],
    "SECURITY_ERROR": [
        ["python", "-c", "import ast; ast.parse(open('.').read())"],
    ],
    "NETWORK_ERROR": [
        ["ping", "-c", "1", "127.0.0.1"],
        ["python", "-c", "import socket; print(socket.gethostname())"],
    ],
    "UNKNOWN": [
        ["python", "-c", "import sys; print(sys.version)"],
    ],
}


async def run_diagnostics(
    file_path: str,
    error_type: str,
    project_dir_path: Path,
    *,
    allow_commands: bool = False,
) -> dict[str, Any]:
    """Run diagnostic commands based on error type."""
    commands = _DIAGNOSTIC_COMMANDS.get(error_type, _DIAGNOSTIC_COMMANDS["UNKNOWN"])
    results: list[dict[str, Any]] = []

    for cmd in commands:
        if not allow_commands:
            results.append(
                {
                    "command": " ".join(cmd),
                    "returncode": None,
                    "stdout": "",
                    "stderr": "diagnostic command not run; explicit approval required",
                    "executed": False,
                }
            )
            continue
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=project_dir_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            results.append(
                {
                    "command": " ".join(cmd),
                    "returncode": proc.returncode,
                    "stdout": stdout.decode("utf-8", errors="replace"),
                    "stderr": stderr.decode("utf-8", errors="replace"),
                    "executed": True,
                }
            )
        except (asyncio.TimeoutError, OSError) as exc:
            results.append(
                {
                    "command": " ".join(cmd),
                    "returncode": -1,
                    "stdout": "",
                    "stderr": str(exc),
                    "executed": True,
                }
            )

    return {"diagnostics": results}


def check_dependencies(file_path: str, project_dir_path: Path) -> dict[str, Any]:
    """Check if dependencies used in the file can be imported."""
    missing: list[str] = []
    path_obj = Path(file_path)
    if not path_obj.exists():
        path_obj = project_dir_path / file_path
    if not path_obj.exists():
        return {"ok": False, "missing": missing}

    try:
        content = path_obj.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"ok": False, "missing": [], "error": str(exc)}

    import_re = __import__("re").compile(
        r"^\s*(?:import|from)\s+([^\s.]+)",
        __import__("re").MULTILINE,
    )
    modules = import_re.findall(content)
    stdlib_modules = {
        "os",
        "sys",
        "re",
        "json",
        "datetime",
        "pathlib",
        "typing",
        "collections",
        "itertools",
        "functools",
        "operator",
        "inspect",
    }

    project_modules = {path.stem for path in project_dir_path.rglob("*.py")}
    external: list[str] = []
    for module in modules:
        if module in stdlib_modules or module in project_modules:
            continue
        if module not in external:
            external.append(module)

    return {"ok": True, "missing": missing, "unverified_external_modules": external}


def check_file_permissions(file_path: str, project_dir_path: Path) -> dict[str, Any]:
    """Check if a file has correct permissions."""
    path_obj = Path(file_path)
    if not path_obj.is_absolute():
        path_obj = project_dir_path / file_path

    if not path_obj.exists():
        return {"ok": False, "error": "file not found"}

    try:
        path_obj.stat()
        return {
            "ok": True,
            "readable": os.access(path_obj, os.R_OK),
            "writable": os.access(path_obj, os.W_OK),
            "executable": os.access(path_obj, os.X_OK),
        }
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
