# PROF × Meta Muse

Muse (launched Sept 2026) runs on Meta's cloud computer. It has no MCP
settings form — you **ask it in chat to build a Custom Connector** to a
**public HTTPS, Streamable-HTTP MCP server**, hand the key to its Secure
Credentials Store (never the chat), test, and save as a skill.
`POST https://<your-domain>/mcp` below is exactly that shape.

## Prerequisites

- PROF reachable over public HTTPS:
  ```sh
  PROF_DOMAIN=prof.example.com docker compose --profile edge up -d --build
  # endpoint: https://prof.example.com/mcp
  ```
- A static bearer key: set `PROF_API_TOKEN` on the gateway (smoothest path
  for Muse's credential flow; OAuth-only services take more back-and-forth).

## Setup — paste this into a Muse chat

```text
Build a custom connector to PROF, my proof-required execution gateway.

Its MCP server is https://<your-domain>/mcp — a hosted, public HTTPS
endpoint that speaks streamable HTTP. Auth is a static bearer token:
ask me for it through the secure credential flow (never the chat).

It has 4 tools: prof.approve (sign a permit), crm.lookup (customer data),
file.write (sandboxed files), payment.transfer (HIGH-RISK, needs a
human-signed permit — open it via the gateway approval queue).

Connect with the official MCP SDK, test every tool end to end, and save
the integration as a reusable skill called "PROF".
```

When Muse asks for the key, paste `PROF_API_TOKEN` into the **secure
credential prompt only**. Then: *"list the PROF tools and look up customer
acme-42"*.

## Approval policy (Settings ↔ PROF tiers)

| Muse connector setting | PROF behavior |
|---|---|
| Allow | low/medium tiers execute (server-minted permit, logged) |
| Require approval | high tier: denied with a request path until a human signs in PROF console Approvals |
| Read-only | equivalent to blocking `payment.*`/`db.*`/`file.write` — enforce in `examples/policies/default.yaml` |

For anything that sends, posts, or spends, keep Muse approval ON: defense
in depth with the gateway's cryptographic enforcement.

## Verify it end-to-end

1. *"Use PROF to look up acme-42"* → succeeds immediately.
2. *"Use PROF to send 100 to acct-9"* → Muse must hit the approval gate;
   sign in PROF console → retry with the permit succeeds.
3. From a fresh conversation, confirm the saved PROF skill is reused
   without rebuilding.

## Limits (honest)

- Localhost/stdio servers are unreachable from Meta's cloud — the public
  HTTPS endpoint is mandatory, not optional.
- Meta doesn't review custom connectors: you trust the PROF operator
  (ideally yourself) with whatever Muse sends it. Revoke by rotating
  `PROF_API_TOKEN`.
- OAuth-only setups work but take more back-and-forth; the static bearer
  key is the tested path.
