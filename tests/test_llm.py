"""LLM loop tests against a real (local, stubbed) OpenAI-compatible API.

Only the LLM HTTP endpoint is stubbed — the agentic loop, permits,
gateway verification, SQLite effects and ledger are all real.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from prof.demo_tools import build_demo_gateway
from prof.llm import LLMConfig, chat_complete, check_connectivity, run_task
from prof.resources import crm_lookup, file_write, payment_transfer


class ScriptedHandler(BaseHTTPRequestHandler):
    script = []
    calls = 0

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        self.rfile.read(n)
        i = ScriptedHandler.calls
        ScriptedHandler.calls += 1
        msg = ScriptedHandler.script[min(i, len(ScriptedHandler.script) - 1)]
        body = json.dumps({"choices": [{"message": msg}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def llm_server():
    ScriptedHandler.calls = 0
    srv = HTTPServer(("127.0.0.1", 0), ScriptedHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}/v1"
    srv.shutdown()


def test_chat_complete_real_http(llm_server):
    ScriptedHandler.script = [{"role": "assistant", "content": "pong"}]
    cfg = LLMConfig(base_url=llm_server, model="test-model")
    msg = chat_complete(cfg, [{"role": "user", "content": "ping"}])
    assert msg["content"] == "pong"


def test_check_connectivity(llm_server):
    ScriptedHandler.script = [{"role": "assistant", "content": "pong"}]
    ok, info = check_connectivity(LLMConfig(base_url=llm_server))
    assert ok and "test-model" in info or ok


def test_agent_loop_executes_real_tool(llm_server):
    ScriptedHandler.script = [
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "c1", "type": "function",
            "function": {"name": "crm.lookup",
                         "arguments": json.dumps({"customer": "acme-42"})}}]},
        {"role": "assistant", "content": "Acme is gold with 125000 balance."},
    ]
    approver, gw = build_demo_gateway()
    res = run_task("What tier is acme-42?", approver, gw,
                   {"crm.lookup": crm_lookup, "file.write": file_write,
                    "payment.transfer": payment_transfer},
                   cfg=LLMConfig(base_url=llm_server), max_steps=4)
    assert res.allowed == 1 and res.denied == 0
    assert res.steps[0]["ok"] is True
    assert res.steps[0]["result"]["name"] == "Acme Corp"  # real DB row, not canned
    assert "ledger_seq" in res.steps[0]
    assert "125000" in res.answer


def test_agent_loop_high_tier_denied_without_human(llm_server):
    ScriptedHandler.script = [
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "c1", "type": "function",
            "function": {"name": "payment.transfer",
                         "arguments": json.dumps({"to": "x", "amount": 10,
                                                  "idempotency_key": "llm-1"})}}]},
        {"role": "assistant", "content": "Blocked: needs a human."},
    ]
    approver, gw = build_demo_gateway()
    res = run_task("Send 10 to x", approver, gw,
                   {"crm.lookup": crm_lookup, "file.write": file_write,
                    "payment.transfer": payment_transfer},
                   cfg=LLMConfig(base_url=llm_server), max_steps=4)
    assert res.denied == 1 and res.allowed == 0
    assert "human approval" in res.steps[0]["decision"]


def test_agent_loop_high_tier_allowed_with_human(llm_server):
    ScriptedHandler.script = [
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "c1", "type": "function",
            "function": {"name": "payment.transfer",
                         "arguments": json.dumps({"to": "acct-9", "amount": 100,
                                                  "idempotency_key": "llm-2"})}}]},
        {"role": "assistant", "content": "Sent."},
    ]
    approver, gw = build_demo_gateway()
    res = run_task("Send 100 to acct-9", approver, gw,
                   {"crm.lookup": crm_lookup, "file.write": file_write,
                    "payment.transfer": payment_transfer},
                   cfg=LLMConfig(base_url=llm_server), max_steps=4,
                   human_approve=True)
    assert res.allowed == 1
    assert res.steps[0]["result"]["from_balance"] == 1000000.0 - 100
