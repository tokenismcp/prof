"""Full-system tests against a live gateway subprocess.

Spins up `python -m prof gateway` with temp durable files and proves:
  1. remote MCP (PROF_GATEWAY_URL) lands in the SAME server ledger/policy/nonces;
  2. LLM loop + approval queue integrate: model asks, human approves over HTTP,
     payment executes, balance moves (LLM HTTP is stubbed; everything else real).
"""

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from prof.client import GatewayClient


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class StubLLM(BaseHTTPRequestHandler):
    script = []
    calls = 0

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        self.rfile.read(n)
        i = StubLLM.calls
        StubLLM.calls += 1
        msg = StubLLM.script[min(i, len(StubLLM.script) - 1)]
        body = json.dumps({"choices": [{"message": msg}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def live():
    gw_port = _free_port()
    llm_port = _free_port()
    tmp = os.environ.get("TMPDIR", "/tmp") + f"/prof-e2e-{gw_port}"
    os.makedirs(tmp, exist_ok=True)
    StubLLM.calls = 0
    llm = HTTPServer(("127.0.0.1", llm_port), StubLLM)
    threading.Thread(target=llm.serve_forever, daemon=True).start()
    env = dict(os.environ, PROF_DEMO="1", PORT=str(gw_port),
               PROF_DB=f"{tmp}/prof.db", PROF_LEDGER=f"{tmp}/ledger.json",
               PROF_NONCES=f"{tmp}/nonces.json",
               PROF_LLM_BASE_URL=f"http://127.0.0.1:{llm_port}/v1",
               PROF_LLM_MODEL="e2e-test", PYTHONPATH="." + os.pathsep + os.environ.get("PYTHONPATH", ""))
    proc = subprocess.Popen([sys.executable, "-m", "prof", "gateway",
                               "--port", str(gw_port)],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{gw_port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(base + "/healthz", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    else:
        proc.terminate()
        raise RuntimeError("gateway did not start")
    yield base
    proc.terminate()
    proc.wait(timeout=10)
    llm.shutdown()


def test_remote_mcp_uses_server_ledger(live):
    os.environ["PROF_GATEWAY_URL"] = live
    try:
        from prof.mcpd import MCPServer
        srv = MCPServer()
        assert srv.remote is not None
        r = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": "prof.approve",
                                   "arguments": {"agent": "agent:e2e", "action": "tool.call",
                                                 "resource": "tool:crm.lookup",
                                                 "args": {"customer": "acme-42"}}}})
        permit = json.loads(r["result"]["content"][0]["text"])["permit"]
        r = srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                        "params": {"name": "crm.lookup",
                                   "arguments": {"customer": "acme-42", "permit": permit}}})
        body = json.loads(r["result"]["content"][0]["text"])
        assert body["ok"] is True and body["result"]["name"] == "Acme Corp"
        # same ledger as the server's own
        led = GatewayClient(live).ledger(limit=50)
        assert any(e["agent"] == "agent:e2e" and e["event"] == "allow"
                   for e in led["entries"])
    finally:
        os.environ.pop("PROF_GATEWAY_URL", None)


def test_llm_queue_human_loop_end_to_end(live):
    StubLLM.script = [
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "c1", "type": "function",
            "function": {"name": "payment.transfer",
                         "arguments": json.dumps({"to": "acct-9", "amount": 250,
                                                  "idempotency_key": "e2e-1"})}}]},
        {"role": "assistant", "content": "Sent 250 with human approval."},
    ]
    client = GatewayClient(live)

    def human():
        for _ in range(60):
            for q in client.list_requests("pending"):
                client.decide_request(q["id"], True)
                return
            time.sleep(0.5)

    threading.Thread(target=human, daemon=True).start()
    out = client.agent_run("Send 250 to acct-9", max_steps=4, wait_approval=True,
                           approval_timeout_s=30)
    assert out["allowed"] == 1 and out["denied"] == 0, out
    assert out["steps"][0]["result"]["from_balance"] == 1000000.0 - 250
    # denial-free, fully audited: request + human approve + allow + agent_run summary
    led = client.ledger(limit=50)
    kinds = [e["event"] for e in led["entries"]]
    for k in ("request", "approve", "allow", "agent_run"):
        assert k in kinds, kinds
    assert led["ok"] is True
