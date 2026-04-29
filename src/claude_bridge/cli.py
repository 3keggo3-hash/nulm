"""Command-line interface for Claude Bridge."""

from __future__ import annotations

import json
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text

from claude_bridge import __version__
from claude_bridge.audit import summarize_session
from claude_bridge.benchmarking import run_index_and_relevance_benchmark
from claude_bridge.benchmarking import compare_benchmark_to_baseline
from claude_bridge.benchmarking import load_benchmark_profile
from claude_bridge.config import APPROVAL_PRESETS, resolve_approval_mode
from claude_bridge.server import current_config, mcp, set_config
from claude_bridge.prompt import SYSTEM_PROMPT, build_desktop_config, generate_mcp_setup_guide

app = typer.Typer(help="Claude Bridge — MCP server for local file and terminal access")
console = Console()


def _resolve_cli_approval_mode(
    *,
    approval_preset: str | None,
    auto_approve: bool,
    client_managed_approval: bool,
) -> tuple[bool, bool, str | None]:
    try:
        return resolve_approval_mode(
            approval_preset=approval_preset,
            auto_approve=auto_approve,
            client_managed_approval=client_managed_approval,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _approval_help_suffix() -> str:
    return "Available presets: " + ", ".join(APPROVAL_PRESETS.keys())


def _default_claude_desktop_config_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Claude/claude_desktop_config.json"
        return Path.home() / "AppData/Roaming/Claude/claude_desktop_config.json"
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home) / "Claude/claude_desktop_config.json"
    return Path.home() / ".config/Claude/claude_desktop_config.json"


def _load_desktop_config(config_path: Path) -> dict[str, object]:
    if not config_path.exists():
        return {}
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Claude Desktop config is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("Claude Desktop config root must be a JSON object")
    return raw


def _write_desktop_config(
    config_path: Path,
    *,
    project_dir: Path,
    allowed_roots: list[Path],
    auto_approve: bool,
    client_managed_approval: bool,
    approval_preset: str | None = None,
) -> Path:
    config = _load_desktop_config(config_path)
    servers = config.get("mcpServers")
    if servers is None:
        config["mcpServers"] = {}
        servers = config["mcpServers"]
    if not isinstance(servers, dict):
        raise ValueError("Claude Desktop config field 'mcpServers' must be a JSON object")

    generated_config = build_desktop_config(
        project_dir.resolve(),
        allowed_roots=allowed_roots,
        auto_approve=auto_approve,
        client_managed_approval=client_managed_approval,
        approval_preset=approval_preset,
    )
    mcp_servers = generated_config.get("mcpServers")
    if not isinstance(mcp_servers, dict):
        raise ValueError("Generated desktop config is missing 'mcpServers'")
    bridge_entry = mcp_servers.get("claude-bridge")
    if not isinstance(bridge_entry, dict):
        raise ValueError("Generated desktop config is missing the 'claude-bridge' entry")
    servers["claude-bridge"] = bridge_entry

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return config_path


@app.command()
def start(
    project_dir: Path = typer.Option(
        Path.cwd(), help="Root directory the bridge is allowed to access"
    ),
    allow_root: list[Path] = typer.Option(
        None, "--allow-root", help="Additional allowed workspace root"
    ),
    approval_preset: str | None = typer.Option(
        None, "--approval-preset", help=_approval_help_suffix()
    ),
    auto_approve: bool = typer.Option(
        False, help="Automatically approve all operations (not recommended)"
    ),
) -> None:
    """Start the MCP bridge server (stdio transport)."""
    extra_roots = [path.resolve() for path in allow_root] if allow_root else []
    resolved_auto_approve, resolved_client_managed, resolved_preset = _resolve_cli_approval_mode(
        approval_preset=approval_preset,
        auto_approve=auto_approve,
        client_managed_approval=False,
    )
    set_config(
        project_dir=project_dir.resolve(),
        allowed_roots=[project_dir.resolve(), *extra_roots],
        auto_approve=resolved_auto_approve,
        client_managed_approval=resolved_client_managed,
        approval_preset=resolved_preset,
    )
    try:
        mcp.run(transport="stdio")
    except KeyboardInterrupt:
        sys.exit(0)


@app.command()
def version() -> None:
    """Show version information."""
    console.print(f"[bold cyan]Claude Bridge[/bold cyan] version [green]{__version__}[/green]")


@app.command()
def setup(
    project_dir: Path = typer.Option(
        Path.cwd(), help="Root directory the bridge is allowed to access"
    ),
    allow_root: list[Path] = typer.Option(
        None, "--allow-root", help="Additional allowed workspace root"
    ),
    approval_preset: str | None = typer.Option(
        None, "--approval-preset", help=_approval_help_suffix()
    ),
    auto_approve: bool = typer.Option(
        False, help="Render config with auto-approve enabled"
    ),
    client_managed_approval: bool = typer.Option(
        False, help="Render config assuming the MCP client handles approvals"
    ),
) -> None:
    """Print Claude Desktop setup instructions and system prompt."""
    resolved_auto_approve, resolved_client_managed, resolved_preset = _resolve_cli_approval_mode(
        approval_preset=approval_preset,
        auto_approve=auto_approve,
        client_managed_approval=client_managed_approval,
    )
    console.print(
        Panel.fit(
            Text.assemble(
                ("Claude Bridge ", "bold cyan"),
                (f"MCP Server v{__version__}", "dim"),
            ),
            title="Setup",
            border_style="cyan",
        )
    )
    console.print(f"Project directory: [green]{project_dir.resolve()}[/green]")
    if resolved_preset is not None:
        console.print(f"Approval preset: [cyan]{resolved_preset}[/cyan]")
    if allow_root:
        console.print(
            "Allowed roots: "
            + ", ".join(f"[green]{path.resolve()}[/green]" for path in allow_root)
        )
    if resolved_auto_approve:
        console.print("[red bold]WARNING:[/red bold] Auto-approve is enabled in the example config.")
    if resolved_client_managed:
        console.print("[yellow bold]NOTE:[/yellow bold] Example config delegates approval to the MCP client.")
    if not resolved_auto_approve and not resolved_client_managed:
        console.print(
            "[yellow bold]NOTE:[/yellow bold] Approval-requiring tools will fail closed until you either enable "
            "client-managed approval or explicitly turn on auto-approve in a trusted local environment."
        )

    console.print("\n[bold]Claude Desktop Setup:[/bold]")
    console.print(
        Panel(
            generate_mcp_setup_guide(
                project_dir.resolve(),
                allowed_roots=[project_dir.resolve(), *([path.resolve() for path in allow_root] if allow_root else [])],
                auto_approve=resolved_auto_approve,
                client_managed_approval=resolved_client_managed,
                approval_preset=resolved_preset,
            ),
            title="Copy into Claude Desktop config",
            border_style="green",
        )
    )
    console.print("\n[bold]System Prompt:[/bold]")
    console.print(
        Panel(
            escape(SYSTEM_PROMPT),
            title="Add to Claude.ai Project Instructions",
            border_style="blue",
        )
    )


@app.command()
def install(
    project_dir: Path = typer.Option(
        Path.cwd(), help="Root directory the bridge is allowed to access"
    ),
    allow_root: list[Path] = typer.Option(
        None, "--allow-root", help="Additional allowed workspace root"
    ),
    config_path: Path = typer.Option(
        None, "--config-path", help="Override Claude Desktop config path"
    ),
    approval_preset: str | None = typer.Option(
        None, "--approval-preset", help=_approval_help_suffix()
    ),
    auto_approve: bool = typer.Option(
        False, help="Write config with auto-approve enabled (trusted local use only)"
    ),
    client_managed_approval: bool = typer.Option(
        True, help="Write config assuming Claude Desktop handles approval prompts"
    ),
) -> None:
    """Install or update Claude Bridge inside Claude Desktop config."""
    resolved_project_dir = project_dir.resolve()
    resolved_allowed_roots = [resolved_project_dir, *([path.resolve() for path in allow_root] if allow_root else [])]
    resolved_config_path = config_path.resolve() if config_path is not None else _default_claude_desktop_config_path()
    resolved_auto_approve, resolved_client_managed, resolved_preset = _resolve_cli_approval_mode(
        approval_preset=approval_preset,
        auto_approve=auto_approve,
        client_managed_approval=client_managed_approval,
    )

    try:
        written_path = _write_desktop_config(
            resolved_config_path,
            project_dir=resolved_project_dir,
            allowed_roots=resolved_allowed_roots,
            auto_approve=resolved_auto_approve,
            client_managed_approval=resolved_client_managed,
            approval_preset=resolved_preset,
        )
    except ValueError as exc:
        console.print(f"[red]Install failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        Panel.fit(
            Text.assemble(
                ("Claude Bridge ", "bold cyan"),
                ("installed for Claude Desktop", "green"),
            ),
            title="Install",
            border_style="green",
        )
    )
    console.print(f"Config updated: [green]{written_path}[/green]")
    console.print(f"Project directory: [green]{resolved_project_dir}[/green]")
    if resolved_preset is not None:
        console.print(f"Approval preset: [cyan]{resolved_preset}[/cyan]")
    if len(resolved_allowed_roots) > 1:
        console.print(
            "Allowed roots: "
            + ", ".join(f"[green]{path}[/green]" for path in resolved_allowed_roots[1:])
        )
    if resolved_client_managed:
        console.print("[yellow]Approval mode:[/yellow] Claude Desktop manages approval prompts.")
    elif resolved_auto_approve:
        console.print("[red]Approval mode:[/red] Auto-approve enabled for trusted local use.")
    else:
        console.print("[yellow]Approval mode:[/yellow] Fail-closed until approval handling is enabled.")
    console.print("Restart Claude Desktop completely, then start a new chat.")


@app.command()
def benchmark(
    project_dir: Path = typer.Option(
        Path.cwd(), help="Root directory to benchmark"
    ),
    profile_file: Path = typer.Option(
        None, "--profile-file", help="Optional benchmark profile JSON file"
    ),
    path: str = typer.Option(".", help="Subdirectory to index and query"),
    query: str = typer.Option("", help="Natural-language relevance query to benchmark"),
    limit: int = typer.Option(5, help="Number of top relevance hits to keep"),
    repeats: int = typer.Option(3, help="How many repeated relevance runs to measure"),
    baseline_file: Path = typer.Option(
        None, "--baseline-file", help="Optional baseline JSON file for regression checks"
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON output"),
) -> None:
    """Benchmark indexing and relevance ranking on a real repository."""
    resolved_project_dir = project_dir.resolve()
    set_config(project_dir=resolved_project_dir, auto_approve=True)
    selected_path = path
    selected_query = query
    selected_limit = limit
    selected_repeats = repeats
    selected_baseline_file = baseline_file

    if profile_file is not None:
        try:
            profile = load_benchmark_profile(profile_file)
            selected_limit = int(profile.get("limit", selected_limit))
            selected_repeats = int(profile.get("repeats", selected_repeats))
        except ValueError as exc:
            console.print(f"[red]Benchmark failed:[/red] {exc}")
            raise typer.Exit(code=1) from exc
        selected_path = str(profile.get("path", selected_path))
        selected_query = str(profile.get("query", selected_query))
        if selected_baseline_file is None and profile.get("baseline_file"):
            selected_baseline_file = (profile_file.parent / str(profile["baseline_file"])).resolve()

    if not selected_query.strip():
        console.print("[red]Benchmark failed:[/red] Query is required.")
        raise typer.Exit(code=1)

    try:
        payload = run_index_and_relevance_benchmark(
            project_dir=resolved_project_dir,
            path=selected_path,
            query=selected_query,
            limit=selected_limit,
            repeats=selected_repeats,
        )
    except ValueError as exc:
        console.print(f"[red]Benchmark failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    except (FileNotFoundError, NotADirectoryError, PermissionError) as exc:
        console.print(f"[red]Benchmark failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    comparison: dict[str, Any] | None = None
    if selected_baseline_file is not None:
        try:
            baseline = json.loads(selected_baseline_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            console.print(f"[red]Benchmark failed:[/red] Could not read baseline file: {exc}")
            raise typer.Exit(code=1) from exc
        comparison = compare_benchmark_to_baseline(payload, baseline)
        payload["baseline_comparison"] = comparison

    if json_output:
        console.print_json(data=payload)
        if comparison is not None and not comparison["ok"]:
            raise typer.Exit(code=1)
        return

    top_paths = [result["path"] for result in payload["top_results"]] or ["<no matches>"]
    console.print(
        Panel.fit(
            Text.assemble(
                ("Claude Bridge ", "bold cyan"),
                ("benchmark", "green"),
            ),
            title="Benchmark",
            border_style="green",
        )
    )
    console.print(f"Project directory: [green]{resolved_project_dir}[/green]")
    console.print(f"Benchmark path: [green]{selected_path}[/green]")
    console.print(f"Query: [cyan]{selected_query}[/cyan]")
    console.print(
        "Index timing: "
        f"[bold]{payload['index_duration_ms']} ms[/bold] across "
        f"{payload['index_summary']['source_files']} source files"
    )
    console.print(
        "Query timing: "
        f"avg [bold]{payload['query_avg_duration_ms']} ms[/bold], "
        f"best {payload['query_best_duration_ms']} ms, "
        f"worst {payload['query_worst_duration_ms']} ms"
    )
    console.print(
        "Parser backends: "
        + ", ".join(payload["index_summary"]["parser_backends"] or ["none"])
    )
    console.print("Top results: " + ", ".join(top_paths))
    if comparison is not None:
        if comparison["ok"]:
            console.print("[green]Baseline check:[/green] passed")
        else:
            console.print("[red]Baseline check:[/red] failed")
            for failure in comparison["failures"]:
                console.print(f"- {failure}")
            raise typer.Exit(code=1)


@app.command()
def audit(
    last: bool = typer.Option(True, "--last", help="Show the latest audit session summary"),
    limit: int = typer.Option(20, help="How many recent audit records to show"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON output"),
) -> None:
    """Show the most recent Claude Bridge audit session summary."""
    if not last:
        console.print("[yellow]Only --last is currently supported.[/yellow]")
    summary = summarize_session(limit=max(1, limit))
    if json_output:
        console.print_json(json.dumps(summary, ensure_ascii=False))
        return

    console.print(
        Panel.fit(
            Text.assemble(
                ("Audit Session ", "bold cyan"),
                (summary["session_id"], "green"),
            ),
            title="Audit",
            border_style="cyan",
        )
    )
    console.print(f"Total records: [green]{summary['total_records']}[/green]")
    console.print(f"Failures: [yellow]{summary['failure_count']}[/yellow]")
    if summary["tool_counts"]:
        console.print("Tool counts:")
        for tool_name, count in sorted(summary["tool_counts"].items()):
            console.print(f"  {tool_name}: {count}")
    if summary["recent_records"]:
        console.print("\nRecent calls:")
        for record in summary["recent_records"]:
            result = record.get("result", {})
            status = "ok" if result.get("ok", False) else "error"
            message = result.get("message", "")
            console.print(
                f"  [{status}] {record.get('timestamp')} {record.get('tool_name')} "
                f"({record.get('duration_ms')}ms) {message}"
            )


@app.command()
def doctor(
    project_dir: Path = typer.Option(Path.cwd(), help="Project directory to inspect"),
) -> None:
    """Run lightweight environment and configuration checks."""
    resolved_project_dir = project_dir.resolve()
    config_snapshot = current_config()
    desktop_config_path = _default_claude_desktop_config_path()
    checks: list[tuple[str, bool, str]] = []

    checks.append(("Project directory exists", resolved_project_dir.exists(), str(resolved_project_dir)))
    checks.append(("Project directory is a folder", resolved_project_dir.is_dir(), str(resolved_project_dir)))
    checks.append(
        (
            "Python version is supported",
            sys.version_info >= (3, 8),
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        )
    )
    checks.append(
        (
            "Tree-sitter package available",
            importlib.util.find_spec("tree_sitter_language_pack") is not None,
            "Optional but recommended for richer indexing",
        )
    )
    checks.append(
        (
            "Claude Desktop config present",
            desktop_config_path.exists(),
            str(desktop_config_path),
        )
    )
    checks.append(
        (
            "Git repository detected",
            (resolved_project_dir / ".git").exists(),
            "Useful for auto-commit and history-aware workflows",
        )
    )

    console.print(
        Panel.fit(
            Text.assemble(("Claude Bridge ", "bold cyan"), ("doctor", "green")),
            title="Doctor",
            border_style="green",
        )
    )
    console.print(f"Project directory: [green]{resolved_project_dir}[/green]")
    if config_snapshot.get("approval_preset"):
        console.print(f"Approval preset: [cyan]{config_snapshot['approval_preset']}[/cyan]")
    else:
        console.print("Approval preset: [yellow]not set[/yellow]")
    console.print(
        "Approval mode: "
        f"auto_approve={config_snapshot['auto_approve']}, "
        f"client_managed_approval={config_snapshot['client_managed_approval']}"
    )
    console.print(f"Onboarding enabled: {config_snapshot['onboarding_enabled']}")

    for label, ok, detail in checks:
        status = "[green]✓[/green]" if ok else "[red]✗[/red]"
        console.print(f"{status} {label}: {detail}")


def main() -> None:
    app()
