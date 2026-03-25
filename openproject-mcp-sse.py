#!/usr/bin/env python3
"""
OpenProject MCP Server - SSE Transport Entry Point

This is the entry point for SSE transport (FastMCP Cloud).
FastMCP-based implementation with automatic tool registration.
"""

import os
from src.server import mcp

if __name__ == "__main__":
    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT", "8000"))

    # Run with SSE transport (for FastMCP Cloud deployment)
    mcp.run(transport="sse", host=host, port=port)
