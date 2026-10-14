"""03 — payment request: high-risk, amount tamper + replay denied."""
import time
from prof.demo_tools import build_demo_gateway, payment_transfer, PAYMENTS
from prof.gateway import ExecuteRequest
from prof.permit import Permit, hash_args

PAYMENTS.clear()
approver, gw = build_demo_gateway()
args = {"to": "acct-7", "amount": 50000, "idempotency_key": "ex-003"}
permit = Permit(subject=approver.subject, agent="agent:examples:03",
                action="payment.transfer", resource="account:krw-1",
                args_hash=hash_args(args), policy_id=gw.policy.policy_id,
                expiry=int(time.time()) + 300)
permit.sign(approver._sk)
dec, result = gw.execute(ExecuteRequest("payment.transfer", "account:krw-1", args, permit), payment_transfer)
print("legit:", dec.reason, result)
assert dec.allow

# replay same permit
dec2, _ = gw.execute(ExecuteRequest("payment.transfer", "account:krw-1", args, permit), payment_transfer)
print("replay:", dec2.reason)
assert not dec2.allow, "replay must be denied"
print("OK — payment replay denied.")
