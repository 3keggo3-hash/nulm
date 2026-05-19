"""System prompt and setup guide helpers for Nulm."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

SYSTEM_PROMPT = """
You are connected to Nulm over MCP.

Local project access:
- You can inspect the configured local project through Nulm tools.
- Do not say you cannot see local files before checking the available Nulm tools.
- For requests about this codebase, first call workspace_status(), then list_directory,
  find_relevant_files, read_file, or read_multiple_files as needed.
- For AI Council, AI Evaluator, Guard Policy, plan review, quality review, setup, or token
  questions, call nulm_assist(goal=..., target=...) first. It routes natural-language IDE
  requests to the right Nulm tools.

Key rules:
- Always inspect files before editing (read_file or list_directory).
- Prefer patch_file over write_file for existing files.
- If a path fails with path_outside_project, call workspace_status() then switch_project_root().
- Cross-check related files before concluding behavior is explained.
- AI Evaluator and Guard Policy are runtime guard layers: inspect them with bridge_status/get_config,
  then use guarded file or shell tools. Do not look for a separate "run evaluator" tool.
- Treat MCP tool results as source of truth.
- Use precise SEARCH/REPLACE blocks.

Response language: Turkish unless user requests otherwise.
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
    tool_profile: str = "standard",
    context_budget_profile: str = "balanced",
    onboarding_enabled: bool = True,
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
        "CLAUDE_BRIDGE_TOOL_PROFILE": tool_profile,
        "CLAUDE_BRIDGE_CONTEXT_BUDGET_PROFILE": context_budget_profile,
        "CLAUDE_BRIDGE_ONBOARDING_ENABLED": "1" if onboarding_enabled else "0",
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
    tool_profile: str = "standard",
    context_budget_profile: str = "balanced",
    onboarding_enabled: bool = True,
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
        tool_profile=tool_profile,
        context_budget_profile=context_budget_profile,
        onboarding_enabled=onboarding_enabled,
    )
    if target == "claude-desktop":
        return {"mcpServers": {"nulm": server_entry}}
    if target == "generic-stdio":
        return {"servers": {"nulm": server_entry}}
    return {"mcp": {"servers": {"nulm": server_entry}}}


def build_desktop_config(
    project_dir: Path,
    *,
    allowed_roots: list[Path] | None = None,
    python_executable: str | None = None,
    package_root: Path | None = None,
    auto_approve: bool = False,
    client_managed_approval: bool = False,
    approval_preset: str | None = None,
    tool_profile: str = "standard",
    context_budget_profile: str = "balanced",
    onboarding_enabled: bool = True,
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
        tool_profile=tool_profile,
        context_budget_profile=context_budget_profile,
        onboarding_enabled=onboarding_enabled,
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
    tool_profile: str = "standard",
    context_budget_profile: str = "balanced",
    onboarding_enabled: bool = True,
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
        tool_profile=tool_profile,
        context_budget_profile=context_budget_profile,
        onboarding_enabled=onboarding_enabled,
    )
    config_json = json.dumps(config, indent=2, ensure_ascii=False)
    target_title = {
        "claude-desktop": "Claude Desktop",
        "generic-stdio": "a generic stdio MCP client",
        "vscode": "VS Code or a VS Code MCP extension",
    }[target]
    location_hint = {
        "claude-desktop": "editing `claude_desktop_config.json`",
        "generic-stdio": ("adding this server entry to your client's MCP JSON config"),
        "vscode": (
            "adding this JSON snippet to the relevant VS Code MCP settings or extension config"
        ),
    }[target]
    wrapper_note = {
        "claude-desktop": ("Uses the `mcpServers` wrapper expected by Claude Desktop."),
        "generic-stdio": (
            "Uses a simple `servers` wrapper. If your client expects a"
            " different top-level key, keep the inner `nulm`"
            " server entry and adapt only the wrapper."
        ),
        "vscode": (
            "Uses an `mcp.servers` wrapper as a practical VS Code-oriented"
            " snippet. If your chosen extension expects a different top-level"
            " key, keep the inner `nulm` entry and adjust only the"
            " wrapper."
        ),
    }[target]
    after_saving = {
        "claude-desktop": (
            "1. Fully quit Claude Desktop.\n"
            "2. Reopen Claude Desktop.\n"
            "3. Start a new chat and confirm the Nulm tools appear."
        ),
        "generic-stdio": (
            "1. Save the config in the location your MCP client reads.\n"
            "2. Restart or reload that client.\n"
            "3. Confirm the Nulm tools appear."
        ),
        "vscode": (
            "1. Save the settings or extension config.\n"
            "2. Reload VS Code or restart the extension host.\n"
            "3. Confirm the Nulm tools appear in the MCP-capable UI."
        ),
    }[target]
    first_message_tip = ""
    if target == "claude-desktop":
        first_message_tip = """

First-message tip:
- Start codebase requests with a direct instruction such as:
  - "Use Nulm to inspect this local project and implement the change."
  - "Call workspace_status(), then read the relevant files."
- If Claude says it cannot access local files, ask it to check the Nulm MCP tools
  before answering.
""".rstrip()

    return f"""
Add Nulm to {target_title} by {location_hint}.

Recommended configuration:

```json
{config_json}
```

Why this format:
- Launches Nulm through `python -m claude_bridge.mcp_server`, which is
  more reliable for Claude Desktop than printing setup text during MCP startup.
- Passes the active project root through `CLAUDE_BRIDGE_PROJECT_DIR`.
- Passes the broader allowed workspace list through
  `CLAUDE_BRIDGE_ALLOWED_ROOTS`.
- Uses `CLAUDE_BRIDGE_TOOL_PROFILE=standard` by default so MCP clients receive
  the common tool set instead of every niche tool schema.
- Uses `CLAUDE_BRIDGE_CONTEXT_BUDGET_PROFILE=balanced` by default to keep file
  previews and context packs bounded.
- Keeps stdout clean for the MCP protocol.
- {wrapper_note}

After saving the config:
{after_saving}

{first_message_tip}

Approval note:
- In MCP stdio mode, Nulm cannot safely pause for terminal `input()`
  prompts.
- If you want `run_shell`, `write_file`, `patch_file`, and `undo_last_patch`
  to work with approvals, generate config with client-managed approval enabled.
- Otherwise, leave the server fail-closed or enable auto-approve only in a
  trusted local environment.

Troubleshooting:
- Make sure the selected Python environment can import `claude_bridge`.
- If you are running from this repository, keep `PYTHONPATH` pointing at the
  local `src` directory.
- If the server does not appear, reopen the target config and check for JSON
  syntax errors.
""".strip()
