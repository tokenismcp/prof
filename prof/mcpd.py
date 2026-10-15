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
from typing import Any, Dict

from prof.demo_tools import build_demo_gateway, crm_lookup, file_write, payment_transfer
from prof.gateway import ExecuteRequest
from prof.permit import Permit, hash_args

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "prof", "version": "0.1.0"}


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
            "description": "Look up a customer (low-risk). Requires permit.",
            "inputSchema": {
                "type": "object", "required": ["customer", "permit"],
                "properties": {"customer": {"type": "string"}, "permit": permit_schema},
            },
        },
        {
            "name": "file.write",
            "description": "Write a file inside the sandbox (/tmp). Requires permit.",
            "inputSchema": {
                "type": "object", "required": ["path", "content", "permit"],
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}, "permit": permit_schema},
            },
        },
        {
            "name": "payment.transfer",
            "description": "Transfer funds (HIGH-RISK: human approval tier). Requires permit.",
            "inputSchema": {
                "type": "object", "required": ["to", "amount", "idempotency_key", "permit"],
                "properties": {
                    "to": {"type": "string"}, "amount": {"type": "number"},
                    "idempotency_key": {"type": "string"}, "permit": permit_schema,
                },
            },
        },
    ]


class MCPServer:
    def __init__(self) -> None:
        self.approver, self.gw = build_demo_gateway()
        self._effects = {
            "crm.lookup": ("tool.call", "tool:crm.lookup", crm_lookup),
            "file.write": ("file.write", "file:/tmp/**", file_write),
            "payment.transfer": ("payment.transfer", "account:krw-1", payment_transfer),
        }

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
        if name not in self._effects:
            return self._text({"ok": False, "error": f"unknown tool: {name}"}, True)
        action, resource, fn = self._effects[name]
        raw_permit = args.get("permit")
        if not isinstance(raw_permit, dict):
            return self._text({"ok": False,
                               "error": "missing permit: call prof.approve first and pass its result as 'permit'"}, True)
        call_args = {k: v for k, v in args.items() if k != "permit"}
        try:
            permit = Permit.from_dict(raw_permit)
        except Exception as exc:
            return self._text({"ok": False, "error": f"bad permit: {exc}"}, True)
        dec, result = self.gw.execute(ExecuteRequest(action, resource, call_args, permit), fn)
        if not dec.allow:
            return self._text({"ok": False, "decision": dec.reason}, True)
        return self._text({"ok": True, "decision": dec.reason, "result": result, "ledger_seq": dec.ledger_seq})

    def _approve(self, args: Dict[str, Any]) -> Dict[str, Any]:
        agent = str(args.get("agent", "agent:mcp"))
        action = str(args.get("action", ""))
        resource = str(args.get("resource", ""))
        call_args = args.get("args", {})
        ttl = int(args.get("ttl_s", 300))
        if not isinstance(call_args, dict):
            return {"ok": False, "error": "args must be an object"}
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
