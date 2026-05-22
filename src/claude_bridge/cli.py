"""Command-line interface for Nulm."""

# Copyright (c) 2026 Nulm Contributors
# SPDX-License-Identifier: MIT


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
from claude_bridge._control_plane_cli import register_control_plane_cli
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


app = typer.Typer(help="Nulm — local-first MCP agent quality and execution layer")
policy_app = typer.Typer(help="Validate and simulate local guard policy files")
anomaly_app = typer.Typer(help="Anomaly detection on audit sessions")
audit_app = typer.Typer(help="Audit session management and export")
doctor_app = typer.Typer(help="Environment and security checks")
skill_app = typer.Typer(help="Skill discovery, inspection, import, and export")
scan_app = typer.Typer(help="Security scan for tools, skills, and config")
control_plane_app = typer.Typer(help="Inspect local control-plane state")
tasks_app = typer.Typer(help="Inspect local task state")
approvals_app = typer.Typer(help="Inspect local approval state")
app.add_typer(policy_app, name="policy")
app.add_typer(anomaly_app, name="anomaly")
app.add_typer(audit_app, name="audit")
app.add_typer(doctor_app, name="doctor")
app.add_typer(skill_app, name="skill")
app.add_typer(scan_app, name="scan")
app.add_typer(tasks_app, name="tasks")
app.add_typer(approvals_app, name="approvals")
app.add_typer(control_plane_app, name="control-plane")
app.add_typer(config_app, name="config")
control_plane_app.add_typer(tasks_app, name="tasks")
control_plane_app.add_typer(approvals_app, name="approvals")
register_control_plane_cli(
    app=app,
    tasks_app=tasks_app,
    approvals_app=approvals_app,
    console=console,
)

COMMAND_GROUPS = {
    "Core": ["start", "init", "update"],
    "Tools": ["skill", "benchmark", "agent-benchmark", "schedule"],
    "Audit": ["audit", "appeal", "anomaly", "replay", "appeal-history"],
    "Config": ["config"],
    "MCP": ["install", "setup"],
    "Admin": ["doctor", "envdoctor", "policy", "dashboard", "workflow-preview"],
    "Sessions": ["sessions"],
    "Worktree": ["worktree"],
    "CI": ["audit-ci"],
}


def _version_option(value: bool) -> None:
    if value:
        console.print(__version__)
        raise typer.Exit()


def _print_grouped_help(ctx: typer.Context) -> None:
    console.print(
        Panel.fit(
            "[bold cyan]Nulm[/bold cyan] command line interface",
            title="Help",
            border_style="cyan",
        )
    )
    console.print()

    all_cmds: dict[str, Any] = {}
    for cmd_info in app.registered_commands:
        if cmd_info.name is not None:
            all_cmds[cmd_info.name] = cmd_info
    for subapp in [
        policy_app,
        anomaly_app,
        audit_app,
        doctor_app,
        skill_app,
        control_plane_app,
        config_app,
    ]:
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
    """Nulm command line interface."""
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


def _agent_benchmark_runtime() -> tuple[Any, Any]:
    from claude_bridge.agents.benchmark_gates import evaluate_agent_benchmark_gates
    from claude_bridge.agents.benchmark_harness import run_agent_benchmark

    return run_agent_benchmark, evaluate_agent_benchmark_gates


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
      nulm policy validate --path policy.json
      nulm policy validate -p policy.yaml
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
        _print_suggestion("nulm doctor", "Check environment and config for issues")
        _print_suggestion("nulm policy --help", "See policy subcommands")
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
      nulm policy simulate --path policy.json --tool run_shell --param command=ls
      nulm policy simulate -p policy.json -t file_read --param path=README.md
      nulm policy simulate -p policy.json -t run_shell --role junior --param command=cat

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
      nulm policy diff --base main.json --head pr.json
      nulm policy diff -b baseline.json -h updated.json

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
    tool_profile: str = "standard",
    context_budget_profile: str = "balanced",
    onboarding_enabled: bool = True,
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
        tool_profile=tool_profile,
        context_budget_profile=context_budget_profile,
        onboarding_enabled=onboarding_enabled,
    )
    mcp_servers = generated_config.get("mcpServers")
    if not isinstance(mcp_servers, dict):
        raise ValueError("Generated desktop config is missing 'mcpServers'")
    bridge_entry = mcp_servers.get("nulm")
    if not isinstance(bridge_entry, dict):
        raise ValueError("Generated desktop config is missing the 'nulm' entry")
    servers["nulm"] = bridge_entry

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return config_path


def _default_target_config_path(project_dir: Path, target: str) -> Path:
    safe_target = target.replace("-", "_")
    return project_dir.resolve() / f".nulm.{safe_target}.json"


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
    tool_profile: str = "standard",
    context_budget_profile: str = "balanced",
    onboarding_enabled: bool = True,
) -> Path:
    if target == "claude-desktop":
        return _write_desktop_config(
            config_path,
            project_dir=project_dir,
            allowed_roots=allowed_roots,
            auto_approve=auto_approve,
            client_managed_approval=client_managed_approval,
            approval_preset=approval_preset,
            tool_profile=tool_profile,
            context_budget_profile=context_budget_profile,
            onboarding_enabled=onboarding_enabled,
        )
    _, build_target_config, _, _ = _prompt_runtime()
    config = build_target_config(
        project_dir.resolve(),
        target=target,
        allowed_roots=allowed_roots,
        auto_approve=auto_approve,
        client_managed_approval=client_managed_approval,
        approval_preset=approval_preset,
        tool_profile=tool_profile,
        context_budget_profile=context_budget_profile,
        onboarding_enabled=onboarding_enabled,
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
      nulm start
      nulm start -d /path/to/project
      nulm start --approval-preset read-only
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
        raise typer.Exit(code=0)


@app.command()
def version() -> None:
    """Show version information."""
    console.print(f"[bold cyan]Nulm[/bold cyan] version [green]{__version__}[/green]")


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
        console.print(
            f"[bold]{escape(meta['name'])}[/bold] v{escape(meta['version'])} {trust_badge}"
        )


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
    manifest: bool = typer.Option(
        False, "--manifest", help="Show full manifest including trust metadata"
    ),
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
        trust_color = {"official": "green", "community": "yellow", "unverified": "red"}.get(
            trust, "dim"
        )
        trust_label = f"[{trust_color}]{trust}[/{trust_color}]"
        console.print(
            Panel.fit(
                json.dumps(loaded.meta.to_dict(), indent=2),
                title=f"{name} {trust_label}",
                border_style=trust_color if trust != "unverified" else "dim",
            )
        )
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
        _print_suggestion("nulm skill list", "List available skills to inspect")
        _print_suggestion("nulm skill inspect <name>", "Inspect a specific skill")
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
    """Check for Nulm updates on PyPI and print the status."""
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
                ("Nulm ", "bold cyan"),
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
        console.print("Upgrade:   [cyan]pip install --upgrade nulm[/cyan]")


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

    examples: list[tuple[str, str, str]] = [
        ("read-only", "ls, cat, git diff, grep", "write_file, run_shell, mv, rm"),
        ("dev-safe", "ls, cat, write to project", "sudo, curl|bash, rm -rf /"),
        ("ci-like", "ls, cat, git, npm test", "sudo, shutdown, rm -rf /"),
        ("power-user", "anything in project dir", "Only built-in hard denies apply"),
    ]
    for example in examples:
        table2.add_row(*example)

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
        None,
        "--ai-provider",
        help=(
            "AI evaluator: local|openai|anthropic|ollama|deepseek|minimax|google|groq|"
            "mistral|cohere|xai|together|openrouter|perplexity|fireworks"
        ),
    ),
    non_interactive: bool = typer.Option(
        False, "--non-interactive", "-y", help="Skip prompts, use defaults/options"
    ),
) -> None:
    """Initialize Nulm guard policy interactively."""
    import signal

    def _on_cancel(signum: int, frame: Any) -> None:
        console.print("\n[yellow]Setup cancelled.[/yellow]")
        raise typer.Exit(0)

    original = signal.signal(signal.SIGINT, _on_cancel)

    try:
        console.print(Panel.fit("Welcome to [bold cyan]Nulm[/] setup!", title="Init"))

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
            provider_options = {
                "1": "local",
                "2": "openai",
                "3": "anthropic",
                "4": "ollama",
                "5": "deepseek",
                "6": "minimax",
                "7": "google",
                "8": "groq",
                "9": "mistral",
                "10": "cohere",
                "11": "xai",
                "12": "together",
                "13": "openrouter",
                "14": "perplexity",
                "15": "fireworks",
            }
            console.print("\n[b]AI evaluator provider:[/b]")
            for key, name in provider_options.items():
                suffix = " (default, no API key)" if name == "local" else ""
                console.print(f"  {key}. [cyan]{name}[/cyan]{suffix}")
            choice = Prompt.ask("Choose", default="1", choices=list(provider_options))
            provider = provider_options[choice]

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
                    ("\n\nReady! Configure your MCP client to use nulm.", "bold"),
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
    parallel: bool = typer.Option(False, "--parallel", help="Show parallel execution grouping"),
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

    if parallel:
        console.print("\n[bold cyan]Parallel Execution Groups:[/bold cyan]")
        # Build a workflow engine to plan parallel groups
        from claude_bridge.workflow_engine import WorkflowEngine

        engine = WorkflowEngine()
        engine.create_plan(result["prompt"])
        groups = engine.plan_parallel_groups()
        if groups:
            for i, group in enumerate(groups, 1):
                agg_label = group.aggregation_mode.value
                console.print(f"  [cyan]Group {i}[/cyan] ({agg_label}): {len(group.steps)} step(s)")
                for step in group.steps:
                    console.print(f"    - {step.action[:60]}")
        else:
            console.print("  No parallel groups available for this workflow.")

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
      nulm setup
      nulm setup -d /path/to/project --target claude-desktop
      nulm setup --approval-preset read-only
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
                ("Nulm ", "bold cyan"),
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
            "[yellow bold]NOTE:[/yellow bold] Approval-requiring tools will fail "
            "closed until you enable client-managed approval or auto-approve."
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
        "-t",
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
    non_interactive: bool = typer.Option(False, "-y", help="Skip interactive prompts"),
    simple: bool = typer.Option(False, "--simple", help="Quick setup with defaults"),
) -> None:
    """Install or write Nulm config for a supported MCP target.

    Examples:
      nulm install
      nulm install --simple
      nulm install -d /path/to/project -t vscode
      nulm install --approval-preset dev-safe
    """
    import signal
    from claude_bridge.config import update_runtime_config

    def _on_cancel(signum: int, frame: Any) -> None:
        console.print("\n[yellow]Setup cancelled.[/yellow]")
        raise typer.Exit(0)

    original = signal.signal(signal.SIGINT, _on_cancel)

    try:
        _, _, _, supported_targets = _prompt_runtime()

        console.print(Panel.fit("[bold cyan]Nulm Setup[/bold cyan]", title="Install"))

        if simple:
            resolved_project_dir = project_dir.resolve()
            resolved_target = target
            resolved_preset = approval_preset or "dev-safe"
            resolved_provider = "local"
            resolved_roots = [resolved_project_dir] + [r.resolve() for r in (allow_root or [])]
            resolved_tool_profile = "standard"
        else:
            console.print("\n[b]Setup type:[/b]")
            console.print("  1. [cyan]Detailed[/cyan] - Configure everything")
            console.print("  2. [cyan]Simple[/cyan] - Quick setup with defaults")
            setup_choice = Prompt.ask("Choose", default="2", choices=["1", "2"])
            is_detailed = setup_choice == "1"

            project_path = project_dir.resolve()
            if is_detailed:
                console.print("\n[b]Project directory:[/b]")
                project_path = Path(Prompt.ask("Directory", default=str(project_path))).resolve()
            resolved_project_dir = project_path

            target_options = {
                "1": "claude-desktop",
                "2": "vscode",
                "3": "generic-stdio",
            }
            if is_detailed:
                console.print("\n[b]Target MCP client:[/b]")
                for k, v in target_options.items():
                    console.print(f"  {k}. [cyan]{v}[/cyan]")
                target_choice = Prompt.ask("Choose", default="1", choices=list(target_options))
                resolved_target = target_options[target_choice]
            else:
                resolved_target = target

            preset_options = {
                "1": "read-only",
                "2": "dev-safe",
                "3": "ci-like",
                "4": "power-user",
            }
            if is_detailed:
                _print_preset_explanation_table()
                console.print("\n[b]Approval mode:[/b]")
                for k, v in preset_options.items():
                    console.print(f"  {k}. [cyan]{v}[/]")
                preset_choice = Prompt.ask("Choose", default="2", choices=list(preset_options))
                resolved_preset = preset_options[preset_choice]
            else:
                resolved_preset = approval_preset or "dev-safe"

            provider_options = {
                "1": "local",
                "2": "openai",
                "3": "anthropic",
                "4": "deepseek",
                "5": "minimax",
                "6": "google",
                "7": "groq",
                "8": "mistral",
                "9": "cohere",
                "10": "xai",
                "11": "together",
                "12": "openrouter",
                "13": "perplexity",
                "14": "fireworks",
            }
            provider_names = {
                "1": "Local (free, no API key)",
                "2": "OpenAI",
                "3": "Anthropic (Claude)",
                "4": "DeepSeek",
                "5": "MiniMax",
                "6": "Google Gemini",
                "7": "Groq",
                "8": "Mistral",
                "9": "Cohere",
                "10": "xAI",
                "11": "Together AI",
                "12": "OpenRouter",
                "13": "Perplexity",
                "14": "Fireworks",
            }
            if is_detailed:
                console.print("\n[b]AI provider:[/b]")
                for k, name in provider_names.items():
                    console.print(f"  {k}. [cyan]{name}[/cyan]")
                provider_choice = Prompt.ask("Choose", default="1", choices=list(provider_options))
                resolved_provider = provider_options[provider_choice]
            else:
                resolved_provider = "local"

            if resolved_provider != "local" and resolved_provider != "ollama":
                if is_detailed:
                    keys = list(provider_options.keys())
                    vals = list(provider_options.values())
                    provider_label = provider_names.get(keys[vals.index(resolved_provider)] or "")
                    env_names = {
                        "openai": "OPENAI_API_KEY",
                        "anthropic": "ANTHROPIC_API_KEY",
                        "deepseek": "DEEPSEEK_API_KEY",
                        "minimax": "MINIMAX_API_KEY",
                        "google": "GEMINI_API_KEY",
                        "groq": "GROQ_API_KEY",
                        "mistral": "MISTRAL_API_KEY",
                        "cohere": "COHERE_API_KEY",
                        "xai": "XAI_API_KEY",
                        "together": "TOGETHER_API_KEY",
                        "openrouter": "OPENROUTER_API_KEY",
                        "perplexity": "PERPLEXITY_API_KEY",
                        "fireworks": "FIREWORKS_API_KEY",
                    }
                    env_name = env_names.get(resolved_provider, "PROVIDER_API_KEY")
                    console.print(
                        f"\n[dim]{provider_label} uses {env_name}; Nulm does not "
                        "store API keys in config.[/dim]"
                    )

            roots_str = str(resolved_project_dir)
            if is_detailed:
                console.print("\n[b]Allowed root directories:[/b]")
                roots_str = Prompt.ask(
                    "Allowed roots (comma-separated)",
                    default=str(resolved_project_dir),
                )
            resolved_roots = [resolved_project_dir]
            for r in roots_str.split(","):
                r = r.strip()
                if r and Path(r).resolve() not in resolved_roots:
                    resolved_roots.append(Path(r).resolve())

            if is_detailed:
                console.print("\n[b]Tool profile:[/b]")
                console.print("  1. [cyan]essential[/cyan] - Minimal tools, lowest token use")
                console.print("  2. [cyan]standard[/cyan] - Default tools, balanced token use")
                console.print("  3. [cyan]full[/cyan] - All tools, highest token use")
                profile_choice = Prompt.ask("Choose", default="2", choices=["1", "2", "3"])
                profile_map = {"1": "essential", "2": "standard", "3": "full"}
                resolved_tool_profile = profile_map[profile_choice]
            else:
                resolved_tool_profile = "standard"

        resolved_auto_approve, resolved_client_managed, _ = _resolve_cli_approval_mode(
            approval_preset=resolved_preset,
            auto_approve=auto_approve,
            client_managed_approval=client_managed_approval,
        )

        if resolved_target not in supported_targets:
            raise typer.BadParameter(
                f"Unsupported target: {resolved_target}. "
                f"Choose one of: {', '.join(supported_targets)}"
            )

        resolved_config_path = (
            config_path.resolve()
            if config_path is not None
            else (
                _default_claude_desktop_config_path()
                if resolved_target == "claude-desktop"
                else _default_target_config_path(resolved_project_dir, resolved_target)
            )
        )

        try:
            written_path = _write_target_config(
                resolved_config_path,
                target=resolved_target,
                project_dir=resolved_project_dir,
                allowed_roots=resolved_roots,
                auto_approve=resolved_auto_approve,
                client_managed_approval=resolved_client_managed,
                approval_preset=resolved_preset,
                tool_profile=resolved_tool_profile,
            )
        except ValueError as exc:
            console.print(f"[red]Install failed:[/red] {exc}")
            console.print()
            console.print("[dim]Hint: check that the target config path is writable and")
            console.print("the MCP client is fully closed before retrying.[/dim]")
            if resolved_target == "claude-desktop":
                console.print("[dim]For Claude Desktop: fully quit the app, then retry.[/dim]")
            raise typer.Exit(code=1) from exc

        if resolved_provider != "local":
            update_runtime_config("ai_evaluator_provider", resolved_provider)
            update_runtime_config("ai_evaluator_enabled", True)
        update_runtime_config("tool_profile", resolved_tool_profile)

        console.print(
            Panel.fit(
                Text.assemble(
                    ("Nulm ", "bold cyan"),
                    (f"installed for {_target_display_name(resolved_target)}", "green"),
                ),
                title="Install",
                border_style="green",
            )
        )
        console.print(f"Config updated: [green]{written_path}[/green]")
        console.print(f"Project directory: [green]{resolved_project_dir}[/green]")
        console.print(f"Target: [cyan]{resolved_target}[/cyan]")
        console.print(f"Approval preset: [cyan]{resolved_preset}[/cyan]")
        if resolved_provider != "local":
            console.print(f"AI provider: [cyan]{resolved_provider}[/cyan]")
            env_names = {
                "openai": "OPENAI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
                "deepseek": "DEEPSEEK_API_KEY",
                "minimax": "MINIMAX_API_KEY",
                "google": "GEMINI_API_KEY",
                "groq": "GROQ_API_KEY",
                "mistral": "MISTRAL_API_KEY",
                "cohere": "COHERE_API_KEY",
                "xai": "XAI_API_KEY",
                "together": "TOGETHER_API_KEY",
                "openrouter": "OPENROUTER_API_KEY",
                "perplexity": "PERPLEXITY_API_KEY",
                "fireworks": "FIREWORKS_API_KEY",
            }
            env_name_optional = env_names.get(resolved_provider)
            if env_name_optional:
                console.print(
                    f"Set [cyan]{env_name_optional}[/cyan] in your shell or MCP client environment "
                    "before using provider-backed AI tools."
                )

        if resolved_target == "claude-desktop":
            console.print("\nRestart Claude Desktop completely, then start a new chat.")
        elif resolved_target == "vscode":
            console.print(
                "\nReload VS Code or restart the MCP extension host, then open a new chat."
            )
        else:
            console.print("\nReload the target MCP client and verify tools appear.")

    finally:
        signal.signal(signal.SIGINT, original)


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
                ("Nulm ", "bold cyan"),
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


@app.command("agent-benchmark")
def agent_benchmark(
    save_path: Path | None = typer.Option(
        None,
        "--save",
        help="Optional path to write the emitted JSON payload",
    ),
    gates_only: bool = typer.Option(
        False,
        "--gates-only",
        help="Print only release gate JSON instead of benchmark plus gate JSON",
    ),
) -> None:
    """Run deterministic local agent benchmark release gates."""
    run_agent_benchmark, evaluate_agent_benchmark_gates = _agent_benchmark_runtime()
    benchmark_run = run_agent_benchmark()
    gate_result = evaluate_agent_benchmark_gates(benchmark_run)
    payload: dict[str, Any] = (
        gate_result.to_dict()
        if gates_only
        else {
            "schema_version": "agent_benchmark_cli.v1",
            "ok": gate_result.ok,
            "benchmark": benchmark_run.to_dict(),
            "gates": gate_result.to_dict(),
        }
    )

    if save_path is not None:
        save_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    console.print_json(data=payload)
    if not gate_result.ok:
        raise typer.Exit(code=1)


@app.command("worktree")
def worktree_cmd(
    project_dir: Path = typer.Option(Path.cwd(), help="Project directory"),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable output"),
) -> None:
    """Show git worktree status for parallel development awareness."""
    from claude_bridge._worktree import worktree_status

    status = worktree_status(project_dir.resolve())
    if json_output:
        console.print_json(data=status)
        return

    console.print(
        Panel.fit(
            "[bold cyan]Git Worktree Status[/bold cyan]",
            title="Worktree",
            border_style="cyan",
        )
    )

    if status["is_worktree"]:
        console.print(
            f"[yellow]You are in a worktree[/yellow] "
            f"— branch: [cyan]{status['current_branch']}[/cyan]"
        )
    else:
        console.print("You are in the main repository")

    if status["has_dirty_context"]:
        console.print("[yellow]Warning:[/yellow] Other worktrees have uncommitted changes")

    if status["worktrees"]:
        console.print(f"\n[bold]Worktrees ({len(status['worktrees'])}):[/bold]")
        for wt in status["worktrees"]:
            path = wt.get("path", "unknown")
            branch = wt.get("branch", "detached" if wt.get("detached") else "unknown")
            console.print(f"  - {path} ([cyan]{branch}[/cyan])")


@app.command("sessions")
def sessions_cmd(
    list_all: bool = typer.Option(False, "--list", "-l", help="List all saved sessions"),
    show: str | None = typer.Option(None, "--show", help="Show session by ID"),
    delete: str | None = typer.Option(None, "--delete", help="Delete session by ID"),
    resume: str | None = typer.Option(None, "--resume", help="Resume session by ID"),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable output"),
) -> None:
    """Manage workflow sessions for long-running workflows."""
    from claude_bridge._session_resume import (
        delete_workflow_session,
        list_workflow_sessions,
        load_workflow_session,
        session_summary,
    )

    if delete:
        if delete_workflow_session(delete):
            console.print(f"[green]Deleted session:[/green] {delete}")
        else:
            console.print(f"[red]Session not found:[/red] {delete}")
        return

    if show:
        session = load_workflow_session(show)
        if not session:
            console.print(f"[red]Session not found:[/red] {show}")
            raise typer.Exit(code=1)
        if json_output:
            console.print_json(data=session)
        else:
            console.print(
                Panel.fit(
                    f"[bold cyan]Session:[/bold cyan] {show}",
                    title="Session",
                    border_style="cyan",
                )
            )
            console.print(f"State: [cyan]{session.get('state', 'unknown')}[/cyan]")
            console.print(f"Task: {session.get('task', 'unknown')}")
            console.print(f"Step: {session.get('current_step', 0)}/{len(session.get('steps', []))}")
            console.print(f"Steps: {len(session.get('steps', []))}")
        return

    if resume:
        session = load_workflow_session(resume)
        if not session:
            console.print(f"[red]Session not found:[/red] {resume}")
            raise typer.Exit(code=1)
        if json_output:
            console.print_json(data=session)
        else:
            console.print(
                Panel.fit(
                    f"[bold green]Resuming session:[/bold green] {resume}",
                    title="Resume",
                    border_style="green",
                )
            )
        console.print(f"Task: {session.get('task', 'unknown')}")
        console.print(
            f"Current step: {session.get('current_step', 0)}/{len(session.get('steps', []))}"
        )
        console.print("[dim]Use this session data to restore workflow state[/dim]")
        return

    sessions = list_workflow_sessions()
    if not sessions:
        console.print("[yellow]No saved sessions[/yellow]")
        return

    if json_output:
        console.print_json(data={"sessions": sessions})
        return

    console.print(
        Panel.fit(
            f"[bold cyan]Workflow Sessions ({len(sessions)})[/bold cyan]",
            title="Sessions",
            border_style="cyan",
        )
    )
    for sess in sessions:
        console.print(f"  {session_summary(sess)}")


@app.command("schedule")
def schedule_cmd(
    name: str | None = typer.Argument(None, help="Schedule name"),
    cron_expr: str | None = typer.Option(
        None, "--cron", help="Cron expression (min hour day month weekday)"
    ),
    project_dir: Path = typer.Option(Path.cwd(), help="Project directory"),
    query: str | None = typer.Option(None, "--query", help="Benchmark query"),
    path: str = typer.Option(".", "--path", help="Subdirectory to benchmark"),
    limit: int = typer.Option(5, "--limit", help="Number of results"),
    repeats: int = typer.Option(3, "--repeats", help="Number of repeats"),
    baseline_file: Path | None = typer.Option(
        None, "--baseline", help="Baseline file for regression"
    ),
    list_schedules: bool = typer.Option(False, "-l", "--list", help="List all schedules"),
    delete_sched: str | None = typer.Option(None, "--delete", help="Delete a schedule"),
    run_now: str | None = typer.Option(None, "--run", help="Run a schedule now"),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable output"),
) -> None:
    """Manage recurring benchmark schedules."""
    from claude_bridge._benchmark_cron import (
        delete_benchmark_schedule,
        list_benchmark_schedules,
        load_benchmark_schedule,
        run_scheduled_benchmark,
        save_benchmark_schedule,
    )

    if delete_sched:
        if delete_benchmark_schedule(delete_sched):
            console.print(f"[green]Deleted schedule:[/green] {delete_sched}")
        else:
            console.print(f"[red]Schedule not found:[/red] {delete_sched}")
        return

    if run_now:
        sched = load_benchmark_schedule(run_now)
        if not sched:
            console.print(f"[red]Schedule not found:[/red] {run_now}")
            raise typer.Exit(code=1)
        result = run_scheduled_benchmark(sched)
        if json_output:
            console.print_json(data=result)
        else:
            if "error" in result:
                console.print(f"[red]Error:[/red] {result['error']}")
            else:
                console.print(f"[green]Ran schedule:[/green] {run_now}")
                console.print(f"Query timing: avg {result.get('query_avg_duration_ms', 'N/A')} ms")
        return

    if list_schedules:
        schedules = list_benchmark_schedules()
        if not schedules:
            console.print("[yellow]No schedules defined[/yellow]")
            return
        if json_output:
            console.print_json(data={"schedules": schedules})
        else:
            console.print(
                Panel.fit(
                    f"[bold cyan]Schedules ({len(schedules)})[/bold cyan]",
                    title="Schedules",
                    border_style="cyan",
                )
            )
            for s in schedules:
                cron = s.get("cron", {})
                cron_str = (
                    f"{cron.get('minute','*')} {cron.get('hour','*')} "
                    f"{cron.get('day','*')} {cron.get('month','*')} "
                    f"{cron.get('weekday','*')}"
                )
                console.print(f"  [cyan]{s['name']}[/cyan] — {cron_str}")
                console.print(f"    Query: {s.get('query', 'N/A')[:60]}")
                console.print(f"    Last run: {s.get('last_run', 'never')}")
        return

    if name is None:
        console.print("[red]NAME is required when creating a schedule[/red]")
        raise typer.Exit(code=1)
    if cron_expr is None or query is None:
        console.print("[red]--cron and --query are required when creating a schedule[/red]")
        raise typer.Exit(code=1)

    try:
        schedule_file = save_benchmark_schedule(
            name=name,
            cron_expr=cron_expr,
            project_dir=project_dir.resolve(),
            query=query,
            path=path,
            limit=limit,
            repeats=repeats,
            baseline_file=baseline_file,
        )
    except ValueError as exc:
        console.print(f"[red]Invalid cron expression:[/red] {exc}")
        raise typer.Exit(code=1)

    console.print(f"[green]Saved schedule:[/green] {name}")
    console.print(f"  Cron: {cron_expr}")
    console.print(f"  Query: {query}")
    console.print(f"  File: {schedule_file}")


@app.command("audit-ci")
def audit_ci_cmd(
    path: Path = typer.Option(Path.cwd(), help="Project directory to audit"),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable output"),
) -> None:
    """Run a one-shot CI audit (shell safety, guard policy, imports, syntax, security patterns)."""
    from claude_bridge._ci_audit import print_audit_report, run_quick_audit

    report = run_quick_audit(path.resolve())
    if json_output:
        console.print_json(data=report)
        return
    print_audit_report(report)
    if not report["ok"]:
        raise typer.Exit(code=1)


@app.command("envdoctor")
def envdoctor_cmd(
    project_dir: Path = typer.Option(Path.cwd(), help="Project directory"),
    json_output: bool = typer.Option(False, "--json", help="Machine-readable output"),
) -> None:
    """Run parallel environment checks for .opencode/ and .claude-bridge/ directories."""
    from claude_bridge._parallel_doctor import (
        check_environment_consistency,
        print_parallel_doctor_report,
    )

    report = check_environment_consistency(project_dir.resolve())
    if json_output:
        console.print_json(data=report)
        return
    print_parallel_doctor_report(report)
    if not report["overall_ok"]:
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
    """Show the most recent Nulm audit session summary."""
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
    agent_runs = summary.get("agent_runs", {})
    if isinstance(agent_runs, dict) and int(agent_runs.get("run_count", 0) or 0) > 0:
        console.print("\nAgent runs:")
        console.print(f"  Runs: {agent_runs.get('run_count', 0)}")
        status_counts = agent_runs.get("status_counts", {})
        if isinstance(status_counts, dict) and status_counts:
            status_text = ", ".join(
                f"{escape(str(status))}={count}" for status, count in sorted(status_counts.items())
            )
            console.print(f"  Status: {status_text}")
        agent_names = agent_runs.get("agent_names", [])
        if isinstance(agent_names, list) and agent_names:
            agents_text = ", ".join(escape(str(name)) for name in agent_names[:8])
            console.print(f"  Agents: {agents_text}")
        failures = agent_runs.get("failures", [])
        if isinstance(failures, list) and failures:
            console.print("  Failures:")
            for failure in failures[:5]:
                if not isinstance(failure, dict):
                    continue
                agent_name = escape(str(failure.get("agent_name", "unknown")))
                task_id = escape(str(failure.get("task_id", "")))
                error_class = escape(str(failure.get("error_class", "AgentFailure")))
                console.print(f"    [{agent_name}] {task_id}: {error_class}")
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
                f"[green]Exported {len(records) if records else 'summary'} "
                f"records to {output}[/green]"
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
            Text.assemble(("Nulm ", "bold cyan"), ("doctor", "green")),
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
        if not check.ok and check.fix_suggestion:
            console.print(f"  [yellow]Fix:[/yellow] {check.fix_suggestion}")

    if report.quick_fixes:
        console.print()
        console.print("[bold]Quick fixes:[/bold]")
        for fix in report.quick_fixes:
            console.print(f"  - {fix}")


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
            Text.assemble(("Nulm ", "bold cyan"), ("doctor security", "green")),
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
        if not check.ok and check.fix_suggestion:
            console.print(f"  [yellow]Fix:[/yellow] {check.fix_suggestion}")

    if report.quick_fixes:
        console.print()
        console.print("[bold]Quick fixes:[/bold]")
        for fix in report.quick_fixes:
            console.print(f"  - {fix}")


@scan_app.command("scan")
def scan_cmd(
    path: Path = typer.Option(Path.cwd(), "--path", "-p", help="Directory to scan"),
    output: str = typer.Option("text", "--output", "-o", help="Output format: text|json|yaml"),
) -> None:
    """Run a security scan on tools, skills, and config."""
    from claude_bridge.scanner import generate_scan_report, scan_all

    result = scan_all(path.resolve())
    report = generate_scan_report(result, format=output)
    if output == "json":
        console.print(report)
    else:
        console.print(Panel.fit(report, title="Security Scan", border_style="cyan"))


def main() -> None:
    app()
