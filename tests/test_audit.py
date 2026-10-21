"""Regression tests for the pre-release security audit (v1.0.1).

Each test pins one finding so it cannot silently return.
"""
import json
import os

os.environ.setdefault("PROF_DEMO", "1")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from prof.identity import Approver  # noqa: E402
from prof.ledger import Ledger  # noqa: E402
from prof.permit import Permit, hash_args  # noqa: E402
from prof.policy import DEFAULT_POLICY  # noqa: E402
from prof.server import app  # noqa: E402
from prof.store import NonceStore  # noqa: E402


def _client():
    return TestClient(app)


# ---- A1: an agent must not mint its own high-tier permit ----
def test_api_approve_refuses_high_tier_by_default():
    r = _client().post("/v1/approve", json={
        "agent": "agent:x", "action": "payment.transfer", "resource": "account:krw-1",
        "args": {"to": "evil", "amount": 5, "idempotency_key": "a1"}})
    assert r.status_code == 403
    assert "human" in r.text


def test_mcp_prof_approve_refuses_high_tier():
    from prof.mcpd import MCPServer
    srv = MCPServer()
    r = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "prof.approve", "arguments": {
            "agent": "agent:x", "action": "payment.transfer", "resource": "account:krw-1",
            "args": {"to": "evil", "amount": 5, "idempotency_key": "a2"}}}})
    body = json.loads(r["result"]["content"][0]["text"])
    assert body["ok"] is False and "human" in body["error"]


def test_approve_ttl_is_capped(monkeypatch):
    monkeypatch.setenv("PROF_MAX_TTL_S", "600")
    r = _client().post("/v1/approve", json={
        "agent": "a", "action": "tool.call", "resource": "tool:crm.lookup",
        "args": {"customer": "acme-42"}, "ttl_s": 10**9})
    assert r.status_code == 200
    import time
    assert r.json()["expiry"] <= int(time.time()) + 601


# ---- A2: HTTP /mcp must use the server's own approver, ledger and nonces ----
def test_http_mcp_shares_server_ledger():
    c = _client()
    before = c.get("/v1/ledger?limit=1").json()["total"]
    c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "crm.lookup", "arguments": {"customer": "acme-42", "_agent": "agent:audit-a2"}}})
    led = c.get("/v1/ledger?limit=20").json()
    assert led["total"] > before
    assert any(e["agent"] == "agent:audit-a2" for e in led["entries"])


# ---- A3: policy amount cap cannot be bypassed ----
@pytest.mark.parametrize("amount", ["nan", float("nan"), -5, "-1", None, "abc"])
def test_policy_rejects_bad_amounts(amount):
    d = DEFAULT_POLICY.evaluate("payment.transfer", "account:krw-1", {"amount": amount})
    assert d.allow is False


def test_policy_requires_amount_when_rule_has_cap():
    d = DEFAULT_POLICY.evaluate("payment.transfer", "account:krw-1", {"to": "x"})
    assert d.allow is False


def test_policy_denies_path_traversal_resource():
    d = DEFAULT_POLICY.evaluate("file.write", "file:/tmp/../etc/passwd", {})
    assert d.allow is False
    d = DEFAULT_POLICY.evaluate("file.write", "file:/tmp/ok/a.txt", {})
    assert d.allow is True


# ---- A4: nonce must stay reserved through the permit's last valid second ----
def test_nonce_not_pruned_at_exact_expiry():
    s = NonceStore()
    assert s.check_and_reserve("n1", now=1000, expiry=1100)
    s.prune(now=1100)               # permit is still valid at now == expiry
    assert s.is_seen("n1")
    s.prune(now=1101)
    assert not s.is_seen("n1")


# ---- A5: torn final append must not brick restart; interior corruption must ----
def test_ledger_and_nonce_tolerate_torn_tail(tmp_path):
    lp, np_ = tmp_path / "l.jsonl", tmp_path / "n.jsonl"
    led = Ledger(str(lp))
    led.append("allow", "n", "a", "r", "s", "g")
    led.append("allow", "n2", "a", "r", "s", "g")
    with open(lp, "a") as f:
        f.write('{"seq": 2, "ts"')            # crash mid-write
    led2 = Ledger(str(lp))
    assert len(led2.entries) == 2 and led2.verify_chain()[0]

    ns = NonceStore(str(np_))
    ns.check_and_reserve("a", 1, 10**10)
    with open(np_, "a") as f:
        f.write('{"nonce": "b", "exp')
    assert NonceStore(str(np_)).is_seen("a")


def test_ledger_interior_corruption_fails_closed(tmp_path):
    lp = tmp_path / "l.jsonl"
    led = Ledger(str(lp))
    for i in range(3):
        led.append("allow", f"n{i}", "a", "r", "s", "g")
    lines = lp.read_text().splitlines()
    lines[1] = lines[1][:20]
    lp.write_text("\n".join(lines) + "\n")
    with pytest.raises(Exception):
        Ledger(str(lp))


# ---- A6: sandbox cannot be escaped through a symlink ----
def test_file_write_blocks_symlink_escape(tmp_path, monkeypatch):
    from prof.resources import ResourceDB
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside)
    monkeypatch.setenv("PROF_DATA_ROOT", str(root))
    db = ResourceDB()
    with pytest.raises(PermissionError):
        db.write_file(str(root / "link" / "pwn.txt"), "x")
    assert not (outside / "pwn.txt").exists()
    assert db.write_file(str(root / "ok.txt"), "x")["bytes"] == 1


# ---- A7: LLM key never reaches a caller-chosen endpoint ----
def test_models_preview_with_custom_base_url_needs_token_and_drops_key(monkeypatch):
    monkeypatch.setenv("PROF_API_TOKEN", "tok")
    monkeypatch.setenv("PROF_LLM_API_KEY", "sk-secret")
    c = _client()
    assert c.get("/v1/llm/models?provider=openai&base_url=http://127.0.0.1:9/v1").status_code == 401
    seen = {}

    def fake_list(cfg):
        seen["key"] = cfg.api_key
        return []
    monkeypatch.setattr("prof.llm.list_models", fake_list)
    c.get("/v1/llm/models?provider=openai&base_url=http://127.0.0.1:9/v1",
          headers={"Authorization": "Bearer tok"})
    assert seen["key"] == ""


def test_agent_run_override_drops_key(monkeypatch):
    monkeypatch.setenv("PROF_LLM_API_KEY", "sk-secret")
    seen = {}

    def fake_run(task, approver, gateway, effects, cfg=None, **kw):
        seen["key"] = cfg.api_key
        from prof.llm import AgentResult
        return AgentResult(answer="ok", steps=[])
    monkeypatch.setattr("prof.llm.run_task", fake_run)
    r = _client().post("/v1/agent/run", json={"task": "t", "base_url_override": "http://127.0.0.1:9/v1"})
    assert r.status_code == 200 and seen["key"] == ""


# ---- A8: ledger content is not public when a token is configured ----
def test_ledger_requires_token_when_configured(monkeypatch):
    monkeypatch.setenv("PROF_API_TOKEN", "tok")
    c = _client()
    assert c.get("/v1/ledger").status_code == 401
    assert c.get("/v1/ledger", headers={"Authorization": "Bearer tok"}).status_code == 200


# ---- A9: llm.env cannot be used to inject extra variables ----
def test_llm_config_rejects_newlines(tmp_path):
    r = _client().post("/v1/llm/config", json={"provider": "ollama",
                                               "model": "x\nPROF_API_TOKEN=pwned"})
    assert r.status_code == 400


# ---- A10: refuse to expose an unauthenticated gateway on a public interface ----
def test_serve_refuses_public_bind_without_token(monkeypatch):
    from prof import server
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.delenv("PROF_API_TOKEN", raising=False)
    monkeypatch.delenv("PROF_ALLOW_INSECURE", raising=False)
    with pytest.raises(SystemExit):
        server.serve()


# ---- A11: gateway still fail-closed end to end after the above ----
def test_gateway_roundtrip_unchanged():
    from prof.gateway import ExecuteRequest, Gateway
    a = Approver.generate("user:t")
    gw = Gateway(a.pubkey, DEFAULT_POLICY)
    args = {"customer": "acme-42"}
    p = Permit("user:t", "agent:t", "tool.call", "tool:crm.lookup", hash_args(args),
               DEFAULT_POLICY.policy_id, 2**31)
    a.sign_permit(p)
    assert gw.authorize(ExecuteRequest("tool.call", "tool:crm.lookup", args, p)).allow
    assert not gw.authorize(ExecuteRequest("tool.call", "tool:crm.lookup", args, p)).allow


# ---- A12: regression found while recording the demo (console "Expired permit" check) ----
def test_negative_ttl_yields_expired_permit_that_is_denied():
    c = _client()
    args = {"customer": "acme-42"}
    p = c.post("/v1/approve", json={"agent": "a", "action": "tool.call", "resource": "tool:crm.lookup",
                                    "args": args, "ttl_s": -5}).json()
    r = c.post("/v1/execute", json={"action": "tool.call", "resource": "tool:crm.lookup",
                                    "args": args, "permit": p}).json()
    assert r["ok"] is False and "expired" in r["decision"]


def test_console_templates_use_backticks_for_interpolation():
    import pathlib
    js = (pathlib.Path(__file__).resolve().parent.parent / "prof" / "console" / "app.js").read_text()
    assert "'<li class=\"mut\">${" not in js
