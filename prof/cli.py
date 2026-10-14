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


@main.command()
def version():
    from prof import __version__
    click.echo(f"prof {__version__}")


if __name__ == "__main__":
    main()
