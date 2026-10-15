"""PROF remote MCP endpoint — Streamable HTTP transport.

Dots (OpenAI) and Muse (Meta) both run in vendor clouds: they cannot reach
localhost or spawn stdio servers. They require a PUBLIC HTTPS endpoint
speaking MCP Streamable HTTP. This module mounts one on the gateway:

  POST /mcp   JSON-RPC request (or notification) -> JSON-RPC response
              (202 with empty body for notifications)

Stateless (no Mcp-Session-Id): each request carries everything the Gateway
needs (permit or auto-approvable args). Auth: Bearer PROF_API_TOKEN when
configured — paste it as a static key (Muse secure prompt, Dots custom
connector key field). The same core (MCPServer.handle) serves stdio and
HTTP, so behavior is identical on both transports.

Deploy publicly: PROF_DOMAIN=... docker compose --profile edge up
(Caddy terminates TLS). Then register the URL https://<domain>/mcp.
"""

from __future__ import annotations

import os
from typing import Any, Dict

_mcp_server = None


def get_server():
    global _mcp_server
    if _mcp_server is None:
        from prof.mcpd import MCPServer
        _mcp_server = MCPServer()
    return _mcp_server


def handle_http(msg: Dict[str, Any]) -> tuple[int, Any]:
    """Process one JSON-RPC message. Returns (http_status, json_body_or_None)."""
    resp = get_server().handle(msg)
    if resp is None:
        return 202, None  # notification acknowledged
    return 200, resp


def check_bearer(authorization: str) -> bool:
    import hmac
    want = os.environ.get("PROF_API_TOKEN", "")
    if not want:
        return True
    if not authorization.lower().startswith("bearer "):
        return False
    return hmac.compare_digest(authorization[7:].strip(), want)
