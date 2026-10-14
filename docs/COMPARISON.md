# Comparison: why PROF

| Approach | When it acts | Tamper binding | Replay protection | Audit |
|---|---|---|---|---|
| Prompt guards / system instructions | inference time | none | none | logs only |
| Observability / post-hoc tracing | after execution | none | none | after the fact |
| API gateway ACLs | execution time | coarse (path/role) | partial | request logs |
| **PROF** | **execution time, pre-effect** | **permit binds subject/agent/action/resource/args_hash/policy/expiry/nonce** | **one-shot nonces + idempotency** | **hash-chained, signed decisions** |

PROF's thesis: **Think Freely. Act With Proof.** Let models reason freely; allow only approved actions to execute — verified cryptographically, enforced at the gateway, recorded in an auditable ledger. Model-, agent-, and tool-agnostic.
