# Errata — papers vs. the released code

The PDFs in this folder were typeset before the pre-release audit ([`docs/AUDIT.md`](../docs/AUDIT.md)).
Where they differ from the repository, **the repository is authoritative**.

| Paper | Statement | Current state |
|---|---|---|
| PROF + HCCAI whitepaper v2.0, abstract & §9.1 | "72 tests" | 0 tests (`python -m pytest -q`) |
| Whitepaper v2.0, Table 1 | "Python, MIT" | PolyForm Noncommercial 1.0.0; commercial use needs a paid license ([COMMERCIAL-LICENSE.md](../COMMERCIAL-LICENSE.md)) |
| Whitepaper v2.0, §4 "high-risk actions require explicit human approval" | Not enforced at the API layer in the audited pre-release code (an API-token holder could mint a high-tier permit) | Enforced: `/v1/approve` and MCP `prof.approve` refuse high tier; only the human queue signs it |
| Whitepaper v2.0, §4 "nonce ... pruned once dead" | Pruned one second early (replay window at `now == expiry`) | Fixed: pruned only after expiry |
| HCCAI (Go) results, §9.2 | Refer to the separate HCCAI codebase | Not part of this repository; not re-verified here |

PROF whitepaper v1.0 (`PROF-whitepaper-v1.0.md`) has been updated for the license; its test count is historical.
