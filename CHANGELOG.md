# Changelog

## v0.1.0 (2026-10-14) — Developer Preview
- Permit (Ed25519) + canonical signing bytes + args_hash binding
- Risk-based policy engine (low/medium/high) + YAML policies
- Gateway enforcement: VerifyProof ∧ Match ∧ PolicyAllow ∧ Fresh ∧ NotExpired, fail-closed
- Hash-chained ledger (tamper-evident) + nonce replay store (crash-durable)
- Gateway HTTP server (`/v1/approve`, `/v1/execute`, `/v1/ledger`) + `prof` CLI + `prof demo`
- MCP adapter + 3 reference workflows (tool call, file modify, payment)
- 9 tests, CI, Docker, docs (architecture / security model / verification / roadmap)
