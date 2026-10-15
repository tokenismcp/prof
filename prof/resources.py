"""PROF resource layer — real, persistent state behind the tools.

Replaces the old canned demo functions. All state lives in SQLite so it
survives restarts, supports concurrent access via transactions, and gives
the ledger something real to point at (row hashes, balances, idempotency).

Tables:
  customers(id PK, name, tier, balance_cents)
  accounts(id PK, balance_cents)
  payments(idempotency_key PK, from_acct, to_acct, amount_cents, ts, permit_nonce)
  files(path PK, sha256, nbytes, updated_ts)

Data root for file writes: PROF_DATA_ROOT (default: /tmp/prof-demo).
DB location: PROF_DB (default: in-memory demo). Production sets
PROF_DB=/data/prof.db (compose/k8s already mount /data).
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
from typing import Any, Dict, Optional

SANDBOX_ENV = "PROF_DATA_ROOT"
DEFAULT_SANDBOX = "/tmp/prof-demo"

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers(
  id TEXT PRIMARY KEY, name TEXT NOT NULL, tier TEXT NOT NULL, balance_cents INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS accounts(
  id TEXT PRIMARY KEY, balance_cents INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS payments(
  idempotency_key TEXT PRIMARY KEY, from_acct TEXT NOT NULL, to_acct TEXT NOT NULL,
  amount_cents INTEGER NOT NULL, ts INTEGER NOT NULL, permit_nonce TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS files(
  path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, nbytes INTEGER NOT NULL, updated_ts INTEGER NOT NULL);
"""

SEED_CUSTOMERS = [
    ("acme-42", "Acme Corp", "gold", 12500000),
    ("globex-7", "Globex Inc", "silver", 4025000),
    ("initech-9", "Initech LLC", "bronze", 750000),
]
SEED_ACCOUNTS = [
    ("account:krw-1", 100000000),   # 1,000,000.00 KRW in cents
    ("account:krw-2", 5000000),
]


class ResourceDB:
    """Thread-safe SQLite store. path=None -> in-memory (demo/test)."""

    def __init__(self, path: Optional[str] = None):
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path or ":memory:", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock, self._conn:
            self._conn.executescript(SCHEMA)
            for cid, name, tier, bal in SEED_CUSTOMERS:
                self._conn.execute(
                    "INSERT OR IGNORE INTO customers VALUES (?,?,?,?)", (cid, name, tier, bal))
            for aid, bal in SEED_ACCOUNTS:
                self._conn.execute(
                    "INSERT OR IGNORE INTO accounts VALUES (?,?)", (aid, bal))

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---- customers ----
    def customer(self, cid: str) -> Dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM customers WHERE id=?", (cid,)).fetchone()
        if row is None:
            raise KeyError(f"unknown customer: {cid}")
        return {"customer": row["id"], "name": row["name"], "tier": row["tier"],
                "balance": row["balance_cents"] / 100}

    # ---- files ----
    def sandbox(self) -> str:
        return os.environ.get(SANDBOX_ENV, DEFAULT_SANDBOX)

    def write_file(self, path: str, content: str) -> Dict[str, Any]:
        norm = os.path.normpath(path)
        root = os.path.normpath(self.sandbox())
        if norm != root and not norm.startswith(root + os.sep):
            raise PermissionError(f"outside sandbox ({root}): {path}")
        pre = self.file_state(norm)
        os.makedirs(os.path.dirname(norm) or root, exist_ok=True)
        data = content.encode("utf-8")
        with open(norm, "wb") as f:
            f.write(data)
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO files VALUES (?,?,?,?)",
                (norm, digest, len(data), int(time.time())))
        return {"path": norm, "bytes": len(data), "sha256": digest,
                "prev_sha256": pre["sha256"] if pre else None}

    def file_state(self, path: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM files WHERE path=?", (path,)).fetchone()
        return dict(row) if row else None

    # ---- payments ----
    def transfer(self, from_acct: str, to_acct: str, amount: float,
                 idempotency_key: str, permit_nonce: str) -> Dict[str, Any]:
        if amount <= 0:
            raise ValueError("amount must be > 0")
        if not idempotency_key:
            raise ValueError("idempotency_key is required")
        cents = int(round(amount * 100))
        with self._lock, self._conn:
            dup = self._conn.execute(
                "SELECT * FROM payments WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if dup is not None:
                return {"duplicate": True, "to": dup["to_acct"],
                        "amount": dup["amount_cents"] / 100,
                        "idempotency_key": idempotency_key}
            src = self._conn.execute(
                "SELECT balance_cents FROM accounts WHERE id=?", (from_acct,)).fetchone()
            if src is None:
                raise KeyError(f"unknown account: {from_acct}")
            if src["balance_cents"] < cents:
                raise ValueError(f"insufficient funds in {from_acct}")
            self._conn.execute("INSERT OR IGNORE INTO accounts VALUES (?,?)", (to_acct, 0))
            self._conn.execute("UPDATE accounts SET balance_cents=balance_cents-? WHERE id=?",
                               (cents, from_acct))
            self._conn.execute("UPDATE accounts SET balance_cents=balance_cents+? WHERE id=?",
                               (cents, to_acct))
            self._conn.execute(
                "INSERT INTO payments VALUES (?,?,?,?,?,?)",
                (idempotency_key, from_acct, to_acct, cents, int(time.time()), permit_nonce))
            bal = self._conn.execute(
                "SELECT balance_cents FROM accounts WHERE id=?", (from_acct,)).fetchone()["balance_cents"]
        return {"duplicate": False, "from": from_acct, "to": to_acct,
                "amount": amount, "idempotency_key": idempotency_key,
                "from_balance": bal / 100}

    def account_balance(self, acct: str) -> float:
        with self._lock:
            row = self._conn.execute(
                "SELECT balance_cents FROM accounts WHERE id=?", (acct,)).fetchone()
        if row is None:
            raise KeyError(f"unknown account: {acct}")
        return row["balance_cents"] / 100


# ---- process-wide default DB (demo/CLI/MCP-server scope) ----
_default: Optional[ResourceDB] = None
_default_lock = threading.Lock()


def get_db(path: Optional[str] = None) -> ResourceDB:
    """Return the process default DB, creating it on first use.

    path defaults to $PROF_DB (production) else in-memory demo.
    """
    global _default
    with _default_lock:
        if _default is None:
            _default = ResourceDB(path or os.environ.get("PROF_DB") or None)
        return _default


def reset_db(path: Optional[str] = None) -> ResourceDB:
    global _default
    with _default_lock:
        if _default is not None:
            try:
                _default.close()
            except Exception:
                pass
        _default = ResourceDB(path or os.environ.get("PROF_DB") or None)
        return _default


# ---- tool effect functions: (args) -> result, real state transitions ----
def crm_lookup(args: Dict[str, Any]) -> Dict[str, Any]:
    return get_db().customer(str(args.get("customer", "")))


def file_write(args: Dict[str, Any]) -> Dict[str, Any]:
    return get_db().write_file(str(args.get("path", "")), str(args.get("content", "")))


def payment_transfer(args: Dict[str, Any]) -> Dict[str, Any]:
    db = get_db()
    return db.transfer(
        from_acct=str(args.get("from", "account:krw-1")),
        to_acct=str(args.get("to", "")),
        amount=float(args.get("amount", 0)),
        idempotency_key=str(args.get("idempotency_key", "")),
        permit_nonce=str(args.get("_permit_nonce", "")),
    )
