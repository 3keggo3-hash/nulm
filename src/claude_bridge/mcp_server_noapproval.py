"""MCP server without interactive approval — for Claude Desktop."""

import sys

from claude_bridge.server import configure_from_env, run_mcp_server

if __name__ == "__main__":
    print(
        "[WARNING] Running with force_auto_approve=True. All operations are auto-approved.",
        file=sys.stderr,
    )
    configure_from_env(force_auto_approve=True)
    run_mcp_server()
