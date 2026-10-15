import os

os.environ.setdefault("PROF_DEMO", "1")

from fastapi.testclient import TestClient  # noqa: E402

from prof.server import app  # noqa: E402


def _client():
    return TestClient(app)


def test_health_and_ready():
    c = _client()
    assert c.get("/healthz").json()["ok"] is True
    r = c.get("/readyz")
    assert r.status_code == 200 and r.json()["ready"] is True


def test_policy_endpoint():
    c = _client()
    p = c.get("/v1/policy").json()
    assert p["policy_id"] == "default@v1" and len(p["rules"]) >= 5


def test_console_served():
    c = _client()
    r = c.get("/console/")
    assert r.status_code == 200 and "PROF Console" in r.text


def test_landing_served():
    c = _client()
    r = c.get("/")
    assert r.status_code == 200 and "Act With Proof" in r.text


def test_approve_execute_roundtrip():
    c = _client()
    ap = c.post("/v1/approve", json={"agent": "agent:t", "action": "tool.call",
                                     "resource": "tool:crm.lookup",
                                     "args": {"customer": "acme-42"}})
    assert ap.status_code == 200, ap.text
    permit = ap.json()
    ex = c.post("/v1/execute", json={"action": "tool.call", "resource": "tool:crm.lookup",
                                     "args": {"customer": "acme-42"}, "permit": permit})
    assert ex.json()["ok"] is True, ex.text
    # tampered -> deny
    ex2 = c.post("/v1/execute", json={"action": "tool.call", "resource": "tool:crm.lookup",
                                      "args": {"customer": "evil"}, "permit": permit})
    assert ex2.json()["ok"] is False


def test_production_refuses_without_key():
    import importlib
    import prof.server as srv
    srv._gateway = None
    os.environ["PROF_DEMO"] = "0"
    os.environ.pop("PROF_APPROVER_PRIV", None)
    try:
        importlib.reload(srv)
        raise AssertionError("should have refused to start")
    except RuntimeError as e:
        assert "refusing to start" in str(e)
    finally:
        os.environ["PROF_DEMO"] = "1"
        importlib.reload(srv)
