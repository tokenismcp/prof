"""Real data-layer tests: SQLite persistence, balances, idempotency, sandboxing."""

import os

import pytest

from prof.gateway import ExecuteRequest
from prof.permit import Permit, hash_args
from prof.resources import ResourceDB, get_db, reset_db
from prof.demo_tools import build_demo_gateway, payment_transfer, file_write, crm_lookup
import time


def _permit(approver, gw, action, resource, args, ttl=300):
    p = Permit(subject=approver.subject, agent="agent:test",
               action=action, resource=resource, args_hash=hash_args(args),
               policy_id=gw.policy.policy_id, expiry=int(time.time()) + ttl)
    p.sign(approver._sk)
    return p


def test_crm_reads_real_row():
    approver, gw = build_demo_gateway()
    args = {"customer": "acme-42"}
    p = _permit(approver, gw, "tool.call", "tool:crm.lookup", args)
    dec, res = gw.execute(ExecuteRequest("tool.call", "tool:crm.lookup", args, p), crm_lookup)
    assert dec.allow, dec.reason
    assert res["name"] == "Acme Corp" and res["tier"] == "gold" and res["balance"] == 125000.0


def test_crm_unknown_customer_fails_closed():
    approver, gw = build_demo_gateway()
    args = {"customer": "nobody-0"}
    p = _permit(approver, gw, "tool.call", "tool:crm.lookup", args)
    dec, res = gw.execute(ExecuteRequest("tool.call", "tool:crm.lookup", args, p), crm_lookup)
    assert not dec.allow and "effect failed" in dec.reason


def test_payment_moves_real_money_and_persists(tmp_path):
    db_path = str(tmp_path / "prof.db")
    approver, gw = build_demo_gateway(db_path=db_path)
    args = {"to": "acct-9", "amount": 1000, "idempotency_key": "persist-1"}
    p = _permit(approver, gw, "payment.transfer", "account:krw-1", args)
    dec, res = gw.execute(ExecuteRequest("payment.transfer", "account:krw-1", args, p), payment_transfer)
    assert dec.allow, dec.reason
    assert res["from_balance"] == 1000000.0 - 1000
    # reopen: balance change survived the restart
    db2 = ResourceDB(db_path)
    assert db2.account_balance("account:krw-1") == 1000000.0 - 1000
    assert db2.account_balance("acct-9") == 1000.0
    db2.close()


def test_payment_idempotent_same_key(tmp_path):
    db_path = str(tmp_path / "prof.db")
    approver, gw = build_demo_gateway(db_path=db_path)
    args = {"to": "acct-9", "amount": 500, "idempotency_key": "idem-7"}
    p1 = _permit(approver, gw, "payment.transfer", "account:krw-1", args)
    dec1, res1 = gw.execute(ExecuteRequest("payment.transfer", "account:krw-1", args, p1), payment_transfer)
    assert dec1.allow and res1["duplicate"] is False
    # same key, fresh permit (not a replay): returns the original result, no double spend
    p2 = _permit(approver, gw, "payment.transfer", "account:krw-1", args)
    dec2, res2 = gw.execute(ExecuteRequest("payment.transfer", "account:krw-1", args, p2), payment_transfer)
    assert dec2.allow and res2["duplicate"] is True
    assert get_db().account_balance("account:krw-1") == 1000000.0 - 500


def test_payment_insufficient_funds():
    approver, gw = build_demo_gateway()
    # drain most of the 1,000,000 balance first (within the 1,000,000 policy cap)
    drain = {"to": "acct-9", "amount": 900000, "idempotency_key": "drain-1"}
    pd = _permit(approver, gw, "payment.transfer", "account:krw-1", drain)
    dec0, _ = gw.execute(ExecuteRequest("payment.transfer", "account:krw-1", drain, pd), payment_transfer)
    assert dec0.allow, dec0.reason
    args = {"to": "acct-9", "amount": 200000, "idempotency_key": "poor-1"}
    p = _permit(approver, gw, "payment.transfer", "account:krw-1", args)
    dec, _ = gw.execute(ExecuteRequest("payment.transfer", "account:krw-1", args, p), payment_transfer)
    assert not dec.allow and "insufficient funds" in dec.reason


def test_file_write_chains_hashes(tmp_path):
    approver, gw = build_demo_gateway()
    target = str(tmp_path / "a.txt")
    os.environ["PROF_DATA_ROOT"] = str(tmp_path)
    try:
        a1 = {"path": target, "content": "v1"}
        p1 = _permit(approver, gw, "file.write", "file:/tmp/**", a1)
        # resource must cover the path: use a permit scoped to tmp_path via glob of parent
        p1.resource = f"file:{tmp_path}/**"
        p1.sign(approver._sk)
        dec1, r1 = gw.execute(ExecuteRequest("file.write", f"file:{target}", a1, p1), file_write)
        assert dec1.allow, dec1.reason
        assert r1["prev_sha256"] is None
        a2 = {"path": target, "content": "v2"}
        p2 = _permit(approver, gw, "file.write", f"file:{tmp_path}/**", a2)
        dec2, r2 = gw.execute(ExecuteRequest("file.write", f"file:{target}", a2, p2), file_write)
        assert dec2.allow, dec2.reason
        assert r2["prev_sha256"] == r1["sha256"]
        assert open(target).read() == "v2"
    finally:
        os.environ.pop("PROF_DATA_ROOT", None)


def test_file_sandbox_escape_denied():
    approver, gw = build_demo_gateway()
    args = {"path": "/etc/prof-evil", "content": "x"}
    p = _permit(approver, gw, "file.write", "file:**", args)
    dec, _ = gw.execute(ExecuteRequest("file.write", "file:/etc/prof-evil", args, p), file_write)
    # high tier under default policy needs human; effect would also refuse outside sandbox
    assert not dec.allow
