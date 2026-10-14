"""Local microbenchmark — prints environment + p50/p95 for authorize().

Not a product claim. Report env with any number you cite.
"""
import platform
import statistics
import sys
import time

sys.path.insert(0, ".")
from prof.demo_tools import build_demo_gateway, crm_lookup  # noqa: E402
from prof.gateway import ExecuteRequest  # noqa: E402
from prof.permit import Permit, hash_args  # noqa: E402


def main(n: int = 2000):
    approver, gw = build_demo_gateway()
    args = {"customer": "acme-42"}
    permits = []
    for _ in range(n):
        p = Permit(subject=approver.subject, agent="agent:bench", action="tool.call",
                   resource="tool:crm.lookup", args_hash=hash_args(args),
                   policy_id=gw.policy.policy_id, expiry=int(time.time()) + 600)
        p.sign(approver._sk)
        permits.append(p)
    dts = []
    for p in permits:
        t0 = time.perf_counter()
        dec, _ = gw.execute(ExecuteRequest("tool.call", "tool:crm.lookup", args, p), crm_lookup)
        dts.append((time.perf_counter() - t0) * 1e6)
        assert dec.allow
    dts.sort()
    print(f"env: {platform.system()} {platform.machine()} {platform.python_version()}")
    print(f"n={n} p50={dts[n//2]:.1f}us p95={dts[int(n*0.95)]:.1f}us mean={statistics.mean(dts):.1f}us")


if __name__ == "__main__":
    main()
