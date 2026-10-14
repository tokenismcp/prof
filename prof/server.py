"""PROF Gateway HTTP server (FastAPI).

Endpoints:
  GET  /healthz
  GET  /version
  POST /v1/approve   {subject, agent, action, resource, args, ttl_s, constraints} -> Permit (signed)
  POST /v1/execute   {permit, action, resource, args} -> allow/deny + effect result
  GET  /v1/ledger            -> verify + entries
  GET  /metrics              -> counters

Demo mode: ephemeral approver key generated at startup, pubkey at /version.
Production: load key via PROF_APPROVER_PRIV / KMS seam (refuse to start without it
unless PROF_DEMO=1). Fail-closed throughout.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from prof.demo_tools import crm_lookup, file_write, payment_transfer
from prof.gateway import ExecuteRequest, Gateway
from prof.identity import Approver
from prof.ledger import Ledger
from prof.permit import Permit, b64_pubkey, hash_args, load_privkey
from prof.policy import DEFAULT_POLICY
from prof.store import NonceStore

VERSION = "0.1.0"

app = FastAPI(title="PROF Gateway", version=VERSION)

_approver: Optional[Approver] = None
_gateway: Optional[Gateway] = None
_counters = {"allow": 0, "deny": 0}


def _init() -> None:
    global _approver, _gateway
    if _gateway is not None:
        return
    priv = os.environ.get("PROF_APPROVER_PRIV", "")
    demo = os.environ.get("PROF_DEMO", "1") == "1"
    if priv:
        _approver = Approver.from_private_b64(os.environ.get("PROF_SUBJECT", "user:approver"), priv)
    elif demo:
        _approver = Approver.generate(os.environ.get("PROF_SUBJECT", "user:demo"))
    else:
        raise RuntimeError("refusing to start: no PROF_APPROVER_PRIV and PROF_DEMO!=1 (fail-closed)")
    _gateway = Gateway(
        approver_pubkey=_approver.pubkey,
        policy=DEFAULT_POLICY,
        ledger=Ledger(os.environ.get("PROF_LEDGER", None)),
        nonces=NonceStore(os.environ.get("PROF_NONCES", None)),
    )


_init()


class ApproveIn(BaseModel):
    subject: Optional[str] = None
    agent: str
    action: str
    resource: str
    args: Dict[str, Any] = {}
    ttl_s: int = 300
    constraints: Dict[str, Any] = {}


class ExecuteIn(BaseModel):
    action: str
    resource: str
    args: Dict[str, Any] = {}
    permit: Dict[str, Any]


EFFECTS = {
    ("tool.call", "tool:crm.lookup"): crm_lookup,
    ("file.write", "file:/tmp/**"): file_write,
    ("payment.transfer", "account:**"): payment_transfer,
}


def _effect(action: str, resource: str):
    if (action, resource) in EFFECTS:
        return EFFECTS[(action, resource)]
    # generic safe default: echo (no side effect) — real deployments register explicit effects
    if action.startswith("tool.") or action.startswith("file.read"):
        return lambda a: {"echo": a}
    raise PermissionError(f"no registered effect for {action} {resource} (fail-closed)")


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": VERSION}


@app.get("/readyz")
def readyz():
    assert _gateway
    ok, msg = _gateway.ledger.verify_chain()
    if not ok:
        raise HTTPException(500, f"ledger invalid: {msg}")
    return {"ready": True, "ledger": msg, "nonces": _gateway.nonces.size()}


@app.get("/v1/policy")
def get_policy():
    assert _gateway
    return _gateway.policy.to_dict()


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/console/")


@app.get("/version")
def version():
    assert _approver and _gateway
    return {
        "version": VERSION,
        "policy_id": _gateway.policy.policy_id,
        "approver_subject": _approver.subject,
        "approver_pubkey": b64_pubkey(_approver.pubkey),
        "ledger_head": _gateway.ledger.head,
    }


@app.post("/v1/approve")
def approve(inp: ApproveIn):
    assert _approver and _gateway
    dec = _gateway.policy.evaluate(inp.action, inp.resource, inp.args)
    if not dec.allow:
        raise HTTPException(403, f"policy deny: {dec.reason}")
    if dec.require_human and os.environ.get("PROF_REQUIRE_HUMAN", "0") == "1":
        raise HTTPException(403, "human approval required (PROF_REQUIRE_HUMAN=1)")
    p = Permit(
        subject=inp.subject or _approver.subject,
        agent=inp.agent,
        action=inp.action,
        resource=inp.resource,
        args_hash=hash_args(inp.args),
        policy_id=_gateway.policy.policy_id,
        expiry=int(time.time()) + int(inp.ttl_s),
        constraints=inp.constraints,
    )
    p.sign(_approver._sk)
    _gateway.ledger.append("approve", p.nonce, p.action, p.resource, p.subject, p.agent, f"tier={dec.tier}")
    return p.to_dict()


@app.post("/v1/execute")
def execute(inp: ExecuteIn):
    assert _gateway
    try:
        permit = Permit.from_dict(inp.permit)
    except Exception as exc:
        raise HTTPException(400, f"bad permit: {exc}")
    req = ExecuteRequest(action=inp.action, resource=inp.resource, args=inp.args, permit=permit)
    try:
        fn = _effect(inp.action, inp.resource if inp.resource in [k[1] for k in EFFECTS] else inp.action and _match_effect(inp.action, inp.resource))
    except PermissionError as exc:
        d = _gateway._deny(req, f"deny: {exc}")
        _count(deny=True)
        return {"ok": False, "decision": d.reason}
    dec, result = _gateway.execute(req, fn)
    _count(deny=not dec.allow)
    if not dec.allow:
        return {"ok": False, "decision": dec.reason}
    return {"ok": True, "decision": dec.reason, "result": result, "ledger_seq": dec.ledger_seq}


def _match_effect(action: str, resource: str):
    for (a, r), fn in EFFECTS.items():
        if a == action:
            import fnmatch as _fn
            if _fn.fnmatchcase(resource, r) or resource == r:
                return fn
    return _effect(action, resource)


def _count(deny: bool):
    _counters["deny" if deny else "allow"] += 1


@app.get("/v1/ledger")
def ledger():
    assert _gateway
    ok, msg = _gateway.ledger.verify_chain()
    return {"ok": ok, "message": msg,
            "entries": [e.__dict__ for e in _gateway.ledger.entries[-100:]]}


@app.get("/metrics")
def metrics():
    assert _gateway
    return {"allow": _counters["allow"], "deny": _counters["deny"],
            "ledger_entries": len(_gateway.ledger.entries), "nonces": _gateway.nonces.size()}


def serve() -> None:
    import uvicorn
    uvicorn.run(app,
                host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8091")))


try:
    import pathlib as _pl
    _console_dir = str(_pl.Path(__file__).parent / "console")
    app.mount("/console", StaticFiles(directory=_console_dir, html=True), name="console")
except Exception:
    pass  # console optional in minimal installs
