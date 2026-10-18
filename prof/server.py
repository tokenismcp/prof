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

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from prof.resources import crm_lookup, file_write, get_db, payment_transfer
from prof.gateway import ExecuteRequest, Gateway
from prof.identity import Approver
from prof.ledger import Ledger
from prof.permit import Permit, b64_pubkey, hash_args
from prof.policy import DEFAULT_POLICY
from prof.store import NonceStore

VERSION = "1.0.0"

app = FastAPI(title="PROF Gateway", version=VERSION)

_approver: Optional[Approver] = None
_gateway: Optional[Gateway] = None


# ---- security: token auth, headers, body cap, rate limit ----
def _api_token() -> str:
    return os.environ.get("PROF_API_TOKEN", "")


async def require_token(request: Request) -> None:
    """Bearer auth for every state-changing or approval-queue endpoint.

    Disabled when PROF_API_TOKEN is unset (local demo). Set it in any
    shared/production deployment; the console prompts for it (lock icon).
    """
    want = _api_token()
    if not want:
        return
    import hmac
    got = request.headers.get("authorization", "")
    if not got.lower().startswith("bearer ") or not hmac.compare_digest(
            got[7:].strip(), want):
        raise HTTPException(401, "missing or invalid API token",
                            headers={"WWW-Authenticate": "Bearer"})


@app.middleware("http")
async def _security_middleware(request: Request, call_next):
    # 1 MB body cap (permits/args are small JSON; fail fast on abuse)
    try:
        if int(request.headers.get("content-length", "0") or 0) > 1_000_000:
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "body too large (1 MB cap)"}, status_code=413)
    except ValueError:
        pass
    # per-IP sliding-window rate limit on hot mutating paths
    if request.method == "POST" and request.url.path in (
            "/v1/approve", "/v1/execute", "/v1/agent/run",
            "/v1/tasks", "/v1/tasks/next"):
        try:
            limit = int(os.environ.get("PROF_RATE_LIMIT", "300"))
        except ValueError:
            limit = 300
        if limit > 0 and not _check_rate(request.client.host if request.client else "?",
                                        request.url.path, limit):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "rate limit exceeded, retry later"},
                                status_code=429, headers={"Retry-After": "60"})
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    if resp.status_code in (401, 429):
        import sys as _sys
        import time as _t
        host = request.client.host if request.client else "?"
        print(f"[prof][auth] {resp.status_code} {request.method} {request.url.path} from {host} "
              f"at {int(_t.time())}", file=_sys.stderr)
    return resp


_rate_buckets: Dict[str, list] = {}


def _check_rate(key_host: str, path: str, limit: int) -> bool:
    import time as _t
    now = _t.time()
    key = f"{key_host}:{path}"
    hits = [t for t in _rate_buckets.get(key, []) if now - t < 60]
    if len(hits) >= limit:
        _rate_buckets[key] = hits
        return False
    hits.append(now)
    _rate_buckets[key] = hits[-limit:]
    return True


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
    wait_approval: bool = False
    approval_timeout_s: int = 120
    provider_override: str = ""
    model_override: str = ""
    base_url_override: str = ""


class LLMConfigIn(BaseModel):
    provider: str = ""
    model: str = ""
    base_url: str = ""


class TaskIn(BaseModel):
    task: str
    agent: str = ""              # optional: target one agent name
    max_steps: int = 8
    human_approve: bool = False
    provider: str = ""           # execution hints for LLM-loop workers
    model: str = ""
    base_url: str = ""


class TaskNextIn(BaseModel):
    agent: str = ""


class TaskDoneIn(BaseModel):
    claim_token: str
    ok: bool = True
    result: str = ""
    error: str = ""


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


@app.post("/v1/auto-approve")
def auto_approve(inp: ApproveIn, _t: None = Depends(require_token)):
    """Server-side auto-approval for NON-human tiers only (transparent agents).

    Lets MCP/agent frontends execute low/medium actions without a permit
    round-trip: the server mints the permit itself, server-side, logged.
    High-tier actions are refused here (403) — they must go through the
    human approval queue, so "use as usual" never silently elevates risk.
    """
    assert _approver and _gateway
    dec = _gateway.policy.evaluate(inp.action, inp.resource, inp.args)
    if not dec.allow:
        raise HTTPException(403, f"policy deny: {dec.reason}")
    if dec.require_human:
        raise HTTPException(403, f"high-tier action: human approval required ({dec.reason})")
    p = Permit(
        subject=inp.subject or _approver.subject,
        agent=inp.agent,
        action=inp.action,
        resource=inp.resource,
        args_hash=hash_args(inp.args),
        policy_id=_gateway.policy.policy_id,
        expiry=int(time.time()) + min(int(inp.ttl_s), 300),
        constraints={**inp.constraints, "auto": True},
    )
    p.sign(_approver._sk)
    _gateway.ledger.append("approve", p.nonce, p.action, p.resource,
                           p.subject, p.agent, f"tier={dec.tier} auto")
    return p.to_dict()


@app.post("/v1/approve")
def approve(inp: ApproveIn, _t: None = Depends(require_token)):
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
def execute(inp: ExecuteIn, _t: None = Depends(require_token)):
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
def _open_request(agent: str, action: str, resource: str, args: Dict[str, Any],
                  ttl_s: int = 300) -> Dict[str, Any]:
    """Shared core: validate tier and open a pending request (ledger-logged)."""
    assert _approver and _gateway
    dec = _gateway.policy.evaluate(action, resource, args)
    if not dec.allow:
        raise HTTPException(403, f"policy deny: {dec.reason}")
    if not dec.require_human:
        raise HTTPException(400, "not a high-tier action: use POST /v1/approve directly")
    rid = _new_request_id()
    _REQUESTS[rid] = {"id": rid, "status": "pending", "agent": agent,
                      "action": action, "resource": resource,
                      "args": args, "ttl_s": int(ttl_s),
                      "tier": dec.tier, "policy_reason": dec.reason,
                      "created_ts": int(time.time()), "decided_ts": None,
                      "permit": None, "deny_reason": None}
    _gateway.ledger.append("request", rid, action, resource,
                           _approver.subject, agent, f"tier={dec.tier} pending human")
    return _REQUESTS[rid]


@app.post("/v1/requests")
def create_request(inp: RequestIn, _t: None = Depends(require_token)):
    return _open_request(inp.agent, inp.action, inp.resource, inp.args, inp.ttl_s)


@app.get("/v1/requests")
def list_requests(status: str = "pending", _t: None = Depends(require_token)):
    assert _gateway
    items = [r for r in _REQUESTS.values() if status == "all" or r["status"] == status]
    return {"requests": sorted(items, key=lambda r: r["created_ts"], reverse=True)}


@app.get("/v1/requests/{rid}")
def get_request(rid: str, _t: None = Depends(require_token)):
    if rid not in _REQUESTS:
        raise HTTPException(404, f"unknown request: {rid}")
    return _REQUESTS[rid]


@app.post("/v1/requests/{rid}/approve")
def approve_request(rid: str, _t: None = Depends(require_token)):
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
def deny_request(rid: str, inp: DenyIn, _t: None = Depends(require_token)):
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


# ---- agent task inbox (console assigns -> any agent claims over MCP) ----
@app.post("/v1/tasks")
def create_task(inp: TaskIn, _t: None = Depends(require_token)):
    """Queue a task for an agent. The console "Queue for agent" button calls
    this; MCP agents pull with POST /v1/tasks/next (prof.task.next)."""
    from prof import tasks as _tasks
    assert _approver and _gateway
    try:
        rec = _tasks.submit(inp.task, agent=inp.agent, max_steps=inp.max_steps,
                            human_approve=inp.human_approve, provider=inp.provider,
                            model=inp.model, base_url=inp.base_url)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    _gateway.ledger.append("task_submit", rec["id"], "agent.task",
                           "task:" + rec["id"], _approver.subject,
                           inp.agent or "agent:any", f"task={rec['task'][:120]}")
    return rec


@app.get("/v1/tasks")
def list_tasks_endpoint(status: str = "", limit: int = 50,
                        _t: None = Depends(require_token)):
    from prof import tasks as _tasks
    return {"tasks": _tasks.list_tasks(status=status, limit=limit),
            "counts": _tasks.counts()}


@app.get("/v1/tasks/{tid}")
def get_task_endpoint(tid: str, _t: None = Depends(require_token)):
    from prof import tasks as _tasks
    rec = _tasks.get(tid)
    if rec is None:
        raise HTTPException(404, f"unknown task: {tid}")
    return rec


@app.post("/v1/tasks/next")
def claim_task(inp: TaskNextIn, _t: None = Depends(require_token)):
    """Claim the next ready task (FIFO). Empty {"task": null} when none."""
    from prof import tasks as _tasks
    assert _approver and _gateway
    rec = _tasks.claim(inp.agent)
    if rec is None:
        return {"task": None}
    _gateway.ledger.append("task_claim", rec["id"], "agent.task",
                           "task:" + rec["id"], _approver.subject,
                           rec["claimed_by"], f"claimed by {rec['claimed_by']}")
    return {"task": rec}


@app.post("/v1/tasks/{tid}/done")
def complete_task(tid: str, inp: TaskDoneIn, _t: None = Depends(require_token)):
    from prof import tasks as _tasks
    assert _approver and _gateway
    ok, msg, rec = _tasks.complete(tid, inp.claim_token, inp.ok, inp.result, inp.error)
    if not ok or rec is None:
        raise HTTPException(400, msg)
    _gateway.ledger.append("task_done", tid, "agent.task", "task:" + tid,
                           _approver.subject, rec["claimed_by"] or "agent",
                           f"ok={rec['ok']} result={(rec['result'] or '')[:120]}")
    return rec


@app.post("/v1/tasks/{tid}/cancel")
def cancel_task(tid: str, _t: None = Depends(require_token)):
    from prof import tasks as _tasks
    assert _approver and _gateway
    ok, msg, rec = _tasks.cancel(tid)
    if not ok or rec is None:
        raise HTTPException(400, msg)
    _gateway.ledger.append("task_cancel", tid, "agent.task", "task:" + tid,
                           _approver.subject, "human", "cancelled")
    return rec


@app.post("/v1/tasks/clear")
def clear_tasks(status: str = "", _t: None = Depends(require_token)):
    """Drop finished tasks (or everything matching ?status=). Returns count."""
    from prof import tasks as _tasks
    return {"removed": _tasks.clear(status)}


# ---- LLM agent surface ----
@app.get("/v1/llm/status")
def llm_status():
    from prof.llm import LLMConfig, PROVIDERS, check_connectivity, list_models
    cfg = LLMConfig()
    # Probe with a short timeout so a slow/unreachable endpoint never blocks
    # the console for the full chat timeout (PROF_LLM_TIMEOUT defaults to 60s).
    cfg.timeout_s = min(cfg.timeout_s, 8)
    ok, info = check_connectivity(cfg)
    return {"configured": True, "reachable": ok, "info": info,
            "provider": cfg.provider, "model": cfg.model, "base_url": cfg.base_url,
            "needs_key": cfg.needs_key, "key_present": bool(cfg.api_key),
            "models": list_models(cfg),  # best-effort; [] if unlistable
            "providers": {k: {"protocol": v["protocol"], "needs_key": v["needs_key"],
                              "blurb": v["blurb"]} for k, v in PROVIDERS.items()}}


@app.get("/v1/llm/models")
def llm_models(provider: str = "", base_url: str = ""):
    """Model catalog for a provider. Uses server env (keys never leave server).

    Optional ?provider=&base_url= previews another endpoint's catalog.
    Falls back to curated defaults (marked) when unlistable/unreachable.
    """
    from prof.llm import FALLBACK_MODELS, LLMConfig, PROVIDERS, list_models
    if provider and provider not in PROVIDERS:
        raise HTTPException(400, "unknown provider (see /v1/llm/status)")
    cfg = LLMConfig(provider=provider or None) if provider else LLMConfig()
    if provider and not base_url:
        # Previewing a provider: the env endpoint belongs to the gateway's own
        # provider — use the preset endpoint unless they match.
        import os as _os
        if _os.environ.get("PROF_LLM_PROVIDER", "") != provider:
            cfg.base_url = PROVIDERS[provider]["base_url"]
    if base_url:
        cfg.base_url = base_url
    models = list_models(cfg)
    if models:
        return {"provider": cfg.provider, "models": models, "fallback": False}
    fb = FALLBACK_MODELS.get(cfg.provider, [])
    preset = PROVIDERS[cfg.provider]["model"]
    if preset and preset not in [m["id"] for m in fb]:
        fb = [{"id": preset, "tools": False}, *fb]
    return {"provider": cfg.provider, "models": fb, "fallback": True}


@app.post("/v1/llm/config")
def llm_config(inp: LLMConfigIn, _t: None = Depends(require_token)):
    """Persist provider/model/base_url (never api keys) to configs/llm.env.

    Takes effect on gateway restart. API keys stay environment-only by design.
    """
    import pathlib as _pl
    from prof.llm import PROVIDERS
    allowed = {"provider", "model", "base_url"}
    data = {k: v for k, v in inp.model_dump().items() if k in allowed and v}
    if "provider" in data and data["provider"] not in PROVIDERS:
        raise HTTPException(400, f"unknown provider (see /v1/llm/status)")
    cfg_dir = _pl.Path(__file__).resolve().parent.parent / "configs"
    cfg_dir.mkdir(exist_ok=True)
    lines = []
    if "provider" in data:
        lines.append(f"PROF_LLM_PROVIDER={data['provider']}")
    if "model" in data:
        lines.append(f"PROF_LLM_MODEL={data['model']}")
    if "base_url" in data:
        lines.append(f"PROF_LLM_BASE_URL={data['base_url']}")
    with open(cfg_dir / "llm.env", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return {"saved": str(cfg_dir / "llm.env"),
            "note": "restart the gateway to apply; API keys are never stored here"}


@app.post("/v1/agent/run")
def agent_run(inp: AgentRunIn, _t: None = Depends(require_token)):
    assert _approver and _gateway
    from prof.llm import LLMConfig, LLMError, run_task
    from prof.resources import crm_lookup, file_write, payment_transfer
    approve_fn = None
    if inp.wait_approval and not inp.human_approve:
        approve_fn = _queue_wait_approver(timeout_s=max(5, min(inp.approval_timeout_s, 600)))
    cfg = LLMConfig()
    if inp.provider_override:
        from prof.llm import PROVIDERS
        if inp.provider_override not in PROVIDERS:
            raise HTTPException(400, "unknown provider (see /v1/llm/status)")
        cfg.provider = inp.provider_override
        if not inp.base_url_override:
            cfg.base_url = PROVIDERS[inp.provider_override]["base_url"]
    if inp.model_override:
        cfg.model = inp.model_override
    if inp.base_url_override:
        cfg.base_url = inp.base_url_override
    try:
        res = run_task(inp.task, _approver, _gateway,
                       {"crm.lookup": crm_lookup, "file.write": file_write,
                        "payment.transfer": payment_transfer},
                       cfg=cfg, max_steps=max(1, min(inp.max_steps, 12)),
                       human_approve=inp.human_approve, approve_fn=approve_fn)
    except LLMError as exc:
        raise HTTPException(502, str(exc))
    _gateway.ledger.append("agent_run", f"task-{len(_gateway.ledger.entries)}",
                           "agent.run", "agent:llm",
                           _approver.subject, "agent:llm",
                           f"allowed={res.allowed} denied={res.denied} "
                           f"answer={res.answer[:160]}")
    return {"answer": res.answer, "steps": res.steps,
            "allowed": res.allowed, "denied": res.denied}


def _queue_wait_approver(timeout_s: int):
    """approve_fn for run_task: open a queue request and block until a human
    decides (or timeout). Connects the LLM loop to the approval workflow."""
    import time as _t

    def _fn(tool_name: str, tool_args: Dict[str, Any]) -> bool:
        binding = {"file.write": ("file.write", f"file:{tool_args.get('path', '')}"),
                   "payment.transfer": ("payment.transfer", "account:krw-1")}
        if tool_name not in binding:
            return False
        action, resource = binding[tool_name]
        try:
            req = _open_request("agent:llm", action, resource, tool_args)
        except HTTPException:
            return False
        rid = req["id"]
        deadline = _t.time() + timeout_s
        while _t.time() < deadline:
            st = _REQUESTS.get(rid, {}).get("status")
            if st == "approved":
                return True
            if st == "denied":
                return False
            _t.sleep(1.0)
        _REQUESTS.get(rid, {}).update(status="denied", decided_ts=int(_t.time()),
                                      deny_reason="approval timeout")
        return False

    return _fn


@app.post("/mcp")
async def mcp_http_endpoint(request: Request):
    """Remote MCP over Streamable HTTP (Dots, Muse, any remote MCP client).

    Stateless JSON-RPC. Bearer PROF_API_TOKEN when configured.
    Deploy behind public HTTPS (compose --profile edge) and register
    https://<domain>/mcp as a custom MCP server / connector.
    """
    from fastapi.responses import JSONResponse, Response
    from prof.mcp_http import check_bearer, handle_http
    if not check_bearer(request.headers.get("authorization", "")):
        return JSONResponse({"jsonrpc": "2.0", "id": None,
                             "error": {"code": -32001, "message": "missing or invalid bearer token"}},
                            status_code=401)
    try:
        msg = await request.json()
    except Exception:
        return JSONResponse({"jsonrpc": "2.0", "id": None,
                             "error": {"code": -32700, "message": "parse error"}},
                            status_code=400)
    if not isinstance(msg, dict) or "method" not in msg:
        return JSONResponse({"jsonrpc": "2.0", "id": msg.get("id") if isinstance(msg, dict) else None,
                             "error": {"code": -32600, "message": "invalid request"}},
                            status_code=400)
    status, resp = handle_http(msg)
    if resp is None:
        return Response(status_code=status)
    return JSONResponse(resp, status_code=status)


@app.get("/mcp")
async def mcp_http_get():
    from fastapi.responses import JSONResponse
    return JSONResponse({"jsonrpc": "2.0", "id": None,
                         "error": {"code": -32600,
                                   "message": "use POST with a JSON-RPC message (stateless Streamable HTTP)"}},
                        status_code=405)


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

    class _RevalidatingStatic(StaticFiles):
        """Console assets: revalidate on every load so code updates always
        apply after a reload (this is a local ops console, not a CDN)."""

        def file_response(self, *args, **kwargs):
            resp = super().file_response(*args, **kwargs)
            resp.headers["Cache-Control"] = "no-cache, must-revalidate"
            return resp

    _console_dir = str(_pl.Path(__file__).parent / "console")
    app.mount("/console", _RevalidatingStatic(directory=_console_dir, html=True), name="console")
except Exception:
    pass  # console optional in minimal installs
