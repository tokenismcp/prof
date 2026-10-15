import json
import subprocess
import sys


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
