import time
import pytest
from prof.demo_tools import build_demo_gateway, crm_lookup, payment_transfer
from prof.gateway import ExecuteRequest
from prof.ledger import Ledger
from prof.permit import Permit, hash_args


def _permit(approver, gw, action, resource, args, ttl=300):
    p = Permit(subject=approver.subject, agent="agent:test",
               action=action, resource=resource, args_hash=hash_args(args),
               policy_id=gw.policy.policy_id, expiry=int(time.time()) + ttl)
    p.sign(approver._sk)
    return p


def test_permit_sign_verify():
    approver, gw = build_demo_gateway()
    p = _permit(approver, gw, "tool.call", "tool:crm.lookup", {"customer": "x"})
    assert p.verify(approver.pubkey)


def test_allow_legit():
    approver, gw = build_demo_gateway()
    args = {"customer": "acme-42"}
    p = _permit(approver, gw, "tool.call", "tool:crm.lookup", args)
    dec, res = gw.execute(ExecuteRequest("tool.call", "tool:crm.lookup", args, p), crm_lookup)
    assert dec.allow, dec.reason


def test_deny_tamper():
    approver, gw = build_demo_gateway()
    args = {"customer": "acme-42"}
    p = _permit(approver, gw, "tool.call", "tool:crm.lookup", args)
    evil = {"customer": "acme-42", "admin": True}
    dec, _ = gw.execute(ExecuteRequest("tool.call", "tool:crm.lookup", evil, p), crm_lookup)
    assert not dec.allow and "args_hash" in dec.reason


def test_deny_replay():
    approver, gw = build_demo_gateway()
    args = {"customer": "acme-42"}
    p = _permit(approver, gw, "tool.call", "tool:crm.lookup", args)
    dec, _ = gw.execute(ExecuteRequest("tool.call", "tool:crm.lookup", args, p), crm_lookup)
    assert dec.allow
    dec2, _ = gw.execute(ExecuteRequest("tool.call", "tool:crm.lookup", args, p), crm_lookup)
    assert not dec2.allow and "replay" in dec2.reason


def test_deny_expiry():
    approver, gw = build_demo_gateway()
    args = {"customer": "acme-42"}
    p = _permit(approver, gw, "tool.call", "tool:crm.lookup", args, ttl=-1)
    dec, _ = gw.execute(ExecuteRequest("tool.call", "tool:crm.lookup", args, p), crm_lookup)
    assert not dec.allow and "expired" in dec.reason


def test_deny_scope_escalation():
    approver, gw = build_demo_gateway()
    args = {"path": "/etc/passwd", "content": "x"}
    # approve only /tmp/**, request /etc/**
    p = _permit(approver, gw, "file.write", "file:/tmp/**", args)
    dec, _ = gw.execute(ExecuteRequest("file.write", "file:/etc/**", args, p), lambda a: "nope")
    assert not dec.allow


def test_payment_amount_tamper():
    approver, gw = build_demo_gateway()
    args = {"to": "a", "amount": 100, "idempotency_key": "k1"}
    p = _permit(approver, gw, "payment.transfer", "account:krw-1", args)
    evil = dict(args, amount=99999999)
    dec, _ = gw.execute(ExecuteRequest("payment.transfer", "account:krw-1", evil, p), payment_transfer)
    assert not dec.allow


def test_ledger_tamper_evident(tmp_path):
    lp = str(tmp_path / "ledger.json")
    approver, gw = build_demo_gateway(ledger_path=lp)
    args = {"customer": "acme-42"}
    p = _permit(approver, gw, "tool.call", "tool:crm.lookup", args)
    gw.execute(ExecuteRequest("tool.call", "tool:crm.lookup", args, p), crm_lookup)
    ok, _ = gw.ledger.verify_chain()
    assert ok
    # tamper with file
    import json
    with open(lp) as f:
        raw = json.load(f)
    raw[0]["detail"] = "forged"
    with open(lp, "w") as f:
        json.dump(raw, f)
    led2 = Ledger(lp)
    ok2, msg2 = led2.verify_chain()
    assert not ok2, msg2


def test_cross_session_reuse_denied():
    approver, gw = build_demo_gateway()
    args = {"customer": "acme-42"}
    p = _permit(approver, gw, "tool.call", "tool:crm.lookup", args)
    dec, _ = gw.execute(ExecuteRequest("tool.call", "tool:crm.lookup", args, p), crm_lookup)
    assert dec.allow
    # second session, same permit bytes -> same nonce -> deny
    dec2, _ = gw.execute(ExecuteRequest("tool.call", "tool:crm.lookup", args, p), crm_lookup)
    assert not dec2.allow
