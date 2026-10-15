"""PROF remote gateway client — one gateway, many frontends.

When PROF_GATEWAY_URL is set (e.g. http://127.0.0.1:8091), out-of-process
frontends (MCP server, remote CLI runs) enforce through the shared HTTP
gateway instead of a private in-process one. Permits are still verified
server-side; this client never sees private keys.

Optional auth: PROF_API_TOKEN (or explicit token) -> Bearer header.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Dict, List, Optional


class ClientError(RuntimeError):
    def __init__(self, status: int, detail: str):
        super().__init__(f"gateway HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


class GatewayClient:
    def __init__(self, base_url: Optional[str] = None, token: str = "",
                 timeout_s: int = 30):
        self.base_url = (base_url or os.environ.get("PROF_GATEWAY_URL", "")).rstrip("/")
        if not self.base_url:
            raise ValueError("no gateway URL: pass base_url or set PROF_GATEWAY_URL")
        self.token = token or os.environ.get("PROF_API_TOKEN", "")
        self.timeout_s = timeout_s

    def _call(self, method: str, path: str, body: Optional[dict] = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.base_url + path, data=data,
                                     headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                raw = resp.read().decode("utf-8") or "{}"
                return json.loads(raw)
        except urllib.error.HTTPError as exc:  # noqa
            try:
                detail = json.loads(exc.read().decode("utf-8") or "{}")
                msg = detail.get("detail", str(detail))
            except Exception:
                msg = f"HTTP {exc.code}"
            raise ClientError(exc.code, str(msg)) from exc
        except OSError as exc:
            raise ClientError(0, f"transport error: {exc}") from exc

    # ---- reads (open) ----
    def version(self) -> dict:
        return self._call("GET", "/version")

    def policy(self) -> dict:
        return self._call("GET", "/v1/policy")

    def ledger(self, limit: int = 100) -> dict:
        return self._call("GET", f"/v1/ledger?limit={limit}")

    def metrics(self) -> dict:
        return self._call("GET", "/metrics")

    def llm_status(self) -> dict:
        return self._call("GET", "/v1/llm/status")

    def llm_config(self, provider: str = "", model: str = "",
                   base_url: str = "") -> dict:
        return self._call("POST", "/v1/llm/config",
                          {"provider": provider, "model": model,
                           "base_url": base_url})

    # ---- writes (token-protected when configured) ----
    def approve(self, agent: str, action: str, resource: str,
                args: Optional[dict] = None, ttl_s: int = 300) -> dict:
        return self._call("POST", "/v1/approve",
                          {"agent": agent, "action": action, "resource": resource,
                           "args": args or {}, "ttl_s": ttl_s})

    def auto_approve(self, agent: str, action: str, resource: str,
                     args: Optional[dict] = None) -> dict:
        """Server-minted permit for non-human tiers. 403 for high-tier."""
        return self._call("POST", "/v1/auto-approve",
                          {"agent": agent, "action": action, "resource": resource,
                           "args": args or {}})

    def execute(self, action: str, resource: str, args: Optional[dict] = None,
                permit: Optional[dict] = None) -> dict:
        return self._call("POST", "/v1/execute",
                          {"action": action, "resource": resource,
                           "args": args or {}, "permit": permit or {}})

    def create_request(self, agent: str, action: str, resource: str,
                       args: Optional[dict] = None, ttl_s: int = 300) -> dict:
        return self._call("POST", "/v1/requests",
                          {"agent": agent, "action": action, "resource": resource,
                           "args": args or {}, "ttl_s": ttl_s})

    def get_request(self, rid: str) -> dict:
        return self._call("GET", f"/v1/requests/{rid}")

    def decide_request(self, rid: str, approve: bool, reason: str = "") -> dict:
        if approve:
            return self._call("POST", f"/v1/requests/{rid}/approve", {})
        return self._call("POST", f"/v1/requests/{rid}/deny", {"reason": reason})

    def agent_run(self, task: str, max_steps: int = 8, human_approve: bool = False,
                  wait_approval: bool = False, approval_timeout_s: int = 120,
                  provider_override: str = "", model_override: str = "",
                  base_url_override: str = "") -> dict:
        return self._call("POST", "/v1/agent/run",
                          {"task": task, "max_steps": max_steps,
                           "human_approve": human_approve,
                           "wait_approval": wait_approval,
                           "approval_timeout_s": approval_timeout_s,
                           "provider_override": provider_override,
                           "model_override": model_override,
                           "base_url_override": base_url_override})

    def list_requests(self, status: str = "pending") -> List[dict]:
        return self._call("GET", f"/v1/requests?status={status}").get("requests", [])
