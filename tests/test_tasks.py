"""Agent task inbox: store semantics, gateway API, and MCP tools.

The inbox is the bridge the console "Run a task" box needed: a human queued a
task, any connected agent (over MCP) claims it and reports back. These tests
cover the store's fail-closed claim rules, the HTTP surface, and the
end-to-end console -> MCP path in one process.
"""

import json
import os

os.environ.setdefault("PROF_DEMO", "1")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from prof import tasks  # noqa: E402
from prof.server import app  # noqa: E402


@pytest.fixture(autouse=True)
def _clean():
    tasks.reset()
    yield
    tasks.reset()


def _client():
    return TestClient(app)


def _mcp(c, mid, name, args):
    r = c.post("/mcp", json={"jsonrpc": "2.0", "id": mid, "method": "tools/call",
                             "params": {"name": name, "arguments": args}})
    return json.loads(r.json()["result"]["content"][0]["text"])


# ---- store semantics ----
def test_submit_claim_done_cycle():
    rec = tasks.submit("look up acme-42")
    assert rec["status"] == "pending" and rec["id"].startswith("task-")
    got = tasks.claim("agent:claude")
    assert got["id"] == rec["id"] and got["status"] == "claimed"
    assert got["claimed_by"] == "agent:claude" and got["claim_token"]
    ok, msg, done = tasks.complete(got["id"], got["claim_token"], True, "gold tier")
    assert ok and done["status"] == "done" and done["result"] == "gold tier"


def test_claim_is_single_and_fifo():
    tasks.submit("first")
    tasks.submit("second")
    c1, c2, c3 = tasks.claim("a"), tasks.claim("a"), tasks.claim("a")
    assert [c1["task"], c2["task"]] == ["first", "second"]
    assert c3 is None  # nothing left; a claimed task isn't handed out twice


def test_targeted_task_reserved_for_named_agent():
    tasks.submit("for claude only", agent="agent:claude")
    assert tasks.claim("agent:codex") is None
    got = tasks.claim("agent:claude")
    assert got and got["task"] == "for claude only"


def test_complete_requires_matching_token_and_is_once():
    rec = tasks.submit("t")
    got = tasks.claim("a")
    ok, msg, _ = tasks.complete(got["id"], "wrong-token")
    assert not ok and "token" in msg
    assert tasks.complete(got["id"], got["claim_token"])[0] is True
    # a finished task cannot be completed again
    assert tasks.complete(got["id"], got["claim_token"])[0] is False


def test_stale_claim_is_reclaimed(monkeypatch):
    rec = tasks.submit("t")
    tasks.claim("a")
    monkeypatch.setattr(tasks, "CLAIM_TTL_S", -1)  # force the claim to look stale
    again = tasks.claim("b")
    assert again and again["id"] == rec["id"] and again["claimed_by"] == "b"


def test_cancel_and_clear():
    rec = tasks.submit("t")
    assert tasks.cancel(rec["id"])[0] is True
    assert tasks.get(rec["id"])["status"] == "cancelled"
    assert tasks.clear() == 1
    assert tasks.list_tasks() == []


def test_submit_rejects_empty():
    with pytest.raises(ValueError):
        tasks.submit("   ")


def test_counts_and_list_filter():
    tasks.submit("a")
    tasks.submit("b")
    tasks.claim("x")
    assert tasks.counts() == {"pending": 1, "claimed": 1}
    assert [t["status"] for t in tasks.list_tasks(status="claimed")] == ["claimed"]


def test_store_returns_copies():
    rec = tasks.submit("t")
    rec["status"] = "evil"  # mutating the returned copy must not touch the store
    assert tasks.get(rec["id"])["status"] == "pending"


# ---- gateway HTTP API ----
def test_api_full_cycle():
    c = _client()
    r = c.post("/v1/tasks", json={"task": "what tier is acme-42?"})
    assert r.status_code == 200, r.text
    tid = r.json()["id"]
    body = c.get("/v1/tasks").json()
    assert body["counts"].get("pending") == 1
    assert any(t["id"] == tid for t in body["tasks"])

    got = c.post("/v1/tasks/next", json={"agent": "agent:claude"}).json()["task"]
    assert got["id"] == tid and got["claim_token"]

    assert c.post(f"/v1/tasks/{tid}/done",
                  json={"claim_token": "nope"}).status_code == 400
    r = c.post(f"/v1/tasks/{tid}/done",
               json={"claim_token": got["claim_token"], "ok": True, "result": "gold"})
    assert r.status_code == 200 and r.json()["status"] == "done"

    assert c.post("/v1/tasks/next", json={}).json()["task"] is None
    assert c.post("/v1/tasks/clear").json()["removed"] == 1
    assert c.get("/v1/tasks").json()["tasks"] == []


def test_api_rejects_empty_and_unknown():
    c = _client()
    assert c.post("/v1/tasks", json={"task": "   "}).status_code == 400
    assert c.get("/v1/tasks/task-nope").status_code == 404
    assert c.post("/v1/tasks/task-nope/done",
                  json={"claim_token": "x"}).status_code == 400


def test_api_cancel():
    c = _client()
    tid = c.post("/v1/tasks", json={"task": "t"}).json()["id"]
    assert c.post(f"/v1/tasks/{tid}/cancel").json()["status"] == "cancelled"
    assert c.post(f"/v1/tasks/{tid}/cancel").status_code == 400


# ---- MCP tools ----
def test_mcp_stdio_task_tools_share_store():
    from prof.mcpd import MCPServer
    srv = MCPServer()  # local mode -> in-process prof.tasks
    names = {t["name"] for t in
             srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]}
    assert {"prof.task.next", "prof.task.done", "prof.task.list"} <= names

    rec = tasks.submit("mcp work")
    res = srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                      "params": {"name": "prof.task.next",
                                 "arguments": {"agent": "agent:mcp"}}})
    payload = json.loads(res["result"]["content"][0]["text"])
    assert payload["task"]["id"] == rec["id"]
    token = payload["task"]["claim_token"]

    res2 = srv.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": "prof.task.done",
                                  "arguments": {"task_id": rec["id"],
                                                "claim_token": token,
                                                "result": "done!"}}})
    p2 = json.loads(res2["result"]["content"][0]["text"])
    assert p2["ok"] and p2["task"]["status"] == "done"


def test_end_to_end_console_to_remote_mcp():
    """Console queues over HTTP; an agent claims and finishes over POST /mcp;
    the console sees the result. One inbox, two surfaces, one process."""
    c = _client()
    tid = c.post("/v1/tasks", json={"task": "e2e: what tier is acme-42?",
                                    "agent": "agent:d"}).json()["id"]

    claimed = _mcp(c, 1, "prof.task.next", {"agent": "agent:d"})["task"]
    assert claimed["id"] == tid and claimed["claim_token"]

    done = _mcp(c, 2, "prof.task.done",
                {"task_id": tid, "claim_token": claimed["claim_token"],
                 "ok": True, "result": "Acme Corp is gold"})
    assert done["ok"] and done["task"]["status"] == "done"

    assert c.get(f"/v1/tasks/{tid}").json()["result"] == "Acme Corp is gold"
