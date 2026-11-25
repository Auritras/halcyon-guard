"""Halcyon Guard policy gateway.

Every agent payment request passes three deterministic checks. No LLM is involved
in any decision here:

  1. Verify agent + grant   — valid session, agent acts for this customer, active permission.
  2. Check transaction      — amount, payee, account and purpose against the permission (incl. cumulative spend).
  3. Check behaviour        — new payees, unusual amounts, rapid retries of blocked payments.

Any fail -> BLOCK. Otherwise any warn -> PAUSE (customer decides). Otherwise ALLOW.
The gateway only decides and records; the bank executes.
"""
import json
import time

from . import audit, auth, grants
from .money import inr, parse_amount
from .store import CUSTOMER_ID, get_payee, norm_account, norm_name, transaction

login = auth.agent_login
agent_for_token = auth.agent_for_token

RETRY_WINDOW = 60  # seconds
RETRY_LIMIT = 2    # this many blocked attempts in the window -> the next one fails check 3
ANOMALY_FACTOR = 1.5
BURST_PREFIX = "Rapid retries"

CHECK_NAMES = {1: "Verify agent + grant", 2: "Check transaction", 3: "Check behaviour"}


def _check(n, result, detail):
    return {"n": n, "name": CHECK_NAMES[n], "result": result, "detail": detail}


def _describe(g) -> str:
    return f"{g['category']} bills up to {inr(g['max_amount'])}"


def _describe_all(active) -> str:
    return "; ".join(_describe(g) for g in active)


def _pick_grant(active, payee_norm, payee, purpose_cat):
    """The permission this request is judged against: named payee, then payee category, then purpose."""
    for g in active:
        if payee_norm in {norm_name(p) for p in g["payees"]}:
            return g
    for cat in (payee["category"] if payee else None, purpose_cat):
        for g in active:
            if cat and g["category"] == cat:
                return g
    return active[0]


def _check_transaction(conn, req, g, active, amount, payee_name, payee, purpose_cat):
    if amount is None:
        return _check(2, "fail", f"Invalid amount: {req.get('amount')!r} is not a positive rupee amount.")
    if req.get("action", "pay_bill") != g["action"]:
        return _check(2, "fail", f"Your permission covers bill payments, not '{req.get('action')}'.")
    account = req.get("account")
    if payee and account and norm_account(account) != norm_account(payee["account"]):
        return _check(2, "fail", f"{inr(amount)} would go to account {account}, but {payee['name']}'s registered "
                                 f"account is {payee['account']}.")
    warns = []
    granted = {norm_name(p) for p in g["payees"]}
    if norm_name(payee_name) not in granted:
        if payee and payee["category"] == g["category"]:
            warns.append(f"{payee['name']} is a registered {g['category']} biller but isn't named in your permission.")
        elif payee is None:
            return _check(2, "fail", f"{inr(amount)} to a new payee ({payee_name}) doesn't match your "
                                     f"permission ({_describe_all(active)}).")
        else:
            return _check(2, "fail", f"{payee['name']} is a {payee['category']} payee, but your permission "
                                     f"covers {_describe_all(active)}.")
    if amount > g["max_amount"]:
        return _check(2, "fail", f"{inr(amount)} is above your limit of {inr(g['max_amount'])}.")
    spent = grants.spent(conn, g["id"])
    if spent + amount > g["max_amount"]:
        return _check(2, "fail", f"This would bring spending under this permission to {inr(spent + amount)}, "
                                 f"above the {inr(g['max_amount'])} limit ({inr(spent)} already paid).")
    if purpose_cat and purpose_cat != g["category"]:
        warns.append(f"The stated purpose mentions {purpose_cat}, but your permission covers {g['category']}.")
    if warns:
        return _check(2, "warn", " ".join(warns))
    left = g["max_amount"] - spent - amount
    return _check(2, "pass", f"{inr(amount)} to {payee_name} fits your permission ({_describe(g)}); "
                             f"{inr(left)} left.")


def _check_behaviour(conn, agent_id, amount, payee_name, payee_norm, payee, now):
    blocked = conn.execute(
        "SELECT COUNT(*) AS n FROM requests WHERE agent_id=? AND payee_norm=? AND decision='BLOCK' "
        "AND ts >= ? AND ts <= ?", (agent_id, payee_norm, now - RETRY_WINDOW, now),
    ).fetchone()["n"]
    if blocked >= RETRY_LIMIT:
        return _check(3, "fail", f"{BURST_PREFIX}: {blocked} blocked attempts to pay {payee_name} "
                                 f"in the last minute.")
    history = payee["history"] if payee else []
    if not history:
        return _check(3, "warn", f"First payment to {payee_name}: you haven't paid them before.")
    if amount is not None and amount > ANOMALY_FACTOR * max(history):
        return _check(3, "warn", f"{inr(amount)} is well above what you usually pay {payee['name']} "
                                 f"(up to {inr(max(history))}).")
    return _check(3, "pass", f"Familiar payee; amount in line with your history "
                             f"({inr(min(history))}–{inr(max(history))}).")


def _reason(decision, checks, amount, payee_name, g):
    if decision == "BLOCK":
        fails = [c for c in checks if c["result"] == "fail"]
        burst = [c for c in fails if c["detail"].startswith(BURST_PREFIX)]
        return "Blocked: " + (burst or fails)[0]["detail"]
    if decision == "PAUSE":
        return "Paused for your approval: " + " ".join(c["detail"] for c in checks if c["result"] == "warn")
    return f"Allowed: {inr(amount)} to {payee_name} fits your permission ({_describe(g)})."


def evaluate(conn, token, req: dict, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    req = dict(req or {})
    with transaction(conn):
        return _evaluate(conn, token, req, now)


def _evaluate(conn, token, req, now):
    payee_name = str(req.get("payee") or "").strip() or "(no payee)"
    payee_norm = norm_name(payee_name)
    payee = get_payee(conn, payee_name)
    if payee:
        payee_name = payee["name"]
    amount = parse_amount(req.get("amount"))
    purpose_cat = grants.parse_category(str(req.get("purpose") or ""))
    # the bank pays the registered account for a known payee; a mismatch is caught by check 2
    account = str(req.get("account") or (payee["account"] if payee else ""))

    agent = agent_for_token(conn, token)
    g = None
    if agent is None:
        c1 = _check(1, "fail", "The agent's session token is not valid, so its identity can't be confirmed.")
    elif agent["owner"] != CUSTOMER_ID:
        c1 = _check(1, "fail", f"{agent['id']} does not act for this customer.")
    else:
        active = grants.active_grants(conn, req.get("action", "pay_bill"), now)
        if not active:
            c1 = _check(1, "fail", "No active permission: it was revoked, has expired, or was never confirmed.")
        else:
            g = _pick_grant(active, payee_norm, payee, purpose_cat)
            c1 = _check(1, "pass", f"{agent['id']} is signed in for Asha Rao and holds active permission #{g['id']}.")

    if c1["result"] == "fail":
        checks = [c1, _check(2, "skip", "Not checked: the agent wasn't verified."),
                  _check(3, "skip", "Not checked: the agent wasn't verified.")]
    else:
        checks = [c1,
                  _check_transaction(conn, req, g, active, amount, payee_name, payee, purpose_cat),
                  _check_behaviour(conn, agent["id"], amount, payee_name, payee_norm, payee, now)]

    results = [c["result"] for c in checks]
    decision = "BLOCK" if "fail" in results else "PAUSE" if "warn" in results else "ALLOW"
    reason = _reason(decision, checks, amount, payee_name, g)
    status = {"ALLOW": "allowed", "PAUSE": "pending", "BLOCK": "blocked"}[decision]

    cur = conn.execute(
        "INSERT INTO requests (ts, agent_id, payload_json, payee, payee_norm, account, amount, grant_id, checks_json,"
        " decision, reason, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (now, agent["id"] if agent else None, json.dumps(req, default=str, ensure_ascii=False), payee_name,
         payee_norm, account, amount, g["id"] if g else None, json.dumps(checks), decision, reason, status),
    )
    rid = cur.lastrowid
    audit.append(conn, "gateway_decision", {
        "request_id": rid, "agent_id": agent["id"] if agent else None, "payee": payee_name, "account": account,
        "amount": amount, "grant_id": g["id"] if g else None, "decision": decision, "reason": reason,
        "checks": checks,
    })
    return {"request_id": rid, "decision": decision, "reason": reason, "checks": checks,
            "payee": payee_name, "account": account, "amount": amount, "grant_id": g["id"] if g else None}
