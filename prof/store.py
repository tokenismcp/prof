"""Nonce / replay store with file persistence (single-node, crash-durable).

Multi-node linearizable store (Postgres/etcd) is an explicit non-goal for v0.1.
See docs/ARCHITECTURE.md for the seam (`NonceStore` interface).
"""

from __future__ import annotations

import json
import os
import threading
from typing import Dict, Optional


class NonceStore:
    def __init__(self, path: Optional[str] = None):
        self._lock = threading.Lock()
        self._path = path
        self._seen: Dict[str, int] = {}  # nonce -> used_at
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._seen = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._seen = {}

    def _persist(self) -> None:
        if not self._path:
            return
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._seen, f)
        os.replace(tmp, self._path)

    def check_and_reserve(self, nonce: str, now: int) -> bool:
        """Return True if fresh (and reserve it). False if replay."""
        with self._lock:
            if nonce in self._seen:
                return False
            self._seen[nonce] = now
            self._persist()
            return True

    def is_seen(self, nonce: str) -> bool:
        with self._lock:
            return nonce in self._seen

    def size(self) -> int:
        with self._lock:
            return len(self._seen)
