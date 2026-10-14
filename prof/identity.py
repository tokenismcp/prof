"""PROF Identity: approvers (humans) and agents.

- Approver holds an Ed25519 keypair. Private key NEVER leaves approver side.
  In v0.1 the demo generates ephemeral keys in-memory; production uses
  OS keychain / KMS / HSM via the `Signer` seam (see docs).
- AgentIdentity is untrusted metadata bound into the Permit.
"""

from __future__ import annotations

from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from prof.permit import b64_privkey, b64_pubkey, load_privkey, load_pubkey


@dataclass
class Approver:
    subject: str  # e.g. "user:alice"
    _sk: Ed25519PrivateKey

    @classmethod
    def generate(cls, subject: str) -> "Approver":
        return cls(subject, Ed25519PrivateKey.generate())

    @property
    def pubkey(self) -> Ed25519PublicKey:
        return self._sk.public_key()

    @property
    def pubkey_b64(self) -> str:
        return b64_pubkey(self.pubkey)

    def export_private_b64(self) -> str:
        return b64_privkey(self._sk)

    @classmethod
    def from_private_b64(cls, subject: str, s: str) -> "Approver":
        return cls(subject, load_privkey(s))

    def sign_permit(self, permit) -> None:
        from prof.permit import Permit as _P  # local import for typing only
        permit.sign(self._sk)


@dataclass
class AgentIdentity:
    agent_id: str   # e.g. "agent:crm-helper:01"
    session: str = "default"

    def __str__(self) -> str:
        return self.agent_id
