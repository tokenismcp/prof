"""PROF MCP server — dependency-free JSON-RPC 2.0 over stdio.

Speaks the MCP stdio transport (newline-delimited JSON-RPC) with
`initialize`, `tools/list`, `tools/call` and `ping`, so any MCP-capable
agent (Claude Code, Codex CLI, Gemini CLI, Cursor, OpenCode, …) can use
PROF-protected tools with zero extra dependencies.

Flow for agents:
  1. call `prof.approve`  -> receive a signed Permit (JSON)
  2. call a protected tool with `{..., "permit": <Permit>}`

The Gateway verifies every call server-side. Tampered args, replays and
expired permits are denied and logged to the ledger.

Run:  python -m prof mcp   (or: prof-mcp)
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from typing import Any, Dict, Optional

from prof.demo_tools import build_demo_gateway
from prof.resources import crm_lookup, file_write, payment_transfer
from prof.gateway import ExecuteRequest
from prof.permit import Permit, hash_args

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "prof", "version": "1.0.0"}


def _tool_defs() -> list:
    permit_schema: Dict[str, Any] = {"type": "object", "description": "Permit JSON from prof.approve"}
    return [
        {
            "name": "prof.approve",
            "description": "Issue a signed PROF Permit for one action/resource/args. Call this first, then pass the permit to the protected tool.",
            "inputSchema": {
                "type": "object",
                "required": ["agent", "action", "resource", "args"],
                "properties": {
                    "agent": {"type": "string"},
                    "action": {"type": "string"},
                    "resource": {"type": "string"},
                    "args": {"type": "object"},
                    "ttl_s": {"type": "integer", "default": 300},
                },
            },
        },
        {
            "name": "crm.lookup",
            "description": "Look up a customer (low-risk, auto-approved). Optional permit for pre-approved calls.",
            "inputSchema": {
                "type": "object", "required": ["customer"],
                "properties": {"customer": {"type": "string"}, "permit": permit_schema},
            },
        },
        {
            "name": "file.write",
            "description": "Write a file inside the sandbox. Auto-approved in /tmp; elsewhere needs a human-signed permit.",
            "inputSchema": {
                "type": "object", "required": ["path", "content"],
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}, "permit": permit_schema},
            },
        },
        {
            "name": "payment.transfer",
            "description": "Transfer funds (HIGH-RISK). Needs a human-signed permit: open a request first (POST /v1/requests or console Approvals).",
            "inputSchema": {
                "type": "object", "required": ["to", "amount", "idempotency_key"],
                "properties": {
                    "to": {"type": "string"}, "amount": {"type": "number"},
                    "idempotency_key": {"type": "string"}, "permit": permit_schema,
                },
            },
        },
    ]


_TOOL_BINDING = {
    "crm.lookup": ("tool.call", "tool:crm.lookup"),
    "file.write": ("file.write", "file:/tmp/**"),
    "payment.transfer": ("payment.transfer", "account:krw-1"),
}

_TOOL_FNS = {
    "crm.lookup": crm_lookup,
    "file.write": file_write,
    "payment.transfer": payment_transfer,
}


class MCPServer:
    """Local mode (default): private in-process gateway + ephemeral approver.

    Remote mode (PROF_GATEWAY_URL set): approve/execute are delegated to the
    shared HTTP gateway, so MCP traffic lands in the same ledger, policy and
    nonce store as the console, CLI and LLM loop. One gateway, many frontends.
    """

    def __init__(self, gateway_url: str = "") -> None:
        import os as _os
        self.remote = None
        self.gateway_url = gateway_url or _os.environ.get("PROF_GATEWAY_URL", "")
        if self.gateway_url:
            from prof.client import GatewayClient
            self.remote = GatewayClient(self.gateway_url)
            self.approver, self.gw = None, None
        else:
            self.approver, self.gw = build_demo_gateway()
        self._effects = {name: _TOOL_FNS[name] for name in _TOOL_BINDING}

    # ---- handlers ----
    def handle(self, msg: Dict[str, Any]) -> Dict[str, Any] | None:
        mid = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params", {}) or {}

        def ok(result: Any) -> Dict[str, Any]:
            return {"jsonrpc": "2.0", "id": mid, "result": result}

        def err(code: int, message: str) -> Dict[str, Any]:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}

        try:
            if method == "initialize":
                return ok({"protocolVersion": PROTOCOL_VERSION,
                           "capabilities": {"tools": {}},
                           "serverInfo": SERVER_INFO})
            if method in ("notifications/initialized", "notifications/cancelled"):
                return None
            if method == "ping":
                return ok({})
            if method == "tools/list":
                return ok({"tools": _tool_defs()})
            if method == "tools/call":
                return ok(self._call(params.get("name", ""), params.get("arguments", {}) or {}))
            return err(-32601, f"unknown method: {method}")
        except Exception as exc:  # fail-closed, never crash the loop
            traceback.print_exc(file=sys.stderr)
            return err(-32603, f"internal error: {exc}")

    def _text(self, obj: Any, is_error: bool = False) -> Dict[str, Any]:
        d: Dict[str, Any] = {"content": [{"type": "text", "text": json.dumps(obj, indent=2, ensure_ascii=False)}]}
        if is_error:
            d["isError"] = True
        return d

    def _call(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if name == "prof.approve":
            return self._text(self._approve(args))
        if name not in _TOOL_BINDING:
            return self._text({"ok": False, "error": f"unknown tool: {name}"}, True)
        action, resource = _TOOL_BINDING[name]
        raw_permit = args.get("permit")
        call_args = {k: v for k, v in args.items() if k != "permit"}
        permit: Optional[Dict[str, Any]] = raw_permit if isinstance(raw_permit, dict) else None
        if permit is None:
            # Transparent mode: no permit round-trip for low/medium tiers.
            # The server mints the permit itself; high-tier still needs a human.
            auto = self._auto_permit(name, action, resource, call_args)
            if auto is None:
                return self._text({
                    "ok": False,
                    "error": f"high-tier {name}: human approval required. "
                             "Call prof.approve is not enough — open a request "
                             "(POST /v1/requests or console Approvals) and retry "
                             "with the signed permit as 'permit'."}, True)
            permit = auto
        if self.remote is not None:
            try:
                out = self.remote.execute(action, resource, call_args, permit)
            except Exception as exc:
                return self._text({"ok": False, "decision": str(exc)}, True)
            if not out.get("ok"):
                return self._text({"ok": False, "decision": out.get("decision", "denied")}, True)
            return self._text(out)
        try:
            permit_obj = Permit.from_dict(permit)
        except Exception as exc:
            return self._text({"ok": False, "error": f"bad permit: {exc}"}, True)
        fn = self._effects[name]
        dec, result = self.gw.execute(ExecuteRequest(action, resource, call_args, permit_obj), fn)
        if not dec.allow:
            return self._text({"ok": False, "decision": dec.reason}, True)
        return self._text({"ok": True, "decision": dec.reason, "result": result, "ledger_seq": dec.ledger_seq})

    def _auto_permit(self, name: str, action: str, resource: str,
                     call_args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Mint a server-side permit for non-human tiers. None => human needed."""
        agent = str(call_args.get("_agent", "agent:mcp"))
        if self.remote is not None:
            try:
                return self.remote.auto_approve(agent, action, resource, call_args)
            except Exception:
                return None
        pol = self.gw.policy.evaluate(action, resource, call_args)
        if not pol.allow or pol.require_human:
            return None
        p = Permit(subject=self.approver.subject, agent=agent, action=action,
                   resource=resource, args_hash=hash_args(call_args),
                   policy_id=self.gw.policy.policy_id,
                   expiry=int(time.time()) + 300,
                   constraints={"auto": True})
        p.sign(self.approver._sk)
        self.gw.ledger.append("approve", p.nonce, p.action, p.resource,
                              p.subject, p.agent, f"tier={pol.tier} auto via-mcp")
        return p.to_dict()

    def _approve(self, args: Dict[str, Any]) -> Dict[str, Any]:
        agent = str(args.get("agent", "agent:mcp"))
        action = str(args.get("action", ""))
        resource = str(args.get("resource", ""))
        call_args = args.get("args", {})
        ttl = int(args.get("ttl_s", 300))
        if not isinstance(call_args, dict):
            return {"ok": False, "error": "args must be an object"}
        if self.remote is not None:
            try:
                permit = self.remote.approve(agent, action, resource, call_args, ttl)
            except Exception as exc:
                return {"ok": False, "error": str(exc)}
            return {"ok": True, "permit": permit}
        pol = self.gw.policy.evaluate(action, resource, call_args)
        if not pol.allow:
            return {"ok": False, "error": f"policy deny: {pol.reason}"}
        p = Permit(subject=self.approver.subject, agent=agent, action=action, resource=resource,
                   args_hash=hash_args(call_args), policy_id=self.gw.policy.policy_id,
                   expiry=int(time.time()) + ttl)
        p.sign(self.approver._sk)
        self.gw.ledger.append("approve", p.nonce, p.action, p.resource, p.subject, p.agent, f"tier={pol.tier} via-mcp")
        return {"ok": True, "permit": p.to_dict(), "tier": pol.tier}


def serve_stdio() -> None:
    srv = MCPServer()
    out = sys.stdout
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            out.write(json.dumps({"jsonrpc": "2.0", "id": None,
                                  "error": {"code": -32700, "message": "parse error"}}) + "\n")
            out.flush()
            continue
        resp = srv.handle(msg)
        if resp is not None:
            out.write(json.dumps(resp, ensure_ascii=False) + "\n")
            out.flush()


if __name__ == "__main__":
    serve_stdio()
