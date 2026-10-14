"""01 — tool call: CRM lookup behind PROF (low-risk, auto-approvable)."""
import time
from prof.demo_tools import build_demo_gateway, crm_lookup
from prof.gateway import ExecuteRequest
from prof.permit import Permit, hash_args

approver, gw = build_demo_gateway()
args = {"customer": "acme-42"}
permit = Permit(subject=approver.subject, agent="agent:examples:01",
                action="tool.call", resource="tool:crm.lookup",
                args_hash=hash_args(args), policy_id=gw.policy.policy_id,
                expiry=int(time.time()) + 300)
permit.sign(approver._sk)
dec, result = gw.execute(ExecuteRequest("tool.call", "tool:crm.lookup", args, permit), crm_lookup)
print("decision:", dec.reason)
print("result:", result)
assert dec.allow, dec.reason
print("OK — tool call allowed with proof.")
