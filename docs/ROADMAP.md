# PROF Roadmap

## Phase 1 — Developer Preview (this release, v0.1)
- [x] Core SDK, Gateway, sample policy, CLI, MCP adapter (stdio + remote HTTP)
- [x] 3 reference workflows + full demo (allow / tamper / replay / amount-tamper)
- [x] Threat tests + ledger verification + SQLite resource layer
- [x] Console dashboard, approval queue UI, LLM loop, agent integrations

## Phase 2 — Public Beta
- [ ] EHCT adapter (privacy-preserving budget proofs)
- [ ] Multi-agent scoping, quorum approvals, SSO (OIDC), persistent queue
- [ ] External pilot, segmented ledger checkpoints

## Phase 3 — Enterprise
- [ ] KMS/HSM + key rotation, Postgres/etcd linearizable nonce store, HA gateway
- [ ] Policy versioning, transparency log / witness cosigning
- [ ] External security assessment, ops docs, SLA

## Phase 4 — Ecosystem
- [ ] LangChain/LlamaIndex/CrewAI adapters, TS/Python SDK parity, partner marketplace
- [ ] Compatibility matrix + community metrics (installs, active projects, protected executions)

## Open-core model

- **Community (this repo, MIT):** SDK, gateway, MCP adapter, ledger, examples.
- **Team Cloud (roadmap):** central policy, approval workflows, log search.
- **Enterprise (roadmap):** on-prem, IAM, KMS/HSM, HA, SLA.
