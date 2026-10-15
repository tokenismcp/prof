# LLM Integration — API-based agentic loop (`prof/llm.py`)

Provider-agnostic: any OpenAI-compatible chat-completions API (OpenAI, Azure
OpenAI, Ollama, vLLM, llama.cpp server, OpenRouter, …) over stdlib `urllib` —
no extra dependencies.

```sh
export PROF_LLM_BASE_URL=http://localhost:11434/v1  # Ollama default
export PROF_LLM_MODEL=llama3.1
prof llm-check                                        # verify connectivity
prof agent-run "What tier is customer acme-42?"       # full loop
prof agent-run "Send 100 to acct-9" --human-approve   # high-tier with sign-off
```

## The loop (`run_task`)

1. Model gets the task + PROF tool schemas (`crm.lookup`, `file.write`, `payment.transfer`).
2. Each requested call is approved (policy tier) and executed through the
   Gateway against the real SQLite DB — never on the model's word alone.
3. High-tier calls without `human_approve` (or an `approve_fn` callback) are
   denied and the denial is fed back to the model as an observation.
4. Loop ends at a final answer or `max_steps`. Every side effect carries a
   `ledger_seq` back to its signed permit.

API keys come from `PROF_LLM_API_KEY` and are never logged. Transport errors,
unknown tools and effect failures are observations, not crashes (fail-closed).

## Programmatic use

```python
from prof.demo_tools import build_demo_gateway
from prof.llm import LLMConfig, run_task
from prof.resources import crm_lookup, file_write, payment_transfer

approver, gw = build_demo_gateway()
res = run_task("What tier is acme-42?", approver, gw,
               {"crm.lookup": crm_lookup, "file.write": file_write,
                "payment.transfer": payment_transfer},
               cfg=LLMConfig(), human_approve=False)
print(res.answer, res.allowed, res.denied)
```

Tests (`tests/test_llm.py`) run the real loop against a local
OpenAI-compatible HTTP server: allow path, high-tier-deny path, and
human-approved payment with a real balance change.
