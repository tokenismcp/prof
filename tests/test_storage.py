import json
import time

from prof.ledger import Ledger
from prof.store import NonceStore


# ---- nonce expiry + journal ----
def test_nonce_replay_blocked_but_expired_pruned(tmp_path):
    p = str(tmp_path / "n.jsonl")
    ns = NonceStore(p)
    now = int(time.time())
    assert ns.check_and_reserve("live-1", now, now + 300) is True
    assert ns.check_and_reserve("live-1", now, now + 300) is False  # replay
    assert ns.check_and_reserve("dead-1", now, now - 1) is True   # stored, already dead
    assert ns.size() == 2
    assert ns.prune(now + 1000) == 2  # both dead by then
    assert ns.size() == 0


def test_nonce_journal_survives_reopen(tmp_path):
    p = str(tmp_path / "n.jsonl")
    ns = NonceStore(p)
    now = int(time.time())
    ns.check_and_reserve("abc", now, now + 9999)
    ns2 = NonceStore(p)
    assert ns2.is_seen("abc") is True
    assert ns2.check_and_reserve("abc", now, now + 9999) is False


def test_nonce_legacy_object_file_migrates(tmp_path):
    p = str(tmp_path / "n.json")
    with open(p, "w") as f:
        json.dump({"old-nonce": int(time.time())}, f)
    ns = NonceStore(p)
    assert ns.is_seen("old-nonce") is True  # grace period, still blocks replay
    assert ns.prune(int(time.time()) + 7200) == 1


# ---- ledger JSONL + incremental verify ----
def test_ledger_jsonl_append_and_reload(tmp_path):
    p = str(tmp_path / "l.jsonl")
    led = Ledger(p)
    led.append("approve", "n1", "a", "r", "s", "ag")
    led.append("allow", "n1", "a", "r", "s", "ag")
    with open(p) as f:
        lines = [x for x in f if x.strip()]
    assert len(lines) == 2 and all(x.startswith("{") for x in lines)
    led2 = Ledger(p)
    assert len(led2.entries) == 2
    ok, _ = led2.verify_chain()
    assert ok


def test_ledger_legacy_array_loads(tmp_path):
    p = str(tmp_path / "l.json")
    led = Ledger()
    led.append("approve", "n1", "a", "r", "s", "ag")
    from dataclasses import asdict
    with open(p, "w") as f:
        json.dump([asdict(e) for e in led.entries], f)
    led2 = Ledger(p)
    ok, _ = led2.verify_chain()
    assert ok and len(led2.entries) == 1


def test_verify_catches_tamper_old_and_new():
    led = Ledger()
    for i in range(5):
        led.append("allow", f"n{i}", "a", "r", "s", "ag")
    ok, _ = led.verify_chain()
    assert ok
    led.append("allow", "n5", "a", "r", "s", "ag")
    ok, _ = led.verify_chain()
    assert ok
    # tamper the newest entry
    led.entries[-1].detail = "forged"
    ok, _ = led.verify_chain()
    assert not ok
    led.entries[-1].detail = ""
    # tamper deep in the prefix
    led.entries[1].detail = "forged-old"
    ok, msg = led.verify_chain()
    assert not ok and "seq 1" in msg
