# Data Layer — real state, not mocks (`prof/resources.py`)

All tool effects read and write a SQLite database, so state survives
restarts, concurrent calls are transactional, and the ledger points at
real rows, hashes and balances.

| Table | Holds |
|---|---|
| `customers` | id, name, tier, balance (seeded: acme-42, globex-7, initech-9) |
| `accounts` | balances in integer cents (seeded: account:krw-1 = 1,000,000.00) |
| `payments` | idempotency_key PK, from/to, amount, timestamp, permit nonce |
| `files` | path PK, sha256, size, timestamp (hash-chained per path) |

Behavior with teeth:
- `crm.lookup` on an unknown customer → effect error → deny (fail-closed).
- `payment.transfer` requires an idempotency key, checks funds, moves money
  atomically; a repeated key returns the original result without double spend.
- `file.write` stays inside `PROF_DATA_ROOT` (default `/tmp/prof-demo`) and
  records predecessor hashes, so overwrites are attributable.
- Every effect receives the executing permit's nonce (`_permit_nonce`,
  injected after verification) and stores it with the outcome.

Location: `$PROF_DB`, default in-memory for demos/tests. Production sets
`PROF_DB=/data/prof.db` (compose, k8s manifest and env example already do).

Coverage: `tests/test_resources.py` — real rows, restart persistence,
idempotency, insufficient funds, hash chaining, sandbox escape.
