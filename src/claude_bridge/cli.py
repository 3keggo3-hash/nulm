"""Command-line interface for Claude Bridge."""

from __future__ import annotations

import json
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
from claude_bridge.config import APPROVAL_PRESETS, resolve_approval_mode
from claude_bridge.doctor import build_doctor_report
from claude_bridge.guard_policy import (
    DecisionAction,
    DecisionSource,
    RiskLevel,
    ToolRequestContext,
    builtin_deny_decision,
    evaluate_rules,
    validate_guard_policy_file,
)

app = typer.Typer(help="Claude Bridge — MCP server for local file and terminal access")
policy_app = typer.Typer(help="Validate and simulate local guard policy files")
app.add_typer(policy_app, name="policy")
console = Console()


class _MCPProxy:
    def __getattr__(self, name: str) -> Any:
        _, runtime_mcp, _ = _server_runtime()
        return getattr(runtime_mcp, name)


mcp = _MCPProxy()


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


def _server_runtime() -> tuple[Any, Any, Any]:
    from claude_bridge.server import current_config, mcp, set_config

    return current_config, mcp, set_config


def _prompt_runtime() -> tuple[str, Any, Any, tuple[str, ...]]:
    from claude_bridge.prompt import (
        SYSTEM_PROMPT,
        SUPPORTED_SETUP_TARGETS,
        build_target_config,
        generate_mcp_setup_guide,
    )

    return SYSTEM_PROMPT, build_target_config, generate_mcp_setup_guide, SUPPORTED_SETUP_TARGETS


def _benchmark_runtime() -> tuple[Any, Any, Any]:
    from claude_bridge.benchmarking import (
        compare_benchmark_to_baseline,
        load_benchmark_profile,
        run_index_and_relevance_benchmark,
    )

    return (
        run_index_and_relevance_benchmark,
        compare_benchmark_to_baseline,
        load_benchmark_profile,
    )


def _parse_policy_params(param: list[str]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for item in param:
        if "=" not in item:
            raise typer.BadParameter("--param values must use key=value syntax")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise typer.BadParameter("--param key must not be empty")
        parsed[key] = value
    return parsed


def _simulate_builtin_decision(tool: str, params: dict[str, Any]) -> Any:
    if tool == "run_shell":
        from claude_bridge.shell_tools import analyze_shell_command

        command = str(params.get("command", ""))
        analysis = analyze_shell_command(command)
        if not analysis["ok"]:
            return builtin_deny_decision(
                str(analysis["message"]),
                risk_level=RiskLevel(str(analysis["details"].get("risk_level", "high"))),
                risk_reasons=[
                    str(item) for item in analysis["details"].get("risk_reasons", [])
                ],
                metadata={"tool": tool, "command": command, "source": "builtin_guard"},
            )
    return None


@policy_app.command("validate")
def policy_validate(
    path: Path = typer.Option(..., "--path", help="Policy file to validate"),
) -> None:
    """Validate a JSON or YAML guard policy file."""
    policy = validate_guard_policy_file(path.resolve())
    if policy.valid:
        console.print("[green]Policy valid[/green]")
    else:
        console.print("[red]Policy invalid[/red]")
    console.print(f"Path: {policy.path}")
    console.print(f"Rules: {policy.rule_count}")
    console.print(f"Warnings: {policy.warning_count}")
    console.print(f"Errors: {policy.error_count}")
    for warning in policy.warnings:
        console.print(f"[yellow]warning:[/yellow] {escape(warning)}")
    for error in policy.errors:
        console.print(f"[red]error:[/red] {escape(error)}")
    if not policy.valid:
        raise typer.Exit(code=1)


@policy_app.command("simulate")
def policy_simulate(
    path: Path = typer.Option(..., "--path", help="Policy file to simulate"),
    tool: str = typer.Option(..., "--tool", help="Tool name, for example run_shell"),
    param: list[str] = typer.Option(
        None,
        "--param",
        help="Tool parameter in key=value form. Can be repeated.",
    ),
) -> None:
    """Evaluate a tool request against policy without running the tool."""
    try:
        params = _parse_policy_params(param or [])
    except typer.BadParameter as exc:
        console.print(f"[red]Policy simulation failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    policy = validate_guard_policy_file(path.resolve())
    if not policy.valid:
        console.print("[red]Policy simulation failed:[/red] policy is invalid")
        for error in policy.errors:
            console.print(f"[red]error:[/red] {escape(error)}")
        raise typer.Exit(code=1)

    builtin_decision = _simulate_builtin_decision(tool, params)
    if builtin_decision is not None:
        decision = builtin_decision
    else:
        context = ToolRequestContext(
            tool_name=tool,
            params=params,
            project_dir=str(path.resolve().parent),
            allowed_roots=[str(path.resolve().parent)],
        )
        decision = evaluate_rules(context, policy)
        if decision is None:
            decision = PolicySimulationDefault.allow(tool)

    console.print(f"Action: {decision.action.value}")
    console.print(f"Source: {decision.source.value}")
    console.print(f"Risk: {decision.risk_level.value}")
    console.print(f"Reason: {escape(decision.reason)}")
    if decision.risk_reasons:
        console.print("Risk reasons:")
        for reason in decision.risk_reasons:
            console.print(f"  - {escape(reason)}")
    metadata = decision.metadata
    rule = metadata.get("rule_name")
    if rule:
        console.print(f"Rule: {escape(str(rule))}")
    if metadata:
        console.print("Metadata:")
        console.print_json(data=metadata)


class PolicySimulationDefault:
    @staticmethod
    def allow(tool: str) -> Any:
        from claude_bridge.guard_policy import PolicyDecision

        return PolicyDecision(
            action=DecisionAction.ALLOW,
            source=DecisionSource.DEFAULT,
            risk_level=RiskLevel.LOW,
            reason="No policy rule matched and no built-in hard deny was triggered",
            risk_reasons=[],
            metadata={"tool": tool},
        )


def _write_desktop_config(
    config_path: Path,
    *,
    project_dir: Path,
    allowed_roots: list[Path],
    auto_approve: bool,
    client_managed_approval: bool,
    approval_preset: str | None = None,
) -> Path:
    _, build_target_config, _, _ = _prompt_runtime()
    config = _load_desktop_config(config_path)
    servers = config.get("mcpServers")
    if servers is None:
        config["mcpServers"] = {}
        servers = config["mcpServers"]
    if not isinstance(servers, dict):
        raise ValueError("Claude Desktop config field 'mcpServers' must be a JSON object")

    generated_config = build_target_config(
        project_dir.resolve(),
        target="claude-desktop",
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
    config_path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return config_path


def _default_target_config_path(project_dir: Path, target: str) -> Path:
    safe_target = target.replace("-", "_")
    return project_dir.resolve() / f".claude-bridge.{safe_target}.json"


def _target_display_name(target: str) -> str:
    return {
        "claude-desktop": "Claude Desktop",
        "generic-stdio": "generic-stdio",
        "vscode": "VS Code",
    }.get(target, target)


def _write_target_config(
    config_path: Path,
    *,
    target: str,
    project_dir: Path,
    allowed_roots: list[Path],
    auto_approve: bool,
    client_managed_approval: bool,
    approval_preset: str | None = None,
) -> Path:
    if target == "claude-desktop":
        return _write_desktop_config(
            config_path,
            project_dir=project_dir,
            allowed_roots=allowed_roots,
            auto_approve=auto_approve,
            client_managed_approval=client_managed_approval,
            approval_preset=approval_preset,
        )
    _, build_target_config, _, _ = _prompt_runtime()
    config = build_target_config(
        project_dir.resolve(),
        target=target,
        allowed_roots=allowed_roots,
        auto_approve=auto_approve,
        client_managed_approval=client_managed_approval,
        approval_preset=approval_preset,
    )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
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
    _, _, set_config = _server_runtime()
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
    target: str = typer.Option(
        "claude-desktop",
        "--target",
        help="Setup target: claude-desktop, generic-stdio, or vscode",
    ),
    approval_preset: str | None = typer.Option(
        None, "--approval-preset", help=_approval_help_suffix()
    ),
    auto_approve: bool = typer.Option(False, help="Render config with auto-approve enabled"),
    client_managed_approval: bool = typer.Option(
        False, help="Render config assuming the MCP client handles approvals"
    ),
) -> None:
    """Print setup instructions and system prompt for a supported MCP target."""
    system_prompt, _, generate_mcp_setup_guide, supported_targets = _prompt_runtime()
    if target not in supported_targets:
        raise typer.BadParameter(
            f"Unsupported target: {target}. Choose one of: {', '.join(supported_targets)}"
        )
    display_target = _target_display_name(target)
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
            title=f"Setup ({target})",
            border_style="cyan",
        )
    )
    console.print(f"Project directory: [green]{project_dir.resolve()}[/green]")
    console.print(f"Target: [cyan]{target}[/cyan]")
    if resolved_preset is not None:
        console.print(f"Approval preset: [cyan]{resolved_preset}[/cyan]")
    if allow_root:
        console.print(
            "Allowed roots: " + ", ".join(f"[green]{path.resolve()}[/green]" for path in allow_root)
        )
    if resolved_auto_approve:
        console.print(
            "[red bold]WARNING:[/red bold] Auto-approve is enabled in the example config."
        )
    if resolved_client_managed:
        console.print(
            "[yellow bold]NOTE:[/yellow bold] Example config delegates approval to the MCP client."
        )
    if not resolved_auto_approve and not resolved_client_managed:
        console.print(
            "[yellow bold]NOTE:[/yellow bold] Approval-requiring tools will fail closed until you either enable "
            "client-managed approval or explicitly turn on auto-approve in a trusted local environment."
        )

    heading = "Claude Desktop Setup" if target == "claude-desktop" else "MCP Setup"
    console.print(f"\n[bold]{heading}:[/bold]")
    console.print(
        Panel(
            generate_mcp_setup_guide(
                project_dir.resolve(),
                target=target,
                allowed_roots=[
                    project_dir.resolve(),
                    *([path.resolve() for path in allow_root] if allow_root else []),
                ],
                auto_approve=resolved_auto_approve,
                client_managed_approval=resolved_client_managed,
                approval_preset=resolved_preset,
            ),
            title=f"Copy into {display_target} config",
            border_style="green",
        )
    )
    console.print("\n[bold]System Prompt:[/bold]")
    console.print(
        Panel(
            escape(system_prompt),
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
    target: str = typer.Option(
        "claude-desktop",
        "--target",
        help="Install target: claude-desktop, generic-stdio, or vscode",
    ),
    config_path: Path = typer.Option(None, "--config-path", help="Override target config path"),
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
    """Install or write Claude Bridge config for a supported MCP target."""
    _, _, _, supported_targets = _prompt_runtime()
    if target not in supported_targets:
        raise typer.BadParameter(
            f"Unsupported target: {target}. Choose one of: {', '.join(supported_targets)}"
        )
    display_target = _target_display_name(target)
    resolved_project_dir = project_dir.resolve()
    resolved_allowed_roots = [
        resolved_project_dir,
        *([path.resolve() for path in allow_root] if allow_root else []),
    ]
    resolved_config_path = (
        config_path.resolve()
        if config_path is not None
        else (
            _default_claude_desktop_config_path()
            if target == "claude-desktop"
            else _default_target_config_path(resolved_project_dir, target)
        )
    )
    resolved_auto_approve, resolved_client_managed, resolved_preset = _resolve_cli_approval_mode(
        approval_preset=approval_preset,
        auto_approve=auto_approve,
        client_managed_approval=client_managed_approval,
    )

    try:
        written_path = _write_target_config(
            resolved_config_path,
            target=target,
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
                (f"installed for {display_target}", "green"),
            ),
            title="Install",
            border_style="green",
        )
    )
    console.print(f"Config updated: [green]{written_path}[/green]")
    console.print(f"Project directory: [green]{resolved_project_dir}[/green]")
    console.print(f"Target: [cyan]{target}[/cyan]")
    if resolved_preset is not None:
        console.print(f"Approval preset: [cyan]{resolved_preset}[/cyan]")
    if len(resolved_allowed_roots) > 1:
        console.print(
            "Allowed roots: "
            + ", ".join(f"[green]{path}[/green]" for path in resolved_allowed_roots[1:])
        )
    if resolved_client_managed:
        console.print(
            "[yellow]Approval mode:[/yellow] Config expects the MCP client to manage approvals."
        )
    elif resolved_auto_approve:
        console.print("[red]Approval mode:[/red] Auto-approve enabled for trusted local use.")
    else:
        console.print(
            "[yellow]Approval mode:[/yellow] Fail-closed until approval handling is enabled."
        )
    if target == "claude-desktop":
        console.print("Restart Claude Desktop completely, then start a new chat.")
    elif target == "vscode":
        console.print(
            "Reload VS Code or restart the MCP extension host, then open a new MCP-enabled chat."
        )
    else:
        console.print("Reload the target MCP client and verify the Claude Bridge tools appear.")


@app.command()
def benchmark(
    project_dir: Path = typer.Option(Path.cwd(), help="Root directory to benchmark"),
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
    _, _, set_config = _server_runtime()
    (
        run_index_and_relevance_benchmark,
        compare_benchmark_to_baseline,
        load_benchmark_profile,
    ) = _benchmark_runtime()
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
        "Parser backends: " + ", ".join(payload["index_summary"]["parser_backends"] or ["none"])
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
    tool: str | None = typer.Option(None, "--tool", help="Filter by tool name"),
    decision: DecisionAction | None = typer.Option(
        None,
        "--decision",
        help="Filter by policy decision: allow, deny, or ask",
    ),
    risk: RiskLevel | None = typer.Option(
        None,
        "--risk",
        help="Filter by risk level: low, medium, high, or critical",
    ),
    source: DecisionSource | None = typer.Option(
        None,
        "--source",
        help="Filter by decision source",
    ),
) -> None:
    """Show the most recent Claude Bridge audit session summary."""
    if not last:
        console.print("[yellow]Only --last is currently supported.[/yellow]")
    summary = summarize_session(
        limit=max(1, limit),
        tool_name=tool,
        decision_action=decision.value if decision else None,
        decision_risk_level=risk.value if risk else None,
        decision_source=source.value if source else None,
    )
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
    telemetry = summary.get("telemetry", {})
    if isinstance(telemetry, dict):
        console.print(
            "Telemetry: "
            f"~{telemetry.get('total_estimated_tokens', 0)} tokens, "
            f"{telemetry.get('total_input_chars', 0)} input chars, "
            f"{telemetry.get('total_output_chars', 0)} output chars, "
            f"{telemetry.get('truncated_results', 0)} truncated results"
        )
    if summary["tool_counts"]:
        console.print("Tool counts:")
        for tool_name, count in sorted(summary["tool_counts"].items()):
            console.print(f"  {tool_name}: {count}")
    activity = summary.get("activity", {})
    if isinstance(activity, dict):
        touched_paths = activity.get("touched_paths", [])
        if touched_paths:
            console.print("\nTouched paths:")
            for path in touched_paths[:10]:
                console.print(f"  {escape(str(path))}")
        commands = activity.get("commands", [])
        if commands:
            console.print("\nCommands:")
            for item in commands[:10]:
                status = "ok" if item.get("ok", False) else "error"
                command = escape(str(item.get("command", "")))
                risk = item.get("risk_level")
                risk_text = f" risk={escape(str(risk))}" if risk else ""
                console.print(f"  [{status}] {command}{risk_text}")
        writes = activity.get("writes", [])
        if writes:
            console.print("\nWrites and patches:")
            for item in writes[:10]:
                status = "ok" if item.get("ok", False) else "error"
                paths = ", ".join(str(path) for path in item.get("paths", []))
                console.print(
                    f"  [{status}] {item.get('tool_name')} {escape(paths)}"
                )
        approval_rejections = activity.get("approval_rejections", [])
        if approval_rejections:
            console.print("\nApproval rejections:")
            for item in approval_rejections[:10]:
                console.print(
                    f"  [error] {item.get('timestamp')} {item.get('tool_name')}"
                )
        risky_actions = activity.get("risky_actions", [])
        if risky_actions:
            console.print("\nRisky actions:")
            for item in risky_actions[:10]:
                console.print(
                    f"  [yellow]{item.get('risk_level')}[/yellow] "
                    f"{item.get('tool_name')} {escape(str(item.get('message', '')))}"
                )
        policy = activity.get("policy", {})
        if isinstance(policy, dict):
            decision_counts = policy.get("decision_counts", {})
            risk_counts = policy.get("risk_counts", {})
            if decision_counts or risk_counts:
                console.print("\nPolicy decisions:")
                if decision_counts:
                    console.print(f"  decisions: {escape(str(decision_counts))}")
                if risk_counts:
                    console.print(f"  risks: {escape(str(risk_counts))}")
                console.print(f"  rule decisions: {policy.get('rule_decision_count', 0)}")
        validation = activity.get("validation", {})
        if isinstance(validation, dict) and validation.get("has_changes"):
            console.print("\nValidation:")
            if validation.get("validation_after_changes"):
                console.print("  [ok] Validation ran after the latest changes.")
            else:
                console.print("  [warning] Changes have not been validated yet.")
                recommended = validation.get("recommended_next_step")
                if recommended:
                    console.print(f"  {escape(str(recommended))}")
            validation_commands = validation.get("validation_commands", [])
            for item in validation_commands[:10]:
                status = "ok" if item.get("ok", False) else "error"
                command = escape(str(item.get("command", "")))
                console.print(f"  [{status}] {command}")
    if summary["recent_records"]:
        console.print("\nRecent calls:")
        for record in summary["recent_records"]:
            result = record.get("result", {})
            status = "ok" if result.get("ok", False) else "error"
            message = result.get("message", "")
            decision_text = ""
            if record.get("decision_action"):
                decision_text = (
                    f" decision={record.get('decision_action')}"
                    f"/{record.get('decision_risk_level')}"
                    f"/{record.get('decision_source')}"
                )
            console.print(
                f"  [{status}] {record.get('timestamp')} {record.get('tool_name')} "
                f"({record.get('duration_ms')}ms){decision_text} {message}"
            )


@app.command()
def replay(
    record_id: str = typer.Option(..., "--record-id", help="Audit record id to replay"),
    policy_path: Path | None = typer.Option(
        None,
        "--policy-path",
        help="Optional policy file. Defaults to the active guard policy.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON output"),
) -> None:
    """Replay an audit record against the deterministic rule engine."""
    from claude_bridge.replay import replay_record_id

    result = replay_record_id(record_id, policy_path=policy_path)
    if result is None:
        console.print(f"[red]Audit record not found:[/red] {escape(record_id)}")
        raise typer.Exit(code=1)
    if json_output:
        console.print_json(json.dumps(result, ensure_ascii=False))
        return

    console.print(
        Panel.fit(
            Text.assemble(("Audit Replay ", "bold cyan"), (record_id, "green")),
            title="Replay",
            border_style="cyan",
        )
    )
    console.print(f"Tool: [green]{escape(str(result['tool_name']))}[/green]")
    console.print(f"Changed: [{'red' if result['changed'] else 'green'}]{result['changed']}[/]")
    console.print(f"Reason: {escape(str(result['change_reason']))}")
    original = result.get("original_decision") or {}
    replayed = result.get("replayed_decision") or {}
    console.print("Original:")
    console.print(
        "  "
        f"action={original.get('action')} "
        f"source={original.get('source')} "
        f"risk={original.get('risk_level')}"
    )
    console.print(f"  reason={escape(str(original.get('reason', '')))}")
    console.print("Replayed:")
    console.print(
        "  "
        f"action={replayed.get('action')} "
        f"source={replayed.get('source')} "
        f"risk={replayed.get('risk_level')}"
    )
    console.print(f"  reason={escape(str(replayed.get('reason', '')))}")
    limitations = result.get("limitations", [])
    if limitations:
        console.print("Limitations:")
        for limitation in limitations:
            console.print(f"  - {escape(str(limitation))}")


@app.command()
def doctor(
    project_dir: Path = typer.Option(Path.cwd(), help="Project directory to inspect"),
) -> None:
    """Run lightweight environment and configuration checks."""
    current_config, _, _ = _server_runtime()
    report = build_doctor_report(
        project_dir=project_dir,
        config_snapshot=current_config(),
        desktop_config_path=_default_claude_desktop_config_path(),
        python_executable=sys.executable,
        python_version=(sys.version_info.major, sys.version_info.minor, sys.version_info.micro),
    )

    console.print(
        Panel.fit(
            Text.assemble(("Claude Bridge ", "bold cyan"), ("doctor", "green")),
            title="Doctor",
            border_style="green",
        )
    )
    console.print(f"Project directory: [green]{report.project_dir}[/green]")
    if report.approval_preset:
        console.print(f"Approval preset: [cyan]{report.approval_preset}[/cyan]")
    else:
        console.print("Approval preset: [yellow]not set[/yellow]")
    console.print(
        "Approval mode: "
        f"auto_approve={report.auto_approve}, "
        f"client_managed_approval={report.client_managed_approval}"
    )
    console.print(f"Onboarding enabled: {report.onboarding_enabled}")

    for check in report.checks:
        status = "[green]✓[/green]" if check.ok else "[red]✗[/red]"
        console.print(f"{status} {check.label}: {check.detail}")


def main() -> None:
    app()
