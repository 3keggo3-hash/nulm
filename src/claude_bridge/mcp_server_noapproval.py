"""MCP server without interactive approval — for Claude Desktop."""

from claude_bridge.server import configure_from_env, run_mcp_server

if __name__ == "__main__":
    configure_from_env(force_auto_approve=True)
    run_mcp_server()
