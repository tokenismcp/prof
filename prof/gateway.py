"""PROF Gateway — the enforcement point.

Allow(request) = VerifyProof(Permit) AND Match(request, Permit)
                 AND PolicyAllow(request) AND Fresh(nonce) AND NotExpired(Permit)

Fail-closed: ANY check failure -> deny. Deny is logged to the Ledger.

State-change actions SHOULD carry `pre_state` / `post_state` binding:
  constraints = {"pre_state": "<id>", "idempotency_key": "<k>"}
The gateway verifies args_hash equality (tamper) and nonce freshness (replay).
External side-effects (DB, bank) need idempotency keys — enforced by
requiring the key in constraints for tier high.
"""

from __future__ import annotations

import fnmatch
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from prof.ledger import Ledger
from prof.permit import Permit, hash_args
from prof.policy import Policy
from prof.store import NonceStore


@dataclass
class ExecuteRequest:
    action: str
    resource: str
    args: Dict[str, Any]
    permit: Permit


@dataclass
class GatewayDecision:
    allow: bool
    reason: str
    tier: str = ""
    ledger_seq: int = -1


EffectFn = Callable[[Dict[str, Any]], Dict[str, Any]]


class Gateway:
    def __init__(
        self,
        approver_pubkey: Ed25519PublicKey,
        policy: Policy,
        ledger: Optional[Ledger] = None,
        nonces: Optional[NonceStore] = None,
    ):
        self.approver_pubkey = approver_pubkey
        self.policy = policy
        self.ledger = ledger or Ledger()
        self.nonces = nonces or NonceStore()

    # ---- core enforcement ----
    def authorize(self, req: ExecuteRequest, now: Optional[int] = None) -> GatewayDecision:
        now = int(time.time()) if now is None else int(now)
        p = req.permit

        # 1. VerifyProof
        if not p.verify(self.approver_pubkey):
            return self._deny(req, "deny: bad approval_proof (signature invalid)")

        # 2. NotExpired
        if p.is_expired(now):
            return self._deny(req, f"deny: permit expired (expiry={p.expiry} now={now})")

        # 3. Match(request, Permit): action + resource + args_hash
        if req.action != p.action:
            return self._deny(req, f"deny: action mismatch ({req.action} != {p.action})")
        if not fnmatch.fnmatchcase(req.resource, p.resource) and req.resource != p.resource:
            # permit resource may itself be a glob (delegation); request must be covered
            if not fnmatch.fnmatchcase(req.resource, p.resource):
                return self._deny(req, f"deny: resource mismatch ({req.resource} not in {p.resource})")
        if hash_args(req.args) != p.args_hash:
            return self._deny(req, "deny: args_hash mismatch (tampered amount/target?)")

        # 4. PolicyAllow
        dec = self.policy.evaluate(req.action, req.resource, req.args)
        if not dec.allow:
            return self._deny(req, f"deny: policy ({dec.reason})", tier=dec.tier)
        if p.policy_id != self.policy.policy_id:
            return self._deny(req, f"deny: policy version mismatch ({p.policy_id} != {self.policy.policy_id})", tier=dec.tier)

        # 5. Fresh(nonce) — reserve atomically; replay -> deny.
        # The nonce is bound to the permit expiry, so dead permits are pruned.
        if not self.nonces.check_and_reserve(p.nonce, now, p.expiry):
            return self._deny(req, f"deny: replay (nonce {p.nonce[:12]}... already used)", tier=dec.tier)

        e = self.ledger.append("allow", p.nonce, req.action, req.resource, p.subject, p.agent, f"tier={dec.tier}")
        return GatewayDecision(True, f"allow: tier={dec.tier} {dec.reason}", tier=dec.tier, ledger_seq=e.seq)

    def _deny(self, req: ExecuteRequest, reason: str, tier: str = "") -> GatewayDecision:
        p = req.permit
        try:
            e = self.ledger.append("deny", p.nonce, req.action, req.resource, p.subject, p.agent, reason)
            seq = e.seq
        except Exception:
            seq = -1
        return GatewayDecision(False, reason, tier=tier, ledger_seq=seq)

    def execute(self, req: ExecuteRequest, effect: EffectFn) -> tuple[GatewayDecision, Optional[Dict[str, Any]]]:
        """Authorize then run `effect(args)` only on allow. Effect exceptions -> deny result, no ledger allow.

        The effect receives a copy of args plus `_permit_nonce` so stateful
        effects (payments ledger, file registry) can bind the outcome to the
        exact permit. Verification always uses the original, unmodified args.
        """
        dec = self.authorize(req)
        if not dec.allow:
            return dec, None
        try:
            result = effect({**req.args, "_permit_nonce": req.permit.nonce})
        except Exception as exc:  # fail-closed, record execution failure
            self.ledger.append("deny", req.permit.nonce, req.action, req.resource,
                               req.permit.subject, req.permit.agent, f"effect failed: {exc}")
            return GatewayDecision(False, f"deny: effect failed: {exc}", tier=dec.tier), None
        self.ledger.append("allow", req.permit.nonce + ":result", req.action, req.resource,
                           req.permit.subject, req.permit.agent, "result ok")
        return dec, result
