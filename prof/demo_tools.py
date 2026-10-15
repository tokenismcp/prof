"""Demo helpers (kept for backward compatibility).

Real tool effects now live in prof.resources (SQLite-backed, persistent).
This module re-exports them and builds demo gateways, so existing
imports keep working.
"""

from __future__ import annotations

from prof.gateway import Gateway
from prof.identity import Approver
from prof.ledger import Ledger
from prof.policy import DEFAULT_POLICY
from prof.resources import crm_lookup, file_write, get_db, payment_transfer, reset_db
from prof.store import NonceStore

__all__ = ["crm_lookup", "file_write", "payment_transfer", "get_db", "reset_db",
           "build_demo_gateway", "demo_pubkey_b64"]


def build_demo_gateway(approver: Approver | None = None, ledger_path: str | None = None,
                       nonce_path: str | None = None, db_path: str | None = None
                       ) -> tuple[Approver, Gateway]:
    approver = approver or Approver.generate("user:demo")
    reset_db(db_path)
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
