"""Tamper-evident audit log: each entry's hash covers the previous entry's hash."""
import hashlib
import json
from datetime import datetime, timezone

from .store import transaction

GENESIS = "0" * 64


def canonical(data: dict) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def compute_hash(prev_hash: str, kind: str, data_json: str, ts: str) -> str:
    return hashlib.sha256((prev_hash + kind + data_json + ts).encode("utf-8")).hexdigest()


def append(conn, kind: str, data: dict) -> dict:
    with transaction(conn):
        last = conn.execute("SELECT hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        prev = last["hash"] if last else GENESIS
        ts = datetime.now(timezone.utc).isoformat()
        data_json = canonical(data)
        h = compute_hash(prev, kind, data_json, ts)
        cur = conn.execute(
            "INSERT INTO audit (ts, kind, data_json, prev_hash, hash) VALUES (?,?,?,?,?)",
            (ts, kind, data_json, prev, h),
        )
    return {"seq": cur.lastrowid, "ts": ts, "kind": kind, "data": data, "prev_hash": prev, "hash": h}


def verify(conn) -> dict:
    prev = GENESIS
    count = 0
    for r in conn.execute("SELECT * FROM audit ORDER BY seq"):
        count += 1
        expected = compute_hash(prev, r["kind"], r["data_json"], r["ts"])
        if r["prev_hash"] != prev or r["hash"] != expected:
            return {"ok": False, "broken_at": r["seq"], "count": count}
        prev = r["hash"]
    return {"ok": True, "broken_at": None, "count": count}


def tamper(conn, seq: int) -> bool:
    """Demo only: rewrite one entry's data WITHOUT recomputing its hash, as an insider might."""
    r = conn.execute("SELECT data_json FROM audit WHERE seq=?", (seq,)).fetchone()
    if r is None:
        return False
    data = json.loads(r["data_json"])
    if "decision" in data:
        data["decision"] = "ALLOW"
        data["reason"] = "Edited after the fact to look approved."
    else:
        data["note"] = "Edited after the fact."
    conn.execute("UPDATE audit SET data_json=? WHERE seq=?", (canonical(data), seq))
    return True


def _entry(r) -> dict:
    return {"seq": r["seq"], "ts": r["ts"], "kind": r["kind"], "data": json.loads(r["data_json"]),
            "prev_hash": r["prev_hash"], "hash": r["hash"]}


def tail(conn, n: int = 50) -> list:
    """Newest entries first."""
    return [_entry(r) for r in conn.execute("SELECT * FROM audit ORDER BY seq DESC LIMIT ?", (n,))]
