# Security Policy

**Do not open public issues for vulnerabilities.** Email the maintainers (see GitHub repo security tab) with:

- affected version (`prof version`), config, policy id
- reproduction (redact private keys **and `PROF_API_TOKEN`**), impact assessment

## Enforcement layers (all live, all tested)

- **Bearer auth**: set `PROF_API_TOKEN` and every state-changing or
  approval-queue endpoint requires `Authorization: Bearer`. Reads
  (ledger, policy, metrics, health) stay open for transparency. The console
  prompts for the token (lock icon, per-tab session storage).
- **Security headers** on every response (`nosniff`, `DENY` framing,
  no referrer). **1 MB body cap** (413) and **per-IP rate limiting**
  on hot mutating paths (`PROF_RATE_LIMIT`/min, 429 + `Retry-After`).
- **Fail-closed everywhere**: bad permits, expired/replayed/tampered,
  unknown tools, effect errors, unreachable LLM (502) — all denied and
  ledger-logged, never crashing the server loop.

## Boundaries (v0.1)

- Agent/SDK/LLM is **untrusted**. Gateway verifies server-side.
- Demo keys are **ephemeral in-memory** (`key_source: ephemeral` in
  `/version`). Production must provide `PROF_APPROVER_PRIV` from a secret
  manager or HSM signer, TLS termination, and persistent stores —
  `key_source: configured` is visible in the console Approver panel.
- The approval queue is **in-process** (lost on restart; transitions are
  ledger-logged). A persistent queue is Beta roadmap.
- Signatures prove permit integrity, not model-output correctness.

We aim to acknowledge reports within 72h and publish fixes with a CHANGELOG entry.
