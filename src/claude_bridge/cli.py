"""Command-line interface for Claude Bridge."""

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from claude_bridge.server import BridgeServer
from claude_bridge.prompt import SYSTEM_PROMPT, BOOKMARKLET_CODE

app = typer.Typer(help="Claude Bridge — Local file and terminal access for Claude.ai")
console = Console()


@app.command()
def start(
    port: int = typer.Option(7337, help="Port to listen on"),
    host: str = typer.Option("127.0.0.1", help="Host to bind to"),
    project_dir: Path = typer.Option(
        Path.cwd(), help="Root directory the bridge is allowed to access"
    ),
    auto_approve: bool = typer.Option(
        False, help="Automatically approve all operations (not recommended)"
    ),
) -> None:
    """Start the local bridge server."""
    console.print(
        Panel.fit(
            Text.assemble(
                ("Claude Bridge ", "bold cyan"),
                ("v0.1.0", "dim"),
            ),
            title="Welcome",
            border_style="cyan",
        )
    )

    console.print(f"Project directory: [green]{project_dir.resolve()}[/green]")
    console.print(f"Server will listen on: [yellow]{host}:{port}[/yellow]")
    if auto_approve:
        console.print("[red bold]WARNING:[/red bold] Auto-approve is enabled!")

    console.print("\n[bold]Bookmarklet Code:[/bold]")
    console.print(
        Panel(
            BOOKMARKLET_CODE,
            title="Copy this into a browser bookmark",
            border_style="green",
        )
    )

    console.print("\n[bold]System Prompt:[/bold]")
    console.print(
        Panel(
            SYSTEM_PROMPT,
            title="Add to Claude.ai Project Instructions",
            border_style="blue",
        )
    )

    server = BridgeServer(
        host=host,
        port=port,
        project_dir=project_dir.resolve(),
        auto_approve=auto_approve,
    )
    try:
        server.run()
    except KeyboardInterrupt:
        console.print("\n[red]Shutting down...[/red]")
        sys.exit(0)


@app.command()
def version() -> None:
    """Show version information."""
    console.print("[bold cyan]Claude Bridge[/bold cyan] version [green]0.1.0[/green]")


def main() -> None:
    app()
