"""The payment path shared by the HTTP API, the live agent and the scripted scenarios."""
from . import audit, bank, gateway, grants
from .store import transaction


class Conflict(Exception):
    """The request can't move to the asked state (already decided, or its permission is gone)."""


def _execute(conn, request_id, amount, payee, secret):
    return bank.execute(conn, request_id, bank.sign_decision(secret, request_id, amount, payee), secret)


def process_payment(conn, token, req: dict, secret: str) -> dict:
    """Gateway decides; only an ALLOW goes on to the bank, carrying a signed decision token."""
    d = gateway.evaluate(conn, token, req)
    if d["decision"] == "ALLOW":
        d["bank"] = _execute(conn, d["request_id"], d["amount"], d["payee"], secret)
    return d


def approve(conn, request_id: int, secret: str) -> dict:
    """Customer approves one paused request. Executes at most once, and never after a revoke."""
    refused = None
    with transaction(conn):
        r = conn.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        if r is None:
            raise LookupError(request_id)
        if r["status"] != "pending":
            refused = f"This request is already {r['status']}, so it can't be approved."
        elif not grants.is_active(grants.get_grant(conn, r["grant_id"])):
            conn.execute("UPDATE requests SET status='cancelled' WHERE id=?", (request_id,))
            refused = "The permission behind this request was revoked or has expired, so it can't be approved."
            audit.append(conn, "approval_refused", {"request_id": request_id, "reason": refused})
        else:
            conn.execute("UPDATE requests SET status='approved' WHERE id=?", (request_id,))
            audit.append(conn, "customer_approved", {"request_id": request_id, "payee": r["payee"],
                                                     "amount": r["amount"]})
    if refused:
        raise Conflict(refused)
    result = _execute(conn, request_id, r["amount"], r["payee"], secret)
    return {"request_id": request_id, "status": "executed" if result["ok"] else "approved", "bank": result}


def deny(conn, request_id: int) -> dict:
    with transaction(conn):
        r = conn.execute("SELECT status FROM requests WHERE id=?", (request_id,)).fetchone()
        if r is None:
            raise LookupError(request_id)
        if r["status"] != "pending":
            raise Conflict(f"This request is already {r['status']}, so it can't be denied.")
        conn.execute("UPDATE requests SET status='denied' WHERE id=?", (request_id,))
        audit.append(conn, "customer_denied", {"request_id": request_id})
    return {"request_id": request_id, "status": "denied"}
