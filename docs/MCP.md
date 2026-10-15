# MCP Integration — real stdio server, zero dependencies

MCP is the first interface, not the security boundary. The boundary is the server-side Gateway.

Run it: `prof mcp` (or `prof-mcp`, or `python examples/mcp_server.py`).
It speaks JSON-RPC 2.0 over stdio (`initialize`, `tools/list`, `tools/call`,
`ping`), verified by `tests/test_mcp.py` against the installed binary.

## Pattern

```
MCP client/agent (untrusted) → prof mcp → Gateway verify → SQLite tools → ledger
```

1. Agent calls `prof.approve {agent, action, resource, args}` → signed Permit.
2. Agent calls the tool with `{..., "permit": <Permit>}`.
3. Tampered args → `args_hash` mismatch → deny. Replayed permit → nonce reuse → deny.
   Missing permit → error telling the agent to approve first.

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
