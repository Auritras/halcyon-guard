"""Regression tests for the issues found in the final code review."""
import threading

import pytest
from fastapi.testclient import TestClient

from halcyon import agent, auth, bank, gateway, grants, payments, store
from halcyon.app import create_app
from halcyon.config import Settings

SECRET = "fix-secret"


def _grant(conn, text="Pay my electricity bill up to ₹5,000 this week"):
    gid = grants.draft_grant(conn, text)["grant"]["id"]
    grants.confirm_grant(conn, gid)
    return gid


def _token(conn):
    return gateway.login(conn, "agent-01", "demo-secret")


def _decisions(events):
    return [e for e in events if e["kind"] == "decision"]


# C1: the destination account must match the registered payee
def test_wrong_account_for_known_payee_is_blocked(conn):
    _grant(conn)
    d = gateway.evaluate(conn, _token(conn), {"action": "pay_bill", "payee": "Sunrise Power",
                                              "account": "50100234567", "amount": 4200, "purpose": "Electricity bill"})
    assert d["decision"] == "BLOCK"
    assert d["checks"][1]["result"] == "fail" and "account" in d["checks"][1]["detail"]


def test_missing_account_uses_registered_one(conn):
    _grant(conn)
    d = payments.process_payment(conn, _token(conn), {"action": "pay_bill", "payee": "Sunrise Power",
                                                      "amount": 4200, "purpose": "Electricity bill"}, SECRET)
    assert d["decision"] == "ALLOW" and d["bank"]["ok"]
    assert conn.execute("SELECT account FROM transactions").fetchone()[0] == "SUNP-0042-7781"


def test_signature_covers_account(conn):
    _grant(conn)
    d = gateway.evaluate(conn, _token(conn), {"action": "pay_bill", "payee": "Sunrise Power", "amount": 4200,
                                              "purpose": "Electricity bill"})
    conn.execute("UPDATE requests SET account='50100234567' WHERE id=?", (d["request_id"],))
    old_sig = bank.sign_decision(SECRET, d["request_id"], 4200, "Sunrise Power", "SUNP-0042-7781")
    assert bank.execute(conn, d["request_id"], old_sig, SECRET)["ok"] is False


# C2: reset must not log the dashboard out
def test_customer_session_survives_reset(conn):
    tok = auth.customer_login(conn, "1234")
    store.reset(conn)
    assert auth.customer_for_token(conn, tok) == "asha"


# C3 + I3: scenarios run back to back still tell the right story
def test_A_then_D_still_allows_the_real_bill(conn):
    agent.run_scenario(conn, "A", SECRET)
    ds = _decisions(agent.run_scenario(conn, "D", SECRET))
    assert [d["decision"] for d in ds] == ["ALLOW", "BLOCK"]


def test_full_sequence_A_to_F(conn):
    expected = {"A": ["ALLOW"], "B": ["PAUSE"], "C": ["BLOCK"], "D": ["ALLOW", "BLOCK"],
                "E": ["BLOCK", "BLOCK", "BLOCK"], "F": ["BLOCK"]}
    for letter, want in expected.items():
        got = [d["decision"] for d in _decisions(agent.run_scenario(conn, letter, SECRET))]
        assert got == want, (letter, got)


def test_block_reason_cites_the_relevant_permission(conn):
    agent.run_scenario(conn, "B", SECRET)  # leaves an electricity and a water grant active
    d = _decisions(agent.run_scenario(conn, "C", SECRET))[0]
    assert "electricity" in d["reason"]


def test_scenarios_reset_bills_to_pending(conn):
    agent.run_scenario(conn, "A", SECRET)
    agent.run_scenario(conn, "C", SECRET)
    assert conn.execute("SELECT status FROM bills WHERE id=1").fetchone()[0] == "pending"


# I1: cumulative cap holds for concurrent requests and approvals
def test_concurrent_payments_respect_cap(db_path):
    c = store.connect(db_path)
    _grant(c)
    tok = _token(c)
    c.close()
    barrier = threading.Barrier(4)

    def worker():
        conn = store.connect(db_path)
        barrier.wait()
        payments.process_payment(conn, tok, {"action": "pay_bill", "payee": "Sunrise Power", "amount": 3000,
                                             "purpose": "Electricity bill"}, SECRET)
        conn.close()

    ts = [threading.Thread(target=worker) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    c = store.connect(db_path)
    spent = c.execute("SELECT COALESCE(SUM(amount),0) FROM transactions").fetchone()[0]
    c.close()
    assert spent <= 5000


def test_approvals_respect_cap(conn):
    _grant(conn, "Pay my water bill up to ₹2,000")
    tok = _token(conn)
    req = {"action": "pay_bill", "payee": "CityWater Board", "amount": 1500, "purpose": "Water bill"}
    d1 = gateway.evaluate(conn, tok, req)
    d2 = gateway.evaluate(conn, tok, req)
    assert d1["decision"] == d2["decision"] == "PAUSE"
    assert payments.approve(conn, d1["request_id"], SECRET)["bank"]["ok"] is True
    assert payments.approve(conn, d2["request_id"], SECRET)["bank"]["ok"] is False
    assert store.balance(conn) == 120000 - 1500


# I2: the bank refuses if the permission was revoked, even for an approved request
def test_bank_refuses_after_revoke(conn):
    gid = _grant(conn, "Pay my water bill up to ₹2,000")
    d = gateway.evaluate(conn, _token(conn), {"action": "pay_bill", "payee": "CityWater Board", "amount": 1800,
                                              "purpose": "Water bill"})
    conn.execute("UPDATE requests SET status='approved' WHERE id=?", (d["request_id"],))
    grants.revoke_grant(conn, gid)
    sig = bank.sign_decision(SECRET, d["request_id"], 1800, "CityWater Board", "CWB-1180-2290")
    r = bank.execute(conn, d["request_id"], sig, SECRET)
    assert r["ok"] is False and "revoked" in r["reason"]


# I4: scenario E's final reason names the retry burst
def test_retry_burst_named_in_reason(conn):
    last = _decisions(agent.run_scenario(conn, "E", SECRET))[-1]
    assert last["reason"].startswith("Blocked: Rapid retries")


# I5: scenario and demo controls need the customer's session
@pytest.fixture
def client(db_path):
    with TestClient(create_app(Settings(db_path=db_path, llm_provider="none", hmac_secret=SECRET))) as c:
        yield c


@pytest.mark.parametrize("path,body", [("/api/agent/scenario/A", None), ("/api/provider", {"provider": "none"}),
                                       ("/api/bills/poison", {"on": True})])
def test_demo_controls_need_customer(client, path, body):
    assert client.post(path, json=body).status_code == 401


# re-graded minors that could crash on camera
def test_huge_integer_amount_is_invalid_not_500(conn):
    _grant(conn)
    d = gateway.evaluate(conn, _token(conn), {"action": "pay_bill", "payee": "Sunrise Power", "amount": 10 ** 400})
    assert d["decision"] == "BLOCK" and "Invalid amount" in d["reason"]


def test_tool_arguments_as_dict_are_accepted(conn):
    _grant(conn)
    steps = iter([
        {"content": None, "tool_calls": [{"id": "1", "type": "function",
                                          "function": {"name": "pay", "arguments": {"payee": "Sunrise Power",
                                                                                     "amount": 4200,
                                                                                     "purpose": "Electricity bill"}}}]},
        {"content": "done", "tool_calls": None},
    ])
    events = agent.run_task(conn, "pay", lambda m, t=None: next(steps), SECRET)
    assert [d["decision"] for d in _decisions(events)] == ["ALLOW"]
