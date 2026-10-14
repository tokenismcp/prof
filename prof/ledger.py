"""Hash-chained audit ledger.

h_0 = genesis (random), h_{t+1} = SHA256(h_t || canonical(decision))

Tamper-evident, not tamper-proof: verifies append-only integrity on load.
External transparency / witness cosigning is roadmap (Enterprise).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


def _canon(d: Dict[str, Any]) -> bytes:
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


@dataclass
class LedgerEntry:
    seq: int
    ts: int
    event: str          # "approve" | "allow" | "deny"
    permit_nonce: str
    action: str
    resource: str
    subject: str
    agent: str
    detail: str
    prev_hash: str
    entry_hash: str


class Ledger:
    def __init__(self, path: Optional[str] = None):
        self._path = path
        self.entries: List[LedgerEntry] = []
        if path and os.path.exists(path):
            self._load()
        if not self.entries:
            genesis = "genesis:" + secrets.token_hex(16)
            gh = "sha256:" + hashlib.sha256(genesis.encode()).hexdigest()
            self._genesis_hash = gh
        else:
            self._genesis_hash = self.entries[0].prev_hash

    @property
    def head(self) -> str:
        if not self.entries:
            return self._genesis_hash
        return self.entries[-1].entry_hash

    def append(self, event: str, permit_nonce: str, action: str, resource: str,
               subject: str, agent: str, detail: str = "") -> LedgerEntry:
        seq = len(self.entries)
        prev = self.head
        ts = int(time.time())
        core = {"seq": seq, "ts": ts, "event": event, "permit_nonce": permit_nonce,
                "action": action, "resource": resource, "subject": subject,
                "agent": agent, "detail": detail, "prev_hash": prev}
        h = "sha256:" + hashlib.sha256(prev.encode() + _canon(core)).hexdigest()
        e = LedgerEntry(seq=seq, ts=ts, event=event, permit_nonce=permit_nonce,
                        action=action, resource=resource, subject=subject,
                        agent=agent, detail=detail, prev_hash=prev, entry_hash=h)
        self.entries.append(e)
        self._save()
        return e

    def verify_chain(self) -> tuple[bool, str]:
        prev = self._genesis_hash
        for e in self.entries:
            core = {"seq": e.seq, "ts": e.ts, "event": e.event, "permit_nonce": e.permit_nonce,
                    "action": e.action, "resource": e.resource, "subject": e.subject,
                    "agent": e.agent, "detail": e.detail, "prev_hash": e.prev_hash}
            expect = "sha256:" + hashlib.sha256(e.prev_hash.encode() + _canon(core)).hexdigest()
            if e.prev_hash != prev:
                return False, f"break at seq {e.seq}: prev mismatch"
            if e.entry_hash != expect:
                return False, f"break at seq {e.seq}: hash mismatch (tampered?)"
            prev = e.entry_hash
        return True, f"ok: {len(self.entries)} entries, head {prev[:18]}..."

    def _save(self) -> None:
        if not self._path:
            return
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump([asdict(e) for e in self.entries], f, indent=2)
        os.replace(tmp, self._path)

    def _load(self) -> None:
        assert self._path
        with open(self._path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        self.entries = [LedgerEntry(**r) for r in raw]
