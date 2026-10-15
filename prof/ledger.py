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
import threading
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
    def __init__(self, path: Optional[str] = None, fsync: bool = False):
        self._path = path
        self._fsync = fsync or os.environ.get("PROF_LEDGER_FSYNC", "0") == "1"
        self._lock = threading.RLock()
        self.entries: List[LedgerEntry] = []
        if path and os.path.exists(path):
            self._load()
        if not self.entries:
            genesis = "genesis:" + secrets.token_hex(16)
            gh = "sha256:" + hashlib.sha256(genesis.encode()).hexdigest()
            self._genesis_hash = gh
        else:
            self._genesis_hash = self.entries[0].prev_hash
        self._verified_head = self._genesis_hash

    @property
    def head(self) -> str:
        if not self.entries:
            return self._genesis_hash
        return self.entries[-1].entry_hash

    def append(self, event: str, permit_nonce: str, action: str, resource: str,
               subject: str, agent: str, detail: str = "") -> LedgerEntry:
        with self._lock:
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
            self._persist(e)
            return e

    def verify_chain(self) -> tuple[bool, str]:
        """Verify append-only integrity over EVERY entry, every time.

        Deliberately no incremental cache: a cache that trusts the prefix
        blindly can miss in-memory tampering of already-verified entries
        (proven by test_incremental_* during review — removed, not shipped).
        Cost is ~1 hash/entry; see bench/ for measured numbers. If chains
        outgrow single-pass verification, the honest fix is segmented
        checkpointing, not skipped checks.
        """
        with self._lock:
            entries = list(self.entries)
            genesis = self._genesis_hash
        prev = genesis
        for e in entries:
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

    def _persist(self, e: LedgerEntry) -> None:
        """Append one JSONL line (O(1)). Legacy array files are still readable."""
        if not self._path:
            return
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(e), ensure_ascii=False) + "\n")
            f.flush()
            if self._fsync:
                os.fsync(f.fileno())

    def _save(self) -> None:  # kept for explicit snapshots (tests, rotation)
        if not self._path:
            return
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for e in self.entries:
                f.write(json.dumps(asdict(e), ensure_ascii=False) + "\n")
        os.replace(tmp, self._path)

    def _load(self) -> None:
        assert self._path
        with open(self._path, "r", encoding="utf-8") as f:
            head = f.read(1)
            if not head:
                return
            f.seek(0)
            if head == "[":
                raw = json.load(f)  # v1 array format
            else:
                raw = [json.loads(line) for line in f if line.strip()]
        self.entries = [LedgerEntry(**r) for r in raw]
