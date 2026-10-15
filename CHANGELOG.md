# Changelog

## v0.1.0 (2026-10-14) — Developer Preview
- Permit (Ed25519) + canonical signing bytes + args_hash binding
- Risk-based policy engine (low/medium/high) + YAML policies
- Gateway enforcement: VerifyProof ∧ Match ∧ PolicyAllow ∧ Fresh ∧ NotExpired, fail-closed
- Hash-chained ledger (tamper-evident) + nonce replay store (crash-durable)
- Gateway HTTP server (`/` → `/console`, `/v1/approve`, `/v1/execute`, `/v1/ledger`, `/v1/policy`, `/healthz`, `/readyz`) + `prof` CLI + `prof demo`
- Console (`/console`, dashboard-only): sidebar nav, KPI deltas, area chart, live feed, toasts, permit inspector, 5-scenario red team, searchable ledger drawer, policy tiers — no emojis, white logo assets
- Real data layer (`prof/resources.py`): SQLite customers/accounts/payments/file registry, balances in cents, persisted idempotency, hash-chained file writes, sandbox enforcement, `PROF_DB` for production persistence
- LLM API integration (`prof/llm.py`): provider-agnostic OpenAI-compatible client (stdlib only) + proof-required agentic loop (`prof agent-run`, `prof llm-check`), high-tier needs human sign-off
- Agent surface hardened: `prof-mcp` now runs the real stdio server, `examples/mcp_server.py` is a working launcher, protocol tests run against the installed binary
- Production deploy: hardened image, compose with volume/healthcheck/logging, Caddy TLS edge, k8s manifests, env template, backup/restore scripts, operations runbook
- MCP adapter + 3 reference workflows (tool call, file modify, payment)
- 14 tests, CI, Docker, docs
