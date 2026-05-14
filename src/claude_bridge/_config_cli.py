"""Config CLI commands."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from claude_bridge.config import (
    BUDGET_PROFILES,
    TOOL_PROFILES,
    APPROVAL_PRESETS,
    current_config,
    update_runtime_config,
    validate_config_value,
)

console = Console()
_TOML_SENSITIVE_KEYS = {"ai_evaluator_api_key"}
_CLI_READONLY_KEYS = _TOML_SENSITIVE_KEYS | {
    "project_dir",
    "allowed_roots",
}


def _cloudflared_available() -> bool:
    return shutil.which("cloudflared") is not None


def _find_config_path() -> Path | None:
    if os.environ.get("CLAUDE_BRIDGE_CONFIG"):
        path = Path(os.environ["CLAUDE_BRIDGE_CONFIG"])
        if path.exists():
            return path
    xdg = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    path = Path(xdg) / "claude-bridge" / "config.toml"
    if path.exists():
        return path
    path = Path.home() / ".config" / "claude-bridge" / "config.toml"
    if path.exists():
        return path
    path = Path.cwd() / "config.toml"
    if path.exists():
        return path
    return None


config_app = typer.Typer(help="Config management")


def _format_config_value(key: str, value: Any) -> str:
    if key == "allowed_roots":
        return ", ".join(str(p) for p in value)
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return str(value)


@config_app.command("list")
def config_list(
    json_output: bool = typer.Option(False, "--json", help="Machine-readable output"),
) -> None:
    """List all current configuration values."""
    cfg = current_config()
    if json_output:
        import json as _json

        safe_cfg = {k: v for k, v in cfg.items() if k != "ai_evaluator_api_key"}
        console.print(_json.dumps(safe_cfg, indent=2))
        return
    table = Table(title="CURRENT CONFIGURATION", show_header=True, header_style="bold")
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")
    for key, value in cfg.items():
        if key in _TOML_SENSITIVE_KEYS:
            value = "[REDACTED]"
        else:
            value = _format_config_value(key, value)
        table.add_row(key, value)
    console.print(table)


@config_app.command("get")
def config_get(
    key: str = typer.Argument(..., help="Config key to retrieve"),
) -> None:
    """Get a single configuration value."""
    cfg = current_config()
    if key not in cfg:
        valid_keys = ", ".join(sorted(cfg.keys()))
        console.print(f"[red]Unknown config key:[/red] {key}")
        console.print(f"Valid keys: {valid_keys}")
        raise typer.Exit(code=1)
    value = cfg[key]
    if key in _TOML_SENSITIVE_KEYS:
        value = "[REDACTED]"
    else:
        value = _format_config_value(key, value)
    console.print(value)


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Config key to set"),
    value: str = typer.Argument(..., help="Value to set"),
) -> None:
    """Set a configuration value."""
    if key in _CLI_READONLY_KEYS:
        console.print(f"[red]Cannot modify {key} via CLI[/red]")
        console.print("This key requires direct config.toml edit or environment variable.")
        raise typer.Exit(code=1)
    parsed_value: Any = value
    try:
        if key in {"shell_timeout", "ai_evaluator_timeout", "max_parallel"}:
            parsed_value = int(value)
        elif key in {"auto_approve", "client_managed_approval", "onboarding_enabled", "intent_compaction_enabled", "ai_evaluator_enabled"}:
            parsed_value = value.lower() in {"true", "1", "yes", "on"}
        validate_config_value(key, parsed_value)
    except ValueError as exc:
        console.print(f"[red]Invalid value for {key}[/red]")
        console.print(f"  {exc}")
        console.print()
        console.print("[bold]Next steps:[/bold]")
        console.print("  [dim]→[/dim] [cyan]claude-bridge config list[/cyan]  Show all config values")
        console.print(f"  [dim]→[/dim] [cyan]claude-bridge config describe {key}[/cyan]  Describe this key")
        raise typer.Exit(code=1)
    try:
        result = update_runtime_config(key, parsed_value)
        console.print(f"[green]✓[/green] {key} set to {parsed_value!r}")
        if "_warning" in result:
            console.print(f"[yellow]Warning:[/yellow] {result['_warning']}")
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        console.print()
        console.print("[bold]Next steps:[/bold]")
        console.print("  [dim]→[/dim] [cyan]claude-bridge config list[/cyan]  Show all config values")
        console.print(f"  [dim]→[/dim] [cyan]claude-bridge config describe {key}[/cyan]  Describe this key")
        raise typer.Exit(code=1)


@config_app.command("describe")
def config_describe(
    key: str = typer.Argument(..., help="Config key to describe"),
) -> None:
    """Describe a configuration key."""
    descriptions: dict[str, str] = {
        "shell_timeout": "Shell command timeout in seconds (positive integer, 1-120)",
        "ai_evaluator_timeout": "AI evaluator timeout in seconds (positive integer)",
        "ai_evaluator_provider": f"AI provider: {', '.join(['local', 'openai', 'anthropic', 'ollama', 'deepseek'])}",
        "ai_evaluator_fallback_action": "Fallback action when evaluator fails: deny or ask",
        "context_budget_profile": f"Context budget: {', '.join(BUDGET_PROFILES)}",
        "tool_profile": f"Tool profile: {', '.join(TOOL_PROFILES)}",
        "approval_preset": f"Approval preset: {', '.join(k for k in APPROVAL_PRESETS if k)}",
        "role": "Role identifier (alphanumeric, hyphen, underscore)",
        "user": "User identifier (alphanumeric, hyphen, underscore)",
        "auto_approve": "Auto-approve tool calls without confirmation",
        "client_managed_approval": "Use client-managed approval flow",
        "onboarding_enabled": "Enable onboarding flow for new users",
        "intent_compaction_enabled": "Enable goal/intent compaction",
        "ai_evaluator_enabled": "Enable AI evaluator for tool calls",
        "ai_evaluator_model": "AI evaluator model name",
        "max_parallel": "Maximum parallel workflow/validation workers, integer 1-32.",
        "auto_approve_risk_level": "Highest risk level auto-approved when auto_approve is enabled: none, low, medium, high.",
    }
    if key not in descriptions:
        console.print(f"[red]Unknown config key:[/red] {key}")
        console.print(f"Describable keys: {', '.join(sorted(descriptions.keys()))}")
        raise typer.Exit(code=1)
    console.print(f"[bold]{key}[/bold]")
    console.print(descriptions[key])