"""PROF LLM integration — API-based agentic loop with proof-required tools.

Provider-agnostic: talks to any OpenAI-compatible chat-completions API
(OpenAI, Azure OpenAI, Ollama, vLLM, llama.cpp server, OpenRouter, …) using
only the standard library, so `pip install prof` stays dependency-free.

Config via environment (or explicit LLMConfig):
  PROF_LLM_PROVIDER   ollama | lmstudio | vllm | openai | azure | openrouter | anthropic
                      default: ollama (local, no key)
  PROF_LLM_BASE_URL   default per provider (override allowed)
  PROF_LLM_API_KEY    default "" (required for hosted providers; never logged)
  PROF_LLM_MODEL      default per provider

Two wire protocols: OpenAI-compatible chat-completions (covers Ollama,
LM Studio, vLLM, llama.cpp, OpenAI, Azure, OpenRouter) and Anthropic
native (/v1/messages, translated tool format).

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
    provider: str = field(default_factory=lambda: os.environ.get("PROF_LLM_PROVIDER", "ollama"))
    base_url: str = field(default_factory=lambda: os.environ.get("PROF_LLM_BASE_URL", ""))
    api_key: str = field(default_factory=lambda: os.environ.get("PROF_LLM_API_KEY", ""))
    model: str = field(default_factory=lambda: os.environ.get("PROF_LLM_MODEL", ""))
    timeout_s: int = 60

    def __post_init__(self) -> None:
        preset = PROVIDERS.get(self.provider, PROVIDERS["ollama"])
        if not self.base_url:
            object.__setattr__(self, "base_url", preset["base_url"])
        if not self.model:
            object.__setattr__(self, "model", preset["model"])

    @property
    def protocol(self) -> str:
        return PROVIDERS.get(self.provider, PROVIDERS["ollama"])["protocol"]

    @property
    def needs_key(self) -> bool:
        return PROVIDERS.get(self.provider, PROVIDERS["ollama"])["needs_key"]

    @property
    def chat_url(self) -> str:
        if self.protocol == "anthropic":
            return self.base_url.rstrip("/") + "/messages"
        return self.base_url.rstrip("/") + "/chat/completions"


PROVIDERS = {
    "ollama": {"protocol": "openai", "base_url": "http://localhost:11434/v1",
               "model": "gemma4:12b", "needs_key": False,
               "blurb": "Local Ollama server. No key. `ollama pull <model>` for more."},
    "lmstudio": {"protocol": "openai", "base_url": "http://localhost:1234/v1",
                 "model": "local-model", "needs_key": False,
                 "blurb": "Local LM Studio server (OpenAI-compatible endpoint)."},
    "vllm": {"protocol": "openai", "base_url": "http://localhost:8000/v1",
             "model": "Qwen/Qwen3-30B-A3B", "needs_key": False,
             "blurb": "Self-hosted vLLM OpenAI-compatible server."},
    "openai": {"protocol": "openai", "base_url": "https://api.openai.com/v1",
               "model": "gpt-6-astra", "needs_key": True,
               "blurb": "OpenAI API. Needs PROF_LLM_API_KEY."},
    "azure": {"protocol": "openai", "base_url": "",
              "model": "", "needs_key": True,
              "blurb": "Azure OpenAI. Set PROF_LLM_BASE_URL to your deployment URL + PROF_LLM_MODEL."},
    "openrouter": {"protocol": "openai", "base_url": "https://openrouter.ai/api/v1",
                   "model": "openai/gpt-6-astra", "needs_key": True,
                   "blurb": "OpenRouter gateway. Needs PROF_LLM_API_KEY."},
    "anthropic": {"protocol": "anthropic", "base_url": "https://api.anthropic.com/v1",
                  "model": "claude-sonnet-5-5", "needs_key": True,
                  "blurb": "Anthropic native API (translated tool format). Needs PROF_LLM_API_KEY."},
    "gemini": {"protocol": "openai", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
               "model": "gemini-4-argon", "needs_key": True,
               "blurb": "Google Gemini API (OpenAI-compat layer). Needs PROF_LLM_API_KEY (AI Studio)."},
}


# Curated defaults when a provider has no listable catalog (Anthropic has
# no /models API) or the endpoint is unreachable. Shown marked as fallback.
# Curated catalogs per provider (Oct 2026). Live /models listing always wins
# when reachable; these are the fallback AND the sane defaults. IDs follow
# vendor API conventions — confirm with `prof llm-setup` (live listing).
FALLBACK_MODELS = {
    "ollama": [
        {"id": "qwen3:30b", "tools": True},
        {"id": "qwen3:8b", "tools": True},
        {"id": "gemma4:12b", "tools": True},
        {"id": "gemma3:12b", "tools": True},
        {"id": "qwen3-coder:30b-a3b", "tools": True},
        {"id": "llama3.3:70b", "tools": True},
        {"id": "gpt-oss:120b", "tools": True},
        {"id": "deepseek-r1:32b", "tools": True},
        {"id": "granite4:3b", "tools": True},
    ],
    "lmstudio": [{"id": "local-model", "tools": False}],
    "vllm": [
        {"id": "Qwen/Qwen3-30B-A3B", "tools": True},
        {"id": "meta-llama/Llama-4-Maverick-17B-128E-Instruct", "tools": True},
        {"id": "meta-llama/llama-4-scout", "tools": True},
        {"id": "deepseek-ai/DeepSeek-V4", "tools": True},
    ],
    "openai": [
        {"id": "gpt-6-astra", "tools": True},
        {"id": "gpt-6.1-sol", "tools": True},
        {"id": "gpt-6-sol", "tools": True},
        {"id": "gpt-6-luna", "tools": True},
        {"id": "gpt-5.6-sol", "tools": True},
        {"id": "gpt-5.6-terra", "tools": True},
        {"id": "gpt-5.6-luna", "tools": True},
        {"id": "gpt-oss-120b", "tools": True},
    ],
    "azure": [],
    "openrouter": [
        {"id": "openai/gpt-6-astra", "tools": True},
        {"id": "openai/gpt-6.1-sol", "tools": True},
        {"id": "anthropic/claude-sonnet-5-5", "tools": True},
        {"id": "anthropic/claude-opus-5-5", "tools": True},
        {"id": "google/gemini-4-argon", "tools": True},
        {"id": "qwen/qwen3-30b-a3b-instruct-2507", "tools": True},
        {"id": "moonshotai/kimi-k2.6", "tools": True},
        {"id": "deepseek/deepseek-v4-pro", "tools": True},
    ],
    "anthropic": [
        {"id": "claude-sonnet-5-5", "tools": True},
        {"id": "claude-opus-5-5", "tools": True},
        {"id": "claude-haiku-5-5", "tools": True},
        {"id": "claude-fable-5-1", "tools": True},
        {"id": "claude-opus-5", "tools": True},
        {"id": "claude-sonnet-5", "tools": True},
    ],
    "gemini": [
        {"id": "gemini-4-argon", "tools": True},
        {"id": "gemini-3.5-flash", "tools": True},
        {"id": "gemini-3.5-flash-lite", "tools": True},
        {"id": "gemini-3.1-pro", "tools": True},
    ],
}


class LLMError(RuntimeError):
    pass


def chat_complete(cfg: LLMConfig, messages: List[Dict[str, Any]],
                  tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """One chat round. Returns an OpenAI-style message dict (normalized)."""
    if cfg.protocol == "anthropic":
        return _anthropic_complete(cfg, messages, tools)
    return _openai_complete(cfg, messages, tools)


def _openai_complete(cfg: LLMConfig, messages: List[Dict[str, Any]],
                     tools: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
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


def _anthropic_tools(tools: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    out = []
    for t in tools or []:
        fn = t.get("function", t)
        out.append({"name": fn.get("name", ""), "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {"type": "object"})})
    return out


def _anthropic_complete(cfg: LLMConfig, messages: List[Dict[str, Any]],
                        tools: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Native Anthropic API, normalized back to OpenAI-style message dict."""
    if cfg.needs_key and not cfg.api_key:
        raise LLMError("anthropic provider needs PROF_LLM_API_KEY")
    system, convo = "", []
    for m in messages:
        if m.get("role") == "system":
            system += str(m.get("content") or "")
        elif m.get("role") == "tool":
            convo.append({"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": m.get("tool_call_id", ""),
                "content": str(m.get("content") or "")}]})
        elif m.get("role") == "assistant" and m.get("tool_calls"):
            blocks: List[Dict[str, Any]] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": str(m["content"])})
            for tc in m["tool_calls"]:
                fn = tc.get("function", {})
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}
                blocks.append({"type": "tool_use", "id": tc.get("id", ""),
                               "name": fn.get("name", ""), "input": args})
            convo.append({"role": "assistant", "content": blocks})
        else:
            convo.append({"role": m.get("role", "user"),
                          "content": str(m.get("content") or "")})
    body: Dict[str, Any] = {"model": cfg.model, "max_tokens": 1024, "messages": convo}
    if system:
        body["system"] = system
    at = _anthropic_tools(tools)
    if at:
        body["tools"] = at
    req = urllib.request.Request(
        cfg.chat_url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "x-api-key": cfg.api_key, "anthropic-version": "2023-06-01"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise LLMError(f"LLM transport error ({cfg.chat_url}): {exc}") from exc
    try:
        blocks = payload["content"]
    except KeyError as exc:
        raise LLMError(f"unexpected Anthropic response: {str(payload)[:200]}") from exc
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    calls = [{"id": b.get("id", ""), "type": "function",
              "function": {"name": b.get("name", ""),
                           "arguments": json.dumps(b.get("input", {}))}}
             for b in blocks if b.get("type") == "tool_use"]
    msg: Dict[str, Any] = {"role": "assistant", "content": text or None}
    if calls:
        msg["tool_calls"] = calls
    return msg


def list_models(cfg: LLMConfig) -> List[Dict[str, Any]]:
    """Best-effort model list. OpenAI-compatible /models, or Anthropic's
    native Models API. Empty when unsupported/unreachable. Each entry is
    {"id": str, "tools": bool}."""
    if cfg.protocol == "anthropic":
        return _anthropic_models(cfg)
    if cfg.protocol != "openai":
        return []
    base = cfg.base_url.strip()
    if not base.startswith(("http://", "https://")):
        return []  # unconfigured/relative endpoint (e.g. azure before env is set)
    url = base.rstrip("/") + "/models"
    try:
        req = urllib.request.Request(url, headers={
            "Content-Type": "application/json", **(
                {"Authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {})})
        with urllib.request.urlopen(req, timeout=min(cfg.timeout_s, 15)) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        models = [m.get("id", "") for m in payload.get("data", []) if m.get("id")]
        tool_map = {m["id"]: m.get("tools", False) for m in FALLBACK_MODELS.get(cfg.provider, [])}
        # A "tools" flag from the live endpoint overrides the curated catalog.
        for m in payload.get("data", []):
            mid = m.get("id")
            if mid and "tools" in m:
                tool_map[mid] = m["tools"]
        return [{"id": m, "tools": tool_map.get(m, False)} for m in sorted(models)]
    except Exception:
        return []


def _anthropic_models(cfg: LLMConfig) -> List[Dict[str, Any]]:
    if not cfg.api_key:
        return []
    base = cfg.base_url.strip()
    if not base.startswith(("http://", "https://")):
        return []
    try:
        req = urllib.request.Request(
            base.rstrip("/") + "/models",
            headers={"x-api-key": cfg.api_key, "anthropic-version": "2023-06-01"})
        with urllib.request.urlopen(req, timeout=min(cfg.timeout_s, 15)) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        models = [m.get("id", "") for m in payload.get("data", []) if m.get("id")]
        tool_map = {m["id"]: m.get("tools", False) for m in FALLBACK_MODELS.get(cfg.provider, [])}
        # A "tools" flag from the live endpoint overrides the curated catalog.
        for m in payload.get("data", []):
            mid = m.get("id")
            if mid and "tools" in m:
                tool_map[mid] = m["tools"]
        return [{"id": m, "tools": tool_map.get(m, False)} for m in sorted(models)]
    except Exception:
        return []


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
