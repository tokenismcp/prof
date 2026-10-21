import os
import threading
import time

os.environ.setdefault("PROF_DEMO", "1")

from fastapi.testclient import TestClient  # noqa: E402

import prof.server as srv  # noqa: E402
from prof.demo_tools import build_demo_gateway, payment_transfer  # noqa: E402
from prof.gateway import ExecuteRequest  # noqa: E402
from prof.permit import Permit, hash_args  # noqa: E402

app = srv.app


def _client():
    return TestClient(app)


def _permit(approver, gw, action, resource, args, ttl=300):
    p = Permit(subject=approver.subject, agent="agent:test",
               action=action, resource=resource, args_hash=hash_args(args),
               policy_id=gw.policy.policy_id, expiry=int(time.time()) + ttl)
    p.sign(approver._sk)
    return p


# ---- token auth ----
def test_writes_open_without_token_by_default():
    c = _client()
    r = c.post("/v1/approve", json={"agent": "a", "action": "tool.call",
                                    "resource": "tool:crm.lookup",
                                    "args": {"customer": "acme-42"}})
    assert r.status_code == 200


def test_writes_need_token_when_configured(monkeypatch):
    monkeypatch.setenv("PROF_API_TOKEN", "s3cret")
    c = _client()
    body = {"agent": "a", "action": "tool.call", "resource": "tool:crm.lookup",
            "args": {"customer": "acme-42"}}
    assert c.post("/v1/approve", json=body).status_code == 401
    assert c.post("/v1/approve", json=body,
                  headers={"Authorization": "Bearer wrong"}).status_code == 401
    r = c.post("/v1/approve", json=body, headers={"Authorization": "Bearer s3cret"})
    assert r.status_code == 200
    # aggregate reads stay open; the ledger (subjects, resources, task text) does not
    assert c.get("/v1/ledger").status_code == 401
    assert c.get("/v1/ledger", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert c.get("/metrics").status_code == 200
    # approval queue reads are protected too
    assert c.get("/v1/requests").status_code == 401
    assert c.get("/v1/requests", headers={"Authorization": "Bearer s3cret"}).status_code == 200


# ---- headers, body cap, rate limit ----
def test_security_headers():
    c = _client()
    r = c.get("/healthz")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"


def test_body_cap_413():
    c = _client()
    big = "x" * 1_100_000
    r = c.post("/v1/approve", content=big,
               headers={"Content-Type": "application/json", "Content-Length": str(len(big))})
    assert r.status_code == 413


def test_rate_limit_429(monkeypatch):
    monkeypatch.setenv("PROF_RATE_LIMIT", "3")
    srv._rate_buckets.clear()
    c = _client()
    body = {"agent": "a", "action": "tool.call", "resource": "tool:crm.lookup",
            "args": {"customer": "acme-42"}}
    codes = [c.post("/v1/approve", json=body).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200]
    assert codes[3] == 429 and codes[4] == 429
    srv._rate_buckets.clear()


# ---- nonce race: one permit, many threads, exactly one allow ----
def test_concurrent_replay_exactly_one_allow():
    approver, gw = build_demo_gateway()
    args = {"customer": "acme-42"}
    p = _permit(approver, gw, "tool.call", "tool:crm.lookup", args)
    from prof.resources import crm_lookup
    results = []

    def one():
        from prof.gateway import ExecuteRequest as ER
        dec, _ = gw.execute(ER("tool.call", "tool:crm.lookup", args, p), crm_lookup)
        results.append(dec.allow)

    threads = [threading.Thread(target=one) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(results) == 1 and len(results) == 16


# ---- audit completeness: every decision leaves a chained entry ----
def test_audit_trail_complete(tmp_path):
    approver, gw = build_demo_gateway(ledger_path=str(tmp_path / "l.json"))
    from prof.resources import crm_lookup
    n0 = len(gw.ledger.entries)
    args = {"customer": "acme-42"}
    p = _permit(approver, gw, "tool.call", "tool:crm.lookup", args)
    gw.execute(ExecuteRequest("tool.call", "tool:crm.lookup", args, p), crm_lookup)  # allow+result
    evil = dict(args, admin=True)
    gw.execute(ExecuteRequest("tool.call", "tool:crm.lookup", evil, p), crm_lookup)  # deny
    kinds = [e.event for e in gw.ledger.entries[n0:]]
    assert kinds[0] == "allow" and "deny" in kinds
    ok, msg = gw.ledger.verify_chain()
    assert ok, msg
