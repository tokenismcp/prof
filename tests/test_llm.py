"""LLM loop tests against a real (local, stubbed) OpenAI-compatible API.

Only the LLM HTTP endpoint is stubbed — the agentic loop, permits,
gateway verification, SQLite effects and ledger are all real.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from prof.demo_tools import build_demo_gateway
from prof.llm import LLMConfig, TOOL_SCHEMAS, chat_complete, check_connectivity, run_task
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


def test_provider_presets_and_overrides():
    from prof.llm import PROVIDERS
    assert set(PROVIDERS) >= {"ollama", "openai", "anthropic", "vllm"}
    cfg = LLMConfig(provider="openai")
    assert cfg.chat_url == "https://api.openai.com/v1/chat/completions"
    assert cfg.needs_key is True
    cfg2 = LLMConfig(provider="anthropic")
    assert cfg2.chat_url.endswith("/messages")
    cfg3 = LLMConfig(provider="ollama", model="custom")
    assert cfg3.model == "custom" and "11434" in cfg3.base_url


def test_anthropic_native_roundtrip():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    seen = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            seen["body"] = json.loads(self.rfile.read(n))
            seen["key"] = self.headers.get("x-api-key")
            out = json.dumps({"content": [
                {"type": "text", "text": "looking up"},
                {"type": "tool_use", "id": "t1", "name": "crm.lookup",
                 "input": {"customer": "acme-42"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cfg = LLMConfig(provider="anthropic",
                    base_url=f"http://127.0.0.1:{srv.server_port}/v1",
                    api_key="test-key", model="test-claude")
    msg = chat_complete(cfg, [{"role": "system", "content": "sys"},
                              {"role": "user", "content": "hi"}],
                        tools=TOOL_SCHEMAS)
    assert seen["key"] == "test-key"
    assert seen["body"]["system"] == "sys"  # system extracted
    assert seen["body"]["tools"][0]["name"] == "crm.lookup"  # translated format
    assert msg["tool_calls"][0]["function"]["name"] == "crm.lookup"  # normalized back
    srv.shutdown()


def test_anthropic_requires_key():
    import pytest as _pt
    cfg = LLMConfig(provider="anthropic", api_key="")
    with _pt.raises(Exception):
        chat_complete(cfg, [{"role": "user", "content": "hi"}])


def test_list_models_against_stub():
    from prof.llm import list_models
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class MH(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            out = json.dumps({"data": [{"id": "m-b"}, {"id": "m-a"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

    srv = HTTPServer(("127.0.0.1", 0), MH)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    models = list_models(LLMConfig(base_url=f"http://127.0.0.1:{srv.server_port}/v1"))
    assert models == ["m-a", "m-b"]  # sorted
    srv.shutdown()


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
