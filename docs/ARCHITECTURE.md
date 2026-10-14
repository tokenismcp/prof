# PROF Architecture

```
User/Admin → Agent (LLM, untrusted) → request normalize → Policy engine
  → Ed25519 approval verify → PROF Gateway (enforcement) → tools/API/tx
  → result + state check → hash-chained Ledger
```

## Modules

| Module | Role | Trust |
|---|---|---|
| `prof/permit.py` | Permit dataclass, canonical bytes, Ed25519 sign/verify, args_hash | crypto boundary |
| `prof/policy.py` | risk tiers, glob rules, amount caps, human-requirement | policy decision only (no enforcement) |
| `prof/gateway.py` | **enforcement point**: VerifyProof ∧ Match ∧ PolicyAllow ∧ Fresh ∧ NotExpired | must be unbypassable in deployment |
| `prof/ledger.py` | append-only hash chain `h{t+1}=H(h_t \|\| decision)` | tamper-evident |
| `prof/store.py` | nonce reservation (replay), file-persisted | single-node; Postgres/etcd seam for HA |
| `prof/identity.py` | approver keys, agent binding | approver privkey never leaves approver |
| `prof/server.py` | HTTP Gateway (`/v1/approve`, `/v1/execute`) | fail-closed |
| `prof/mcp_adapter.py` | wraps tools with Gateway | agent still untrusted |

## Enforcement formula

```
Permit = (subject, agent, action, resource, args_hash, policy_id, expiry, nonce, constraints, approval_proof)
Allow  = VerifyProof ∧ Match(action/resource/args_hash) ∧ PolicyAllow ∧ Fresh(nonce) ∧ NotExpired
```

- `VerifyProof`: Ed25519 over domain-separated canonical JSON (`prof/v1/permit:`).
- `Match`: exact action; resource supports permit-side globs; `args_hash` must equal `hash_args(request.args)`.
- `PolicyAllow`: current policy version must equal `permit.policy_id`; rule must allow.
- `Fresh`: nonce atomically reserved; reuse (replay, retry, cross-session) denied.
- `NotExpired`: `now <= expiry`; short TTLs (default 300s).

## Deployment rule

> Every real tool path must go through the Gateway. Direct tool credentials must not be reachable by the agent.

In production: Gateway behind mTLS, signer in separate UID/container (HSM/KMS), ledger + nonce stores on durable volumes, `PROF_DEMO=0` + `PROF_APPROVER_PRIV` from a secret manager. See `docs/SECURITY_MODEL.md`.

## Relation to HCCAI / EHCT

PROF is a standalone product, but inherits proven ideas from the separate HCCAI engine: one-shot capabilities, hash-chained audit, fail-closed verification. EHCT (Elliptic Curve Homomorphic Cryptographic Token) is an integration candidate for privacy-preserving budget/amount proofs — it does **not** replace signatures, policy checks, or gateway enforcement. See `docs/ROADMAP.md`.
