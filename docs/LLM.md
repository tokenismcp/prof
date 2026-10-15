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
tasks in-browser with per-step ledger references.

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
