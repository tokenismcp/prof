import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


def run_cli(*args, **kwargs):
    return subprocess.run([sys.executable, "-m", "prof", *args],
                          capture_output=True, text=True, timeout=30, **kwargs)


def test_approve_prints_permit():
    r = run_cli("approve", "--action", "tool.call", "--resource", "tool:crm.lookup",
                "--args", '{"customer":"acme-42"}')
    assert r.returncode == 0, r.stderr
    p = json.loads(r.stdout)
    assert p["action"] == "tool.call" and p["approval_proof"]


def test_exec_allows_low_tier():
    r = run_cli("exec", "--action", "tool.call", "--resource", "tool:shell",
                "--args", '{"cmd":"hi"}', "--", "echo", "prof-ok")
    assert r.returncode == 0, r.stderr
    assert "prof-ok" in r.stdout


def test_exec_denies_high_without_human():
    r = run_cli("exec", "--action", "payment.transfer", "--resource", "account:krw-1",
                "--args", '{"to":"a","amount":1}', "--", "echo", "nope")
    assert r.returncode == 3
    assert "nope" not in r.stdout


def test_decide_json():
    r = run_cli("decide", "--action", "tool.call", "--resource", "tool:crm.lookup",
                "--args", '{"customer":"x"}')
    assert r.returncode == 0
    assert json.loads(r.stdout)["allow"] is True


def test_decide_hook_blocks_high():
    r = run_cli("decide", "--action", "payment.transfer", "--resource", "account:krw-1",
                "--args", '{"amount":5}', "--claude-hook")
    assert r.returncode == 2
    assert "PROF blocked" in r.stderr


def test_llm_check_lists_models_with_tool_flags():
    """llm-check must format the {"id","tools"} catalog as clean IDs (with a
    warning marker for non-tool models) — never a raw dict repr."""

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            body = json.dumps({"data": [{"id": "m-tool", "tools": True},
                                        {"id": "m-plain", "tools": False}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            self.rfile.read(n)
            body = json.dumps({"choices": [{"message": {"role": "assistant",
                                                        "content": "pong"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        r = run_cli("llm-check", "--provider", "ollama",
                    "--base-url", f"http://127.0.0.1:{srv.server_port}/v1",
                    "--model", "m-tool")
    finally:
        srv.shutdown()
    assert r.returncode == 0, r.stderr
    assert "m-tool" in r.stdout and "m-plain ⚠" in r.stdout
    assert "{'id'" not in r.stdout and '"id"' not in r.stdout
