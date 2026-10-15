import json
import subprocess
import sys

import pytest

from prof.mcpd import MCPServer


def rpc(srv, method, params=None, mid=1):
    msg = {"jsonrpc": "2.0", "id": mid, "method": method}
    if params is not None:
        msg["params"] = params
    return srv.handle(msg)


def test_initialize_and_list():
    srv = MCPServer()
    r = rpc(srv, "initialize", {"protocolVersion": "2024-11-05"})
    assert r["result"]["serverInfo"]["name"] == "prof"
    r = rpc(srv, "tools/list", {}, mid=2)
    names = {t["name"] for t in r["result"]["tools"]}
    assert {"prof.approve", "crm.lookup", "file.write", "payment.transfer"} <= names


def test_approve_then_call_allow():
    srv = MCPServer()
    r = rpc(srv, "tools/call", {"name": "prof.approve", "arguments": {
        "agent": "agent:mcp-test", "action": "tool.call",
        "resource": "tool:crm.lookup", "args": {"customer": "acme-42"}}}, mid=3)
    body = json.loads(r["result"]["content"][0]["text"])
    assert body["ok"] is True
    permit = body["permit"]
    r = rpc(srv, "tools/call", {"name": "crm.lookup",
                                "arguments": {"customer": "acme-42", "permit": permit}}, mid=4)
    body = json.loads(r["result"]["content"][0]["text"])
    assert body["ok"] is True and "acme-42" in str(body["result"])


def test_call_without_permit_fails():
    srv = MCPServer()
    r = rpc(srv, "tools/call", {"name": "crm.lookup", "arguments": {"customer": "x"}}, mid=5)
    assert r["result"].get("isError") is True


def test_tampered_args_denied():
    srv = MCPServer()
    r = rpc(srv, "tools/call", {"name": "prof.approve", "arguments": {
        "agent": "agent:mcp-test", "action": "tool.call",
        "resource": "tool:crm.lookup", "args": {"customer": "acme-42"}}}, mid=6)
    permit = json.loads(r["result"]["content"][0]["text"])["permit"]
    r = rpc(srv, "tools/call", {"name": "crm.lookup",
                                "arguments": {"customer": "evil", "permit": permit}}, mid=7)
    assert r["result"].get("isError") is True


def test_unknown_method():
    srv = MCPServer()
    r = rpc(srv, "nope/method", {}, mid=8)
    assert r["error"]["code"] == -32601


def test_stdio_end_to_end():
    payload = (
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n'
        '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}\n'
    )
    p = subprocess.run([sys.executable, "-m", "prof", "mcp"], input=payload,
                       capture_output=True, text=True, timeout=30)
    lines = [json.loads(x) for x in p.stdout.strip().splitlines()]
    assert lines[0]["result"]["serverInfo"]["name"] == "prof"
    assert any(t["name"] == "prof.approve" for t in lines[1]["result"]["tools"])
