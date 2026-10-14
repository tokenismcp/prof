"""Permit model and Ed25519 approval proofs.

Permit = (subject, agent, action, resource, args_hash, policy_id,
          expiry, nonce, constraints, approval_proof)

Security notes (honest, reviewable):
- Ed25519 signatures provide authenticity + integrity of the *permit bytes*.
- They do NOT prove semantic correctness of model output or external systems.
- Replay protection, expiry, and scope matching are enforced by the Gateway,
  not by the signature alone.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


PROF_DOMAIN = b"prof/v1/permit:"


def new_nonce(nbytes: int = 16) -> str:
    return secrets.token_hex(nbytes)


def hash_args(args: Dict[str, Any]) -> str:
    """Stable SHA-256 over canonical JSON of tool arguments."""
    raw = json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def canonical_permit_bytes(d: Dict[str, Any]) -> bytes:
    """Domain-separated canonical bytes for signing / verification.

    Excludes `approval_proof` itself. Keys sorted, compact separators.
    """
    payload = {k: v for k, v in d.items() if k != "approval_proof"}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return PROF_DOMAIN + raw


@dataclass
class Permit:
    subject: str          # human / org approving, e.g. "user:alice"
    agent: str            # agent identity, e.g. "agent:crm-helper:01"
    action: str           # e.g. "tool.call", "file.write", "payment.transfer"
    resource: str         # e.g. "tool:crm.lookup", "file:/repo/**", "account:krw-*"
    args_hash: str        # hash_args(tool args)
    policy_id: str        # policy version, e.g. "default@v3"
    expiry: int           # unix seconds
    nonce: str = field(default_factory=new_nonce)
    constraints: Dict[str, Any] = field(default_factory=dict)
    approval_proof: str = ""  # base64 signature over canonical bytes

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Permit":
        return cls(**d)

    def is_expired(self, now: Optional[int] = None) -> bool:
        return int(time.time() if now is None else now) > int(self.expiry)

    def sign(self, private_key: Ed25519PrivateKey) -> "Permit":
        sig = private_key.sign(canonical_permit_bytes(self.to_dict()))
        self.approval_proof = base64.b64encode(sig).decode("ascii")
        return self

    def verify(self, public_key: Ed25519PublicKey) -> bool:
        try:
            sig = base64.b64decode(self.approval_proof.encode("ascii"))
            public_key.verify(sig, canonical_permit_bytes(self.to_dict()))
            return True
        except (InvalidSignature, ValueError, KeyError):
            return False


def generate_approver_keypair() -> tuple[Ed25519PrivateKey, Ed25519PublicKey]:
    sk = Ed25519PrivateKey.generate()
    return sk, sk.public_key()


def b64_pubkey(pk: Ed25519PublicKey) -> str:
    return base64.b64encode(pk.public_bytes_raw()).decode("ascii")


def load_pubkey(s: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(s.encode("ascii")))


def b64_privkey(sk: Ed25519PrivateKey) -> str:
    return base64.b64encode(sk.private_bytes_raw()).decode("ascii")


def load_privkey(s: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(base64.b64decode(s.encode("ascii")))
