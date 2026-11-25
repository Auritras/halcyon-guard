"""Fake bank. It executes a payment only with a gateway-signed decision token (HMAC-SHA256)."""
import hashlib
import hmac
import json
import time

from . import audit, grants
from .store import CUSTOMER_ID, balance, get_payee, norm_name, transaction


def sign_decision(secret: str, request_id: int, amount, payee: str) -> str:
    msg = f"{int(request_id)}|{float(amount):.2f}|{norm_name(payee)}"
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()


def _refuse(conn, request_id, reason):
    audit.append(conn, "bank_refused", {"request_id": request_id, "reason": reason})
    return {"ok": False, "reason": reason}


def execute(conn, request_id, token: str, secret: str) -> dict:
    with transaction(conn):
        r = conn.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        if r is None:
            return _refuse(conn, request_id, "Unknown request.")
        if r["status"] == "executed":
            return _refuse(conn, request_id, "Payment already executed.")
        if r["amount"] is None:
            return _refuse(conn, request_id, "Request has no valid amount.")
        expected = sign_decision(secret, r["id"], r["amount"], r["payee"])
        if not hmac.compare_digest(expected, str(token or "")):
            return _refuse(conn, request_id, "Invalid decision signature: this payment wasn't authorised by the gateway.")
        if not ((r["decision"] == "ALLOW" and r["status"] == "allowed") or r["status"] == "approved"):
            return _refuse(conn, request_id, f"Not authorised: the gateway decision was {r['decision']}.")
        amount = r["amount"]
        if balance(conn) < amount:
            return _refuse(conn, request_id, "Insufficient balance.")

        now = time.time()
        conn.execute("UPDATE customer SET balance = balance - ? WHERE id=?", (amount, CUSTOMER_ID))
        cur = conn.execute(
            "INSERT INTO transactions (ts, request_id, grant_id, payee, account, amount) VALUES (?,?,?,?,?,?)",
            (now, r["id"], r["grant_id"], r["payee"], r["account"], amount),
        )
        payee = get_payee(conn, r["payee"])
        if payee:
            conn.execute("UPDATE payees SET history_json=? WHERE name=?",
                         (json.dumps(payee["history"] + [amount]), payee["name"]))
        else:
            g = grants.get_grant(conn, r["grant_id"]) if r["grant_id"] else None
            conn.execute("INSERT INTO payees VALUES (?,?,?,?)",
                         (r["payee"], r["account"], g["category"] if g else "other", json.dumps([amount])))
        for b in conn.execute("SELECT id, payee FROM bills WHERE status='pending' AND amount=?", (amount,)).fetchall():
            if norm_name(b["payee"]) == r["payee_norm"]:
                conn.execute("UPDATE bills SET status='paid' WHERE id=?", (b["id"],))
        conn.execute("UPDATE requests SET status='executed' WHERE id=?", (r["id"],))
        new_balance = balance(conn)
        audit.append(conn, "bank_executed", {"request_id": r["id"], "transaction_id": cur.lastrowid,
                                             "payee": r["payee"], "amount": amount, "balance": new_balance})
    return {"ok": True, "transaction_id": cur.lastrowid, "balance": new_balance}
