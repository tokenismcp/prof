"""PROF agent task inbox — one queue, many frontends.

The console (or CLI/API) submits a task; any connected agent claims it over
MCP (``prof.task.next``), does the work with PROF-protected tools, and reports
the outcome (``prof.task.done``). This turns the console "Run a task" box into
an assignment surface for agents that run elsewhere (Claude Code, Codex,
Gemini CLI, Dots, Muse, …), while the built-in LLM loop keeps running tasks
directly.

The store is a process-wide singleton: the gateway's HTTP API (``/v1/tasks``)
and its in-process MCP endpoint (``POST /mcp``) share one inbox. Out-of-process
agents reach it through ``PROF_GATEWAY_URL`` (remote mode) — see
``prof.mcpd`` and ``prof.client``.

Fail-closed by construction: a claim is atomic (one agent, one task, one
token), a completion must present that token, and a claimed-but-unfinished
task returns to the pool after ``CLAIM_TTL_S`` so a crashed agent never
strands work.
"""

from __future__ import annotations

import secrets
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

# A claimed-but-unfinished task returns to the pool after this many seconds,
# so a crashed/stalled agent doesn't strand work.
CLAIM_TTL_S = 600

_LOCK = threading.Lock()
_TASKS: Dict[str, Dict[str, Any]] = {}

FINISHED = ("done", "failed", "cancelled")


def _new_id() -> str:
    return "task-" + secrets.token_hex(6)


def submit(task: str, *, agent: str = "", max_steps: int = 8,
           human_approve: bool = False, provider: str = "", model: str = "",
           base_url: str = "", created_by: str = "human") -> Dict[str, Any]:
    """Enqueue a task. ``agent`` (optional) targets one agent name."""
    task = (task or "").strip()
    if not task:
        raise ValueError("task must not be empty")
    tid = _new_id()
    now = int(time.time())
    rec: Dict[str, Any] = {
        "id": tid, "task": task, "status": "pending",
        "target_agent": (agent or "").strip(), "max_steps": int(max_steps),
        "human_approve": bool(human_approve),
        "provider": provider or "", "model": model or "",
        "base_url": base_url or "", "created_by": created_by,
        "created_ts": now, "claimed_by": None, "claimed_ts": None,
        "claim_token": None, "result": None, "ok": None,
        "error": None, "done_ts": None,
    }
    with _LOCK:
        _TASKS[tid] = rec
        return dict(rec)


def get(tid: str) -> Optional[Dict[str, Any]]:
    with _LOCK:
        rec = _TASKS.get(tid)
        return dict(rec) if rec else None


def list_tasks(status: str = "", limit: int = 50) -> List[Dict[str, Any]]:
    with _LOCK:
        items = list(_TASKS.values())
    if status:
        items = [t for t in items if t["status"] == status]
    items.sort(key=lambda t: t["created_ts"], reverse=True)
    return [dict(t) for t in items[: max(1, int(limit))]]


def _reclaimable(rec: Dict[str, Any], now: int) -> bool:
    return (rec["status"] == "claimed" and rec.get("claimed_ts") is not None
            and now - rec["claimed_ts"] > CLAIM_TTL_S)


def claim(agent: str = "") -> Optional[Dict[str, Any]]:
    """Atomically take the oldest matching ready task. None when none ready."""
    agent = (agent or "agent:mcp").strip()
    now = int(time.time())
    with _LOCK:
        ready = [t for t in _TASKS.values()
                 if t["status"] == "pending" or _reclaimable(t, now)]
        # An unset target means "any agent"; otherwise only that agent may take it.
        ready = [t for t in ready
                 if not t["target_agent"] or t["target_agent"] == agent]
        if not ready:
            return None
        rec = min(ready, key=lambda t: t["created_ts"])
        rec["status"] = "claimed"
        rec["claimed_by"] = agent
        rec["claimed_ts"] = now
        rec["claim_token"] = secrets.token_hex(8)
        return dict(rec)


def complete(tid: str, token: str, ok: bool = True, result: str = "",
             error: str = "") -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Finish a claimed task. Returns (success, message, record)."""
    now = int(time.time())
    with _LOCK:
        rec = _TASKS.get(tid)
        if rec is None:
            return False, f"unknown task: {tid}", None
        if rec["status"] in FINISHED:
            return False, f"task already {rec['status']}", dict(rec)
        if rec["status"] != "claimed":
            return False, "task is not claimed", dict(rec)
        if not token or not secrets.compare_digest(str(token), str(rec.get("claim_token") or "")):
            return False, "invalid claim token", dict(rec)
        rec["status"] = "done" if ok else "failed"
        rec["ok"] = bool(ok)
        rec["result"] = result or None
        rec["error"] = error or None
        rec["done_ts"] = now
        return True, "ok", dict(rec)


def cancel(tid: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    now = int(time.time())
    with _LOCK:
        rec = _TASKS.get(tid)
        if rec is None:
            return False, f"unknown task: {tid}", None
        if rec["status"] in FINISHED:
            return False, f"task already {rec['status']}", dict(rec)
        rec["status"] = "cancelled"
        rec["done_ts"] = now
        return True, "cancelled", dict(rec)


def clear(status: str = "") -> int:
    """Drop finished tasks (or everything matching ``status``). Returns count."""
    with _LOCK:
        if status:
            ids = [k for k, v in _TASKS.items() if v["status"] == status]
        else:
            ids = [k for k, v in _TASKS.items() if v["status"] in FINISHED]
        for k in ids:
            del _TASKS[k]
        return len(ids)


def counts() -> Dict[str, int]:
    with _LOCK:
        out: Dict[str, int] = {}
        for v in _TASKS.values():
            out[v["status"]] = out.get(v["status"], 0) + 1
        return out


def reset() -> None:
    """Test helper: empty the inbox."""
    with _LOCK:
        _TASKS.clear()
