# MCP Integration — real stdio server, zero dependencies

MCP is the first interface, not the security boundary. The boundary is the server-side Gateway.

Run it: `prof mcp` (or `prof-mcp`, or `python examples/mcp_server.py`).
It speaks JSON-RPC 2.0 over stdio (`initialize`, `tools/list`, `tools/call`,
`ping`), verified by `tests/test_mcp.py` against the installed binary.

## Pattern (transparent for low/medium, explicit for high-risk)

```
MCP client/agent (usual tools, no PROF knowledge needed)
  → prof mcp → auto-approve (low/medium, server-minted, logged) → execute
  → high-tier without permit → request id for human sign-off → retry with permit
```

1. Agent calls the tool directly — no permit needed for low/medium tiers.
   The server mints the permit itself (`POST /v1/auto-approve`, `auto: true`
   constraint, TTL capped at 300 s).
2. Agents that already do the permit round-trip keep working: an explicit
   `permit` argument is still honored and verified.
3. High-tier without a human-signed permit is denied with a request path
   (`POST /v1/requests` or console Approvals), never silently elevated.

## Tools

| Tool | Effect (real state) |
|---|---|
| `prof.approve` | issues a signed Permit (policy-checked, ledger-logged) |
| `crm.lookup` | reads the customer row from SQLite (`unknown` → fail-closed deny) |
| `file.write` | writes inside the sandbox, records sha256 + predecessor hash in SQLite |
| `payment.transfer` | atomic debit/credit with persisted idempotency keys and balance checks |

## Minimal example

```python
from prof.demo_tools import build_demo_gateway
from prof.mcp_adapter import ProfMCP
from prof.permit import Permit, hash_args
import time

approver, gw = build_demo_gateway()
bridge = ProfMCP(gw)
bridge.register("crm.lookup", lambda a: {"customer": a["customer"]}, resource="tool:crm.lookup")

args = {"customer": "acme-42"}
p = Permit(subject=approver.subject, agent="agent:mcp:01", action="tool.call",
           resource="tool:crm.lookup", args_hash=hash_args(args),
           policy_id=gw.policy.policy_id, expiry=int(time.time()) + 300)
p.sign(approver._sk)
print(bridge.call("crm.lookup", args, p))            # ok
print(bridge.call("crm.lookup", {"customer": "evil"}, p))  # denied
```

Client setup per agent: see `docs/AGENTS.md` and `integrations/`.
