<p align="center">
  <img src="./logo-white.png" alt="PROF — Think Freely. Act With Proof." width="480" />
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

> AI should reason freely — but only **approved actions** may execute. PROF binds every side-effect (tool call, file write, payment) to a signed, scoped, single-use **Permit**, verified at a server-side **Gateway** and recorded in a tamper-evident **Ledger**.

---

## 5-minute quickstart

```sh
git clone https://github.com/4chains-inc/prof && cd prof
sh integrations/install.sh   # installs + verifies + prints MCP JSON (works on old pip too)
prof demo
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

## Console dashboard

`python -m prof gateway`, then open **http://127.0.0.1:8091/** (redirects to the console):

  - *Overview*: allow/deny KPIs, decision-mix donut, activity chart, live events, compact verification checks, approver identity (subject, key source, fingerprint) + pending human approvals with one-click sign/deny
  - *Approve & Execute*: 3-step workflow with permit inspector (expiry countdown, args-hash, nonce) + copy + copy-as-curl + human-approval request with auto-poll
  - *Agents & LLM*: provider/model selection (8 presets, per-run override or save-to-gateway), connection status, in-browser task runner with wait-for-approval, remote MCP self-test + endpoint URL, per-agent setup panes (Dots/Muse/Claude/Codex/Gemini/Cursor/hook)
  - *Ledger*: filter by event, full-text search, click any row for the hash-linked entry detail, JSON export
  - *Policy*: tier badges, caps, default-deny note

## Production deploy

```sh
cp configs/prof.env.example configs/prof.env   # fill PROF_APPROVER_PRIV + PROF_API_TOKEN
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
| low | `tool:crm.lookup`, `file.read` | pre-delegated scope, auto-approvable |
| medium | `tool:*`, `file:/tmp/**`, `message.send` | constrained token (limits, expiry, prefix) |
| high | `payment.*`, `db.*`, `system.*` | explicit human approval, amount caps |

Full design: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · policy: [`docs/POLICY.md`](docs/POLICY.md) · MCP: [`docs/MCP.md`](docs/MCP.md)

## Agent integrations

| Agent | Setup |
|---|---|
| Claude Code | `claude mcp add prof -- prof mcp` + PreToolUse hook (`integrations/claude-code/`) |
| Codex CLI | append `integrations/codex/config-snippet.toml` to `~/.codex/config.toml` |
| Gemini CLI | merge `integrations/gemini/settings-snippet.json` into `~/.gemini/settings.json` |
| Cursor / Windsurf / Cline / VS Code | `integrations/cursor/mcp.json` |
| OpenCode | `integrations/opencode/opencode.json` |
| Dots (OpenAI) | remote MCP app: `https://<domain>/mcp` + key (`integrations/dots/`) |
| Muse (Meta) | chat-built custom connector, copy-paste prompt (`integrations/muse/`) |
| Others (shell hooks) | `prof exec -- …` / `integrations/generic/prof-gate.sh` |

Two surfaces: **MCP server** (`prof mcp`, stdio, zero deps — transparent for low/medium, human-gated for high-tier) and **shell gate** (`prof exec`, `prof decide --claude-hook`). Details + mapping table: [`docs/AGENTS.md`](docs/AGENTS.md).

## Human approvals (high-tier workflow)

High-risk actions don't self-approve — they open a request a human signs in the console (Overview → Approver → pending) or via API:

```sh
curl -s -X POST localhost:8091/v1/requests -H 'content-type: application/json' \
  -d '{"agent":"agent:llm","action":"payment.transfer","resource":"account:krw-1",
       "args":{"to":"acct-9","amount":100,"idempotency_key":"q-1"}}'
# → {"id":"req-…","status":"pending",…}
curl -s -X POST localhost:8091/v1/requests/req-…/approve   # human signs → permit
curl -s -X POST localhost:8091/v1/requests/req-…/deny -d '{"reason":"…"}'
```

Query `GET /v1/requests?status=pending|all`. Every transition is ledger-logged. The Operate tab's "Request human approval" polls until decided and loads the signed permit automatically.

## LLM integration (API-based)

Provider-agnostic agentic loop over local or hosted models — every model-requested tool call is approved and executed through the Gateway against the real database:

```sh
prof llm-setup   # probes Ollama/LM Studio, picks model, verifies
prof agent-run "What tier is customer acme-42?"
prof agent-run "Send 100 to acct-9" --human-approve   # high-tier needs sign-off
```

Providers: `ollama` (default, local, no key) · `lmstudio` · `vllm` · `openai` · `azure` · `openrouter` · `anthropic` (native API, translated tools) · `gemini`. Keys stay env-only — never logged, never in API responses. Details: [`docs/LLM.md`](docs/LLM.md). Real state behind the tools: [`docs/DATA.md`](docs/DATA.md) (SQLite customers/accounts/payments/file registry, persistent via `PROF_DB`).

## HTTP Gateway
```sh
curl -s localhost:8091/version
curl -s -X POST localhost:8091/v1/approve -H 'content-type: application/json' \
  -d '{"agent":"agent:web","action":"tool.call","resource":"tool:crm.lookup","args":{"customer":"acme-42"}}'
```

`POST /v1/execute` enforces server-side and runs the registered effect only on allow. Unknown tool paths → deny (fail-closed).

## Performance (measured)

Reference machine (macOS arm64, Python 3.9): authorize+execute **p50 182 µs** in-process, **p50 1.5 ms** over local HTTP; 8-thread **11,458 TPS with 0 mis-decisions**; 10k-entry chain verifies in 33 ms. Bottleneck at scale is ledger growth (~0.5 KB/entry) — see rotation procedure. Full tables, method, limits: [`docs/PERFORMANCE.md`](docs/PERFORMANCE.md). Reproduce: `PYTHONPATH=. python3 bench/bench.py`.

## Security (on by default where configured)

Set `PROF_API_TOKEN` and all writes + the approval queue require Bearer auth (console lock icon prompts per tab). Every response carries hardened headers; 1 MB body cap and per-IP rate limiting (`PROF_RATE_LIMIT`) on hot paths. Full model: [`SECURITY.md`](SECURITY.md).

## Security: honest boundaries

What PROF proves: permit authenticity + integrity (Ed25519), request-permit match, freshness, expiry, policy-version binding, and a hash-chained audit trail.

What it does **not** claim: model-output correctness, universal prompt-injection immunity, "100% blocking", or fixed microsecond overhead. Earlier internal notes ("12.4µs", "~200 scenarios") lack published env/code/taxonomy — so they are **not** product claims. Reproduce locally: `python -m pytest -q`, `PYTHONPATH=. python3 bench/bench.py` (prints env + p50/p95).

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

- **v0.1 Developer Preview** (here): Core, Gateway, MCP + remote MCP, CLI, console, approval queue, LLM loop, 3 reference workflows
- **Beta**: EHCT adapter, quorum approvals, persistent queue, load/fault tests, segmented ledger checkpoints
- **Enterprise**: KMS/HSM, HA stores, SSO/IAM, external assessment
- **Ecosystem**: LangChain/LlamaIndex adapters, TS SDK parity

See [`docs/ROADMAP.md`](docs/ROADMAP.md). Open-core: this repo (MIT) is the community core; Team Cloud / Enterprise are commercial options.

## Repo layout

```
prof/            core (permit/policy/gateway/ledger/store/identity/server/cli/client/resources/llm/mcpd/mcp_http/console)
examples/        01_tool_call · 02_file_modify · 03_payment_request · mcp_server · policies/
integrations/    claude-code · codex · gemini · cursor · opencode · dots · muse · generic + install.sh
deploy/          k8s.yaml · Caddyfile (TLS edge)
configs/         prof.env.example (production env template)
scripts/         backup.sh · restore.sh
sdk-typescript/  TS Gateway client (beta)
papers/          PROF-whitepaper-v0.1.md (this paper)
bench/           local microbenchmark (env-disclosed)
docs/            ARCHITECTURE · SECURITY_MODEL · VERIFICATION · ROADMAP · MCP · POLICY · COMPARISON · OPERATIONS · AGENTS · LLM · DATA
tests/           72 enforcement + API + MCP + LLM + data + storage + security + e2e tests
```

## Contributing

Fail-closed first, no absolute claims, small reviewable PRs. See [`CONTRIBUTING.md`](CONTRIBUTING.md). Security reports: [`SECURITY.md`](SECURITY.md) (private, 72h ack).

---

<p align="center"><b>Think Freely. Act With Proof.</b> — 4Chains Inc., PROF v0.1 Developer Preview.<br/>Standalone from HCCAI; inherits its one-shot capability + hash-chain audit ideas. EHCT is an integration candidate, not a replacement for signatures or enforcement.</p>
