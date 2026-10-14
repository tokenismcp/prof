"""PROF — Proof-Required Operation Framework.

Think Freely. Act With Proof.

Public surface intentionally small: Permit -> Policy -> Gateway -> Ledger.
"""

from prof.permit import Permit, canonical_permit_bytes, hash_args, new_nonce
from prof.policy import Policy, PolicyDecision, load_policy_file, DEFAULT_POLICY
from prof.gateway import Gateway, GatewayDecision, ExecuteRequest
from prof.ledger import Ledger
from prof.identity import Approver, AgentIdentity

__all__ = [
    "Permit",
    "canonical_permit_bytes",
    "hash_args",
    "new_nonce",
    "Policy",
    "PolicyDecision",
    "load_policy_file",
    "DEFAULT_POLICY",
    "Gateway",
    "GatewayDecision",
    "ExecuteRequest",
    "Ledger",
    "Approver",
    "AgentIdentity",
]

__version__ = "0.1.0"
