import json
import os

os.environ.setdefault("PROF_DEMO", "1")

from fastapi.testclient import TestClient  # noqa: E402

from prof.server import app  # noqa: E402


def _client():
    return TestClient(app)


def test_mcp_http_handshake():
    c = _client()
    r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                             "params": {"protocolVersion": "2024-11-05"}})
    assert r.status_code == 200
    assert r.json()["result"]["serverInfo"]["name"] == "prof"
    r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list",
                             "params": {}})
    names = {t["name"] for t in r.json()["result"]["tools"]}
    assert {"prof.approve", "crm.lookup", "file.write", "payment.transfer"} <= names


def test_mcp_http_transparent_call_and_high_tier_guidance():
    c = _client()
    r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                             "params": {"name": "crm.lookup",
                                        "arguments": {"customer": "acme-42"}}})
    body = json.loads(r.json()["result"]["content"][0]["text"])
    assert body["ok"] is True and body["result"]["name"] == "Acme Corp"
    r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                             "params": {"name": "payment.transfer",
                                        "arguments": {"to": "x", "amount": 1,
                                                      "idempotency_key": "http-1"}}})
    assert r.json()["result"].get("isError") is True
    body = json.loads(r.json()["result"]["content"][0]["text"])
    assert "human approval" in body["error"]


def test_mcp_http_notifications_and_errors():
    c = _client()
    r = c.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert r.status_code == 202 and r.content == b""
    r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 9, "method": "nope"})
    assert r.json()["error"]["code"] == -32601
    assert c.get("/mcp").status_code == 405


def test_mcp_http_bearer_gating(monkeypatch):
    monkeypatch.setenv("PROF_API_TOKEN", "tok123")
    c = _client()
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    assert c.post("/mcp", json=msg).status_code == 401
    r = c.post("/mcp", json=msg, headers={"Authorization": "Bearer tok123"})
    assert r.status_code == 200 and "tools" in r.json()["result"]
