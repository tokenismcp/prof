"""Demo tool implementations (pure functions, no network).

Three reference workflows from the product spec:
1. tool.call  — CRM lookup (low risk)
2. file.write — sandboxed file modification (medium/high by path)
3. payment.transfer — payment request with amount limits (high)
"""

from __future__ import annotations

import os
from typing import Any, Dict

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from prof.gateway import Gateway
from prof.identity import Approver
from prof.ledger import Ledger
from prof.policy import DEFAULT_POLICY
from prof.store import NonceStore


def crm_lookup(args: Dict[str, Any]) -> str:
    customer = args.get("customer", "unknown")
    return f"customer:{customer}:tier=gold:balance=125000"


CRM_ROOT = "/tmp/prof-demo"


def file_write(args: Dict[str, Any]) -> str:
    path = args.get("path", "")
    content = args.get("content", "")
    # sandbox: only allow CRM_ROOT or /tmp
    norm = os.path.normpath(path)
    if not (norm.startswith(CRM_ROOT) or norm.startswith("/tmp/")):
        raise PermissionError(f"outside sandbox: {path}")
    os.makedirs(os.path.dirname(norm) or "/tmp", exist_ok=True)
    with open(norm, "w", encoding="utf-8") as f:
        f.write(content)
    return f"wrote {len(content)} bytes to {norm}"


PAYMENTS: list = []


def payment_transfer(args: Dict[str, Any]) -> str:
    to = args.get("to", "")
    amount = float(args.get("amount", 0))
    key = args.get("idempotency_key", "")
    if amount <= 0:
        raise ValueError("amount must be > 0")
    for p in PAYMENTS:
        if p.get("idempotency_key") == key and key:
            raise ValueError(f"duplicate idempotency_key {key}")
    PAYMENTS.append({"to": to, "amount": amount, "idempotency_key": key})
    return f"transferred {amount} to {to} (key={key})"


def build_demo_gateway(approver: Approver | None = None, ledger_path: str | None = None,
                       nonce_path: str | None = None) -> tuple[Approver, Gateway]:
    approver = approver or Approver.generate("user:demo")
    gw = Gateway(
        approver_pubkey=approver.pubkey,
        policy=DEFAULT_POLICY,
        ledger=Ledger(ledger_path),
        nonces=NonceStore(nonce_path),
    )
    return approver, gw


def demo_pubkey_b64() -> str:
    a, _ = build_demo_gateway()
    return a.pubkey_b64
