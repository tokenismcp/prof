"""Nonce / replay store with file persistence (single-node, crash-durable).

v2: entries carry the permit expiry, so spent nonces are pruned once the
permit itself is dead (an expired permit can never authorize, so forgetting
its nonce is safe). The file is an append-only JSONL journal; pruning
rewrites a compact snapshot. Memory/disk stay proportional to *live*
permits, not history.

Multi-node linearizable store (Postgres/etcd) is an explicit non-goal for v0.1.
See docs/ARCHITECTURE.md for the seam (`NonceStore` interface).
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Dict, Optional

DEFAULT_TTL_S = 300
_PRUNE_INTERVAL_S = 60
_PRUNE_SIZE_TRIGGER = 5000


def _jsonl(f) -> list:
    """Parse a JSONL journal. A malformed *final* line is a torn append from a
    crash (never acknowledged, so safe to drop); malformed interior lines mean
    corruption and raise (fail-closed: forgetting a spent nonce would allow replay)."""
    lines = [ln for ln in f.read().splitlines() if ln.strip()]
    out = []
    for i, ln in enumerate(lines):
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            if i == len(lines) - 1:
                break
            raise
    return out


class NonceStore:
    def __init__(self, path: Optional[str] = None):
        # RLock: check_and_reserve() prunes under the same guard.
        # (A plain Lock deadlocked here once the 60 s prune timer fired —
        # caught by faulthandler during review. Never downgrade this.)
        self._lock = threading.RLock()
        self._path = path
        self._seen: Dict[str, int] = {}  # nonce -> expiry (unix seconds)
        self._last_prune = time.time()
        if path and os.path.exists(path):
            self._load()

    # ---- persistence ----
    def _load(self) -> None:
        assert self._path
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                head = f.read(1)
                if not head:
                    return
                if head == "[":
                    f.seek(0)
                    raw = json.load(f)  # v1 array format
                elif head == "{":
                    rest = f.read()
                    try:
                        one = json.loads(head + rest)
                        is_single = isinstance(one, dict)
                    except json.JSONDecodeError:
                        is_single = False
                    if is_single:
                        raw = [one] if "nonce" in one else []
                        if not raw:
                            self._load_legacy_mapping(one)
                            return
                    else:
                        f.seek(0)
                        raw = _jsonl(f)
                else:
                    f.seek(0)
                    raw = _jsonl(f)
        except json.JSONDecodeError:
            raise  # interior corruption: refuse to start (forgetting nonces = replay)
        for rec in raw:
            try:
                self._seen[str(rec["nonce"])] = int(rec["expiry"])
            except (KeyError, ValueError, TypeError):
                continue

    def _load_legacy_mapping(self, raw: dict) -> None:
        """v1 files mapped nonce -> used_at. Grant a 1h grace expiry, then prune."""
        now = int(time.time())
        for nonce in raw:
            self._seen[str(nonce)] = now + 3600

    def _journal(self, nonce: str, expiry: int) -> None:
        if not self._path:
            return
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"nonce": nonce, "expiry": expiry}) + "\n")

    def _snapshot(self) -> None:
        if not self._path:
            return
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for nonce, expiry in self._seen.items():
                f.write(json.dumps({"nonce": nonce, "expiry": expiry}) + "\n")
        os.replace(tmp, self._path)

    # ---- core ----
    def check_and_reserve(self, nonce: str, now: int,
                          expiry: Optional[int] = None) -> bool:
        """Return True if fresh (and reserve it until `expiry`). False if replay."""
        exp = int(expiry) if expiry is not None else int(now) + DEFAULT_TTL_S
        with self._lock:
            if nonce in self._seen:
                return False
            self._seen[nonce] = exp
            self._journal(nonce, exp)
            self._maybe_prune(now)
            return True

    def _maybe_prune(self, now: int) -> None:
        if (len(self._seen) < _PRUNE_SIZE_TRIGGER
                and now - self._last_prune < _PRUNE_INTERVAL_S):
            return
        self.prune(now)

    def prune(self, now: Optional[int] = None) -> int:
        """Drop nonces whose permits are dead. Returns evicted count."""
        now = int(time.time()) if now is None else int(now)
        with self._lock:
            # a permit is still valid at now == expiry (is_expired uses `>`), so keep it
            dead = [n for n, e in self._seen.items() if e < now]
            for n in dead:
                del self._seen[n]
            self._last_prune = now
            if dead:
                self._snapshot()
            return len(dead)

    def is_seen(self, nonce: str) -> bool:
        with self._lock:
            return nonce in self._seen

    def size(self) -> int:
        with self._lock:
            return len(self._seen)
