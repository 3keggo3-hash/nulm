"""System prompt and setup guide helpers for Claude Bridge."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

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
        "mcpServers": {
            "claude-bridge": {
                "command": python_cmd,
                "args": ["-m", "claude_bridge.mcp_server"],
                "env": env,
            }
        }
    }


def generate_mcp_setup_guide(
    project_dir: Path,
    *,
    allowed_roots: list[Path] | None = None,
    python_executable: str | None = None,
    package_root: Path | None = None,
    auto_approve: bool = False,
    client_managed_approval: bool = False,
    approval_preset: str | None = None,
) -> str:
    """Render a copy-paste setup guide for Claude Desktop."""
    config = build_desktop_config(
        project_dir,
        allowed_roots=allowed_roots,
        python_executable=python_executable,
        package_root=package_root,
        auto_approve=auto_approve,
        client_managed_approval=client_managed_approval,
        approval_preset=approval_preset,
    )
    config_json = json.dumps(config, indent=2, ensure_ascii=False)

    return f"""
Add Claude Bridge to Claude Desktop by editing `claude_desktop_config.json`.

Recommended configuration:

```json
{config_json}
```

Why this format:
- Launches Claude Bridge through `python -m claude_bridge.mcp_server`, which is more reliable for Claude Desktop than printing setup text during MCP startup.
- Passes the active project root through `CLAUDE_BRIDGE_PROJECT_DIR`.
- Passes the broader allowed workspace list through `CLAUDE_BRIDGE_ALLOWED_ROOTS`.
- Keeps stdout clean for the MCP protocol.

After saving the config:
1. Fully quit Claude Desktop.
2. Reopen Claude Desktop.
3. Start a new chat and confirm the Claude Bridge tools appear.

First-message tip:
- Claude Desktop may occasionally delay MCP tool routing until the second turn.
- If the first reply claims it cannot access files, retry with a more explicit message such as:
  - "Read the files in this project with claude-bridge"
  - "Use workspace_status() and inspect the codebase"
  - "Review this folder and use claude-bridge tools"

Approval note:
- In MCP stdio mode, Claude Bridge cannot safely pause for terminal `input()` prompts.
- If you want `run_shell`, `write_file`, `patch_file`, and `undo_last_patch` to work with approvals, generate config with client-managed approval enabled.
- Otherwise, leave the server fail-closed or enable auto-approve only in a trusted local environment.

Troubleshooting:
- Make sure the selected Python environment can import `claude_bridge`.
- If you are running from this repository, keep `PYTHONPATH` pointing at the local `src` directory.
- If the server does not appear, reopen `claude_desktop_config.json` and check for JSON syntax errors.
""".strip()
