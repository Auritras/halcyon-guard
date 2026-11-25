"""Session tokens for the agent and the customer. They are separate kinds and never interchangeable."""
import hmac
import secrets
import time

from . import audit
from .store import CUSTOMER_ID, row


def _issue(conn, kind: str, subject: str) -> str:
    token = secrets.token_urlsafe(24)
    conn.execute("INSERT INTO sessions VALUES (?,?,?,?)", (token, kind, subject, time.time()))
    return token


def _lookup(conn, token, kind):
    if not token or not isinstance(token, str):
        return None
    s = conn.execute("SELECT * FROM sessions WHERE token=? AND kind=?", (token, kind)).fetchone()
    return s["subject"] if s else None


def agent_login(conn, agent_id: str, secret: str) -> str | None:
    a = conn.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
    if a is None or not hmac.compare_digest(str(a["secret"]), str(secret)):
        audit.append(conn, "agent_login_failed", {"agent_id": agent_id})
        return None
    token = _issue(conn, "agent", agent_id)
    audit.append(conn, "agent_login", {"agent_id": agent_id, "owner": a["owner"]})
    return token


def agent_for_token(conn, token):
    agent_id = _lookup(conn, token, "agent")
    if agent_id is None:
        return None
    return row(conn.execute("SELECT id, owner FROM agents WHERE id=?", (agent_id,)).fetchone())


def customer_login(conn, pin: str) -> str | None:
    c = conn.execute("SELECT pin FROM customer WHERE id=?", (CUSTOMER_ID,)).fetchone()
    if c is None or not hmac.compare_digest(str(c["pin"]), str(pin)):
        return None
    return _issue(conn, "customer", CUSTOMER_ID)


def customer_for_token(conn, token):
    return _lookup(conn, token, "customer")
