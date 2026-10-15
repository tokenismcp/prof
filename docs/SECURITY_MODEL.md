# PROF Security Model

## What PROF proves

- The **permit bytes** (who approved what action/resource/args/policy/expiry/nonce) are authentic and unmodified (Ed25519).
- The executed request **matches** the approved permit (no swapped target, amount, or file path).
- The permit is **fresh** (not replayed) and **unexpired**, and allowed by the **current policy version**.
- Every approve/allow/deny is appended to a **tamper-evident ledger**.

## What PROF does NOT claim

- Model-output correctness, prompt-injection immunity in general, or external-system integrity.
- "100% blocking" or microsecond overhead as universal guarantees. See `docs/VERIFICATION.md`.
- Multi-node HA, HSM attestation, or formal verification in v1.0.

## Threats handled (with tests)

| Threat | Enforcement | Test |
|---|---|---|
| Approval tamper (swap amount/target) | `args_hash` equality | `test_deny_tamper`, `test_payment_amount_tamper` |
| Replay / retry / cross-session reuse | nonce reservation | `test_deny_replay`, `test_cross_session_reuse_denied` |
| Expired permit | `NotExpired` | `test_deny_expiry` |
| Scope escalation (`/tmp` → `/etc`) | resource match | `test_deny_scope_escalation` |
| Ledger forgery | hash-chain verify | `test_ledger_tamper_evident` |
| Unknown tool path | no registered effect → deny | server `_effect` fail-closed |

## Remaining threats (roadmap)

Prompt injection → tool-result poisoning, TOCTOU on external state, gateway bypass at infra layer, approver-key compromise, multi-agent confused deputy, idempotency gaps on external payments. Mitigations: result/state binding (`pre_state`/`post_state`), idempotency keys, infra network policy (no direct tool creds for agents), short TTL + narrow scope + key rotation, quorum approvals. See `docs/ROADMAP.md`.
