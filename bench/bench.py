"""PROF performance audit — deep, honest, reproducible.

Measures, on THIS machine (env is printed and saved):
  1. authorize() latency: p50/p95/p99 + mean
  2. component breakdown: sign / verify / policy / hash_args / nonce / ledger
  3. persistence cost: memory vs file ledger+nonce, fsync on/off, SQLite transfer
  4. concurrency: N threads x M decisions — TPS + zero mis-decisions
  5. scaling: full chain verify at 1k/10k entries, memory per entry
  6. optional live HTTP: --http URL approves+executes for real (needs gateway)

Writes bench/results/bench-<ts>.json. Not a product claim: durable-mode
numbers depend on disk; report env with any number you cite.

Usage:  PYTHONPATH=. python3 bench/bench.py [--n 2000] [--http http://127.0.0.1:8091]
"""

import json
import os
import platform
import statistics
import sys
import tempfile
import threading
import time

sys.path.insert(0, ".")

from prof.demo_tools import build_demo_gateway  # noqa: E402
from prof.gateway import ExecuteRequest  # noqa: E402
from prof.ledger import Ledger  # noqa: E402
from prof.permit import Permit, hash_args  # noqa: E402
from prof.policy import DEFAULT_POLICY  # noqa: E402
from prof.resources import payment_transfer, reset_db  # noqa: E402
from prof.store import NonceStore  # noqa: E402


def pct(data, p):
    if not data:
        return 0.0
    s = sorted(data)
    return s[min(len(s) - 1, int(len(s) * p / 100))]


def summary_us(name, data):
    return {"op": name, "n": len(data), "mean_us": round(statistics.mean(data), 1),
            "p50_us": round(pct(data, 50), 1), "p95_us": round(pct(data, 95), 1),
            "p99_us": round(pct(data, 99), 1)}


def fresh_permit(approver, policy_id, args, ttl=600):
    p = Permit(subject=approver.subject, agent="agent:bench", action="tool.call",
               resource="tool:crm.lookup", args_hash=hash_args(args),
               policy_id=policy_id, expiry=int(time.time()) + ttl)
    p.sign(approver._sk)
    return p


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=2000)
    ap.add_argument("--http", default="")
    cfg = ap.parse_args()
    n = cfg.n
    out = {"env": {"system": platform.system(), "machine": platform.machine(),
                   "python": platform.python_version(), "cpu": os.cpu_count(),
                   "ts": int(time.time())}, "sections": {}}

    approver, gw = build_demo_gateway()
    args = {"customer": "acme-42"}

    # 1. authorize latency (memory stores)
    permits = [fresh_permit(approver, gw.policy.policy_id, args) for _ in range(n)]
    dts = []
    for p in permits:
        t0 = time.perf_counter()
        dec, _ = gw.execute(ExecuteRequest("tool.call", "tool:crm.lookup", args, p),
                            lambda a: {"ok": True})
        dts.append((time.perf_counter() - t0) * 1e6)
        assert dec.allow
    out["sections"]["authorize_mem"] = summary_us("gateway.execute (mem stores, echo effect)", dts)

    # 2. component breakdown
    p0 = fresh_permit(approver, gw.policy.policy_id, args)
    t = lambda: time.perf_counter()  # noqa: E731
    def timeit(fn, k=500):
        ds = []
        for _ in range(k):
            t0 = t()
            fn()
            ds.append((t() - t0) * 1e6)
        return ds
    out["sections"]["sign"] = summary_us("permit.sign (Ed25519)", timeit(lambda: fresh_permit(approver, gw.policy.policy_id, args), 300))
    out["sections"]["verify"] = summary_us("permit.verify", timeit(lambda: p0.verify(approver.pubkey), 500))
    out["sections"]["policy"] = summary_us("policy.evaluate", timeit(lambda: DEFAULT_POLICY.evaluate("tool.call", "tool:crm.lookup", args), 2000))
    out["sections"]["hash_args"] = summary_us("hash_args", timeit(lambda: hash_args(args), 2000))
    ns, now = NonceStore(), int(time.time())
    c = [0]
    def _rsv():
        c[0] += 1
        ns.check_and_reserve(f"bench-{c[0]}", now, now + 600)
    out["sections"]["nonce_mem"] = summary_us("nonce reserve (mem)", timeit(_rsv, 2000))
    led = Ledger()
    out["sections"]["ledger_mem"] = summary_us("ledger append (mem)", timeit(
        lambda: led.append("allow", "n", "a", "r", "s", "ag"), 2000))

    # 3. persistence cost (tmp files)
    with tempfile.TemporaryDirectory() as tmp:
        led_f = Ledger(f"{tmp}/l.jsonl")
        out["sections"]["ledger_file"] = summary_us("ledger append (file, flush)", timeit(
            lambda: led_f.append("allow", "n", "a", "r", "s", "ag"), 500))
        os.environ["PROF_LEDGER_FSYNC"] = "1"
        led_s = Ledger(f"{tmp}/l2.jsonl")
        out["sections"]["ledger_fsync"] = summary_us("ledger append (file, fsync)", timeit(
            lambda: led_s.append("allow", "n", "a", "r", "s", "ag"), 200))
        del os.environ["PROF_LEDGER_FSYNC"]
        ns_f = NonceStore(f"{tmp}/n.jsonl")
        cc = [0]
        def _rsvf():
            cc[0] += 1
            ns_f.check_and_reserve(f"b-{cc[0]}", now, now + 600)
        out["sections"]["nonce_file"] = summary_us("nonce reserve (journal)", timeit(_rsvf, 500))
        reset_db(f"{tmp}/p.db")
        from prof.resources import get_db
        db = get_db()
        pay = {"to": "a", "amount": 1, "idempotency_key": "b-pay"}
        out["sections"]["sqlite_lookup"] = summary_us("sqlite customer read", timeit(
            lambda: db.customer("acme-42"), 500))
        kk = [0]
        def _pay():
            kk[0] += 1
            a2 = dict(pay, idempotency_key=f"b-pay-{kk[0]}")
            db.transfer("account:krw-1", "a", 1, a2["idempotency_key"], "n")
        out["sections"]["sqlite_transfer"] = summary_us("sqlite transfer (tx)", timeit(_pay, 200))

    # 4. concurrency: threads x decisions, all unique permits, zero mis-decisions
    approver2, gw2 = build_demo_gateway()
    per, workers = 250, 8
    misuse = [0]
    t0 = t()
    def worker(w):
        for i in range(per):
            a = {"customer": "acme-42", "w": w, "i": i}
            p = Permit(subject=approver2.subject, agent="agent:bench",
                       action="tool.call", resource="tool:crm.lookup",
                       args_hash=hash_args(a), policy_id=gw2.policy.policy_id,
                       expiry=int(time.time()) + 600)
            p.sign(approver2._sk)
            dec, _ = gw2.execute(ExecuteRequest("tool.call", "tool:crm.lookup", a, p),
                                 lambda x: {"ok": True})
            if not dec.allow:
                misuse[0] += 1
    ths = [threading.Thread(target=worker, args=(w,)) for w in range(workers)]
    for th in ths:
        th.start()
    for th in ths:
        th.join()
    total = per * workers
    dt = t() - t0
    out["sections"]["concurrency"] = {"threads": workers, "decisions": total,
                                      "seconds": round(dt, 2),
                                      "tps": round(total / dt, 1),
                                      "mis_decisions": misuse[0]}
    assert misuse[0] == 0

    # 5. chain verify scaling + memory per entry
    import resource as _res
    # ru_maxrss units differ by OS: bytes on macOS, KB on Linux
    _rss_unit = 1024.0 if platform.system() == "Darwin" else 1.0
    mem0 = _res.getrusage(_res.RUSAGE_SELF).ru_maxrss / _rss_unit
    led3 = Ledger()
    for i in range(2000):
        led3.append("allow", f"n{i}", "a", "r", "s", "ag")
    t0 = t()
    ok, _ = led3.verify_chain()
    v1 = (t() - t0) * 1000
    assert ok
    for i in range(8000):
        led3.append("allow", f"m{i}", "a", "r", "s", "ag")
    t0 = t()
    ok, _ = led3.verify_chain()
    v10 = (t() - t0) * 1000
    assert ok
    mem1 = _res.getrusage(_res.RUSAGE_SELF).ru_maxrss / _rss_unit
    out["sections"]["verify_scaling"] = {"verify_2k_ms": round(v1, 1),
                                         "verify_10k_ms": round(v10, 1),
                                         "rss_per_10k_entries_kb": mem1 - mem0}

    # 6. optional live HTTP
    if cfg.http:
        import urllib.request
        base = cfg.http.rstrip("/")
        def post(path, body):
            req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode())
        hts = []
        for i in range(100):
            a = {"customer": "acme-42"}
            t0 = t()
            pm = post("/v1/approve", {"agent": "agent:bench", "action": "tool.call",
                                     "resource": "tool:crm.lookup", "args": a})
            r = post("/v1/execute", {"action": "tool.call", "resource": "tool:crm.lookup",
                                    "args": a, "permit": pm})
            hts.append((t() - t0) * 1000)
            assert r["ok"]
        out["sections"]["http_approve_execute_rtt"] = summary_us("approve+execute RTT (ms→shown as us/1000)", [x * 1000 for x in hts])

    os.makedirs("bench/results", exist_ok=True)
    fn = f"bench/results/bench-{int(time.time())}.json"
    with open(fn, "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))
    print("saved", fn)


if __name__ == "__main__":
    main()
