# Performance Audit — measured, not claimed

Method: `PYTHONPATH=. python3 bench/bench.py [--n N] [--http URL]`.
Every run prints env + percentiles and saves raw JSON. Reproduce on your
hardware before citing any number. Durable-mode figures depend on disk.

## Latest run (reference machine)

macOS arm64 · Python 3.9.6 · 10 cores · `bench/results/bench-1792069956.json`

| Operation | p50 | p95 | Notes |
|---|---|---|---|
| gateway authorize+execute (mem) | 182 µs | 192 µs | dominated by Ed25519 verify (166 µs) |
| permit sign | 86 µs | 90 µs | approver-side only |
| policy evaluate | 1.5 µs | 1.5 µs | glob rules, negligible |
| nonce reserve (mem) / journal | 0.6 µs / 23 µs | 0.7 / 25 µs | journal = 1 line append |
| ledger append (mem / file / fsync) | 4 / 39 / 50 µs | 5 / 49 / 63 µs | O(1) JSONL since v2 |
| SQLite customer read / transfer | 5 / 217 µs | 5 / 254 µs | transfer = real tx |
| HTTP approve+execute RTT (localhost) | 1.49 ms | 6.6 ms | n=100, same machine |
| concurrency | — | — | 8 threads × 250: **11,458 TPS, 0 mis-decisions** |
| chain verify 2k / 10k entries | 6.4 ms | 32.8 ms | full re-hash every time, by design |
| memory | — | — | ~5 MB per 10k ledger entries (~0.5 KB/entry) |

## What this means for sizing

- Enforcement overhead is ~0.2 ms in-process, ~1.5 ms over local HTTP —
  irrelevant next to any LLM call (seconds).
- Bottleneck at scale is **ledger growth**: verify is linear, memory is
  ~0.5 KB/entry. At 1M entries expect ~3 s verify + ~0.5 GB RAM.
- Rotation procedure (no silent drops): stop gateway → verify chain
  (`prof verify-ledger`) → archive the file offline → restart with a fresh
  chain → keep archives verifiable. Segmented checkpointing is Beta roadmap.

## Deliberate non-optimizations (audited, kept)

- `verify_chain` re-hashes everything on every call. An incremental cache
  was prototyped and **rejected**: it missed in-memory tampering of
  already-verified entries (test caught it; see `Ledger.verify_chain`
  docstring). Soundness over speed for the audit path.
- Nonce pruning keys off permit expiry (safe: expired permits deny anyway);
  legacy v1 files get a 1 h grace window, then prune.
- `PROF_LEDGER_FSYNC=1` trades ~10 µs/append for crash durability; default
  flush-only matches the previous atomic-replace durability.

## Limits of these numbers

Single machine, localhost, demo policy (10 rules), Ed25519 software keys.
No network, no TLS, no HSM/KMS latency, no multi-node store. Production
sizing must re-run with production stores and load (`--http` against a
deployed gateway).
