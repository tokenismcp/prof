"""PROF MCP stdio server — real launcher (dependency-free).

Exposes PROF-protected tools to any MCP client. Every tool call requires
a Permit issued via `prof.approve`; the server verifies server-side —
the MCP client/agent is untrusted.

Run:  python examples/mcp_server.py   (or: prof mcp / prof-mcp)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prof.mcpd import serve_stdio  # noqa: E402

if __name__ == "__main__":
    serve_stdio()
