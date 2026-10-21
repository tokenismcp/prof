# Changelog

## v1.0.0 — release audit (before first public release)
- **License:** MIT -> PolyForm Noncommercial 1.0.0 + paid commercial license (`COMMERCIAL-LICENSE.md`).
- **Security (see `docs/AUDIT.md`):** agents can no longer self-issue high-tier permits via `/v1/approve` or MCP `prof.approve` (`PROF_REQUIRE_HUMAN` now defaults on); HTTP `/mcp` shares the server's key, ledger and nonce store; payment cap rejects NaN/negative/missing amounts; `..` resources denied; nonce kept through the permit's final valid second; torn-append recovery for ledger/nonce journals, interior corruption refuses to start; symlink-safe file sandbox; LLM API key never sent to caller-chosen endpoints; `/v1/ledger` needs the token; `llm.env` injection closed; gateway refuses a public bind without a strong `PROF_API_TOKEN`; startup ledger verification; permit TTL cap (`PROF_MAX_TTL_S`).
- 22 new regression tests (`tests/test_audit.py`).

## v1.0.0 (2026-10-16)
- First stable release. Everything below, hardened and fully tested.
- Korean/English console UI (toggle, persisted, tested). Provider-matched LLM catalogs, latest models, per-model tool-calling flag (non-tool models flagged and blocked from save/run).
- Transparent agents (auto-approve), remote MCP for Dots/Muse, approval queue.
- Agent task inbox: queue a task in the console ("Queue for an agent") and any connected agent claims it over MCP (`prof.task.next` / `prof.task.done` / `prof.task.list`) and reports back; `prof task add|list|next|done` CLI + `POST /v1/tasks` REST; atomic single-claim with token-bound completion and stale-claim reclaim.
- 98 tests green (incl. release-hygiene + i18n parity + console-asset parse), performance audit published, whitepaper included.
- Verified packaging: sdist contains console/integrations/examples/docs, clean reinstall validated, Docker 1.0.0 smoke-tested.

## v0.1.0 (2026-10-14) — Developer Preview
- Permit (Ed25519) + canonical signing bytes + args_hash binding
- Risk-based policy engine (low/medium/high) + YAML policies
- Gateway enforcement: VerifyProof ∧ Match ∧ PolicyAllow ∧ Fresh ∧ NotExpired, fail-closed
- Hash-chained ledger (tamper-evident) + nonce replay store (crash-durable)
- Gateway HTTP server (`/` → `/console`, `/v1/approve`, `/v1/execute`, `/v1/ledger`, `/v1/policy`, `/healthz`, `/readyz`) + `prof` CLI + `prof demo`
- Console (`/console`, dashboard-only): light top-nav layout, transparent logo with no backdrop box, approver identity panel, ledger JSON export, copy-as-curl, ledger-derived metrics (restart-durable), `/v1/ledger?limit=`, `key_source` in `/version`
- Human approval queue (`POST/GET /v1/requests`, `.../approve`, `.../deny`): high-tier actions open human-signed permits with `approved_by` binding, pending queue + polling in console, ledger-logged transitions
- Agent surface in console (Agents tab): LLM status, in-browser task runner on `POST /v1/agent/run`, copy-paste MCP/hook snippets
- Fixed `_effect` routing bug: non-exact resources (e.g. `account:krw-1`) were wrongly denied over HTTP; glob-matched effects now resolve correctly
- Security hardening: Bearer auth (`PROF_API_TOKEN`) on writes + approval queue, security headers, 1 MB body cap, per-IP rate limits, console token prompt; secrets never logged
- True integration: remote gateway client (`prof/client.py`, `PROF_GATEWAY_URL` mode for MCP), LLM loop ↔ approval queue via `wait_approval`, `agent_run` ledger summaries, 16-thread replay race test, audit-completeness test, live-server e2e
- Transparent agents: `POST /v1/auto-approve` (server-minted permits for non-human tiers, TTL ≤ 300 s, 403 for high-tier); MCP tools work permit-less for low/medium with explicit permits still honored; high-tier without permit returns the human-approval path instead of failing cryptically
- Remote MCP over Streamable HTTP (`POST /mcp`, stateless, Bearer-gated): the shape OpenAI Dots (custom MCP app) and Meta Muse (chat-built custom connector) require — stdio/localhost can't reach vendor clouds. Packs: `integrations/dots/`, `integrations/muse/` (setup, approval mapping, verification, honest limits); public HTTPS via existing compose edge profile
- Compact console (5 tabs): verification folded into Overview as one-line checks, Agents tab gains provider/model selection with per-run override (`provider_override`, validated 400) and save-to-gateway
- Deep performance audit: `bench/bench.py` v2 (percentiles, component costs, persistence modes, threaded TPS, verify scaling, RSS/entry, optional live HTTP) + `docs/PERFORMANCE.md` with reference numbers and rotation guidance
- Storage hardening: expiry-bound nonce pruning (safe: expired permits deny anyway), JSONL journals for nonces+ledger (O(1) appends), legacy format migration, rejected unsound incremental verify (documented), 401/429 stderr audit logging, `prof audit` CLI, DB in backup script
- Real data layer (`prof/resources.py`): SQLite customers/accounts/payments/file registry, balances in cents, persisted idempotency, hash-chained file writes, sandbox enforcement, `PROF_DB` for production persistence
- LLM provider layer: 7 presets (ollama/lmstudio/vllm/openai/azure/openrouter/anthropic-native), `prof llm-setup` wizard with local probing + model listing, `/v1/llm/models` surface, per-run model override + `POST /v1/llm/config` persistence (keys never stored), Agents tab provider/model UI — verified live vs local Ollama
- Agent surface hardened: `prof-mcp` now runs the real stdio server, `examples/mcp_server.py` is a working launcher, protocol tests run against the installed binary
- Production deploy: hardened image, compose with volume/healthcheck/logging, Caddy TLS edge, k8s manifests, env template, backup/restore scripts, operations runbook
- MCP adapter + 3 reference workflows (tool call, file modify, payment)
- 14 tests, CI, Docker, docs
