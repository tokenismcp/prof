# PROF: Proof-Required Operation Framework
## Cryptographic execution control for AI agents

**4Chains Inc. · Technical Whitepaper v1.0 · October 2026**
Companion to the open-source implementation: `https://github.com/tokenismcp/prof`

> This paper describes exactly what the accompanying code does. Every
> security claim maps to an enforced check (§4) with a test (§6); every
> performance number is a measured run with published method (§6).
> Anything not yet built is labeled as such (§7).

---

## 1. Abstract

AI agents act: they call tools, modify files, move money, and change
databases. Natural-language instructions cannot reliably constrain these
side effects against prompt injection, argument tampering, replay, or
privilege escalation. PROF (Proof-Required Operation Framework) moves the
security boundary from the model's reasoning to the **execution step**:
every side effect must carry a signed, scoped, single-use **Permit** that a
server-side **Gateway** verifies before the effect runs, and every decision
is appended to a tamper-evident **Ledger**. Models think freely; only
approved actions execute. The reference implementation (Python, PolyForm Noncommercial + commercial license) covers
a policy engine, an MCP server (stdio + remote Streamable HTTP), an
API-driven LLM agentic loop, a human-approval workflow, and an operations
console — verified by 72 tests and benchmarked with disclosed method.

## 2. Introduction

Existing agent controls cluster at two weak points: *prompt-level*
(system instructions, guardrails — advisory, bypassable by injection) and
*post-hoc* (logging, tracing — detective, not preventive). API-gateway ACLs
enforce at execution time but bind only coarse identity (path/role), not the
exact approved arguments, and rarely prevent replay.

PROF's thesis: **bind the approval to the exact action**. A permit commits
to subject, agent, action, resource, argument hash, policy version, expiry,
nonce, and constraints, signed with Ed25519. The gateway enforces:

```
Allow  =  VerifyProof ∧ Match ∧ PolicyAllow ∧ Fresh ∧ NotExpired
```

Any failing conjunct denies, fail-closed, and the denial is logged.

## 3. Threat model

**In scope** (each enforced + tested): approval tampering (argument/target
swap after signing), replay/retry/cross-session reuse, expired permits,
scope escalation (e.g. `/tmp` → `/etc`), ledger forgery, unknown tool
paths, insufficient funds / duplicate payments, concurrent double-execution
(16-thread race: exactly one allow).

**Out of scope** (stated, not hand-waved): model-output correctness,
general prompt-injection immunity, external-system integrity, multi-node
consensus, HSM attestation, formal verification. The signature proves permit
integrity — nothing more.

## 4. Design

**Permit.** `Permit = (subject, agent, action, resource, args_hash,
policy_id, expiry, nonce, constraints, approval_proof)`, canonical
domain-separated JSON (`prof/v1/permit:`), Ed25519.

**Risk tiers.** Low (pre-delegated reads, auto-approvable), medium
(constrained tokens: limits, expiry, resource prefix), high (explicit human
approval, amount caps). Unmatched requests default-deny; rotating
`policy_id` invalidates outstanding permits.

**Gateway.** The single enforcement point. It verifies the proof, matches
action/resource/`args_hash`, re-evaluates current policy, reserves the nonce
atomically (bound to permit expiry, pruned when dead), and only then runs
the effect — receiving `_permit_nonce` so stateful effects bind outcomes to
permits. Effect exceptions become logged denials.

**Ledger.** Append-only hash chain `h_{t+1} = H(h_t ‖ decision)`, JSONL
persistence (O(1) appends), full re-verification on every check — an
incremental cache was prototyped and *rejected* after review proved it could
miss in-memory tampering of verified entries.

**Human workflow.** High-tier actions open queue requests; a human signs
(`approved_by=human` constraint) or denies via console or API. LLM loops can
block on the queue (`wait_approval`) instead of failing.

## 5. Implementation map

| Paper concept | Code |
|---|---|
| Permit, sign/verify | `prof/permit.py` |
| Policy tiers | `prof/policy.py`, `examples/policies/default.yaml` |
| Gateway enforcement | `prof/gateway.py` |
| Ledger / nonces | `prof/ledger.py`, `prof/store.py` (JSONL, expiry pruning) |
| Real state | `prof/resources.py` (SQLite customers/accounts/payments/files) |
| HTTP API + console | `prof/server.py`, `prof/console/` |
| MCP stdio + remote HTTP | `prof/mcpd.py`, `prof/mcp_http.py` (`POST /mcp`) |
| LLM loop (OpenAI-protocol + Anthropic native) | `prof/llm.py` |
| Agent packs | `integrations/` (Claude Code, Codex, Gemini, Cursor, OpenCode, Dots, Muse, generic) |

## 6. Evaluation

Method: `PYTHONPATH=. python3 bench/bench.py` (raw JSON saved per run).
Reference machine: macOS arm64, Python 3.9.6, 10 cores.

| Operation | p50 | p95 |
|---|---|---|
| authorize + execute (in-process) | 182 µs | 192 µs |
| Ed25519 verify (dominant cost) | 166 µs | 171 µs |
| approve + execute over local HTTP | 1.49 ms | 6.6 ms |
| 8 threads × 250 decisions | 11,458 TPS, 0 mis-decisions | — |
| chain verify, 10k entries | 32.8 ms | — |
| memory | ~0.5 KB/entry | — |

Functional: 72 tests (unit → live-server e2e, incl. LLM→queue→human→payment
with real balance movement, and a 16-thread replay race). Reproduce with
`python -m pytest -q`. No absolute claims are made: single machine,
localhost, software keys; production sizing must re-run with production
stores (§7).

## 7. Limitations and roadmap

Single-node stores (durable, not HA); in-process approval queue;
ledger growth is linear (rotation procedure documented; segmented
checkpoints planned); no HSM/KMS signer yet; no external audit.
Beta: quorum approvals, persistent queue, Postgres/etcd backend.
Enterprise: HSM, HA, SSO, third-party assessment.

## 8. Related work

Model Context Protocol (Anthropic) — PROF's first interface, not its
boundary. API-gateway authorization (coarse identity, weak replay story).
AI-agent guardrails and tracing (advisory/post-hoc). Capability systems and
macaroons (shared lineage: scoped, attenuable bearer credentials; PROF adds
gateway enforcement + hash-chained audit + human workflow).

## 9. Conclusion

PROF connects "what the AI may do" to "what actually executes" with
cryptography, enforcement, and audit — model-agnostic, openly specified,
and honestly measured. Think freely. Act with proof.
