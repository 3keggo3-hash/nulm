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
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from claude_bridge import __version__
from claude_bridge._config_cli import config_app
from claude_bridge.audit import summarize_session
from claude_bridge.config import APPROVAL_PRESETS, resolve_approval_mode
from claude_bridge.doctor import build_doctor_report, build_security_doctor_report
from claude_bridge.update import check_update
from claude_bridge.guard_policy import (
    DecisionAction,
    DecisionSource,
    RiskLevel,
    ToolRequestContext,
    builtin_deny_decision,
    evaluate_rules,
    validate_guard_policy_file,
)
from claude_bridge.policy_diff import load_bundle_from_file as _load_bundle_from_file

console = Console()


def _print_suggestion(command: str, description: str) -> None:
    console.print(f"  [dim]→[/dim] [cyan]{command}[/cyan]  {description}")

app = typer.Typer(help="Claude Bridge — MCP server for local file and terminal access")
policy_app = typer.Typer(help="Validate and simulate local guard policy files")
anomaly_app = typer.Typer(help="Anomaly detection on audit sessions")
audit_app = typer.Typer(help="Audit session management and export")
doctor_app = typer.Typer(help="Environment and security checks")
skill_app = typer.Typer(help="Skill discovery, inspection, import, and export")
control_plane_app = typer.Typer(help="Inspect local control-plane state")
tasks_app = typer.Typer(help="Inspect local task state")
approvals_app = typer.Typer(help="Inspect local approval state")
app.add_typer(policy_app, name="policy")
app.add_typer(anomaly_app, name="anomaly")
app.add_typer(audit_app, name="audit")
app.add_typer(doctor_app, name="doctor")
app.add_typer(skill_app, name="skill")
app.add_typer(tasks_app, name="tasks")
app.add_typer(approvals_app, name="approvals")
app.add_typer(control_plane_app, name="control-plane")
app.add_typer(config_app, name="config")
control_plane_app.add_typer(tasks_app, name="tasks")
control_plane_app.add_typer(approvals_app, name="approvals")
console = Console()

COMMAND_GROUPS = {
    "Core": ["start", "init", "update"],
    "Tools": ["skill", "benchmark"],
    "Audit": ["audit", "appeal", "anomaly", "replay", "appeal-history"],
    "Config": ["config"],
    "MCP": ["install", "setup"],
    "Admin": ["doctor", "policy", "dashboard", "workflow-preview"],
}


def _version_option(value: bool) -> None:
    if value:
        console.print(__version__)
        raise typer.Exit()


def _print_grouped_help(ctx: typer.Context) -> None:
    console.print(Panel.fit("[bold cyan]Claude Bridge[/bold cyan] command line interface", title="Help", border_style="cyan"))
    console.print()

    all_cmds: dict[str, Any] = {}
    for cmd_info in app.registered_commands:
        if cmd_info.name is not None:
            all_cmds[cmd_info.name] = cmd_info
    for subapp in [policy_app, anomaly_app, audit_app, doctor_app, skill_app, control_plane_app, config_app]:
        for cmd_info in subapp.registered_commands:
            if cmd_info.name is not None:
                all_cmds[cmd_info.name] = cmd_info

    rows = []
    for group_name, cmd_names in COMMAND_GROUPS.items():
        _cmds = []
        for name in cmd_names:
            if name in all_cmds:
                _cmds.append(name)
        if not _cmds:
            continue
        row = [f"[bold]{group_name}[/bold]", ""]
        cmd_docs = []
        for name in _cmds:
            cmd_info = all_cmds[name]
            doc = (cmd_info.callback.__doc__ or cmd_info.help or "").split("\n")[0].strip()
            cmd_docs.append(f"[cyan]{name}[/cyan]  {doc}")
        row[1] = "\n".join(cmd_docs)
        rows.append(row)

    table = Table(show_header=False, box=None, pad_edge=False, collapse_padding=True)
    table.add_column(min_width=10, max_width=12, style="bold")
    table.add_column(min_width=60)
    for row in rows:
        table.add_row(*row)

    console.print(table)
    console.print("  Use [cyan]--help[/cyan] on a specific command for detailed options.")
    raise typer.Exit()


@app.callback(invoke_without_command=True, help="Show this help message.")
def root_options(
    ctx: typer.Context,
    version_option: bool = typer.Option(
        False,
        "--version",
        callback=_version_option,
        is_eager=True,
        help="Show version and exit.",
    ),
) -> None:
    """Claude Bridge command line interface."""
    _ = version_option
    if ctx.invoked_subcommand is None:
        _print_grouped_help(ctx)


class _MCPProxy:
    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}

    def __getattr__(self, name: str) -> Any:
        if name not in self._cache:
            _, runtime_mcp, _, _ = _server_runtime()
            self._cache[name] = getattr(runtime_mcp, name)
        return self._cache[name]


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


def _server_runtime() -> tuple[Any, Any, Any, Any]:
    from claude_bridge.server import current_config, mcp, run_mcp_server, set_config

    return current_config, mcp, set_config, run_mcp_server


def _prompt_runtime() -> tuple[str, Any, Any, tuple[str, ...]]:
    from claude_bridge.prompt import (
        SUPPORTED_SETUP_TARGETS,
        SYSTEM_PROMPT,
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
                risk_reasons=[str(item) for item in analysis["details"].get("risk_reasons", [])],
                metadata={"tool": tool, "command": command, "source": "builtin_guard"},
            )
    return None


@policy_app.command("validate")
def policy_validate(
    path: Path = typer.Option(
        ...,
        "--path",
        "-p",
        help="Policy file to validate (JSON or YAML)",
    ),
) -> None:
    """Validate a JSON or YAML guard policy file.

    Examples:
      claude-bridge policy validate --path policy.json
      claude-bridge policy validate -p policy.yaml
    """
    resolved_path = path.resolve()
    if not resolved_path.exists():
        console.print(f"[red]Policy file not found:[/red] {escape(str(resolved_path))}")
        raise typer.Exit(code=1)
    policy = validate_guard_policy_file(resolved_path)
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
        console.print()
        console.print("[bold]Next steps:[/bold]")
        _print_suggestion("claude-bridge doctor", "Check environment and config for issues")
        _print_suggestion("claude-bridge policy --help", "See policy subcommands")
        raise typer.Exit(code=1)


@policy_app.command("simulate")
def policy_simulate(
    path: Path = typer.Option(
        ...,
        "--path",
        "-p",
        help="Policy file to simulate (JSON or YAML)",
    ),
    tool: str = typer.Option(
        ...,
        "--tool",
        "-t",
        help="Tool name to simulate (e.g., run_shell, file_read)",
    ),
    param: list[str] = typer.Option(
        None,
        "--param",
        help="Tool parameter in key=value form (can be specified multiple times)",
    ),
    role: str | None = typer.Option(
        None,
        "--role",
        help="Role to simulate as (e.g., junior, senior, ci, contractor)",
    ),
    with_ai: bool = typer.Option(
        False,
        "--with-ai",
        help="Also run the AI evaluator as an advisory layer",
    ),
    ai_deny: list[str] = typer.Option(
        None,
        "--ai-deny",
        help="AI evaluator deny keyword (can be specified multiple times)",
    ),
    ai_ask: list[str] = typer.Option(
        None,
        "--ai-ask",
        help="AI evaluator ask keyword (can be specified multiple times)",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print machine-readable JSON output",
    ),
) -> None:
    """Evaluate a tool request against policy without running the tool.

    Examples:
      claude-bridge policy simulate --path policy.json --tool run_shell --param command=ls
      claude-bridge policy simulate -p policy.json -t file_read --param path=README.md
      claude-bridge policy simulate -p policy.json -t run_shell --role junior --param command=cat

    When --role is provided, the full policy chain is evaluated including
    role-based restrictions (pre-rule and post-rule checks).
    """
    try:
        params = _parse_policy_params(param or [])
    except typer.BadParameter as exc:
        if json_output:
            console.print_json(data={"error": str(exc), "tool": tool})
            raise typer.Exit(code=1) from exc
        console.print(f"[red]Policy simulation failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if role is not None:
        _run_role_simulation(
            path=path,
            tool=tool,
            params=params,
            role=role,
            with_ai=with_ai,
            ai_deny=ai_deny,
            ai_ask=ai_ask,
            json_output=json_output,
        )
        return

    policy = validate_guard_policy_file(path.resolve())
    if not policy.valid:
        if json_output:
            console.print_json(
                data={
                    "error": "policy is invalid",
                    "errors": policy.errors,
                }
            )
            raise typer.Exit(code=1)
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

    if json_output:
        payload = {
            "tool": tool,
            "role": role,
            "action": decision.action.value,
            "source": decision.source.value,
            "risk_level": decision.risk_level.value,
            "reason": decision.reason,
            "risk_reasons": list(decision.risk_reasons),
            "metadata": dict(decision.metadata),
        }
        console.print_json(data=payload)
        return

    console.print("[bold]Policy Decision:[/bold]")
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

    if with_ai:
        console.print("")
        console.print("[bold cyan]AI Advisor:[/bold cyan]")
        ai_result = _simulate_ai_evaluation(
            tool=tool,
            params=params,
            policy_decision=decision,
            deny_patterns=list(ai_deny) if ai_deny else None,
            ask_patterns=list(ai_ask) if ai_ask else None,
        )
        if ai_result is not None:
            _print_ai_advisory(decision, ai_result)
        else:
            console.print(
                "[yellow]AI evaluator returned no advisory (disabled or not available).[/yellow]"
            )


def _run_role_simulation(
    *,
    path: Path,
    tool: str,
    params: dict[str, Any],
    role: str,
    with_ai: bool,
    ai_deny: list[str] | None,
    ai_ask: list[str] | None,
    json_output: bool,
) -> None:
    """Run a role-based policy simulation and print results."""
    from claude_bridge.policy_diff import simulate_tool_with_role

    bundle = _load_bundle_from_file(path.resolve())
    project_dir = str(path.resolve().parent)

    if bundle is None:
        if json_output:
            console.print_json(
                data={
                    "error": "Could not load policy bundle from file",
                    "path": str(path),
                }
            )
            raise typer.Exit(code=1)
        console.print("[red]Policy simulation failed:[/red] Could not load policy bundle from file")
        raise typer.Exit(code=1)

    result = simulate_tool_with_role(
        tool=tool,
        params=params,
        role_name=role,
        project_dir=project_dir,
        allowed_roots=[project_dir],
        bundle=bundle,
    )

    if json_output:
        console.print_json(data=result.to_dict())
        return

    console.print(f"[bold]Role Simulation ({role}):[/bold]")
    console.print(f"Tool: {tool}")
    console.print(f"Action: {result.action}")
    console.print(f"Source: {result.source}")
    console.print(f"Risk: {result.risk_level}")
    console.print(f"Reason: {escape(result.reason)}")
    if result.risk_reasons:
        console.print("Risk reasons:")
        for reason in result.risk_reasons:
            console.print(f"  - {escape(reason)}")
    if result.metadata:
        console.print("Metadata:")
        console.print_json(data=result.metadata)


@policy_app.command("diff")
def policy_diff(
    base: Path = typer.Option(
        ...,
        "--base",
        "-b",
        help="Base policy file (e.g., main branch)",
    ),
    head: Path = typer.Option(
        ...,
        "--head",
        "-h",
        help="Head policy file (e.g., PR branch)",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Print machine-readable JSON output",
    ),
) -> None:
    """Compare two policy files and report semantic differences.

    Examples:
      claude-bridge policy diff --base main.json --head pr.json
      claude-bridge policy diff -b baseline.json -h updated.json

    Detects role additions, removals, permission changes, restriction
    changes, and inheritance issues. Exits with code 1 if validation
    errors or meaningful diffs are found (CI-friendly).
    """
    from claude_bridge.policy_diff import diff_policies

    base_path = base.resolve()
    head_path = head.resolve()

    base_bundle = _load_bundle_from_file(base_path)
    head_bundle = _load_bundle_from_file(head_path)

    if base_bundle is None:
        msg = f"Could not load base policy from {base_path}"
        if json_output:
            console.print_json(data={"error": msg})
            raise typer.Exit(code=1)
        console.print(f"[red]{msg}[/red]")
        raise typer.Exit(code=1)

    if head_bundle is None:
        msg = f"Could not load head policy from {head_path}"
        if json_output:
            console.print_json(data={"error": msg})
            raise typer.Exit(code=1)
        console.print(f"[red]{msg}[/red]")
        raise typer.Exit(code=1)

    result = diff_policies(base_bundle, head_bundle)

    if json_output:
        console.print_json(data=result.to_dict())
        if result.has_issues:
            raise typer.Exit(code=1)
        return

    exit_code = 0

    if result.status.value == "ok":
        console.print("[green]Policy diff:[/green] no changes detected.")
        return

    console.print(f"[bold]Policy Diff:[/bold] {result.base_name} [dim]→[/dim] {result.head_name}")

    if result.name_changed:
        console.print(
            f"[yellow]Name changed:[/yellow] {escape(result.old_name)} → {escape(result.new_name)}"
        )

    if result.roles_added:
        console.print("[green]Roles added:[/green]")
        for name in result.roles_added:
            console.print(f"  + {name}")

    if result.roles_removed:
        console.print("[red]Roles removed:[/red]")
        for name in result.roles_removed:
            console.print(f"  - {name}")

    for rd in result.role_diffs:
        if rd.status.value == "unchanged":
            continue
        status_color = {
            "added": "green",
            "removed": "red",
            "modified": "yellow",
        }.get(rd.status.value, "dim")
        console.print(
            f"\n[{status_color}]{rd.status.value.upper()}[/{status_color}]: {rd.role_name}"
        )
        if rd.extends_changed:
            console.print(
                f"  Extends: {escape(str(rd.old_extends))} → {escape(str(rd.new_extends))}"
            )
        if rd.description_changed:
            console.print("  Description changed")
        if rd.enabled_changed:
            console.print(f"  Enabled: {rd.old_enabled} → {rd.new_enabled}")
        if rd.restrictions_added:
            console.print("  Restrictions added:")
            for r in rd.restrictions_added:
                console.print(f"    [green]+ {r}[/green]")
        if rd.restrictions_removed:
            console.print("  Restrictions removed:")
            for r in rd.restrictions_removed:
                console.print(f"    [red]- {r}[/red]")
        for pd in rd.permission_diffs:
            pcolor = {
                "added": "green",
                "removed": "red",
                "modified": "yellow",
            }.get(pd.status.value, "dim")
            line = f"    [{pcolor}]{pd.status.value}[/{pcolor}]: {pd.tool}"
            if pd.status.value == "modified":
                line += f" ({pd.old_action} → {pd.new_action})"
            elif pd.status.value == "added":
                line += f" ({pd.new_action})"
            elif pd.status.value == "removed":
                line += f" ({pd.old_action})"
            console.print(line)

    # Print validation/inheritance errors for head
    if result.head_validation_errors:
        console.print("\n[red]Head validation errors:[/red]")
        for e in result.head_validation_errors:
            code_label = escape(f"[{e.get('code', 'error')}]")
            console.print(
                f"  [red]{code_label}[/red] "
                f"{escape(str(e.get('path', '')))}: "
                f"{escape(str(e.get('message', '')))}"
            )
        exit_code = 1

    if result.head_inheritance_errors:
        console.print("\n[red]Head inheritance errors:[/red]")
        for e in result.head_inheritance_errors:
            code_label = escape(f"[{e.get('code', 'error')}]")
            console.print(
                f"  [red]{code_label}[/red] "
                f"{escape(str(e.get('path', '')))}: "
                f"{escape(str(e.get('message', '')))}"
            )
        exit_code = 1

    if exit_code != 0:
        raise typer.Exit(code=exit_code)


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


def _simulate_ai_evaluation(
    *,
    tool: str,
    params: dict[str, Any],
    policy_decision: Any,
    deny_patterns: list[str] | None = None,
    ask_patterns: list[str] | None = None,
) -> Any | None:
    """Run the local AI evaluator as an advisory layer for policy simulation.

    The AI evaluator is advisory only: it cannot override a built-in hard deny.
    For built-in denies, it reports the decision that the guard already made.
    """
    from claude_bridge.ai_evaluator import (
        EvaluationRequest,
        LocalEvaluatorProvider,
        evaluation_response_to_policy_decision,
    )
    from claude_bridge.guard_policy import ToolRequestContext

    provider = LocalEvaluatorProvider(
        deny_patterns=deny_patterns or [],
        ask_patterns=ask_patterns or [],
    )
    prompt = f"Tool: {tool}\nParams: {json.dumps(params)}"
    context = ToolRequestContext(
        tool_name=tool,
        params=params,
        project_dir="",
        allowed_roots=[],
    )
    request = EvaluationRequest(
        prompt=prompt,
        tool_name=tool,
        tool_params=params,
        context={"simulation": True},
    )
    response = provider.evaluate(request)
    ai_decision = evaluation_response_to_policy_decision(response, ctx=context)
    return ai_decision


def _print_ai_advisory(policy_decision: Any, ai_decision: Any) -> None:
    """Print the AI advisory alongside the policy decision with delta markers."""
    from claude_bridge.guard_policy import DecisionAction

    policy_action = policy_decision.action.value
    ai_action = ai_decision.action.value
    if policy_action == ai_action:
        delta = "agrees with policy"
        delta_style = ""
    elif policy_decision.action == DecisionAction.DENY and policy_decision.source in (
        DecisionSource.BUILTIN_GUARD,
        DecisionSource.RULE,
    ):
        delta = "advisory overridden: built-in/rule deny wins (AI is advisor only)"
        delta_style = "[yellow]"
    elif ai_action == "allow" and policy_action in ("ask", "deny"):
        delta = "AI suggests allowing (advisory only — policy chain decides)"
        delta_style = "[yellow]"
    elif ai_action == "deny":
        delta = "AI suggests stricter action"
        delta_style = "[red]"
    else:
        delta = "AI advisor differs from policy"
        delta_style = "[yellow]"

    console.print(f"Action: {ai_action}")
    console.print(f"Risk: {ai_decision.risk_level.value}")
    console.print(f"Reason: {escape(str(ai_decision.reason))}")
    if ai_decision.risk_reasons:
        console.print("Risk reasons:")
        for reason in ai_decision.risk_reasons:
            console.print(f"  - {escape(reason)}")
    console.print(f"{delta_style}Delta: {escape(delta)}{delta_style}")
    metadata = ai_decision.metadata
    if metadata:
        console.print("Metadata:")
        console.print_json(data=metadata)


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
        Path.cwd(),
        "--project-dir",
        "-d",
        help="Root directory the bridge is allowed to access",
    ),
    allow_root: list[Path] = typer.Option(
        None,
        "--allow-root",
        help="Additional allowed workspace root (can be specified multiple times)",
    ),
    approval_preset: str | None = typer.Option(
        None,
        "--approval-preset",
        help=_approval_help_suffix(),
    ),
    auto_approve: bool = typer.Option(
        False,
        help="Automatically approve all operations (use with caution)",
    ),
) -> None:
    """Start the MCP bridge server (stdio transport).

    Examples:
      claude-bridge start
      claude-bridge start -d /path/to/project
      claude-bridge start --approval-preset read-only
    """
    _, _, set_config, run_mcp_server = _server_runtime()
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
        run_mcp_server()
    except KeyboardInterrupt:
        sys.exit(0)


@app.command()
def version() -> None:
    """Show version information."""
    console.print(f"[bold cyan]Claude Bridge[/bold cyan] version [green]{__version__}[/green]")


@app.command("dashboard")
def control_plane_dashboard(
    host: str = typer.Option("127.0.0.1", "--host", help="Loopback host to bind"),
    port: int = typer.Option(8765, "--port", help="Local dashboard port"),
    token: str | None = typer.Option(None, "--token", help="Optional dashboard token"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable startup info"),
    tunnel: bool = typer.Option(False, "--tunnel", help="Expose dashboard via Cloudflare tunnel"),
) -> None:
    """Serve the local control-plane dashboard on a loopback address."""
    from claude_bridge._tunnel_manager import TunnelManager
    from claude_bridge.control_plane_dashboard import create_dashboard_server

    try:
        server, resolved_token = create_dashboard_server(host=host, port=port, token=token)
    except ValueError as exc:
        if json_output:
            console.print_json(data={"error": str(exc)})
        else:
            console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from exc
    actual_port = server.server_address[1]
    local_url = f"http://{host}:{actual_port}/?token={resolved_token}"
    tunnel_url: str | None = None
    if tunnel:
        try:
            with TunnelManager() as tm:
                tunnel_url = tm.start(actual_port)
                display_url = tunnel_url
        except RuntimeError as exc:
            if json_output:
                console.print_json(data={"error": str(exc)})
            else:
                console.print(f"[red]Tunnel error:[/red] {exc}")
            raise typer.Exit(code=1) from exc
    else:
        display_url = local_url
    if json_output:
        console.print_json(
            data={
                "schema_version": "control_plane.dashboard_start.v1",
                "host": host,
                "port": actual_port,
                "url": display_url,
                "local_url": local_url,
                "tunnel_url": tunnel_url,
            }
        )
    else:
        if tunnel and tunnel_url:
            console.print(Panel.fit(
                f"[bold link={tunnel_url}]Tunnel URL:[/bold link] [cyan]{tunnel_url}[/cyan]\n\n"
                f"[dim]Local URL:[/dim] {local_url}\n\n"
                f"Press Ctrl-C to stop.",
                title="Tunnel Active",
                border_style="green",
            ))
        else:
            console.print(f"Control-plane dashboard: [cyan]{escape(display_url)}[/cyan]")
            console.print("Press Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


@tasks_app.command("list")
def control_plane_tasks_list(
    status: str | None = typer.Option(None, "--status", help="Filter by task status"),
    limit: int = typer.Option(20, "--limit", help="Maximum tasks to show; 0 means all"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON output"),
) -> None:
    """List durable local control-plane tasks."""
    from claude_bridge.control_plane import control_plane_dir, list_tasks

    tasks = list_tasks(status=status, limit=limit)
    payload = {
        "schema_version": "control_plane.tasks.v1",
        "state_dir": str(control_plane_dir()),
        "tasks": tasks,
    }
    if json_output:
        console.print_json(data=payload)
        return
    if not tasks:
        console.print("No control-plane tasks found.")
        return
    for task in tasks:
        console.print(
            f"[bold]{escape(task['id'])}[/bold] "
            f"{escape(task.get('status', 'pending'))} {escape(task['title'])}"
        )
        summary = task.get("summary", "")
        if summary:
            console.print(f"  {escape(summary)}")


@tasks_app.command("show")
def control_plane_tasks_show(
    task_id: str,
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON output"),
) -> None:
    """Show one durable local control-plane task."""
    from claude_bridge.control_plane import get_task

    task = get_task(task_id)
    if task is None:
        error_payload = {"error": f"Task '{task_id}' not found"}
        if json_output:
            console.print_json(data=error_payload)
        else:
            console.print(f"[red]{escape(error_payload['error'])}[/red]")
        raise typer.Exit(code=1)
    payload: dict[str, Any] = {"schema_version": "control_plane.task.v1", "task": task}
    if json_output:
        console.print_json(data=payload)
        return
    console.print(Panel.fit(json.dumps(task, indent=2), title=task_id))


@tasks_app.command("summary")
def control_plane_tasks_summary(
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON output"),
) -> None:
    """Summarize durable local control-plane tasks."""
    from claude_bridge.control_plane import control_plane_dir, summarize_tasks

    summary = summarize_tasks()
    payload = {
        "schema_version": "control_plane.task_summary.v1",
        "state_dir": str(control_plane_dir()),
        "summary": summary,
    }
    if json_output:
        console.print_json(data=payload)
        return
    console.print(Panel.fit(f"Tasks: {summary['total']}", title="Control Plane"))
    for status, count in summary["by_status"].items():
        console.print(f"{escape(status)}: {count}")


@tasks_app.command("cancel")
def control_plane_tasks_cancel(
    task_id: str,
    reason: str = typer.Option("", "--reason", help="Optional cancellation reason"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON output"),
) -> None:
    """Mark one durable local control-plane task as cancelled."""
    from claude_bridge.control_plane import update_task_status

    task = update_task_status(
        task_id,
        "cancelled",
        summary=reason or None,
        metadata={"cancel_reason": reason} if reason else None,
    )
    if task is None:
        error_payload = {"error": f"Task '{task_id}' not found"}
        if json_output:
            console.print_json(data=error_payload)
        else:
            console.print(f"[red]{escape(error_payload['error'])}[/red]")
        raise typer.Exit(code=1)
    payload: dict[str, Any] = {"schema_version": "control_plane.task.v1", "task": task}
    if json_output:
        console.print_json(data=payload)
        return
    console.print(f"[green]Cancelled[/green] {escape(task['id'])}")


@approvals_app.command("list")
def control_plane_approvals_list(
    status: str | None = typer.Option(None, "--status", help="Filter by approval status"),
    limit: int = typer.Option(20, "--limit", help="Maximum approvals to show; 0 means all"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON output"),
) -> None:
    """List durable local control-plane approval requests."""
    from claude_bridge.control_plane import control_plane_dir, list_approvals

    approvals = list_approvals(status=status, limit=limit)
    payload = {
        "schema_version": "control_plane.approvals.v1",
        "state_dir": str(control_plane_dir()),
        "approvals": approvals,
    }
    if json_output:
        console.print_json(data=payload)
        return
    if not approvals:
        console.print("No control-plane approvals found.")
        return
    for approval in approvals:
        console.print(
            f"[bold]{escape(approval['id'])}[/bold] "
            f"{escape(approval.get('status', 'pending'))} {escape(approval['title'])}"
        )
        tool = approval.get("tool", "")
        reason = approval.get("reason", "")
        details = " ".join(part for part in (tool, reason) if part)
        if details:
            console.print(f"  {escape(details)}")


@approvals_app.command("show")
def control_plane_approvals_show(
    approval_id: str,
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON output"),
) -> None:
    """Show one durable local control-plane approval request."""
    from claude_bridge.control_plane import get_approval

    approval = get_approval(approval_id)
    if approval is None:
        error_payload = {"error": f"Approval '{approval_id}' not found"}
        if json_output:
            console.print_json(data=error_payload)
        else:
            console.print(f"[red]{escape(error_payload['error'])}[/red]")
        raise typer.Exit(code=1)
    payload: dict[str, Any] = {
        "schema_version": "control_plane.approval.v1",
        "approval": approval,
    }
    if json_output:
        console.print_json(data=payload)
        return
    console.print(Panel.fit(json.dumps(approval, indent=2), title=approval_id))


@approvals_app.command("approve")
def control_plane_approvals_approve(
    approval_id: str,
    reason: str = typer.Option("", "--reason", help="Optional approval reason"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON output"),
) -> None:
    """Mark one durable local control-plane approval request as approved."""
    _resolve_control_plane_approval(approval_id, "approved", reason, json_output)


@approvals_app.command("reject")
def control_plane_approvals_reject(
    approval_id: str,
    reason: str = typer.Option("", "--reason", help="Optional rejection reason"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON output"),
) -> None:
    """Mark one durable local control-plane approval request as denied."""
    _resolve_control_plane_approval(approval_id, "denied", reason, json_output)


def _resolve_control_plane_approval(
    approval_id: str,
    status: str,
    reason: str,
    json_output: bool,
) -> None:
    from typing import Literal, cast

    from claude_bridge.control_plane import resolve_approval

    approval = resolve_approval(
        approval_id,
        cast(Literal["approved", "denied"], status),
        reason=reason,
        metadata={"decision_reason": reason} if reason else None,
    )
    if approval is None:
        error_payload = {"error": f"Approval '{approval_id}' not found"}
        if json_output:
            console.print_json(data=error_payload)
        else:
            console.print(f"[red]{escape(error_payload['error'])}[/red]")
        raise typer.Exit(code=1)
    payload: dict[str, Any] = {
        "schema_version": "control_plane.approval.v1",
        "approval": approval,
    }
    if json_output:
        console.print_json(data=payload)
        return
    console.print(f"[green]{escape(status)}[/green] {escape(approval['id'])}")


@skill_app.command("list")
def skill_list(
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON output"),
) -> None:
    """List registered skills without executing skill code."""
    from claude_bridge.skill_registry import get_registry

    skills = get_registry().list_skill_metadata()
    payload = {"schema_version": "skill_list.v1", "skills": skills}
    if json_output:
        console.print_json(data=payload)
        return
    if not skills:
        console.print("No skills registered.")
        return
    for item in skills:
        meta = item["meta"]
        trust = meta.get("trust_level", "unverified")
        trust_badge = f"[dim][{trust}][/dim]" if trust != "unverified" else ""
        console.print(f"[bold]{escape(meta['name'])}[/bold] v{escape(meta['version'])} {trust_badge}")


@skill_app.command("trust-levels")
def skill_trust_levels(
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON output"),
) -> None:
    """List skills grouped by trust level.

    Trust levels: official (signed), community, unverified.
    """
    from claude_bridge.skill_registry import get_registry

    registry = get_registry()
    by_level: dict[str, list[str]] = {
        "official": [],
        "community": [],
        "unverified": [],
    }
    for skill in registry.list_skills():
        level = skill.meta.trust_level
        if level not in by_level:
            by_level[level] = []
        by_level[level].append(skill.meta.name)

    payload = {"schema_version": "skill_trust_levels.v1", "trust_levels": by_level}
    if json_output:
        console.print_json(data=payload)
        return
    for level in ("official", "community", "unverified"):
        names = by_level[level]
        label = f"[bold]{level.upper()}[/bold]" if level != "unverified" else level.upper()
        if names:
            console.print(f"{label}: {', '.join(escape(n) for n in sorted(names))}")
        else:
            console.print(f"{label}: [dim]none[/dim]")


@skill_app.command("inspect")
def skill_inspect(
    name: str,
    manifest: bool = typer.Option(False, "--manifest", help="Show full manifest including trust metadata"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON output"),
) -> None:
    """Inspect a registered skill without executing it."""
    from claude_bridge.skill_registry import get_registry

    loaded = get_registry().inspect_skill(name)
    if loaded is None:
        payload = {"error": f"Skill '{name}' not found"}
        if json_output:
            console.print_json(data=payload)
        else:
            console.print(f"[red]{escape(payload['error'])}[/red]")
        raise typer.Exit(code=1)
    if manifest:
        success_payload: dict[str, Any] = {
            "schema_version": "skill_inspect_manifest.v1",
            "manifest": loaded.meta.to_dict(),
            "code_loaded": bool(loaded.code),
        }
    else:
        success_payload = {
            "schema_version": "skill_inspect.v1",
            "skill": loaded.metadata_dict(),
        }
    if json_output:
        console.print_json(data=success_payload)
        return
    if manifest:
        trust = loaded.meta.trust_level
        trust_color = {"official": "green", "community": "yellow", "unverified": "red"}.get(trust, "dim")
        trust_label = f"[{trust_color}]{trust}[/{trust_color}]"
        console.print(Panel.fit(
            json.dumps(loaded.meta.to_dict(), indent=2),
            title=f"{name} {trust_label}",
            border_style=trust_color if trust != "unverified" else "dim",
        ))
    else:
        console.print(Panel.fit(json.dumps(loaded.meta.to_dict(), indent=2), title=name))


@skill_app.command("recommend")
def skill_recommend(
    query: str,
    context: list[str] = typer.Option(None, "--context", help="Context tag for matching"),
    limit: int = typer.Option(5, "--limit", help="Maximum recommendations to return"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON output"),
) -> None:
    """Recommend registered skills for a task."""
    from claude_bridge.skill_registry import get_registry

    matches = get_registry().recommend(query, context=context or [], limit=limit)
    payload = {
        "schema_version": "skill_recommendations.v1",
        "query": query,
        "matches": [match.to_dict() for match in matches],
    }
    if json_output:
        console.print_json(data=payload)
        return
    if not matches:
        console.print("No matching skills found.")
        return
    for match in matches:
        console.print(f"[bold]{escape(match.name)}[/bold] score={match.score}")
        for reason in match.reasons:
            console.print(f"  - {escape(reason)}")


@skill_app.command("packages")
def skill_packages(
    directory: Path,
    query: str = typer.Option("", "--query", help="Package metadata query"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON output"),
) -> None:
    """Search local skill packages without importing them."""
    from claude_bridge.skill_marketplace import search_packages

    packages = search_packages(directory, query)
    payload = {"schema_version": "skill_packages.v1", "packages": packages}
    if json_output:
        console.print_json(data=payload)
        return
    if not packages:
        console.print("No matching packages found.")
        return
    for package in packages:
        console.print(
            f"[bold]{escape(str(package['name']))}[/bold] "
            f"{escape(str(package['version']))} {escape(str(package['file']))}"
        )


@skill_app.command("package-inspect")
def skill_package_inspect(
    package: Path,
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON output"),
) -> None:
    """Inspect a skill package without importing or executing it."""
    from claude_bridge.skill_marketplace import inspect_package

    inspection, errors = inspect_package(package)
    if errors:
        payload = {"error": "Package inspection failed", "errors": errors}
        if json_output:
            console.print_json(data=payload)
        else:
            for error in errors:
                console.print(f"[red]{escape(error)}[/red]")
        raise typer.Exit(code=1)
    success_payload: dict[str, Any] = {
        "schema_version": "skill_package_inspect.v1",
        "inspection": inspection,
    }
    if json_output:
        console.print_json(data=success_payload)
        return
    console.print(Panel.fit(json.dumps(inspection, indent=2), title=str(package)))


@skill_app.command("import")
def skill_import(
    package: Path,
    allow_high_risk: bool = typer.Option(
        False,
        "--allow-high-risk",
        help="Allow importing a package scored as high risk",
    ),
    skip_unverified_approval: bool = typer.Option(
        False,
        "--skip-unverified-approval",
        help="Skip approval prompt for unverified skills",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON output"),
) -> None:
    """Import a reviewed skill package."""
    from claude_bridge.skill_marketplace import import_skill_reviewed

    success, errors = import_skill_reviewed(
        package,
        allow_high_risk=allow_high_risk,
        skip_unverified_approval=skip_unverified_approval,
    )
    payload = {"ok": success, "errors": errors}
    if json_output:
        console.print_json(data=payload)
    elif success:
        console.print("[green]Skill imported[/green]")
    else:
        for error in errors:
            console.print(f"[red]{escape(error)}[/red]")
        console.print()
        console.print("[bold]Next steps:[/bold]")
        _print_suggestion("claude-bridge skill list", "List available skills to inspect")
        _print_suggestion("claude-bridge skill inspect <name>", "Inspect a specific skill")
    if not success:
        raise typer.Exit(code=1)


@skill_app.command("export")
def skill_export(
    name: str,
    destination: Path,
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON output"),
) -> None:
    """Export a registered skill package."""
    from claude_bridge.skill_marketplace import export_skill

    success, errors = export_skill(name, destination)
    payload = {"ok": success, "errors": errors, "destination": str(destination)}
    if json_output:
        console.print_json(data=payload)
    elif success:
        console.print(f"[green]Skill exported to {escape(str(destination))}[/green]")
    else:
        for error in errors:
            console.print(f"[red]{escape(error)}[/red]")
    if not success:
        raise typer.Exit(code=1)


@app.command()
def update(
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON output"),
) -> None:
    """Check for claude-bridge updates on PyPI and print the status."""
    result = json.loads(check_update())
    if json_output:
        console.print_json(data=result)
        return

    details = result.get("details", {})
    current = details.get("current_version", "?")
    latest = details.get("latest_version", "?")
    up_to_date = details.get("up_to_date", False)

    console.print(
        Panel.fit(
            Text.assemble(
                ("Claude Bridge ", "bold cyan"),
                ("Update Check", "green"),
            ),
            title="Update",
            border_style="cyan",
        )
    )
    console.print(f"Installed: [green]{current}[/green]")
    console.print(f"Latest:    [green]{latest}[/green]")
    if current == "unknown" or latest == "unknown":
        console.print("[yellow]Status:[/yellow] Could not fully determine versions")
    elif up_to_date:
        console.print("[green]Status:[/green] Up to date")
    else:
        console.print("[yellow]Status:[/yellow] Update available")
        console.print("Upgrade:   [cyan]pip install --upgrade claude-bridge[/cyan]")


def _print_preset_explanation_table() -> None:
    table = Table(title="Approval Preset Tradeoffs", show_header=True, header_style="bold")
    table.add_column("Preset", style="cyan", width=14)
    table.add_column("Tool Behavior", width=22)
    table.add_column("Security Tradeoff", width=30)
    table.add_column("Works Well For", width=22)

    rows = [
        (
            "[cyan]read-only[/cyan]",
            "All writes/shells [red]deny[/red]",
            "Maximum safety; no accidental writes",
            "Auditing, exploring repos",
        ),
        (
            "[cyan]dev-safe[/cyan]",
            "Writes need approval; system cmds blocked",
            "Balanced: catches risky ops before exec",
            "Daily development work",
        ),
        (
            "[cyan]ci-like[/cyan]",
            "Same as dev-safe; explicit preset for bots",
            "Reviewable by humans; CI-friendly",
            "Automated pipelines",
        ),
        (
            "[cyan]power-user[/cyan]",
            "Everything auto-approved (no prompt)",
            "Fast but no guard rails — mistakes allowed",
            "Trusted local environment",
        ),
    ]
    for row in rows:
        table.add_row(*row)

    table2 = Table(title="What Succeeds vs Fails Per Preset", show_header=True, header_style="bold")
    table2.add_column("Preset", style="cyan", width=14)
    table2.add_column("[green]Succeeds[/green]", width=26)
    table2.add_column("[red]Fails / Blocked[/red]", width=26)

    examples = [
        ("read-only", "ls, cat, git diff, grep", "write_file, run_shell, mv, rm"),
        ("dev-safe", "ls, cat, write to project", "sudo, curl|bash, rm -rf /"),
        ("ci-like", "ls, cat, git, npm test", "sudo, shutdown, rm -rf /"),
        ("power-user", "anything in project dir", "Only built-in hard denies apply"),
    ]
    for row in examples:
        table2.add_row(*row)

    console.print(table)
    console.print(table2)


@app.command()
def init(
    project_dir: str = typer.Option(".", "--project-dir", "-d", help="Project directory path"),
    approval_mode: str | None = typer.Option(
        None, "--approval", "-a", help="Approval mode: read-only|dev-safe|ci-like|power-user"
    ),
    allowed_roots: str | None = typer.Option(
        None, "--roots", "-r", help="Comma-separated allowed root paths"
    ),
    ai_provider: str | None = typer.Option(
        None, "--ai-provider", help="AI evaluator: local|openai|anthropic|ollama"
    ),
    non_interactive: bool = typer.Option(
        False, "--non-interactive", "-y", help="Skip prompts, use defaults/options"
    ),
) -> None:
    """Initialize claude-bridge guard policy interactively."""
    import signal

    def _on_cancel(signum: int, frame: Any) -> None:
        console.print("\n[yellow]Setup cancelled.[/yellow]")
        raise typer.Exit(0)

    original = signal.signal(signal.SIGINT, _on_cancel)

    try:
        console.print(Panel.fit("Welcome to [bold cyan]Claude Bridge[/] setup!", title="Init"))

        project_path = Path(project_dir).resolve()
        if not non_interactive:
            project_path = Path(
                Prompt.ask("Project directory", default=str(project_path))
            ).resolve()
        if not project_path.exists():
            project_path.mkdir(parents=True, exist_ok=True)

        presets = {"1": "read-only", "2": "dev-safe", "3": "ci-like", "4": "power-user"}
        mode = approval_mode or "dev-safe"
        if not non_interactive:
            _print_preset_explanation_table()
            console.print("\n[b]Approval mode:[/b]")
            for key, val in presets.items():
                desc = {
                    "read-only": "Filesystem read-only, no destructive commands",
                    "dev-safe": "Allow writes to project dir, block system-level",
                    "ci-like": "Auto-approve all, no human in the loop",
                    "power-user": "Minimal restrictions with AI evaluation",
                }
                console.print(f"  {key}. [cyan]{val}[/] - {desc[val]}")
            choice = Prompt.ask("Choose", default="2", choices=list(presets.keys()))
            mode = presets.get(choice, "dev-safe")

        roots_str = allowed_roots or str(project_path)
        if not non_interactive:
            roots_str = Prompt.ask(
                "Allowed root directories (comma-separated)",
                default=str(project_path),
            )

        provider = ai_provider or "local"
        if not non_interactive:
            console.print("\n[b]AI evaluator provider:[/b]")
            console.print("  1. local (default, no API key)")
            console.print("  2. openai")
            console.print("  3. anthropic")
            console.print("  4. ollama (local)")
            choice = Prompt.ask("Choose", default="1", choices=["1", "2", "3", "4"])
            provider = {"1": "local", "2": "openai", "3": "anthropic", "4": "ollama"}[choice]

        guard_config: dict[str, Any] = {
            "default_deny": False,
            "allowed_shell_commands": [],
            "blocked_shell_patterns": [],
            "sensitive_path_patterns": [".env*", "*.key", "*.pem", ".git/**"],
        }

        if mode == "read-only":
            guard_config["allowed_shell_commands"] = [
                "ls",
                "cat",
                "git",
                "echo",
                "find",
                "wc",
                "head",
                "tail",
            ]
            guard_config["blocked_shell_patterns"] = ["rm*", "mv*", "cp*", "chmod*", "mkfs*"]
        elif mode == "dev-safe":
            guard_config["blocked_shell_patterns"] = [
                "sudo*",
                "mkfs*",
                "shutdown*",
                "reboot*",
                "rm -rf /*",
                "dd if=*",
                "> /dev/*",
            ]
        elif mode == "ci-like":
            guard_config["default_deny"] = False
        elif mode == "power-user":
            guard_config["default_deny"] = False

        config_path = project_path / ".claude-bridge-guard.json"
        config_path.write_text(
            json.dumps(guard_config, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        console.print(f"\n[green]Config written to:[/] {config_path}")
        console.print(
            Panel.fit(
                Text.assemble(
                    ("Project: ", "dim"),
                    (str(project_path), "cyan"),
                    ("\nMode: ", "dim"),
                    (mode, "green"),
                    ("\nAI Provider: ", "dim"),
                    (provider, "green"),
                    ("\nRoots: ", "dim"),
                    (roots_str, "cyan"),
                    ("\n\nReady! Configure your MCP client to use claude-bridge.", "bold"),
                ),
                title="Summary",
                border_style="green",
            )
        )
    finally:
        signal.signal(signal.SIGINT, original)


@app.command("workflow-preview")
def workflow_preview(
    mode: str,
    target: str = ".",
    option: str | None = typer.Option(None, "--option", help="Workflow focus/option"),
    language: str = typer.Option("English", "--language", help="Response language"),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable output"),
) -> None:
    """Preview a workflow prompt without executing it."""
    from claude_bridge.workflow_presets import preview_workflow

    result = preview_workflow(mode, target, option, language)
    if json_output:
        console.print_json(data=result)
        return
    if not result["ok"]:
        console.print(f"[red]Error:[/red] {result['error']}")
        console.print(f"Valid modes: {', '.join(result['valid_modes'])}")
        raise typer.Exit(code=1)
    console.print(
        Panel.fit(
            f"[bold]Mode:[/bold] {result['mode']}  [bold]Target:[/bold] {result['target']}",
            title="Workflow Preview",
        )
    )
    console.print(f"\n[bold]Token estimate:[/bold] ~{result['token_estimate']} tokens")
    console.print(f"\n[bold]Steps:[/bold] {result['steps_summary']}")
    console.print(f"\n[bold]Prompt:[/bold]\n{result['prompt']}")


@app.command()
def setup(
    project_dir: Path = typer.Option(
        Path.cwd(),
        "--project-dir",
        "-d",
        help="Root directory the bridge is allowed to access",
    ),
    allow_root: list[Path] = typer.Option(
        None,
        "--allow-root",
        help="Additional allowed workspace root (can be specified multiple times)",
    ),
    target: str = typer.Option(
        "claude-desktop",
        "--target",
        help="Setup target: claude-desktop, generic-stdio, or vscode",
    ),
    approval_preset: str | None = typer.Option(
        None,
        "--approval-preset",
        help=_approval_help_suffix(),
    ),
    auto_approve: bool = typer.Option(
        False,
        help="Render config with auto-approve enabled (use with caution)",
    ),
    client_managed_approval: bool = typer.Option(
        False,
        help="Render config assuming the MCP client handles approvals",
    ),
) -> None:
    """Print setup instructions and system prompt for a supported MCP target.

    Examples:
      claude-bridge setup
      claude-bridge setup -d /path/to/project --target claude-desktop
      claude-bridge setup --approval-preset read-only
    """
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
        Path.cwd(),
        "--project-dir",
        "-d",
        help="Root directory the bridge is allowed to access",
    ),
    allow_root: list[Path] = typer.Option(
        None,
        "--allow-root",
        help="Additional allowed workspace root (can be specified multiple times)",
    ),
    target: str = typer.Option(
        "claude-desktop",
        "--target",
        help="Install target: claude-desktop, generic-stdio, or vscode",
    ),
    config_path: Path = typer.Option(
        None,
        "--config-path",
        help="Override target config path",
    ),
    approval_preset: str | None = typer.Option(
        None,
        "--approval-preset",
        help=_approval_help_suffix(),
    ),
    auto_approve: bool = typer.Option(
        False,
        help="Write config with auto-approve enabled (use with caution)",
    ),
    client_managed_approval: bool = typer.Option(
        True,
        help="Write config assuming Claude Desktop handles approval prompts",
    ),
) -> None:
    """Install or write Claude Bridge config for a supported MCP target.

    Examples:
      claude-bridge install
      claude-bridge install -d /path/to/project --target claude-desktop
      claude-bridge install --approval-preset dev-safe
    """
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
    _, _, set_config, _ = _server_runtime()
    (
        run_index_and_relevance_benchmark,
        compare_benchmark_to_baseline,
        load_benchmark_profile,
    ) = _benchmark_runtime()
    resolved_project_dir = project_dir.resolve()
    set_config(project_dir=resolved_project_dir, auto_approve=False, client_managed_approval=True)
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


@audit_app.command("summary")
def audit_summary(
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
        console.print_json(data=summary)
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
                console.print(f"  [{status}] {item.get('tool_name')} {escape(paths)}")
        approval_rejections = activity.get("approval_rejections", [])
        if approval_rejections:
            console.print("\nApproval rejections:")
            for item in approval_rejections[:10]:
                console.print(f"  [error] {item.get('timestamp')} {item.get('tool_name')}")
        risky_actions = activity.get("risky_actions", [])
        if risky_actions:
            console.print("\nRisky actions:")
            for item in risky_actions[:10]:
                console.print(
                    f"  [yellow]{item.get('risk_level')}[/yellow] "
                    f"{item.get('tool_name')} {escape(str(item.get('message', '')))}"
                )
        policy = activity.get("policy_decisions", {})
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


@audit_app.command("export")
def audit_export(
    session: str | None = typer.Option(
        None,
        "--session",
        help="Session ID to export (default: latest session)",
    ),
    format: str = typer.Option(
        "jsonl",
        "--format",
        help="Export format: jsonl or summary-json",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file path (default: stdout)",
    ),
    limit: int | None = typer.Option(
        None,
        "--limit",
        help="Maximum number of records to export",
    ),
    tool: str | None = typer.Option(
        None,
        "--tool",
        help="Filter by tool name",
    ),
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
    """Export audit session records with optional filtering."""
    from claude_bridge.audit import (
        ExportFormat,
        export_audit_records,
        filter_audit_records,
        latest_session_id,
    )

    # Validate format
    try:
        export_format = ExportFormat(format.lower())
    except ValueError:
        console.print(f"[red]Invalid format:[/red] {format}")
        console.print("Supported formats: jsonl, summary-json")
        raise typer.Exit(code=1)

    # Determine session
    target_session = session
    if target_session is None:
        target_session = latest_session_id()
        if target_session is None:
            console.print("[red]No audit sessions found[/red]")
            raise typer.Exit(code=1)

    # Export records
    try:
        audit_export_result = export_audit_records(
            session_id=target_session,
            export_format=export_format,
            limit=limit,
        )
    except Exception as exc:
        console.print(f"[red]Export failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    # Get records payload
    records: list[dict[str, Any]] = []
    if isinstance(audit_export_result.records_payload, list):
        records = audit_export_result.records_payload
    elif isinstance(audit_export_result.records_payload, dict):
        # For summary-json, we still apply filters to the underlying records
        # but summary-json format doesn't support filtering at the moment
        pass

    # Apply filters if any are specified
    has_filters = any(param is not None for param in (tool, decision, risk, source))
    if has_filters and records:
        records = filter_audit_records(
            records,
            tool_name=tool,
            decision_action=decision.value if decision else None,
            decision_risk_level=risk.value if risk else None,
            decision_source=source.value if source else None,
        )

    # Prepare output
    if export_format == ExportFormat.JSONL:
        output_content = "\n".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) for record in records
        )
        if output_content:
            output_content += "\n"
    else:  # summary-json
        if has_filters and records:
            # Rebuild summary with filtered records
            from claude_bridge.audit import summarize_session

            summary = summarize_session(target_session, limit=len(records))
            # Replace recent_records with filtered records
            summary["recent_records"] = records
            summary["returned_records"] = len(records)
            output_content = json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2)
        else:
            output_content = audit_export_result.to_summary_json()

    # Write output
    if output:
        try:
            output.write_text(output_content, encoding="utf-8")
            console.print(
                f"[green]Exported {len(records) if records else 'summary'} records to {output}[/green]"
            )
        except OSError as exc:
            console.print(f"[red]Failed to write output file:[/red] {exc}")
            raise typer.Exit(code=1) from exc
    else:
        # Print to stdout (use plain print to avoid Rich formatting)
        print(output_content, end="")


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
        console.print_json(data=result)
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
def appeal(
    record_id: str = typer.Option(..., "--record-id", help="Audit record id to appeal"),
    justification: str = typer.Option(..., "--justification", "-j", help="Reason for the appeal"),
    escalate: bool = typer.Option(
        False,
        "--escalate",
        help="Create a pending local escalation event if the appeal remains denied",
    ),
    escalation_target: str = typer.Option(
        "team_lead",
        "--escalation-target",
        help="Local escalation target label",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON output"),
) -> None:
    """Appeal a policy decision by record id with a justification."""
    from claude_bridge.audit import process_appeal

    try:
        result = process_appeal(
            record_id,
            justification,
            escalate=escalate,
            escalation_target=escalation_target,
        )
    except ValueError as exc:
        console.print(f"[red]Appeal failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if json_output:
        console.print_json(data=result)
        return

    console.print(
        Panel.fit(
            Text.assemble(("Appeal ", "bold cyan"), (record_id, "green")),
            title="Appeal",
            border_style="cyan",
        )
    )
    appeal_result = result.get("appeal_result", {})
    console.print(f"Appeal ID: [green]{escape(str(appeal_result.get('appeal_id', '')))}[/green]")
    console.print(f"Status: [cyan]{escape(str(appeal_result.get('status', '')))}[/cyan]")
    console.print(f"Reviewed by: {escape(str(appeal_result.get('reviewed_by', '')))}")
    console.print(f"Reason: {escape(str(appeal_result.get('decision_reason', '')))}")

    original = result.get("original_record", {})
    console.print("\nOriginal decision:")
    console.print(
        f"  action={escape(str(original.get('decision_action', 'N/A')))} "
        f"source={escape(str(original.get('decision_source', 'N/A')))} "
        f"risk={escape(str(original.get('decision_risk_level', 'N/A')))}"
    )

    replay = result.get("replay_result", {})
    console.print("\nReplay result:")
    console.print(f"  changed={replay.get('changed', False)}")
    console.print(f"  change_reason={escape(str(replay.get('change_reason', '')))}")

    meta = replay.get("metadata", {})
    if meta.get("requires_human_review"):
        console.print(
            f"\n[yellow]Human review required:[/yellow] "
            f"{escape(str(meta.get('review_reason', '')))}"
        )

    escalation = result.get("escalation")
    if isinstance(escalation, dict) and escalation.get("requested"):
        if escalation.get("created"):
            event = escalation.get("event", {})
            console.print(
                "\n[yellow]Escalation created:[/yellow] "
                f"{escape(str(event.get('escalation_id', '')))} "
                f"target={escape(str(event.get('target', '')))}"
            )
        else:
            console.print(
                "\n[yellow]Escalation not created:[/yellow] "
                f"{escape(str(escalation.get('reason', '')))}"
            )

    console.print(f"\nTotal appeals for this record: {result.get('appeal_history_count', 0)}")


@app.command()
def appeal_history(
    record_id: str = typer.Option(..., "--record-id", help="Audit record id"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON output"),
) -> None:
    """Show appeal history for a given audit record."""
    from claude_bridge.audit import get_appeal_history

    history = get_appeal_history(record_id)

    if not history:
        console.print(f"[yellow]No appeals found for record:[/yellow] {escape(record_id)}")
        return

    if json_output:
        console.print_json(data={"record_id": record_id, "appeals": history})
        return

    console.print(
        Panel.fit(
            Text.assemble(
                ("Appeal History ", "bold cyan"),
                (record_id, "green"),
            ),
            title="Appeals",
            border_style="cyan",
        )
    )
    console.print(f"Total appeals: [green]{len(history)}[/green]")

    for index, appeal in enumerate(history, start=1):
        console.print(f"\n--- Appeal {index} ---")
        console.print(f"  Appeal ID: {escape(str(appeal.get('appeal_id', '')))}")
        console.print(f"  Timestamp: {escape(str(appeal.get('timestamp', '')))}")
        console.print(f"  Status: {escape(str(appeal.get('appeal_status', 'pending')))}")
        reviewed_by = appeal.get("appeal_reviewed_by")
        if reviewed_by:
            console.print(f"  Reviewed by: {escape(str(reviewed_by))}")

        params = appeal.get("params", {})
        if isinstance(params, dict):
            justification = params.get("justification", "")
            if justification:
                console.print(f"  Justification: {escape(str(justification))}")

        result_details = appeal.get("result", {})
        if isinstance(result_details, dict):
            details = result_details.get("details", {})
            if isinstance(details, dict):
                result_data = details.get("result", {})
                if isinstance(result_data, dict):
                    reason = result_data.get("decision_reason", "")
                    if reason:
                        console.print(f"  Decision reason: {escape(str(reason))}")


@anomaly_app.command("scan")
def anomaly_scan(
    last: bool = typer.Option(True, "--last", help="Scan the latest audit session"),
    limit: int = typer.Option(50, help="Maximum number of records to scan"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON output"),
) -> None:
    """Run anomaly detection on recent audit records."""
    from claude_bridge.anomaly import build_anomaly_summary
    from claude_bridge.audit import get_recent_tool_calls

    if not last:
        console.print("[yellow]Only --last is currently supported.[/yellow]")
    safe_limit = max(1, limit)
    recent = get_recent_tool_calls(limit=safe_limit)
    records = recent.get("records", [])
    session_id = recent.get("session_id", "")
    summary = build_anomaly_summary(
        records=records,
        session_id=session_id,
        limit=safe_limit,
    )

    if json_output:
        console.print_json(data=summary)
        return

    console.print(
        Panel.fit(
            Text.assemble(
                ("Anomaly Scan ", "bold cyan"),
                (summary["session_id"], "green"),
            ),
            title="Anomaly",
            border_style="cyan",
        )
    )
    console.print(f"Records scanned: [green]{summary['total_records_scanned']}[/green]")
    console.print(
        f"Overall max score: "
        f"[{'red' if summary['overall_max_score'] > 55 else 'green'}]"
        f"{summary['overall_max_score']}[/] "
        f"({summary['overall_level']})"
    )
    runtime_policy = summary.get("runtime_policy", {})
    if isinstance(runtime_policy, dict):
        console.print(
            "Runtime policy: "
            f"[cyan]{escape(str(runtime_policy.get('mode', 'unknown')))}[/cyan] "
            f"(effective: {escape(str(runtime_policy.get('effective_action', 'unknown')))})"
        )

    anomaly_counts = summary.get("anomaly_counts", {})
    if anomaly_counts:
        console.print("\nAnomaly counts:")
        for atype, count in sorted(anomaly_counts.items()):
            console.print(f"  {atype}: {count}")

    critical_count = summary.get("critical_count", 0)
    if critical_count > 0:
        console.print(f"\n[red]Critical anomalies: {critical_count}[/red]")
        for decision in summary.get("policy_decisions", []):
            console.print(
                f"  [red]record={escape(decision['record_id'][:12])}[/red] "
                f"score={decision['score']} "
                f"types={escape(str(decision['anomaly_types']))} "
                f"decision={escape(decision['decision_action'])}/"
                f"{escape(decision['decision_risk_level'])}/"
                f"{escape(decision['decision_source'])} "
                f"-> {escape(decision['recommended_action'])}"
            )
            if decision.get("explanation"):
                console.print(f"    {escape(decision['explanation'])}")
    else:
        console.print("\n[green]No critical anomalies detected.[/green]")

    mvp = summary.get("mvp_limits", {})
    if mvp:
        console.print(f"\nMVP scope: {escape(str(mvp.get('scope', '')))}")


@anomaly_app.command("baseline")
def anomaly_baseline(
    project_dir: Path = typer.Option(Path.cwd(), help="Project directory for baseline storage"),
    limit: int = typer.Option(500, help="Maximum recent audit records to learn from"),
    output: Path | None = typer.Option(
        None,
        "--output",
        help="Optional baseline output path (default: <project>/.claude-bridge/baseline.json)",
    ),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable JSON output"),
) -> None:
    """Build or update an anomaly baseline from recent audit records."""
    from claude_bridge.audit import get_recent_tool_calls
    from claude_bridge.baseline import load_baseline, merge_baseline, save_baseline

    safe_limit = max(1, min(limit, 10000))
    baseline_path = output or (project_dir.resolve() / ".claude-bridge" / "baseline.json")
    recent = get_recent_tool_calls(limit=safe_limit)
    records = recent.get("records", [])
    if not isinstance(records, list):
        records = []

    existing = load_baseline(baseline_path)
    baseline = merge_baseline(existing, records)
    save_baseline(baseline_path, baseline)

    payload = {
        "ok": True,
        "baseline_path": str(baseline_path),
        "records_used": len(records),
        "session_id": recent.get("session_id", ""),
        "baseline": baseline,
    }

    if json_output:
        console.print_json(data=payload)
        return

    console.print("[green]Anomaly baseline updated[/green]")
    console.print(f"Path: {escape(str(baseline_path))}")
    console.print(f"Records used: [green]{len(records)}[/green]")
    console.print(f"Sessions learned: [green]{baseline['session_count']}[/green]")
    console.print(f"Average records/session: [green]{baseline['avg_records_per_session']}[/green]")


@doctor_app.callback(invoke_without_command=True)
def doctor(
    project_dir: Path = typer.Option(Path.cwd(), help="Project directory to inspect"),
) -> None:
    """Run lightweight environment and configuration checks."""
    current_config, _, _, _ = _server_runtime()
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


@doctor_app.command()
def security(
    project_dir: Path = typer.Option(Path.cwd(), help="Project directory to inspect"),
) -> None:
    """Run security-focused checks on the current configuration."""
    current_config, _, _, _ = _server_runtime()
    report = build_security_doctor_report(
        project_dir=project_dir,
        config_snapshot=current_config(),
    )

    console.print(
        Panel.fit(
            Text.assemble(("Claude Bridge ", "bold cyan"), ("doctor security", "green")),
            title="Security Doctor",
            border_style="cyan",
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
