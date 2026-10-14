"""Risk-based policy engine.

Design goal: no per-action human clicks for everything.
- low / read-only  -> pre-delegated auto-approvable scope
- medium           -> constrained token (limits, expiry, resource prefix)
- high             -> explicit human approval (+ optional quorum)

Policy file format (YAML): see examples/policies/default.yaml
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class PolicyDecision:
    allow: bool
    tier: str
    reason: str
    require_human: bool = False
    require_quorum: int = 1


@dataclass
class Rule:
    action: str      # glob, e.g. "tool.call", "file.*", "payment.*"
    resource: str    # glob
    tier: str        # low | medium | high
    require_human: bool = False
    max_amount: Optional[float] = None
    quorum: int = 1

    def matches(self, action: str, resource: str) -> bool:
        return fnmatch.fnmatchcase(action, self.action) and fnmatch.fnmatchcase(resource, self.resource)


class Policy:
    def __init__(self, policy_id: str, rules: List[Rule], default_tier: str = "high"):
        self.policy_id = policy_id
        self.rules = rules
        self.default_tier = default_tier

    def evaluate(self, action: str, resource: str, args: Dict[str, Any]) -> PolicyDecision:
        for r in self.rules:
            if r.matches(action, resource):
                if r.max_amount is not None and "amount" in args:
                    try:
                        if float(args["amount"]) > float(r.max_amount):
                            return PolicyDecision(False, "high", f"amount {args['amount']} exceeds max {r.max_amount}", True, r.quorum)
                    except (TypeError, ValueError):
                        return PolicyDecision(False, "high", "unparsable amount", True, r.quorum)
                req_human = r.require_human or r.tier == "high"
                return PolicyDecision(True, r.tier, f"matched {r.action} {r.resource} -> {r.tier}", req_human, r.quorum)
        # default deny unless default_tier is low (we default to high=require human)
        if self.default_tier == "low":
            return PolicyDecision(True, "low", "default allow (low)", False, 1)
        return PolicyDecision(False, self.default_tier, "no rule matched: default deny", True, 1)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "default_tier": self.default_tier,
            "rules": [r.__dict__ for r in self.rules],
        }


DEFAULT_POLICY = Policy(
    policy_id="default@v1",
    default_tier="high",
    rules=[
        Rule("tool.call", "tool:*.read*", "low"),
        Rule("tool.call", "tool:crm.lookup", "low"),
        Rule("tool.call", "tool:*", "medium"),
        Rule("file.read", "file:**", "low"),
        Rule("file.write", "file:/tmp/**", "medium"),
        Rule("file.write", "file:**", "high", require_human=True),
        Rule("message.send", "channel:**", "medium"),
        Rule("payment.*", "account:**", "high", require_human=True, max_amount=1_000_000),
        Rule("db.*", "db:**", "high", require_human=True),
        Rule("system.*", "*", "high", require_human=True),
    ],
)


def load_policy_file(path: str) -> Policy:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    rules = [Rule(**r) for r in data.get("rules", [])]
    return Policy(
        policy_id=data.get("policy_id", "file@v1"),
        rules=rules,
        default_tier=data.get("default_tier", "high"),
    )
