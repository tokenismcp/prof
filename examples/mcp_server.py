"""Native MCP stdio server example (requires `pip install 'prof[mcp]'`).

Exposes PROF-protected tools to MCP clients. Every tool call requires
a Permit issued via the Gateway (/v1/approve). The server verifies
server-side — the MCP client/agent is untrusted.
"""
# NOTE: kept dependency-optional so core stays light. Wire-up:
#   from mcp.server.fastmcp import FastMCP
# See docs/MCP.md for the full walkthrough.

TOOLS = ["crm.lookup", "file.write", "payment.transfer"]

if __name__ == "__main__":
    print("PROF MCP tools:", ", ".join(TOOLS))
    print("See docs/MCP.md — run: pip install 'prof[mcp]' then python examples/mcp_server.py")
