"""PROF LLM integration — API-based agentic loop with proof-required tools.

Provider-agnostic: talks to any OpenAI-compatible chat-completions API
(OpenAI, Azure OpenAI, Ollama, vLLM, llama.cpp server, OpenRouter, …) using
only the standard library, so `pip install prof` stays dependency-free.

Config via environment (or explicit LLMConfig):
  PROF_LLM_BASE_URL  default http://localhost:11434/v1  (Ollama)
  PROF_LLM_API_KEY   default "" (unset for local servers like Ollama)
  PROF_LLM_MODEL     default gpt-4o-mini

How it works (run_task):
  1. The model receives the user task + PROF tool schemas (OpenAI tools format).
  2. Every model-requested tool call goes through the PROF Gateway:
     approve (policy tier) -> verify -> execute against the real SQLite
     resource DB. High-tier calls need human_approve=True, otherwise they
     are denied and the denial is fed back to the model.
  3. Tool results return to the model; loop until a final answer or max_steps.
  4. The full transcript plus ledger sequence numbers is returned, so every
     side effect is attributable to a signed permit.

No API key is ever logged. Fail-closed: transport errors, unknown tools,
denied permits and effect failures are all reported back as observations
and abort the loop after max_steps.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from prof.gateway import ExecuteRequest, Gateway
from prof.identity import Approver
from prof.permit import Permit, hash_args


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "crm.lookup",
            "description": "Look up a customer by ID. Returns name, tier and balance.",
            "parameters": {"type": "object",
                           "properties": {"customer": {"type": "string"}},
                           "required": ["customer"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file.write",
            "description": "Write text content to a file inside the sandbox.",
            "parameters": {"type": "object",
                           "properties": {"path": {"type": "string"},
                                          "content": {"type": "string"}},
                           "required": ["path", "content"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "payment.transfer",
            "description": "Transfer funds. HIGH-RISK: needs human approval.",
            "parameters": {"type": "object",
                           "properties": {"to": {"type": "string"},
                                          "amount": {"type": "number"},
                                          "idempotency_key": {"type": "string"}},
                           "required": ["to", "amount", "idempotency_key"]},
        },
    },
]

TOOL_BINDING = {
    "crm.lookup": ("tool.call", "tool:crm.lookup"),
    "file.write": ("file.write", None),          # resource derived from path
    "payment.transfer": ("payment.transfer", None),
}

SYSTEM_PROMPT = (
    "You are an operations agent. You can act ONLY through the provided tools, "
    "one call per turn. Every call is cryptographically approved and may be "
    "denied (expired permit, tampered args, replay, insufficient funds, or a "
    "high-risk action needing human approval). If a call is denied, explain "
    "why and either retry lawfully or stop. Never invent tool results."
)


@dataclass
class LLMConfig:
    base_url: str = field(default_factory=lambda: os.environ.get(
        "PROF_LLM_BASE_URL", "http://localhost:11434/v1"))
    api_key: str = field(default_factory=lambda: os.environ.get("PROF_LLM_API_KEY", ""))
    model: str = field(default_factory=lambda: os.environ.get("PROF_LLM_MODEL", "gpt-4o-mini"))
    timeout_s: int = 60

    @property
    def chat_url(self) -> str:
        return self.base_url.rstrip("/") + "/chat/completions"


class LLMError(RuntimeError):
    pass


def chat_complete(cfg: LLMConfig, messages: List[Dict[str, Any]],
                  tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """One OpenAI-compatible chat-completions call. Returns the message dict."""
    body = {"model": cfg.model, "messages": messages}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    req = urllib.request.Request(
        cfg.chat_url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **(
            {"Authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {})},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise LLMError(f"LLM transport error ({cfg.chat_url}): {exc}") from exc
    try:
        return payload["choices"][0]["message"]
    except (KeyError, IndexError) as exc:
        raise LLMError(f"unexpected LLM response shape: {str(payload)[:200]}") from exc


def check_connectivity(cfg: LLMConfig) -> Tuple[bool, str]:
    try:
        msg = chat_complete(cfg, [{"role": "user", "content": "ping"}])
        return True, f"ok: model={cfg.model} reply={str(msg.get('content', ''))[:80]}"
    except LLMError as exc:
        return False, str(exc)


@dataclass
class AgentResult:
    answer: str
    steps: List[Dict[str, Any]]
    allowed: int = 0
    denied: int = 0


def run_task(task: str, approver: Approver, gateway: Gateway,
             effects: Dict[str, Callable[[Dict[str, Any]], Any]],
             cfg: Optional[LLMConfig] = None, max_steps: int = 8,
             human_approve: bool = False,
             approve_fn: Optional[Callable[[Permit, Dict[str, Any]], bool]] = None,
             ) -> AgentResult:
    """Run one task through model -> PROF permit -> verified execution loop.

    effects: tool name -> effect function (see prof.resources).
    human_approve: if True, high-tier permits are signed (a human said yes).
    approve_fn: optional callback(permit, tool_args) -> bool for interactive approval.
    """
    cfg = cfg or LLMConfig()
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]
    steps: List[Dict[str, Any]] = []
    allowed = denied = 0
    for _ in range(max_steps):
        msg = chat_complete(cfg, messages, tools=TOOL_SCHEMAS)
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            return AgentResult(answer=str(msg.get("content") or ""), steps=steps,
                               allowed=allowed, denied=denied)
        messages.append({"role": "assistant", "content": msg.get("content"),
                         "tool_calls": tool_calls})
        for tc in tool_calls:
            name = (tc.get("function") or {}).get("name", "")
            raw_args = (tc.get("function") or {}).get("arguments", "{}")
            try:
                targs = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except json.JSONDecodeError:
                targs = {}
            call_id = tc.get("id", "")
            obs = _guarded_call(name, targs, approver, gateway, effects,
                                human_approve, approve_fn)
            steps.append({"tool": name, "args": targs, **obs})
            if obs["ok"]:
                allowed += 1
            else:
                denied += 1
            messages.append({"role": "tool", "tool_call_id": call_id,
                             "content": json.dumps(obs, ensure_ascii=False)[:4000]})
    return AgentResult(answer="(stopped: max_steps reached — no final answer)",
                       steps=steps, allowed=allowed, denied=denied)


def _guarded_call(name: str, targs: Dict[str, Any], approver: Approver,
                  gateway: Gateway, effects: Dict[str, Callable],
                  human_approve: bool,
                  approve_fn: Optional[Callable[[Permit, Dict[str, Any]], bool]]
                  ) -> Dict[str, Any]:
    binding = TOOL_BINDING.get(name)
    if binding is None or name not in effects:
        return {"ok": False, "decision": f"deny: unknown tool '{name}' (fail-closed)"}
    action, resource = binding
    if resource is None:  # derive concrete resource from args
        if name == "file.write":
            resource = f"file:{targs.get('path', '')}"
        elif name == "payment.transfer":
            resource = "account:krw-1"
    pol = gateway.policy.evaluate(action, resource, targs)
    if not pol.allow:
        return {"ok": False, "decision": f"deny: policy ({pol.reason})"}
    if pol.require_human:
        ok_human = human_approve or (approve_fn is not None and approve_fn(name, targs))
        if not ok_human:
            gateway.ledger.append("deny", "no-permit", action, resource,
                                  approver.subject, "agent:llm",
                                  f"high-tier {name} needs human approval")
            return {"ok": False,
                    "decision": f"deny: high-tier {name} requires human approval ({pol.reason})"}
    permit = Permit(subject=approver.subject, agent="agent:llm", action=action,
                    resource=resource, args_hash=hash_args(targs),
                    policy_id=gateway.policy.policy_id,
                    expiry=int(time.time()) + 300)
    permit.sign(approver._sk)
    dec, result = gateway.execute(
        ExecuteRequest(action, resource, targs, permit), effects[name])
    if not dec.allow:
        return {"ok": False, "decision": dec.reason}
    return {"ok": True, "decision": dec.reason, "result": result,
            "ledger_seq": dec.ledger_seq}
