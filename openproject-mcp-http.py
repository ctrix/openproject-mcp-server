#!/usr/bin/env python3
"""
OpenProject MCP Server - HTTP Transport Entry Point

Runs the MCP server over HTTP with OAuth 2.1 authentication.
Requires OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, and MCP_BASE_URL
environment variables in addition to OPENPROJECT_URL.
"""

import os
import sys

import httpx

from src.server import mcp
from src.oauth import create_oauth_provider

if __name__ == "__main__":
    # Disable SSL verification for all httpx clients when configured.
    # This is needed because the OAuthProxy uses httpx internally for
    # token exchange with the upstream provider (OpenProject), which
    # may use a self-signed certificate.
    if os.getenv("OPENPROJECT_VERIFY_SSL", "true").lower() == "false":
        _original_init = httpx.AsyncClient.__init__

        def _no_verify_init(self, *args, **kwargs):
            kwargs.setdefault("verify", False)
            _original_init(self, *args, **kwargs)

        httpx.AsyncClient.__init__ = _no_verify_init

    # Validate required OAuth env vars
    missing = [
        v for v in ("OAUTH_CLIENT_ID", "OAUTH_CLIENT_SECRET", "MCP_BASE_URL")
        if not os.getenv(v)
    ]
    if missing:
        print(
            f"ERROR: Missing required environment variables for HTTP/OAuth mode: {', '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Wire OAuth provider into FastMCP
    mcp.auth = create_oauth_provider()

    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT", "8000"))

    print(f"Starting OpenProject MCP Server (HTTP + OAuth)")
    print(f"   Host: {host}")
    print(f"   Port: {port}")
    print(f"   OpenProject: {os.getenv('OPENPROJECT_URL')}")

    mcp.run(transport="http", host=host, port=port)
