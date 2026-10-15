import os

os.environ.setdefault("PROF_DEMO", "1")

from fastapi.testclient import TestClient  # noqa: E402

from prof.server import app  # noqa: E402


def _client():
    return TestClient(app)


def test_approval_queue_full_cycle():
    c = _client()
    # low-tier action is not eligible for the human queue
    r = c.post("/v1/requests", json={"agent": "agent:t", "action": "tool.call",
                                     "resource": "tool:crm.lookup",
                                     "args": {"customer": "acme-42"}})
    assert r.status_code == 400
    # high-tier payment opens a pending request
    r = c.post("/v1/requests", json={"agent": "agent:t", "action": "payment.transfer",
                                     "resource": "account:krw-1",
                                     "args": {"to": "acct-9", "amount": 100,
                                              "idempotency_key": "queue-1"}})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    assert r.json()["status"] == "pending"
    # listed as pending
    pend = c.get("/v1/requests").json()["requests"]
    assert any(q["id"] == rid for q in pend)
    # human approves -> signed permit bound to the exact args
    r = c.post(f"/v1/requests/{rid}/approve")
    assert r.status_code == 200, r.text
    permit = r.json()["permit"]
    assert permit["constraints"]["approved_by"] == "human"
    # double decision is rejected
    assert c.post(f"/v1/requests/{rid}/deny", json={"reason": "x"}).status_code == 409
    # the issued permit executes for real (balance moves)
    r = c.post("/v1/execute", json={"action": "payment.transfer",
                                    "resource": "account:krw-1",
                                    "args": {"to": "acct-9", "amount": 100,
                                             "idempotency_key": "queue-1"},
                                    "permit": permit})
    assert r.json()["ok"] is True, r.text


def test_approval_queue_deny():
    c = _client()
    r = c.post("/v1/requests", json={"agent": "agent:t", "action": "payment.transfer",
                                     "resource": "account:krw-1",
                                     "args": {"to": "x", "amount": 10,
                                              "idempotency_key": "queue-2"}})
    rid = r.json()["id"]
    r = c.post(f"/v1/requests/{rid}/deny", json={"reason": "looks phishy"})
    assert r.json()["status"] == "denied"
    assert c.get(f"/v1/requests/{rid}").json()["deny_reason"] == "looks phishy"


def test_approval_queue_unknown_id():
    c = _client()
    assert c.get("/v1/requests/req-nope").status_code == 404
    assert c.post("/v1/requests/req-nope/approve").status_code == 404


def test_llm_status_unreachable_fail_closed():
    c = _client()
    r = c.get("/v1/llm/status")
    body = r.json()
    assert "model" in body and "base_url" in body
    assert body["reachable"] is False  # no LLM in test env
    assert "api_key" not in body and "PROF_LLM_API_KEY" not in r.text


def test_agent_run_no_llm_fails_closed():
    c = _client()
    r = c.post("/v1/agent/run", json={"task": "hi", "max_steps": 2})
    assert r.status_code == 502  # LLM transport error, not a crash
