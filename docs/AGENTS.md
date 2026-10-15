# Agent Integrations — put PROF in front of any agent

## 0 · Install first (required)

```sh
sh integrations/install.sh
```

This installs the package, verifies `prof demo`, and prints MCP JSON with an
**absolute** `prof` path (GUI-launched agents don't inherit your shell `$PATH`).
If `prof` isn't on your PATH afterwards, add the printed bin dir to your shell rc.
Developers with modern pip can use `pip install -e ".[dev]"` instead.

Two integration surfaces. Pick one (or both — they compose).

| Surface | What | For |
|---|---|---|
| **MCP server** (`prof mcp`, stdio, zero deps) | Transparent: low/medium calls just work (server-minted permits); high-tier needs a human-signed permit. Explicit `permit` arg still honored. | Claude Code, Codex CLI, Gemini CLI, Cursor, Windsurf, Cline, VS Code, OpenCode, any MCP client |
| **Shell gate** (`prof exec` / `prof decide`) | Pre-tool hook or command wrapper. Allow runs, deny blocks (exit 3; `--claude-hook` uses 0/2). | Claude Code hooks, Dots + any agent with shell hooks, CI scripts |

Policy is shared: low/medium tiers auto-flow, high tier (`payment.*`, `db.*`, `system.*`, writes outside `/tmp`) needs `--human-approve` / human sign-off. Tune in `examples/policies/default.yaml`.

## 1 · Claude Code

**MCP (project scope):** copy `integrations/claude-code/.mcp.json` into your project, or user scope:
```sh
claude mcp add prof -- prof mcp
```

**PreToolUse hook** (recommended — gates Write/Edit/Bash automatically):
1. Install: `sh integrations/install.sh` (puts a working `prof` on PATH)
2. Merge `integrations/claude-code/settings-snippet.json` into `~/.claude/settings.json`
   (fix the hook path to your checkout), or project `.claude/settings.json`.
3. Test: `echo '{"tool_name":"Bash","tool_input":{"command":"ls"}}' | python3 integrations/claude-code/prof-hook.py; echo "exit=$?"` → `exit=0`.
4. High-tier: `echo '{"tool_name":"Write","tool_input":{"file_path":"/etc/pwn"}}' | …` → `exit=2` + reason.
5. Strict mode (block unmapped tools too): `PROF_STRICT=1`.

## 2 · Codex CLI (OpenAI)

Append `integrations/codex/config-snippet.toml` to `~/.codex/config.toml`, restart `codex`. Tools appear as `prof/*`. Flow in-chat: *"approve crm lookup for acme-42, then call it with the permit"*.

## 3 · Gemini CLI (Google)

Merge `integrations/gemini/settings-snippet.json` `mcpServers` into `~/.gemini/settings.json`, restart. Same `prof.approve` → tool flow.

## 4 · Cursor / Windsurf / Cline / VS Code

Copy `integrations/cursor/mcp.json` content into the client's MCP config
(`.cursor/mcp.json`, Windsurf `mcp_config.json`, Cline MCP settings, VS Code `mcp.json`). Restart the client/Agent.

## 5 · OpenCode

Merge `integrations/opencode/opencode.json` `mcp` block into `opencode.json`. Run with `opencode run "use prof.approve, then call the tool"`.

## 6 · Dots (OpenAI) — remote MCP app

Dots run in OpenAI's cloud and take tools as **custom MCP apps** (public
HTTPS, Streamable HTTP, OAuth or pasted key). PROF serves exactly that at
`POST https://<domain>/mcp`:

```sh
PROF_DOMAIN=prof.example.com docker compose --profile edge up -d --build
```

Then ChatGPT web → Settings → Apps → Advanced → Developer mode → Plugins →
**+** → Create MCP App (`PROF`, `https://<domain>/mcp`, your
`PROF_API_TOKEN` as key). Map Dots Custom Rules to PROF tiers (take action
≈ low/medium auto-approve; ask/hand-off ≈ high-tier queue). Full steps,
verification and limits: `integrations/dots/README.md`. Note: Pro
workspaces get read/fetch-only custom apps — writes need Business+.

## 7 · Muse (Meta) — custom connector via chat

Muse runs in Meta's cloud and has no MCP settings form: paste a setup
message in chat with the server name, public HTTPS Streamable-HTTP URL and
auth, hand the bearer key to its Secure Credentials Store (never the chat),
test every tool, and save as a skill. A ready-to-paste prompt, approval
mapping and troubleshooting: `integrations/muse/README.md`.

## 8 · Other shell-hook agents (generic)

```sh
export PROF_ACTION=tool.call PROF_RESOURCE='tool:shell' PROF_ARGS='{"cmd":"deploy"}'
sh integrations/generic/prof-gate.sh   # exit 0 allow / 2 block
# or wrap a command end-to-end (high tier needs --human-approve):
prof exec --action tool.call --resource tool:shell --args '{"cmd":"deploy"}' -- ./deploy.sh
```

## 7 · LLM tasks (API-based, in console or CLI)

Any OpenAI-compatible API (`PROF_LLM_BASE_URL`, `PROF_LLM_MODEL`, `PROF_LLM_API_KEY`).
Console: **Agents** tab shows connection status, runs tasks (model → permit →
verified execution with per-step ledger refs), and offers copy-paste snippets.
CLI: `prof llm-check`, `prof agent-run "task" [--human-approve]`.
API: `GET /v1/llm/status`, `POST /v1/agent/run`. Full loop spec: `docs/LLM.md`.

## 8 · Human approval queue (high-tier workflow)
High-risk actions can't self-approve. They open a request (`POST /v1/requests`)
that a human signs (`POST /v1/requests/{id}/approve`) or rejects (`.../deny`)
in the console Approver panel or via API. The issued permit carries
`constraints.approved_by=human` + request id, and every transition is
ledger-logged. Operate-tab "Request human approval" polls until decided and
loads the signed permit automatically.

## 9 · One gateway, many frontends (remote mode)

Set `PROF_GATEWAY_URL=http://your-gateway:8091` and the MCP server enforces
through the shared gateway — same ledger, policy and nonce store as the
console, CLI and LLM loop. Authenticated automatically via `PROF_API_TOKEN`.

```sh
PROF_GATEWAY_URL=http://127.0.0.1:8091 prof mcp   # MCP traffic in server ledger
prof agent-run "Send 250 to acct-9" --gateway-url http://127.0.0.1:8091 --wait-approval
# high-tier opens a queue request; a human approves in console → payment executes
```

## Tool → PROF mapping (hooks)

| Agent tool | PROF action / resource | Tier |
|---|---|---|
| Write/Edit (any path) | `file.write` / `file:<path>` | medium in `/tmp`, **high (block)** elsewhere |
| Bash / shell | `tool.call` / `tool:shell` | medium (auto) |
| WebFetch/Search | `tool.call` / `tool:web.fetch` | medium (auto) |
| Read/Glob/Grep | `tool.call` / `tool:code.read` | low (auto) |
| payment/db/system | as-is | **high (block)** without human |

## Troubleshooting

- `prof: command not found` → run `sh integrations/install.sh`; ensure the printed bin dir is on PATH (or use `python -m prof …` from this repo).
- MCP client shows no tools → restart the client after config change; run `prof mcp` manually and send `{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}` to smoke-test.
- Hook blocks everything → check `PROF_STRICT`; unmapped tools pass by default.
- Permit rejected as expired → TTL (default 300s) too short for long tasks; raise `--ttl` / `ttl_s`.
- `deny: policy version mismatch` → policy file changed; re-approve outstanding permits.
