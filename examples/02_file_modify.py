"""02 — file modification: sandboxed write, tamper is denied."""
import time
from prof.demo_tools import build_demo_gateway, file_write
from prof.gateway import ExecuteRequest
from prof.permit import Permit, hash_args

approver, gw = build_demo_gateway()
args = {"path": "/tmp/prof-demo/notes.txt", "content": "hello prof\n"}
permit = Permit(subject=approver.subject, agent="agent:examples:02",
                action="file.write", resource="file:/tmp/**",
                args_hash=hash_args(args), policy_id=gw.policy.policy_id,
                expiry=int(time.time()) + 300)
permit.sign(approver._sk)
dec, result = gw.execute(ExecuteRequest("file.write", "file:/tmp/**", args, permit), file_write)
print("legit:", dec.reason, result)
assert dec.allow

# attacker swaps content after approval -> args_hash mismatch -> deny
evil = {"path": "/tmp/prof-demo/notes.txt", "content": "pwned\n"}
dec2, _ = gw.execute(ExecuteRequest("file.write", "file:/tmp/**", evil, permit), file_write)
print("tampered:", dec2.reason)
assert not dec2.allow, "tamper must be denied"
print("OK — tampered file write denied.")
