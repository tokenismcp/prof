# LLM Integration — API-based agentic loop (`prof/llm.py`)

Local-first, provider-agnostic, stdlib-only (no extra dependencies).

## Providers (`PROF_LLM_PROVIDER`)

| Provider | Protocol | Default endpoint | Key |
|---|---|---|---|
| `ollama` (default) | OpenAI-compat | `http://localhost:11434/v1` | no |
| `lmstudio` | OpenAI-compat | `http://localhost:1234/v1` | no |
| `vllm` | OpenAI-compat | `http://localhost:8000/v1` | no |
| `openai` | OpenAI-compat | `https://api.openai.com/v1` | `PROF_LLM_API_KEY` |
| `azure` | OpenAI-compat | your deployment URL | `PROF_LLM_API_KEY` |
| `openrouter` | OpenAI-compat | `https://openrouter.ai/api/v1` | `PROF_LLM_API_KEY` |
| `anthropic` | native `/v1/messages` | `https://api.anthropic.com/v1` | `PROF_LLM_API_KEY` |
| `gemini` | OpenAI-compat layer | `…/v1beta/openai/` | `PROF_LLM_API_KEY` |

Current catalogs (verified Oct 16, 2026 against vendor docs + live APIs:
Anthropic Models overview, OpenRouter `/api/v1/models` (465 entries), Google
AI docs; confirm exact IDs anytime with `prof llm-setup`, which lists live
catalogs): OpenAI (`gpt-6-astra`, 6.1-Sol, 6-Sol/Luna, 5.6 trio, `gpt-oss-120b`),
Anthropic (Sonnet/Opus/Haiku 5.5, Fable 5.1, Opus/Sonnet 5 — all tool-capable,
1M context), Google (`gemini-4-argon`, 3.5 family), local tool-callers
(`qwen3`, `gemma4/3`, `qwen3-coder`, `llama3.3`, `gpt-oss`, `deepseek-r1`,
`granite4`). Live `/models` listing always wins when reachable (including
Anthropic's native Models API); otherwise the curated list shows marked as
fallback.

### Tool-calling flag

Every catalog entry is `{"id": str, "tools": bool}`. PROF drives **every**
action through a tool call, so a model without tool-calling is unusable.
The flag comes from the live endpoint when it advertises one (`"tools"` on a
`/models` entry) and otherwise from the curated catalog.

- `GET /v1/llm/models` returns the objects; the console marks non-tool models
  and **blocks** Save / Run with a warning (`model.notools`).
- `list_models()` returns the same objects; `prof llm-check` / `prof llm-setup`
  append `⚠` to non-tool models and warn when one is chosen.
- Fail-closed: an unconfigured or unreachable endpoint lists `[]` (never
  raises), and the console falls back to the marked curated catalog.

Anthropic requests use the native tool format and responses are normalized
back to the OpenAI shape, so the loop is identical for every provider.

```sh
prof llm-setup   # probes local servers, lists models, verifies, prints exports
prof llm-check   # provider/model/url + connectivity + model list

export PROF_LLM_PROVIDER=ollama PROF_LLM_MODEL=gemma4:12b
prof agent-run "What tier is customer acme-42?"       # full loop
prof agent-run "Send 100 to acct-9" --human-approve   # high-tier with sign-off
```

Verified live against local Ollama (gemma4:12b): lookup ALLOW → correct
answer from the real DB; payment without human → DENY → model explains why.

## The loop (`run_task`)

1. Model gets the task + PROF tool schemas (`crm.lookup`, `file.write`, `payment.transfer`).
2. Each requested call is approved (policy tier) and executed through the
   Gateway against the real SQLite DB — never on the model's word alone.
3. High-tier calls without `human_approve` (or an `approve_fn` callback) are
   denied and the denial is fed back to the model as an observation.
4. Loop ends at a final answer or `max_steps`. Every side effect carries a
   `ledger_seq` back to its signed permit.

API keys come from `PROF_LLM_API_KEY` and are never logged, never returned
by any API (`/v1/llm/status` reports only presence), and never accepted by
`/v1/llm/config` — which persists only provider/model/base_url to
`configs/llm.env` (gateway restart applies it). Transport errors, unknown
tools and effect failures are observations, not crashes (fail-closed).

## Console

The Agents tab shows provider/endpoint/model/key-presence, lists models for
one-click switching (per-run override; save persists to `llm.env`), and runs
tasks in-browser with per-step ledger references. Changing the provider
reloads that provider's catalog live; non-tool models are flagged and cannot
be saved or run. Console assets carry a `?v=<version>` query and are served
`no-cache` so an upgrade never runs a stale `i18n.js`/`app.js`.

"Run with proof" drives the built-in loop above. **"Queue for an agent"**
instead drops the same task into the shared **agent task inbox**
(`prof.tasks`, `POST /v1/tasks`) — an external agent claims it over MCP
(`prof.task.next`) and reports back (`prof.task.done`), and the console shows
the result. See `docs/AGENTS.md §10`.

## Programmatic use

```python
from prof.demo_tools import build_demo_gateway
from prof.llm import LLMConfig, run_task
from prof.resources import crm_lookup, file_write, payment_transfer

approver, gw = build_demo_gateway()
res = run_task("What tier is acme-42?", approver, gw,
               {"crm.lookup": crm_lookup, "file.write": file_write,
                "payment.transfer": payment_transfer},
               cfg=LLMConfig(provider="ollama"), human_approve=False)
print(res.answer, res.allowed, res.denied)
```

Tests (`tests/test_llm.py`) run the real loop against a local
OpenAI-compatible HTTP server (allow / high-tier-deny / human-approved
payment with real balance change), plus Anthropic translation round-trip,
provider presets, and model listing.
