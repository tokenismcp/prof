"""`prof` CLI — 5-minute path to Proof-Required execution."""

from __future__ import annotations

import json
import time

import click

from prof.demo_tools import build_demo_gateway, crm_lookup, file_write, payment_transfer
from prof.gateway import ExecuteRequest
from prof.identity import Approver
from prof.ledger import Ledger
from prof.permit import Permit, hash_args
from prof.store import NonceStore


@click.group()
def main():
    """PROF — Think Freely. Act With Proof."""


@main.command()
def quickstart():
    """Print the 5-minute quickstart."""
    click.echo(
        """PROF 5-minute quickstart
1. pip install -e .
2. prof demo            # allow + tamper-deny + replay-deny in one run
3. prof gateway         # start HTTP gateway on :8091
4. python examples/01_tool_call.py
Docs: docs/ARCHITECTURE.md, docs/SECURITY_MODEL.md"""
    )


@main.command()
@click.option("--ledger", default=None, help="ledger file (optional)")
def demo(ledger):
    """Run allow / tamper-deny / replay-deny back-to-back."""
    approver, gw = build_demo_gateway(ledger_path=ledger)
    click.echo(f"[PROF demo] approver={approver.subject} policy={gw.policy.policy_id}")

    # 1. ALLOW — CRM lookup
    args = {"customer": "acme-42"}
    p = Permit(subject=approver.subject, agent="agent:demo:01", action="tool.call",
               resource="tool:crm.lookup", args_hash=hash_args(args),
               policy_id=gw.policy.policy_id, expiry=int(time.time()) + 300)
    p.sign(approver._sk)
    dec, res = gw.execute(ExecuteRequest("tool.call", "tool:crm.lookup", args, p), crm_lookup)
    click.echo(f" 1. legit request      -> {'ALLOW' if dec.allow else 'DENY'} ({dec.reason}) result={res}")

    # 2. TAMPER — change args after approval
    evil = {"customer": "acme-42", "admin": True}
    dec2, _ = gw.execute(ExecuteRequest("tool.call", "tool:crm.lookup", evil, p), crm_lookup)
    click.echo(f" 2. tampered args      -> {'ALLOW' if dec2.allow else 'DENY'} ({dec2.reason})")

    # 3. REPLAY — reuse same permit (nonce already spent)
    dec3, _ = gw.execute(ExecuteRequest("tool.call", "tool:crm.lookup", args, p), crm_lookup)
    click.echo(f" 3. replay same permit -> {'ALLOW' if dec3.allow else 'DENY'} ({dec3.reason})")

    # 4. PAYMENT with tampered amount
    pay = {"to": "acct-7", "amount": 50000, "idempotency_key": "demo-001"}
    pp = Permit(subject=approver.subject, agent="agent:demo:01", action="payment.transfer",
                resource="account:krw-1", args_hash=hash_args(pay),
                policy_id=gw.policy.policy_id, expiry=int(time.time()) + 300)
    pp.sign(approver._sk)
    evil_pay = dict(pay, amount=5000000)
    dec4, _ = gw.execute(ExecuteRequest("payment.transfer", "account:krw-1", evil_pay, pp), payment_transfer)
    click.echo(f" 4. amount tamper      -> {'ALLOW' if dec4.allow else 'DENY'} ({dec4.reason})")

    ok, msg = gw.ledger.verify_chain()
    click.echo(f" ledger: {msg}")
    if dec.allow and not dec2.allow and not dec3.allow and not dec4.allow:
        click.echo("DEMO PASS: legit allowed, attacks denied. Think Freely. Act With Proof.")
    else:
        raise click.ClickException("DEMO FAIL — see reasons above")


@main.command()
@click.option("--port", default=8091)
def gateway(port):
    """Start the PROF Gateway HTTP server."""
    import os
    os.environ["PORT"] = str(port)
    from prof.server import serve
    serve()


@main.command("verify-ledger")
@click.argument("path")
def verify_ledger(path):
    led = Ledger(path)
    ok, msg = led.verify_chain()
    click.echo(msg)
    if not ok:
        raise click.ClickException("ledger INVALID")


@main.command("audit")
@click.option("--ledger", default=None, help="ledger file (default: $PROF_LEDGER or ephemeral)")
@click.option("--limit", default=20, show_default=True)
def audit(ledger, limit):
    """Verify the chain and print recent entries (operator audit)."""
    import os as _os
    led = Ledger(ledger or _os.environ.get("PROF_LEDGER"))
    ok, msg = led.verify_chain()
    click.echo(msg)
    counts: dict = {}
    for e in led.entries:
        counts[e.event] = counts.get(e.event, 0) + 1
    click.echo("events: " + " ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    for e in led.entries[-max(1, limit):]:
        click.echo(f"#{e.seq} {e.event:8} {e.action} {e.resource} {e.agent} :: {(e.detail or '')[:80]}")
    if not ok:
        raise click.ClickException("ledger INVALID")


@main.command("llm-check")
@click.option("--provider", default=None)
@click.option("--base-url", default=None)
@click.option("--model", default=None)
def llm_check(provider, base_url, model):
    """Verify connectivity to the LLM API (env PROF_LLM_* or flags)."""
    from prof.llm import LLMConfig, PROVIDERS, check_connectivity, list_models
    cfg = LLMConfig(provider=provider or LLMConfig().provider)
    if base_url:
        cfg.base_url = base_url
    if model:
        cfg.model = model
    ok, info = check_connectivity(cfg)
    click.echo(f"provider={cfg.provider} model={cfg.model} url={cfg.base_url}")
    click.echo(info)
    if ok:
        models = list_models(cfg)
        if models:
            click.echo("models (⚠ = no tool-calling): " + ", ".join(
                m["id"] + ("" if m.get("tools") else " ⚠") for m in models[:15]))
    if provider and provider not in PROVIDERS:
        raise click.ClickException(f"unknown provider. choices: {', '.join(PROVIDERS)}")
    if not ok:
        raise click.ClickException("LLM unreachable — run `prof llm-setup`")


@main.command("llm-setup")
def llm_setup():
    """Interactive LLM setup: probe local servers, pick provider/model, verify."""
    import urllib.request
    from prof.llm import LLMConfig, PROVIDERS, check_connectivity, list_models
    click.echo("PROF LLM setup — local first, keys stay in env.")
    found = []
    for name, url in (("ollama", "http://localhost:11434"), ("lmstudio", "http://localhost:1234")):
        try:
            urllib.request.urlopen(url + "/v1/models", timeout=3)
            found.append(name)
        except Exception:
            pass
    if found:
        click.echo("local servers detected: " + ", ".join(found))
    names = list(PROVIDERS)
    for i, name in enumerate(names, 1):
        p = PROVIDERS[name]
        mark = " [local]" if name in found or not p["needs_key"] else ""
        click.echo(f"  {i}. {name}{mark} — {p['blurb']}")
    choice = click.prompt("provider number", default="1")
    try:
        provider = names[int(choice) - 1]
    except (ValueError, IndexError):
        raise click.ClickException("bad choice")
    cfg = LLMConfig(provider=provider)
    if cfg.needs_key and not cfg.api_key:
        click.echo(f"set your key first: export PROF_LLM_API_KEY=…  (never stored by PROF)")
    models = list_models(cfg)
    if models:
        click.echo("available models (⚠ = no tool-calling; PROF needs tools):")
        for i, m in enumerate(models[:15], 1):
            click.echo(f"  {i}. {m['id']}" + ("" if m.get("tools") else " ⚠"))
        pick = click.prompt("model number (0 = keep default)", default="0")
        try:
            if int(pick) > 0:
                chosen = models[int(pick) - 1]
                cfg.model = chosen["id"]
                if not chosen.get("tools"):
                    click.echo(f"warning: {chosen['id']} may not support tool calls; "
                               "PROF drives every action through tools.")
        except (ValueError, IndexError):
            pass
    ok, info = check_connectivity(cfg)
    click.echo(info)
    if not ok:
        raise click.ClickException("unreachable — check the server/model and retry")
    click.echo("to persist for the gateway:")
    click.echo(f"  export PROF_LLM_PROVIDER={provider} PROF_LLM_MODEL={cfg.model}")
    if cfg.base_url != PROVIDERS[provider]["base_url"]:
        click.echo(f"  export PROF_LLM_BASE_URL={cfg.base_url}")


@main.command("agent-run")
@click.argument("task")
@click.option("--model", default=None)
@click.option("--base-url", default=None)
@click.option("--max-steps", default=8, show_default=True)
@click.option("--human-approve", is_flag=True, default=False,
              help="pre-approve high-tier actions for this run")
@click.option("--wait-approval", is_flag=True, default=False,
              help="with --gateway-url: open queue requests and wait for a human")
@click.option("--approval-timeout", default=120, show_default=True)
@click.option("--gateway-url", default=None,
              help="delegate the whole run to a shared gateway (integrates with console queue)")
@click.option("--db", default=None, help="SQLite path (default: in-memory demo)")
def agent_run(task, model, base_url, max_steps, human_approve, wait_approval,
              approval_timeout, gateway_url, db):
    """Run a task through model -> PROF permit -> verified execution loop."""
    from prof.llm import LLMConfig
    if gateway_url:
        from prof.client import ClientError, GatewayClient
        try:
            out = GatewayClient(gateway_url).agent_run(
                task, max_steps=max_steps, human_approve=human_approve,
                wait_approval=wait_approval, approval_timeout_s=approval_timeout)
        except ClientError as exc:
            raise click.ClickException(str(exc))
        for s in out["steps"]:
            mark = "ALLOW" if s["ok"] else "DENY"
            click.echo(f"[{mark}] {s['tool']} {s.get('decision', '')}")
        click.echo(f"--- allowed={out['allowed']} denied={out['denied']} ---")
        click.echo(out["answer"])
        return
    from prof.demo_tools import build_demo_gateway
    from prof.llm import run_task
    from prof.resources import crm_lookup, file_write, payment_transfer
    approver, gw = build_demo_gateway(db_path=db)
    cfg = LLMConfig()
    if base_url:
        cfg.base_url = base_url
    if model:
        cfg.model = model
    res = run_task(task, approver, gw,
                   {"crm.lookup": crm_lookup, "file.write": file_write,
                    "payment.transfer": payment_transfer},
                   cfg=cfg, max_steps=max_steps, human_approve=human_approve)
    for s in res.steps:
        mark = "ALLOW" if s["ok"] else "DENY"
        click.echo(f"[{mark}] {s['tool']} {s.get('decision', '')}")
    gw.ledger.append("agent_run", f"task-{len(gw.ledger.entries)}",
                     "agent.run", "agent:llm", approver.subject, "agent:llm",
                     f"allowed={res.allowed} denied={res.denied} answer={res.answer[:160]}")
    click.echo(f"--- allowed={res.allowed} denied={res.denied} ---")
    click.echo(res.answer)


@main.command()
def version():
    from prof import __version__
    click.echo(f"prof {__version__}")


@main.command("mcp")
def mcp_cmd():
    """Run the PROF MCP stdio server (for Claude Code, Codex, Gemini, Cursor, …)."""
    from prof.mcpd import serve_stdio
    serve_stdio()


@main.command()
@click.option("--agent", default="agent:cli", show_default=True)
@click.option("--action", required=True, help="e.g. tool.call, file.write, payment.transfer")
@click.option("--resource", required=True, help="e.g. tool:crm.lookup, file:/tmp/**, account:krw-1")
@click.option("--args", "args_json", default="{}", show_default=True, help="JSON object")
@click.option("--ttl", default=300, show_default=True)
def approve(agent, action, resource, args_json, ttl):
    """Issue a signed Permit (prints JSON). Agents pass it to the tool call."""
    import json as _json
    from prof.demo_tools import build_demo_gateway
    from prof.permit import Permit, hash_args
    approver, gw = build_demo_gateway()
    try:
        args = _json.loads(args_json)
        assert isinstance(args, dict)
    except Exception:
        raise click.ClickException("--args must be a JSON object")
    pol = gw.policy.evaluate(action, resource, args)
    if not pol.allow:
        raise click.ClickException(f"policy deny: {pol.reason}")
    import time as _t
    p = Permit(subject=approver.subject, agent=agent, action=action, resource=resource,
               args_hash=hash_args(args), policy_id=gw.policy.policy_id,
               expiry=int(_t.time()) + ttl)
    p.sign(approver._sk)
    click.echo(_json.dumps(p.to_dict(), indent=2))


@main.command(context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.option("--agent", default="agent:cli")
@click.option("--action", required=True)
@click.option("--resource", required=True)
@click.option("--args", "args_json", default="{}")
@click.option("--human-approve", is_flag=True, default=False,
              help="assert a human approved this run (required for high tier)")
@click.pass_context
def exec(ctx, agent, action, resource, args_json, human_approve):
    """Approve + run a shell command only if the Gateway allows it.

    Example: prof exec --action tool.call --resource tool:shell --args '{"cmd":"ls"}' -- ls -la
    """
    import json as _json
    import subprocess as _sp
    import time as _t
    from prof.demo_tools import build_demo_gateway
    from prof.gateway import ExecuteRequest
    from prof.permit import Permit, hash_args
    cmd = ctx.args
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        raise click.ClickException("no command given after --")
    try:
        args = _json.loads(args_json)
        assert isinstance(args, dict)
    except Exception:
        raise click.ClickException("--args must be a JSON object")
    args = dict(args, _cmd=cmd)
    approver, gw = build_demo_gateway()
    pol = gw.policy.evaluate(action, resource, args)
    if not pol.allow:
        click.echo(f"DENY: {pol.reason}", err=True)
        raise SystemExit(3)
    if pol.require_human and not human_approve:
        click.echo(f"DENY: high-tier action needs a human: re-run with --human-approve ({pol.reason})", err=True)
        raise SystemExit(3)
    p = Permit(subject=agent if agent.startswith("user:") else approver.subject,
               agent=agent, action=action, resource=resource,
               args_hash=hash_args(args), policy_id=gw.policy.policy_id,
               expiry=int(_t.time()) + 300)
    p.sign(approver._sk)
    dec, _ = gw.execute(ExecuteRequest(action, resource, args, p), lambda a: {"cmd": cmd})
    if not dec.allow:
        click.echo(f"DENY: {dec.reason}", err=True)
        raise SystemExit(3)
    click.echo(f"ALLOW: {dec.reason}", err=True)
    r = _sp.run(cmd)
    raise SystemExit(r.returncode)


@main.command()
@click.option("--action", required=True)
@click.option("--resource", required=True)
@click.option("--args", "args_json", default="{}")
@click.option("--claude-hook", is_flag=True, default=False,
              help="Claude Code PreToolUse format: exit 0 allow / exit 2 block")
def decide(action, resource, args_json, claude_hook):
    """Decide allow/deny for action/resource/args without running anything.

    Used by agent hooks (Claude Code PreToolUse, generic pre-tool gates).
    """
    import json as _json
    import time as _t
    from prof.demo_tools import build_demo_gateway
    from prof.gateway import ExecuteRequest
    from prof.permit import Permit, hash_args
    try:
        args = _json.loads(args_json)
        assert isinstance(args, dict)
    except Exception:
        args = {}
    approver, gw = build_demo_gateway()
    pol = gw.policy.evaluate(action, resource, args)
    allow, reason = False, f"policy deny: {pol.reason}" if not pol.allow else ""
    if pol.allow:
        if pol.require_human:
            reason = f"high-tier action requires human approval ({pol.reason}); run `prof approve` + human sign-off first"
        else:
            p = Permit(subject=approver.subject, agent="agent:hook", action=action,
                       resource=resource, args_hash=hash_args(args),
                       policy_id=gw.policy.policy_id, expiry=int(_t.time()) + 300)
            p.sign(approver._sk)
            dec, _ = gw.execute(ExecuteRequest(action, resource, args, p), lambda a: {"ok": True})
            allow, reason = dec.allow, dec.reason
    if claude_hook:
        if allow:
            raise SystemExit(0)
        click.echo(f"PROF blocked this action: {reason}", err=True)
        raise SystemExit(2)
    click.echo(_json.dumps({"allow": allow, "reason": reason}))
    raise SystemExit(0 if allow else 3)


if __name__ == "__main__":
    main()
