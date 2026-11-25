"""Scenarios G-L: more ways an agent payment goes wrong."""
import pytest

from halcyon import agent, store

SECRET = "more-secret"


def decisions(events):
    return [e for e in events if e["kind"] == "decision"]


@pytest.mark.parametrize("letter,expected", [
    ("G", ["BLOCK"]),
    ("H", ["ALLOW", "BLOCK"]),
    ("I", ["BLOCK"]),
    ("J", ["BLOCK"]),
    ("K", ["PAUSE"]),
    ("L", ["BLOCK"]),
])
def test_new_scenarios(conn, letter, expected):
    assert [d["decision"] for d in decisions(agent.run_scenario(conn, letter, SECRET))] == expected


def test_G_changed_bank_details_blocked_on_account(conn):
    d = decisions(agent.run_scenario(conn, "G", SECRET))[0]
    assert d["checks"][1]["result"] == "fail" and "account" in d["checks"][1]["detail"]


def test_H_split_payment_blocked_on_total(conn):
    second = decisions(agent.run_scenario(conn, "H", SECRET))[1]
    assert "would bring spending" in second["checks"][1]["detail"]
    assert store.balance(conn) == 120000 - 3000


def test_I_other_category_blocked(conn):
    d = decisions(agent.run_scenario(conn, "I", SECRET))[0]
    assert "mobile" in d["reason"] and "electricity" in d["reason"]


def test_J_forged_token_fails_check_1(conn):
    d = decisions(agent.run_scenario(conn, "J", SECRET))[0]
    assert d["checks"][0]["result"] == "fail"


def test_K_agent_cannot_approve_its_own_pause(conn):
    events = agent.run_scenario(conn, "K", SECRET)
    refused = [e for e in events if e["kind"] == "refused"]
    assert refused and "Asha" in refused[0]["text"]
    rid = decisions(events)[0]["request_id"]
    assert conn.execute("SELECT status FROM requests WHERE id=?", (rid,)).fetchone()[0] == "pending"
    assert store.balance(conn) == 120000
    kinds = [r[0] for r in conn.execute("SELECT kind FROM audit")]
    assert "agent_rejected" in kinds


def test_L_garbled_amount(conn):
    d = decisions(agent.run_scenario(conn, "L", SECRET))[0]
    assert "Invalid amount" in d["reason"]


def test_all_scenarios_back_to_back(conn):
    for letter in agent.SCENARIOS:
        assert decisions(agent.run_scenario(conn, letter, SECRET)) or letter == "K"


def test_full_tour_in_group_order(conn):
    """'Run all scenarios' plays the groups in order, back to back. Each must still tell its own story."""
    expected = {"A": ["ALLOW"], "B": ["PAUSE"], "C": ["BLOCK"], "D": ["ALLOW", "BLOCK"],
                "E": ["BLOCK", "BLOCK", "BLOCK"], "F": ["BLOCK"], "G": ["BLOCK"], "H": ["ALLOW", "BLOCK"],
                "I": ["BLOCK"], "J": ["BLOCK"], "K": ["PAUSE"], "L": ["BLOCK"]}
    for letter in [k for ks in agent.SCENARIO_GROUPS.values() for k in ks]:
        got = [d["decision"] for d in decisions(agent.run_scenario(conn, letter, SECRET))]
        assert got == expected[letter], (letter, got)


def test_retry_burst_is_about_the_same_payment(conn):
    """Different blocked payments to one payee are not 'retries' of each other."""
    from halcyon import gateway, grants
    gid = grants.draft_grant(conn, "Pay my electricity bill up to ₹5,000")["grant"]["id"]
    grants.confirm_grant(conn, gid)
    tok = gateway.login(conn, "agent-01", "demo-secret")
    base = {"action": "pay_bill", "payee": "Sunrise Power", "purpose": "Electricity bill"}
    gateway.evaluate(conn, tok, {**base, "amount": 9000}, now=1000)   # over limit
    gateway.evaluate(conn, tok, {**base, "amount": 8000}, now=1001)   # over limit
    d = gateway.evaluate(conn, tok, {**base, "amount": 3000}, now=1002)
    assert d["decision"] == "ALLOW", d["reason"]


def test_scenarios_have_groups():
    assert set(agent.SCENARIO_GROUPS) >= {"Everyday", "Attacks", "Agent mistakes"}
    grouped = [k for ks in agent.SCENARIO_GROUPS.values() for k in ks]
    assert sorted(grouped) == sorted(agent.SCENARIOS)
