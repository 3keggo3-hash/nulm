"""System prompt and setup guide helpers for Claude Bridge."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

SYSTEM_PROMPT = """
You are connected to Claude Bridge over MCP.

Available tools:
- `read_file(path)` to inspect files before making changes
- `list_directory(path)` to understand project structure
- `run_shell(command)` for safe, non-interactive commands after user approval
- `patch_file(file, search, replace)` to apply SEARCH/REPLACE edits
- `workspace_status()` to see the active project root and allowed roots
- `switch_project_root(path)` to move into another allowed project folder

Rules:
- Never write full files when a targeted patch is enough.
- Always inspect the relevant file first with `read_file` or `list_directory`.
- When any tool returns code `path_outside_project`, do not claim access is unavailable yet. First call `workspace_status()`, then `switch_project_root(path)` if the target is inside an allowed root, and then retry the original operation.
- Any subdirectory inside an allowed root is also switchable. If `/Users/me/Desktop` is allowed, `/Users/me/Desktop/my-game` is valid for `switch_project_root(...)`.
- Prefer `patch_file` with precise SEARCH and REPLACE blocks.
- Mention when a shell command or patch will require approval or confirmation.
- Treat MCP tool results as the source of truth.
- Do not stop after finding a single matching constant, comment, or obvious-looking file. Cross-check related files before concluding the behavior is fully explained.
- When a project has framework-specific runtime files, inspect them too. Example: in Godot projects, check scripts together with `project.godot`, scene files, and `export_presets.cfg` when they may affect runtime behavior.
- For larger changes, hold a quality bar: correctness first, then regression safety, then readability, then tests, then user-visible impact.
- For larger tasks, prefer decomposition: identify independent workstreams, keep ownership boundaries clear, then merge only after an integration pass and a final quality check.

When editing code, think in small verified steps:
1. Read the file or directory you need.
2. Cross-check nearby config, entrypoint, scene, or export files when the first file alone may be misleading.
3. Explain the bug, risk, or gap briefly.
4. Apply a focused SEARCH/REPLACE patch.
5. Run validation commands when useful.
6. Summarize what changed and any remaining risks.

SEARCH/REPLACE reminder:
SEARCH:
<exact existing text>
REPLACE:
<new text>
""".strip()

SUPPORTED_SETUP_TARGETS = ("claude-desktop", "generic-stdio", "vscode")


def build_stdio_server_entry(
    project_dir: Path,
    *,
    allowed_roots: list[Path] | None = None,
    python_executable: str | None = None,
    package_root: Path | None = None,
    auto_approve: bool = False,
    client_managed_approval: bool = False,
    approval_preset: str | None = None,
) -> dict[str, Any]:
    """Build a portable stdio MCP server entry."""
    python_cmd = python_executable or sys.executable
    package_root = package_root or Path(__file__).resolve().parents[2]

    env = {
        "CLAUDE_BRIDGE_PROJECT_DIR": str(project_dir.resolve()),
        "CLAUDE_BRIDGE_ALLOWED_ROOTS": os.pathsep.join(
            str(root.resolve()) for root in (allowed_roots or [project_dir])
        ),
        "CLAUDE_BRIDGE_AUTO_APPROVE": "1" if auto_approve else "0",
        "CLAUDE_BRIDGE_CLIENT_MANAGED_APPROVAL": "1" if client_managed_approval else "0",
        "PYTHONUNBUFFERED": "1",
    }
    if approval_preset is not None:
        env["CLAUDE_BRIDGE_APPROVAL_PRESET"] = approval_preset

    src_dir = package_root / "src"
    if src_dir.exists():
        env["PYTHONPATH"] = str(src_dir)

    return {
        "command": python_cmd,
        "args": ["-m", "claude_bridge.mcp_server"],
        "env": env,
    }


def build_target_config(
    project_dir: Path,
    *,
    target: str = "claude-desktop",
    allowed_roots: list[Path] | None = None,
    python_executable: str | None = None,
    package_root: Path | None = None,
    auto_approve: bool = False,
    client_managed_approval: bool = False,
    approval_preset: str | None = None,
) -> dict[str, Any]:
    """Build a target-specific MCP config snippet."""
    if target not in SUPPORTED_SETUP_TARGETS:
        raise ValueError(f"Unsupported setup target: {target}")
    server_entry = build_stdio_server_entry(
        project_dir,
        allowed_roots=allowed_roots,
        python_executable=python_executable,
        package_root=package_root,
        auto_approve=auto_approve,
        client_managed_approval=client_managed_approval,
        approval_preset=approval_preset,
    )
    if target == "claude-desktop":
        return {"mcpServers": {"claude-bridge": server_entry}}
    if target == "generic-stdio":
        return {"servers": {"claude-bridge": server_entry}}
    return {"mcp": {"servers": {"claude-bridge": server_entry}}}


def build_desktop_config(
    project_dir: Path,
    *,
    allowed_roots: list[Path] | None = None,
    python_executable: str | None = None,
    package_root: Path | None = None,
    auto_approve: bool = False,
    client_managed_approval: bool = False,
    approval_preset: str | None = None,
) -> dict[str, object]:
    """Build a Claude Desktop MCP config snippet."""
    return build_target_config(
        project_dir,
        target="claude-desktop",
        allowed_roots=allowed_roots,
        python_executable=python_executable,
        package_root=package_root,
        auto_approve=auto_approve,
        client_managed_approval=client_managed_approval,
        approval_preset=approval_preset,
    )


def generate_mcp_setup_guide(
    project_dir: Path,
    *,
    target: str = "claude-desktop",
    allowed_roots: list[Path] | None = None,
    python_executable: str | None = None,
    package_root: Path | None = None,
    auto_approve: bool = False,
    client_managed_approval: bool = False,
    approval_preset: str | None = None,
) -> str:
    """Render a copy-paste setup guide for a supported MCP client target."""
    config = build_target_config(
        project_dir,
        target=target,
        allowed_roots=allowed_roots,
        python_executable=python_executable,
        package_root=package_root,
        auto_approve=auto_approve,
        client_managed_approval=client_managed_approval,
        approval_preset=approval_preset,
    )
    config_json = json.dumps(config, indent=2, ensure_ascii=False)
    target_title = {
        "claude-desktop": "Claude Desktop",
        "generic-stdio": "a generic stdio MCP client",
        "vscode": "VS Code or a VS Code MCP extension",
    }[target]
    location_hint = {
        "claude-desktop": "editing `claude_desktop_config.json`",
        "generic-stdio": "adding this server entry to your client's MCP JSON config",
        "vscode": "adding this JSON snippet to the relevant VS Code MCP settings or extension config",
    }[target]
    wrapper_note = {
        "claude-desktop": "Uses the `mcpServers` wrapper expected by Claude Desktop.",
        "generic-stdio": "Uses a simple `servers` wrapper. If your client expects a different top-level key, keep the inner `claude-bridge` server entry and adapt only the wrapper.",
        "vscode": "Uses an `mcp.servers` wrapper as a practical VS Code-oriented snippet. If your chosen extension expects a different top-level key, keep the inner `claude-bridge` entry and adjust only the wrapper.",
    }[target]
    after_saving = {
        "claude-desktop": (
            "1. Fully quit Claude Desktop.\n"
            "2. Reopen Claude Desktop.\n"
            "3. Start a new chat and confirm the Claude Bridge tools appear."
        ),
        "generic-stdio": (
            "1. Save the config in the location your MCP client reads.\n"
            "2. Restart or reload that client.\n"
            "3. Confirm the Claude Bridge tools appear."
        ),
        "vscode": (
            "1. Save the settings or extension config.\n"
            "2. Reload VS Code or restart the extension host.\n"
            "3. Confirm the Claude Bridge tools appear in the MCP-capable UI."
        ),
    }[target]
    first_message_tip = ""
    if target == "claude-desktop":
        first_message_tip = """

First-message tip:
- Claude Desktop may occasionally delay MCP tool routing until the second turn.
- If the first reply claims it cannot access files, retry with a more explicit message such as:
  - "Read the files in this project with claude-bridge"
  - "Use workspace_status() and inspect the codebase"
  - "Review this folder and use claude-bridge tools"
""".rstrip()

    return f"""
Add Claude Bridge to {target_title} by {location_hint}.

Recommended configuration:

```json
{config_json}
```

Why this format:
- Launches Claude Bridge through `python -m claude_bridge.mcp_server`, which is more reliable for Claude Desktop than printing setup text during MCP startup.
- Passes the active project root through `CLAUDE_BRIDGE_PROJECT_DIR`.
- Passes the broader allowed workspace list through `CLAUDE_BRIDGE_ALLOWED_ROOTS`.
- Keeps stdout clean for the MCP protocol.
- {wrapper_note}

After saving the config:
{after_saving}

{first_message_tip}

Approval note:
- In MCP stdio mode, Claude Bridge cannot safely pause for terminal `input()` prompts.
- If you want `run_shell`, `write_file`, `patch_file`, and `undo_last_patch` to work with approvals, generate config with client-managed approval enabled.
- Otherwise, leave the server fail-closed or enable auto-approve only in a trusted local environment.

Troubleshooting:
- Make sure the selected Python environment can import `claude_bridge`.
- If you are running from this repository, keep `PYTHONPATH` pointing at the local `src` directory.
- If the server does not appear, reopen the target config and check for JSON syntax errors.
""".strip()
