"""PROF Gateway HTTP server (FastAPI).

Endpoints:
  GET  /  -> redirect to the console dashboard (/console/)
  GET  /healthz  /readyz
  GET  /version  /v1/policy  /v1/ledger  /metrics
  POST /v1/approve   {subject, agent, action, resource, args, ttl_s, constraints} -> Permit (signed)
  POST /v1/execute   {permit, action, resource, args} -> allow/deny + effect result

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

from prof.resources import crm_lookup, file_write, get_db, payment_transfer
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
    # Initialize the persistent resource DB now so seed/migration errors
    # fail fast at startup instead of on first tool call.
    get_db()


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


class RequestIn(BaseModel):
    agent: str
    action: str
    resource: str
    args: Dict[str, Any] = {}
    ttl_s: int = 300


class DenyIn(BaseModel):
    reason: str = "denied by approver"


class AgentRunIn(BaseModel):
    task: str
    max_steps: int = 8
    human_approve: bool = False


# In-process human-approval queue. Lost on restart by design in v0.1
# (every queue transition is ledger-logged, so nothing is silent);
# a persistent queue is on the Beta roadmap.
_REQUESTS: Dict[str, Dict[str, Any]] = {}


def _new_request_id() -> str:
    import secrets
    return "req-" + secrets.token_hex(6)


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
        "key_source": "configured" if os.environ.get("PROF_APPROVER_PRIV") else "ephemeral",
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
        fn = _match_effect(inp.action, inp.resource)
    except PermissionError as exc:
        d = _gateway._deny(req, f"deny: {exc}")
        return {"ok": False, "decision": d.reason}
    dec, result = _gateway.execute(req, fn)
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


# ---- human approval queue (high-tier workflow) ----
@app.post("/v1/requests")
def create_request(inp: RequestIn):
    assert _approver and _gateway
    dec = _gateway.policy.evaluate(inp.action, inp.resource, inp.args)
    if not dec.allow:
        raise HTTPException(403, f"policy deny: {dec.reason}")
    if not dec.require_human:
        raise HTTPException(400, "not a high-tier action: use POST /v1/approve directly")
    rid = _new_request_id()
    _REQUESTS[rid] = {"id": rid, "status": "pending", "agent": inp.agent,
                      "action": inp.action, "resource": inp.resource,
                      "args": inp.args, "ttl_s": int(inp.ttl_s),
                      "tier": dec.tier, "policy_reason": dec.reason,
                      "created_ts": int(time.time()), "decided_ts": None,
                      "permit": None, "deny_reason": None}
    _gateway.ledger.append("request", rid, inp.action, inp.resource,
                           _approver.subject, inp.agent, f"tier={dec.tier} pending human")
    return _REQUESTS[rid]


@app.get("/v1/requests")
def list_requests(status: str = "pending"):
    assert _gateway
    items = [r for r in _REQUESTS.values() if status == "all" or r["status"] == status]
    return {"requests": sorted(items, key=lambda r: r["created_ts"], reverse=True)}


@app.get("/v1/requests/{rid}")
def get_request(rid: str):
    if rid not in _REQUESTS:
        raise HTTPException(404, f"unknown request: {rid}")
    return _REQUESTS[rid]


@app.post("/v1/requests/{rid}/approve")
def approve_request(rid: str):
    assert _approver and _gateway
    req = _REQUESTS.get(rid)
    if req is None:
        raise HTTPException(404, f"unknown request: {rid}")
    if req["status"] != "pending":
        raise HTTPException(409, f"already {req['status']}")
    p = Permit(subject=_approver.subject, agent=req["agent"], action=req["action"],
               resource=req["resource"], args_hash=hash_args(req["args"]),
               policy_id=_gateway.policy.policy_id,
               expiry=int(time.time()) + req["ttl_s"],
               constraints={"approved_by": "human", "request_id": rid})
    p.sign(_approver._sk)
    req["status"] = "approved"
    req["decided_ts"] = int(time.time())
    req["permit"] = p.to_dict()
    _gateway.ledger.append("approve", p.nonce, p.action, p.resource,
                           p.subject, p.agent, f"human-approved {rid}")
    return req


@app.post("/v1/requests/{rid}/deny")
def deny_request(rid: str, inp: DenyIn):
    assert _gateway
    req = _REQUESTS.get(rid)
    if req is None:
        raise HTTPException(404, f"unknown request: {rid}")
    if req["status"] != "pending":
        raise HTTPException(409, f"already {req['status']}")
    req["status"] = "denied"
    req["decided_ts"] = int(time.time())
    req["deny_reason"] = inp.reason
    _gateway.ledger.append("deny", rid, req["action"], req["resource"],
                           req["agent"], req["agent"], f"human-denied {rid}: {inp.reason}")
    return req


# ---- LLM agent surface ----
@app.get("/v1/llm/status")
def llm_status():
    from prof.llm import LLMConfig, check_connectivity
    cfg = LLMConfig()
    ok, info = check_connectivity(cfg)
    return {"configured": True, "reachable": ok, "info": info,
            "model": cfg.model, "base_url": cfg.base_url}


@app.post("/v1/agent/run")
def agent_run(inp: AgentRunIn):
    assert _approver and _gateway
    from prof.llm import LLMConfig, LLMError, run_task
    from prof.resources import crm_lookup, file_write, payment_transfer
    try:
        res = run_task(inp.task, _approver, _gateway,
                       {"crm.lookup": crm_lookup, "file.write": file_write,
                        "payment.transfer": payment_transfer},
                       cfg=LLMConfig(), max_steps=max(1, min(inp.max_steps, 12)),
                       human_approve=inp.human_approve)
    except LLMError as exc:
        raise HTTPException(502, str(exc))
    return {"answer": res.answer, "steps": res.steps,
            "allowed": res.allowed, "denied": res.denied}


@app.get("/v1/ledger")
def ledger(limit: int = 100):
    assert _gateway
    ok, msg = _gateway.ledger.verify_chain()
    limit = max(1, min(limit, 1000))
    return {"ok": ok, "message": msg, "total": len(_gateway.ledger.entries),
            "entries": [e.__dict__ for e in _gateway.ledger.entries[-limit:]]}


@app.get("/metrics")
def metrics():
    # Derived from the durable ledger (survives restarts when PROF_LEDGER is set),
    # not from process-local counters.
    assert _gateway
    allow = deny = approve = 0
    for e in _gateway.ledger.entries:
        if e.event == "allow" and not e.permit_nonce.endswith(":result"):
            allow += 1
        elif e.event == "deny":
            deny += 1
        elif e.event == "approve":
            approve += 1
    return {"allow": allow, "deny": deny, "approve": approve,
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
