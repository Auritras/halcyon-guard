"""Intent & permission service: turns what the customer says into a scoped, revocable grant.

A drafted grant is never active until the customer confirms it, so permissions
cannot widen without the customer seeing them.
"""
import json
import re
import time
from datetime import datetime

from . import audit
from .store import row, rows

CATEGORIES = {
    "electricity": ["electricity", "electric", "power", "light", "lights"],
    "water": ["water"],
    "gas": ["gas", "lpg"],
    "mobile": ["mobile", "phone", "recharge"],
    "internet": ["internet", "broadband", "wifi", "wi-fi"],
}
MAX_GRANT = 200000  # a single permission can never exceed ₹2,00,000 in this demo

_NUM = r"(\d[\d,]*(?:\.\d+)?)"
_AMOUNT_PATTERNS = [
    re.compile(r"(?:₹|\brs\.?|\binr)\s*" + _NUM + r"\s*(k\b|lakh\b)?", re.I),
    re.compile(r"\b" + _NUM + r"\s*(k|lakh)\b", re.I),
    re.compile(r"\b(?:up\s*to|upto|max(?:imum)?|limit(?:\s+of)?|under|below|at\s+most|not\s+more\s+than)\s*"
               + _NUM + r"\s*(k\b|lakh\b)?", re.I),
    re.compile(_NUM + r"\s*(?:rupees|rs\b|inr\b)", re.I),
]


def _to_amount(num: str, mult: str | None) -> float | None:
    try:
        v = float(num.replace(",", ""))
    except ValueError:
        return None
    m = (mult or "").lower()
    if m == "k":
        v *= 1000
    elif m == "lakh":
        v *= 100000
    return v


def parse_amount(text: str) -> float | None:
    for pat in _AMOUNT_PATTERNS:
        m = pat.search(text)
        if m:
            groups = m.groups()
            mult = groups[1] if len(groups) > 1 else None
            v = _to_amount(groups[0], mult)
            if v and v > 0:
                return v
    return None


def parse_category(text: str) -> str | None:
    low = text.lower()
    for cat, words in CATEGORIES.items():
        if any(re.search(r"\b" + re.escape(w) + r"\b", low) for w in words):
            return cat
    return None


def _valid_until(text: str, now: float) -> float:
    low = text.lower()
    if "today" in low:
        end = datetime.fromtimestamp(now).replace(hour=23, minute=59, second=59)
        return end.timestamp()
    if "month" in low:
        return now + 30 * 86400
    return now + 7 * 86400


def _question(category, amount) -> str:
    if category is None and amount is None:
        return ("Which bill should the agent pay, and what is the maximum amount? "
                "For example: \"Pay my electricity bill up to ₹5,000\".")
    if amount is None:
        return f"What is the maximum amount the agent may pay for your {category} bill? For example: \"up to ₹5,000\"."
    return "Which bill should the agent pay: electricity, water, gas, mobile or internet?"


def _grant_dict(category, amount, valid_until, text):
    return {
        "action": "pay_bill",
        "category": category,
        "max_amount": amount,
        "valid_until": valid_until,
        "purpose": f"Pay {category} bill",
        "source_text": text,
    }


def parse_intent_keywords(text: str, now: float | None = None) -> dict:
    now = now or time.time()
    category, amount = parse_category(text), parse_amount(text)
    if category is None or amount is None:
        return {"status": "unclear", "question": _question(category, amount)}
    if amount > MAX_GRANT:
        return {"status": "unclear",
                "question": f"That limit is above ₹{MAX_GRANT:,}. Please choose a smaller maximum amount."}
    return {"status": "ok", "grant": _grant_dict(category, amount, _valid_until(text, now), text)}


def _from_llm(text: str, llm, now: float) -> dict | None:
    """Ask the LLM to structure an unclear request. Its answer is validated, never trusted."""
    try:
        out = llm(text)
    except Exception:
        return None
    if not isinstance(out, dict):
        return None
    category = out.get("category")
    try:
        amount = float(out.get("max_amount"))
        days = float(out.get("days", 7))
    except (TypeError, ValueError):
        return None
    if category not in CATEGORIES or not (0 < amount <= MAX_GRANT) or not (0 < days <= 31):
        return None
    return _grant_dict(category, amount, now + days * 86400, text)


def draft_grant(conn, text: str, llm=None, now: float | None = None) -> dict:
    now = now or time.time()
    parsed = parse_intent_keywords(text, now)
    if parsed["status"] != "ok" and llm is not None:
        g = _from_llm(text, llm, now)
        if g:
            parsed = {"status": "ok", "grant": g, "drafted_by": "llm"}
    if parsed["status"] != "ok":
        audit.append(conn, "intent_unclear", {"text": text, "question": parsed["question"]})
        return parsed
    g = parsed["grant"]
    known = [p["name"] for p in conn.execute("SELECT name, category, history_json FROM payees ORDER BY name")
             if p["category"] == g["category"] and json.loads(p["history_json"])]
    cur = conn.execute(
        "INSERT INTO grants (action, category, payees_json, max_amount, valid_until, purpose, source_text, status, created)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (g["action"], g["category"], json.dumps(known), g["max_amount"], g["valid_until"], g["purpose"],
         text, "draft", now),
    )
    grant = get_grant(conn, cur.lastrowid)
    audit.append(conn, "grant_drafted", {"grant_id": grant["id"], "text": text, "category": grant["category"],
                                         "max_amount": grant["max_amount"], "payees": grant["payees"],
                                         "drafted_by": parsed.get("drafted_by", "keywords")})
    return {"status": "ok", "grant": grant, "drafted_by": parsed.get("drafted_by", "keywords")}


def _decode(g):
    if g is None:
        return None
    g = dict(g)
    g["payees"] = json.loads(g.pop("payees_json"))
    return g


def get_grant(conn, grant_id):
    return _decode(row(conn.execute("SELECT * FROM grants WHERE id=?", (grant_id,)).fetchone()))


def list_grants(conn):
    return [_decode(g) for g in rows(conn.execute("SELECT * FROM grants ORDER BY id DESC"))]


def _set_status(conn, grant_id, frm, to, kind) -> bool:
    cur = conn.execute(f"UPDATE grants SET status=? WHERE id=? AND status IN ({','.join('?' * len(frm))})",
                       (to, grant_id, *frm))
    if cur.rowcount:
        audit.append(conn, kind, {"grant_id": grant_id})
        return True
    return False


def confirm_grant(conn, grant_id) -> bool:
    return _set_status(conn, grant_id, ["draft"], "active", "grant_confirmed")


def revoke_grant(conn, grant_id) -> bool:
    return _set_status(conn, grant_id, ["draft", "active"], "revoked", "grant_revoked")


def revoke_all(conn) -> int:
    ids = [r["id"] for r in conn.execute("SELECT id FROM grants WHERE status IN ('draft','active')")]
    for gid in ids:
        revoke_grant(conn, gid)
    return len(ids)


def is_active(g, now=None) -> bool:
    return bool(g) and g["status"] == "active" and g["valid_until"] > (now or time.time())


def active_grants(conn, action: str, now: float | None = None) -> list:
    now = now or time.time()
    return [g for g in list_grants(conn) if g["action"] == action and is_active(g, now)]


def active_grant(conn, action: str, now: float | None = None):
    gs = active_grants(conn, action, now)
    return gs[0] if gs else None
