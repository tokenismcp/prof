# Changelog

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
- Deep performance audit: `bench/bench.py` v2 (percentiles, component costs, persistence modes, threaded TPS, verify scaling, RSS/entry, optional live HTTP) + `docs/PERFORMANCE.md` with reference numbers and rotation guidance
- Storage hardening: expiry-bound nonce pruning (safe: expired permits deny anyway), JSONL journals for nonces+ledger (O(1) appends), legacy format migration, rejected unsound incremental verify (documented), 401/429 stderr audit logging, `prof audit` CLI, DB in backup script
- Real data layer (`prof/resources.py`): SQLite customers/accounts/payments/file registry, balances in cents, persisted idempotency, hash-chained file writes, sandbox enforcement, `PROF_DB` for production persistence
- LLM provider layer: 7 presets (ollama/lmstudio/vllm/openai/azure/openrouter/anthropic-native), `prof llm-setup` wizard with local probing + model listing, `/v1/llm/models` surface, per-run model override + `POST /v1/llm/config` persistence (keys never stored), Agents tab provider/model UI — verified live vs local Ollama
- Agent surface hardened: `prof-mcp` now runs the real stdio server, `examples/mcp_server.py` is a working launcher, protocol tests run against the installed binary
- Production deploy: hardened image, compose with volume/healthcheck/logging, Caddy TLS edge, k8s manifests, env template, backup/restore scripts, operations runbook
- MCP adapter + 3 reference workflows (tool call, file modify, payment)
- 14 tests, CI, Docker, docs
