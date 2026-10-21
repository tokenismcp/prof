# Pre-release security audit (v1.0.0)

Scope: all of `prof/`, deployment files, console auth flow, and consistency with the
whitepaper (`papers/`). Method: manual review of every module, then a failing regression
test per finding (`tests/test_audit.py`), then the fix. Not an independent third-party audit.

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | Critical | `/v1/approve` and MCP `prof.approve` signed **high-tier** permits for any caller, so an agent could approve its own payment (`PROF_REQUIRE_HUMAN` defaulted to off). Contradicted whitepaper §4. | High tier refused; only the human queue signs it. Default on. |
| 2 | High | `POST /mcp` ran a private demo gateway (own key, ephemeral ledger/nonces) and reset the resource DB. Actions bypassed the server's audit trail. | `/mcp` uses the server's approver, gateway, ledger. |
| 3 | High | `GET /v1/llm/models?base_url=` (unauthenticated) and `agent/run` overrides sent the server's LLM API key to a caller-chosen URL. | Key dropped unless provider+endpoint are the configured ones; custom URL needs token. |
| 4 | High | Policy cap bypass: `amount="nan"`, negative, or missing `amount` skipped `max_amount`. | Capped rules require a finite positive amount. |
| 5 | Medium | `fnmatch` `*` matches `/`: `file:/tmp/../etc/x` matched `file:/tmp/**`. | Traversal/control-char resources denied. |
| 6 | Medium | Nonce pruned at `expiry` while the permit was valid through `expiry` (1-second replay window). | Prune `< now`. |
| 7 | Medium | Torn last journal line crashed restart; unreadable nonce file silently emptied the replay set. | Drop only a torn final line; interior corruption refuses to start. |
| 8 | Medium | Sandbox used `normpath`; symlink inside the root escaped it. | `realpath`. |
| 9 | Medium | Gateway could listen on 0.0.0.0 with no token (Docker default `HOST=0.0.0.0`); k8s manifest had no token at all. | `serve()` refuses; k8s wires `PROF_API_TOKEN`. |
| 10 | Low | `/v1/ledger` (subjects, task text) public; `/v1/llm/config` newline injection into `llm.env`; permit TTL uncapped; token compare on `str`; unbounded rate-limit map; no ledger verification at startup. | Token on ledger; control chars rejected; `PROF_MAX_TTL_S`; bytes compare; bounded map; verify on start. |

## Not fixed / documented limits
- Single shared API token; no per-agent identity or SSO. Software Ed25519 key only (no HSM/KMS).
- Single-node stores; ledger tail truncation undetectable without an external head anchor.
- Body cap trusts `Content-Length`; enforce a limit at the reverse proxy.
- `/v1/execute` binds the *resource string*, not `args.from`, for payments: the approver sees full args, but policy by account should key on the arg. Roadmap.
- Whitepaper v2.0 cites 72 tests; the repo now has 120. HCCAI (Go) is a separate codebase and is not in this repo.
