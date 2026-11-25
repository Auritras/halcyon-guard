"""Fake bank. It executes a payment only with a gateway-signed decision token (HMAC-SHA256).

As defence in depth it re-checks, inside the same transaction as the debit, that the
permission is still active and that the payment stays within its limit.
"""
import hashlib
import hmac
import json
import time

from . import audit, grants
from .store import CUSTOMER_ID, balance, get_payee, norm_account, norm_name, transaction


def sign_decision(secret: str, request_id: int, amount, payee: str, account: str) -> str:
    msg = f"{int(request_id)}|{float(amount):.2f}|{norm_name(payee)}|{norm_account(account)}"
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
        expected = sign_decision(secret, r["id"], r["amount"], r["payee"], r["account"])
        if not hmac.compare_digest(expected, str(token or "")):
            return _refuse(conn, request_id, "Invalid decision signature: this payment wasn't authorised by the gateway.")
        if not ((r["decision"] == "ALLOW" and r["status"] == "allowed") or r["status"] == "approved"):
            return _refuse(conn, request_id, f"Not authorised: the gateway decision was {r['decision']}.")
        amount = r["amount"]
        g = grants.get_grant(conn, r["grant_id"]) if r["grant_id"] else None
        if not grants.is_active(g):
            return _refuse(conn, request_id, "The permission was revoked or has expired.")
        if grants.spent(conn, g["id"]) + amount > g["max_amount"]:
            return _refuse(conn, request_id, "This payment would exceed the permission's limit.")
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
            conn.execute("INSERT INTO payees VALUES (?,?,?,?)",
                         (r["payee"], r["account"], g["category"], json.dumps([amount])))
        # bills 1 and 2 are the clean and attacker-edited copies of the same bill
        for b in conn.execute("SELECT id, payee FROM bills WHERE status='pending' AND amount=?", (amount,)).fetchall():
            if norm_name(b["payee"]) == r["payee_norm"]:
                conn.execute("UPDATE bills SET status='paid' WHERE id=?", (b["id"],))
        conn.execute("UPDATE requests SET status='executed' WHERE id=?", (r["id"],))
        new_balance = balance(conn)
        audit.append(conn, "bank_executed", {"request_id": r["id"], "transaction_id": cur.lastrowid,
                                             "payee": r["payee"], "account": r["account"], "amount": amount,
                                             "balance": new_balance})
    return {"ok": True, "transaction_id": cur.lastrowid, "balance": new_balance}
