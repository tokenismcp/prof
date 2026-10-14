# Verification (honest)

## Status: Developer Preview — reproducible, not certified

- `python -m pytest -q` — 9 tests covering allow, tamper-deny, replay-deny, expiry-deny, scope-deny, ledger-tamper-evidence.
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
