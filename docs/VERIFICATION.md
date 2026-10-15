# Verification (honest)

## Status: Developer Preview — reproducible, not certified

- `python -m pytest -q` — 52 tests: enforcement, tamper/replay/expiry/scope,
  SQLite persistence/idempotency/funds, MCP protocol (against the installed
  binary), LLM loop (allow/deny/human paths), approval queue, token auth,
  rate limits, body cap, headers, 16-thread nonce race (exactly one allow),
  audit-trail completeness, and live-server e2e (remote MCP + LLM→queue→
  human→payment with real balance movement).
- `python -m prof demo` — allow + 3 attack denials in one run, ledger verified.
- `examples/0*.py` — 3 reference workflows (tool call, file modify, payment).

## What we do NOT claim

Earlier internal notes mentioned "12.4μs overhead" and "100% over ~200 scenarios". Those numbers lack published environment, code, threat taxonomy, confidence intervals, and independent reproduction — so they are **not** stated as product guarantees anywhere in this repo.

## How to verify (reproducible)

```sh
pip install -e ".[dev]"
python -m pytest -q
python -m prof demo
python bench/bench.py   # local microbenchmark; prints env + p50/p95
```

Report format for any performance claim: hardware, OS, Python version, concurrency, policy size, key location, p50/p95/p99, TPS, and the exact commit + dataset. External red-team and audit are roadmap gates before any Enterprise claim.
