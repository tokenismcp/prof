"""MCP adapter: wrap any tool function with PROF enforcement.

Usage:
    adapter = ProfMCP(approver_pubkey, policy, gateway_factory...)
    adapter.register("crm.lookup", my_fn, resource="tool:crm.lookup")

The adapter requires a valid Permit for every call. It does NOT trust
the agent: permits are verified server-side in the Gateway.

For the wire protocol, use the dependency-free stdio server in
`prof/mcpd.py` (`prof mcp` / `prof-mcp`). This module stays import-light
for embedding PROF enforcement inside your own Python tools.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

from prof.gateway import ExecuteRequest, Gateway
from prof.permit import Permit


class ProfMCP:
    def __init__(self, gateway: Gateway):
        self.gateway = gateway
        self._tools: Dict[str, dict] = {}

    def register(self, name: str, fn: Callable[[Dict[str, Any]], Any], resource: str, action: str = "tool.call") -> None:
        self._tools[name] = {"fn": fn, "resource": resource, "action": action}

    @property
    def tool_names(self):
        return sorted(self._tools.keys())

    def call(self, name: str, args: Dict[str, Any], permit: Permit) -> Dict[str, Any]:
        if name not in self._tools:
            return {"ok": False, "error": f"unknown tool {name}"}
        t = self._tools[name]
        req = ExecuteRequest(action=t["action"], resource=t["resource"], args=args, permit=permit)
        dec, result = self.gateway.execute(req, lambda a: {"result": t["fn"](a)})
        if not dec.allow:
            return {"ok": False, "error": dec.reason}
        return {"ok": True, "result": result["result"] if isinstance(result, dict) else result, "ledger_seq": dec.ledger_seq}


def serve() -> None:
    """Entry point `prof-mcp` — runs the example MCP bridge (HTTP)."""
    import uvicorn
    from prof.server import app as _app  # noqa
    print("prof-mcp: MCP bridge runs through the PROF Gateway at http://127.0.0.1:8091")
    print("For the MCP stdio server, use `prof mcp` (prof/mcpd.py).")
    uvicorn.run(_app, host="127.0.0.1", port=8091)
