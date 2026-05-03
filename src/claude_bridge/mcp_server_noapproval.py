"""MCP server without interactive approval — for Claude Desktop."""

import logging
import os
import sys

from claude_bridge.server import configure_from_env, run_mcp_server

if __name__ == "__main__":
    if os.environ.get("CLAUDE_BRIDGE_UNSAFE_NOAPPROVAL_CONFIRMED") != "1":
        print(
            "HATA: CLAUDE_BRIDGE_UNSAFE_NOAPPROVAL_CONFIRMED=1 ayarlanmamis.",
            file=sys.stderr,
        )
        sys.exit(1)

    logging.warning(
        "force_auto_approve=True — tüm güvenlik kontrolleri devre dışı. "
        "Sadece test ortamında kullan."
    )

    configure_from_env(force_auto_approve=True)
    run_mcp_server()
