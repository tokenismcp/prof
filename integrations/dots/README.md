# PROF × OpenAI Dots

Dots (launched Sept 2026) are always-on agents in ChatGPT with their own
cloud computers. They reach third-party tools through **custom MCP apps**:
a **public HTTPS, Streamable-HTTP MCP server** registered at
chatgpt.com → Plugins, signed in with OAuth or a pasted key.
`POST https://<your-domain>/mcp` below is exactly that shape.

## Prerequisites

- ChatGPT plan with Developer mode + custom MCP apps
  (Pro: custom apps are **read/fetch only** — full PROF enforcement including
  writes needs Business / Enterprise / Edu).
- PROF reachable over public HTTPS (the gateway serves `/mcp`):
  ```sh
  PROF_DOMAIN=prof.example.com docker compose --profile edge up -d --build
  # endpoint: https://prof.example.com/mcp
  ```
- `PROF_API_TOKEN` set on the gateway (Dots stores it as the connector key).

## Setup

1. ChatGPT (web) → Settings → Apps → Advanced → enable **Developer mode**.
2. Plugins → **+** → **Create MCP App**. Name: `PROF`.
   Server URL: `https://<your-domain>/mcp`. Auth: paste your
   `PROF_API_TOKEN` as the key when asked (never in chat).
3. Ask your dot to confirm: *"list your PROF tools and look up customer
   acme-42"*. Expect `crm.lookup` to just work (low-tier auto-approval)
   and payments to ask for human approval.

## Approval mapping (Dots Custom Rules ↔ PROF tiers)

| Dots Custom Rule | PROF behavior |
|---|---|
| Take action without asking | low/medium tiers: server-minted permit, executed + logged |
| Ask before taking action | high tier: denied with a request path; approve in PROF console Approvals |
| Hand off to you | same as ask, plus `POST /v1/requests/{id}/deny` |
| Built-in stops (money, deletes) | PROF `payment.*`/`db.*`/`system.*` are high-tier by default |

Set matching Custom Rules in Settings → Personalization → Custom rules so
the dot's instincts agree with the gateway's enforcement.

## Verify it end-to-end

1. *"Use PROF to look up acme-42"* → succeeds, no questions.
2. *"Use PROF to send 100 to acct-9"* → dot must surface an approval step;
   approve in PROF console → retry succeeds; the ledger shows
   request → approve → allow with one chain.
3. Tamper check: ask for a lookup, then (in another chat) reuse fails —
   nonces are single-use; replays deny.

## Limits (honest)

- Dots docs promise only "supported plugins" see custom MCP apps; if your
  dot can't see PROF, use the connected-computer route or wait for rollout.
- Pro workspaces: reads only. Writes/auto-approve of medium tier need a
  plan with full MCP.
- No Dots API/SDK exists — this integration is account-plugin based, and
  every enforcement decision stays in the PROF ledger regardless.
