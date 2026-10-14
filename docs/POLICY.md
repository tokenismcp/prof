# Policy Guide

Risk-based, not click-everything:

| Tier | Examples | Behavior |
|---|---|---|
| low | `tool:crm.lookup`, `file.read` | pre-delegated scope, auto-approvable short-lived permits |
| medium | `tool:*`, `file:/tmp/**`, `message.send` | constrained token (limits, expiry, resource prefix) |
| high | `payment.*`, `db.*`, `system.*`, `file:/etc/**` | explicit human approval (quorum optional), amount caps |

## YAML rule

```yaml
policy_id: default@v1
default_tier: high   # unmatched = deny (fail-closed)
rules:
  - {action: "payment.*", resource: "account:**", tier: high, require_human: true, max_amount: 1000000}
```

- `action`/`resource` are globs (`fnmatch`). First match wins.
- `max_amount` caps `args.amount`; over-cap → deny.
- Changing `policy_id` invalidates outstanding permits (version binding).

Human-approval model: low runs unattended inside delegated scope; medium runs with narrow constraints; high requires a human (or M-of-N quorum in Beta). Approval fatigue is handled by short TTLs + narrow scopes, not by trusting the agent.
