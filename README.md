<p align="center">
  <img src="./logo.png" alt="PROF — Think Freely. Act With Proof." width="480" />
</p>

<h1 align="center">PROF — Proof-Required Operation Framework</h1>
<p align="center"><b>Think Freely. Act With Proof.</b><br/>Cryptographic execution control for AI agents. Model-agnostic. MCP-ready.</p>

<p align="center">
  <a href="https://github.com/4chains-inc/prof"><img alt="stars" src="https://img.shields.io/github/stars/4chains-inc/prof?style=social" /></a>
  <img alt="python" src="https://img.shields.io/badge/python-3.9%2B-blue" />
  <img alt="license" src="https://img.shields.io/badge/license-MIT-green" />
  <img alt="ci" src="https://img.shields.io/badge/ci-passing-brightgreen" />
  <img alt="status" src="https://img.shields.io/badge/status-developer%20preview-orange" />
</p>

> AI should reason freely — but only **approved actions** may execute. PROF binds every side-effect (tool call, file write, payment, DB change) to a signed, scoped, single-use **Permit**, verified at a server-side **Gateway** and recorded in a tamper-evident **Ledger**.

---

## 5-minute quickstart

```sh
git clone https://github.com/4chains-inc/prof && cd prof
pip install -e ".[dev]"
python -m prof demo
```

Real output:

```
[PROF demo] approver=user:demo policy=default@v1
 1. legit request      -> ALLOW (tier=low ...)
 2. tampered args      -> DENY (args_hash mismatch)
 3. replay same permit -> DENY (replay, nonce already used)
 4. amount tamper      -> DENY (args_hash mismatch)
 ledger: ok: 5 entries ...
DEMO PASS: legit allowed, attacks denied. Think Freely. Act With Proof.
```

Then:

```sh
python examples/01_tool_call.py       # CRM lookup (low-risk allow)
python examples/02_file_modify.py     # file write + tamper-deny
python examples/03_payment_request.py # payment + replay-deny
python -m prof gateway                # HTTP gateway on :8091
```

## Console dashboard & product page

`python -m prof gateway`, then:

- **http://127.0.0.1:8091/** — product landing (hero, quickstart, risk tiers, roadmap)
- **http://127.0.0.1:8091/console/** — operations console:
  - *Overview*: allow/deny KPIs, decision-mix donut, activity sparkline, live event feed, one-click full demo
  - *Approve & Execute*: 3-step workflow with permit inspector (expiry countdown, args-hash, nonce) + copy
  - *Red Team*: 5 scenarios (legit / tamper / replay / expired / scope escalation) with expected-verdict badges
  - *Ledger*: filter by event, full-text search, click any row for the hash-linked entry detail
  - *Policy*: tier badges, caps, default-deny note

## Production deploy

```sh
cp configs/prof.env.example configs/prof.env   # fill PROF_APPROVER_PRIV
docker compose up -d --build
curl -sf localhost:8091/readyz && echo READY
```

- Hardened image (non-root, healthcheck), named volume for ledger+nonces, `unless-stopped`, log rotation
- Optional TLS edge: `PROF_DOMAIN=prof.example.com docker compose --profile edge up -d`
- Kubernetes: `deploy/k8s.yaml` (secret + PVC + probes + resource limits)
- Runbook: [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — keys, rotation, monitoring, backup/restore, bypass incident

---

## How it works

```
User/Admin → Agent (LLM, untrusted) → normalize → Policy → Ed25519 verify
  → PROF Gateway (enforce) → tools/API/tx → Ledger
```

```python
Permit = (subject, agent, action, resource, args_hash, policy_id, expiry, nonce, constraints, approval_proof)
Allow  = VerifyProof ∧ Match ∧ PolicyAllow ∧ Fresh(nonce) ∧ NotExpired
```

| Tier | Examples | Behavior |
|---|---|---|
| 🟢 low | `tool:crm.lookup`, `file.read` | pre-delegated scope, auto-approvable |
| 🟡 medium | `tool:*`, `file:/tmp/**`, `message.send` | constrained token (limits, expiry, prefix) |
| 🔴 high | `payment.*`, `db.*`, `system.*` | explicit human approval, amount caps |

Full design: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · policy: [`docs/POLICY.md`](docs/POLICY.md) · MCP: [`docs/MCP.md`](docs/MCP.md)

## HTTP Gateway

```sh
curl -s localhost:8091/version
curl -s -X POST localhost:8091/v1/approve -H 'content-type: application/json' \
  -d '{"agent":"agent:web","action":"tool.call","resource":"tool:crm.lookup","args":{"customer":"acme-42"}}'
```

`POST /v1/execute` enforces server-side and runs the registered effect only on allow. Unknown tool paths → deny (fail-closed).

## Security: honest boundaries

What PROF proves: permit authenticity + integrity (Ed25519), request-permit match, freshness, expiry, policy-version binding, and a hash-chained audit trail.

What it does **not** claim: model-output correctness, universal prompt-injection immunity, "100% blocking", or fixed microsecond overhead. Earlier internal notes ("12.4µs", "~200 scenarios") lack published env/code/taxonomy — so they are **not** product claims. Reproduce locally: `python -m pytest -q`, `python bench/bench.py` (prints env + p50/p95).

Details: [`docs/SECURITY_MODEL.md`](docs/SECURITY_MODEL.md) · [`docs/VERIFICATION.md`](docs/VERIFICATION.md) · [`docs/COMPARISON.md`](docs/COMPARISON.md)

## Threats covered (tested)

| Attack | Result |
|---|---|
| Tampered amount/target after approval | DENY (`args_hash` mismatch) |
| Replay / retry / cross-session reuse | DENY (nonce spent) |
| Expired permit | DENY |
| Scope escalation (`/tmp` → `/etc`) | DENY |
| Ledger forgery | detected by chain verify |

## Roadmap

- **v0.1 Developer Preview** (here): Core, Gateway, MCP adapter, CLI, 3 reference workflows
- **Beta**: EHCT adapter, approval UI, audit console, quorum, load/fault tests
- **Enterprise**: KMS/HSM, HA stores, SSO/IAM, external assessment
- **Ecosystem**: LangChain/LlamaIndex adapters, TS SDK parity

See [`docs/ROADMAP.md`](docs/ROADMAP.md). Open-core: this repo (MIT) is the community core; Team Cloud / Enterprise are commercial options.

## Repo layout

```
prof/            core (permit/policy/gateway/ledger/store/identity/server/cli/mcp_adapter/console)
examples/        01_tool_call · 02_file_modify · 03_payment_request · mcp_server · policies/
deploy/          k8s.yaml · Caddyfile (TLS edge)
configs/         prof.env.example (production env template)
scripts/         backup.sh · restore.sh
sdk-typescript/  TS Gateway client (beta)
bench/           local microbenchmark (env-disclosed)
docs/            ARCHITECTURE · SECURITY_MODEL · VERIFICATION · ROADMAP · MCP · POLICY · COMPARISON · OPERATIONS
tests/           14 enforcement + API tests
```

## Contributing

Fail-closed first, no absolute claims, small reviewable PRs. See [`CONTRIBUTING.md`](CONTRIBUTING.md). Security reports: [`SECURITY.md`](SECURITY.md) (private, 72h ack).

---

<p align="center"><b>Think Freely. Act With Proof.</b> — 4Chains Inc., PROF v0.1 Developer Preview.<br/>Standalone from HCCAI; inherits its one-shot capability + hash-chain audit ideas. EHCT is an integration candidate, not a replacement for signatures or enforcement.</p>
