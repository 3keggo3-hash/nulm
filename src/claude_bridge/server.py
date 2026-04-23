"""FastAPI-based local bridge server."""

import os
import subprocess
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class ToolRequest(BaseModel):
    tool: str
    params: dict[str, Any]


class BridgeServer:
    """Local server that executes Tool Protocol commands from the browser bookmarklet."""

    BLOCKED_COMMANDS = {"rm -rf", "sudo", "chmod", "mkfs", "dd if=", "> /dev"}

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7337,
        project_dir: Path | None = None,
        auto_approve: bool = False,
    ) -> None:
        self.host = host
        self.port = port
        self.project_dir = project_dir or Path.cwd()
        self.auto_approve = auto_approve
        self.app = FastAPI(title="Claude Bridge", version="0.1.0")
        self._setup_routes()

    def _setup_routes(self) -> None:
        @self.app.post("/execute")
        async def execute_tool(request: ToolRequest) -> dict[str, Any]:
            return await self._handle_tool(request.tool, request.params)

    async def _handle_tool(self, tool: str, params: dict[str, Any]) -> dict[str, Any]:
        if tool == "READ":
            return self._cmd_read(params.get("path", ""))
        elif tool == "LIST":
            return self._cmd_list(params.get("path", ""))
        elif tool == "SHELL":
            return self._cmd_shell(params.get("command", ""))
        elif tool == "PATCH":
            return self._cmd_patch(
                params.get("file", ""),
                params.get("search", ""),
                params.get("replace", ""),
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

    def _resolve_path(self, rel_path: str) -> Path:
        target = (self.project_dir / rel_path).resolve()
        try:
            target.relative_to(self.project_dir.resolve())
        except ValueError as exc:
            raise HTTPException(
                status_code=403,
                detail="Access denied: path outside project directory",
            ) from exc
        return target

    def _cmd_read(self, path: str) -> dict[str, Any]:
        target = self._resolve_path(path)
        if not target.exists():
            return {"ok": False, "error": f"File not found: {path}"}
        if not target.is_file():
            return {"ok": False, "error": f"Not a file: {path}"}
        try:
            content = target.read_text(encoding="utf-8")
            return {"ok": True, "content": content}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _cmd_list(self, path: str) -> dict[str, Any]:
        target = self._resolve_path(path)
        if not target.exists():
            return {"ok": False, "error": f"Directory not found: {path}"}
        if not target.is_dir():
            return {"ok": False, "error": f"Not a directory: {path}"}
        try:
            entries = []
            for entry in sorted(target.iterdir()):
                entries.append(
                    {
                        "name": entry.name,
                        "type": "directory" if entry.is_dir() else "file",
                        "size": entry.stat().st_size if entry.is_file() else None,
                    }
                )
            return {"ok": True, "entries": entries}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _cmd_shell(self, command: str) -> dict[str, Any]:
        lowered = command.lower()
        for blocked in self.BLOCKED_COMMANDS:
            if blocked in lowered:
                return {
                    "ok": False,
                    "error": f"Command blocked for safety: contains '{blocked}'",
                }
        if not self.auto_approve:
            print(f"\n[SHELL] {command}")
            answer = input("Approve? (y/n): ").strip().lower()
            if answer != "y":
                return {"ok": False, "error": "User rejected shell command"}
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=self.project_dir,
                timeout=30,
            )
            return {
                "ok": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Command timed out after 30s"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _cmd_patch(self, file_path: str, search: str, replace: str) -> dict[str, Any]:
        target = self._resolve_path(file_path)
        if not target.exists():
            return {"ok": False, "error": f"File not found: {file_path}"}
        try:
            original = target.read_text(encoding="utf-8")
        except Exception as exc:
            return {"ok": False, "error": f"Failed to read file: {exc}"}

        # Normalize line endings
        original_norm = original.replace("\r\n", "\n")
        search_norm = search.replace("\r\n", "\n")
        replace_norm = replace.replace("\r\n", "\n")

        occurrences = original_norm.count(search_norm)
        if occurrences == 0:
            return {"ok": False, "error": "SEARCH text not found in file"}
        if occurrences > 1:
            return {
                "ok": False,
                "error": f"SEARCH text is ambiguous (found {occurrences} times). Please use a more specific block.",
            }

        new_content_norm = original_norm.replace(search_norm, replace_norm, 1)

        # Basic syntax check for Python files
        if target.suffix == ".py":
            try:
                import ast
                ast.parse(new_content_norm)
            except SyntaxError as exc:
                return {
                    "ok": False,
                    "error": f"Python syntax error after patch: {exc}",
                }

        if not self.auto_approve:
            print(f"\n[PATCH] {file_path}")
            print(f"  SEARCH:  {search_norm[:40].replace(chr(10), ' ')}...")
            print(f"  REPLACE: {replace_norm[:40].replace(chr(10), ' ')}...")
            answer = input("Approve patch? (y/n): ").strip().lower()
            if answer != "y":
                return {"ok": False, "error": "User rejected patch"}

        # Preserve original line endings
        if "\r\n" in original:
            new_content = new_content_norm.replace("\n", "\r\n")
        else:
            new_content = new_content_norm

        try:
            target.write_text(new_content, encoding="utf-8")
            self._auto_git_commit(file_path)
            return {"ok": True, "message": f"Patched {file_path}"}
        except Exception as exc:
            return {"ok": False, "error": f"Failed to write file: {exc}"}

    def _auto_git_commit(self, file_path: str) -> None:
        git_dir = self.project_dir / ".git"
        if not git_dir.exists():
            subprocess.run(["git", "init"], cwd=self.project_dir, capture_output=True)
        subprocess.run(
            ["git", "add", file_path],
            cwd=self.project_dir,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", f"bridge: update {file_path}"],
            cwd=self.project_dir,
            capture_output=True,
        )

    def run(self) -> None:
        import uvicorn

        uvicorn.run(self.app, host=self.host, port=self.port, log_level="info")
