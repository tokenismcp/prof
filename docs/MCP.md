# MCP Integration

MCP is the first interface, not the security boundary. The boundary is the server-side Gateway.

## Pattern

```
MCP client/agent (untrusted) → PROF Gateway → MCP tool server / API
```

1. Agent requests approval: `POST /v1/approve {agent, action, resource, args}` → signed Permit.
2. Agent invokes tool with the Permit; `ProfMCP.call(name, args, permit)` verifies server-side.
3. Tampered args → `args_hash` mismatch → deny. Replayed permit → nonce reuse → deny.

## Minimal example

```python
from prof.demo_tools import build_demo_gateway
from prof.mcp_adapter import ProfMCP
from prof.permit import Permit, hash_args
import time

approver, gw = build_demo_gateway()
bridge = ProfMCP(gw)
bridge.register("crm.lookup", lambda a: f"customer:{a['customer']}", resource="tool:crm.lookup")

args = {"customer": "acme-42"}
p = Permit(subject=approver.subject, agent="agent:mcp:01", action="tool.call",
           resource="tool:crm.lookup", args_hash=hash_args(args),
           policy_id=gw.policy.policy_id, expiry=int(time.time()) + 300)
p.sign(approver._sk)
print(bridge.call("crm.lookup", args, p))            # ok
print(bridge.call("crm.lookup", {"customer": "evil"}, p))  # denied
```

Native MCP stdio servers (`mcp` SDK) follow the same rule: verify the Permit inside the Gateway before touching any real tool. See `examples/mcp_server.py`.
