import time

import pytest

from halcyon import grants


def test_parse_electricity_intent():
    r = grants.parse_intent_keywords("Pay my electricity bill up to ₹5,000 this week")
    assert r["status"] == "ok"
    g = r["grant"]
    assert g["action"] == "pay_bill"
    assert g["category"] == "electricity"
    assert g["max_amount"] == 5000
    assert abs(g["valid_until"] - (time.time() + 7 * 86400)) < 60


@pytest.mark.parametrize("text,amount", [
    ("pay power bill, max Rs 5000", 5000),
    ("pay the light bill up to 5k", 5000),
    ("pay water bill limit INR 2,000", 2000),
])
def test_amount_formats(text, amount):
    r = grants.parse_intent_keywords(text)
    assert r["status"] == "ok"
    assert r["grant"]["max_amount"] == amount


def test_unclear_asks_for_amount():
    r = grants.parse_intent_keywords("pay my bills")
    assert r["status"] == "unclear"
    assert "amount" in r["question"].lower()


def test_unclear_without_category():
    r = grants.parse_intent_keywords("pay up to ₹5,000")
    assert r["status"] == "unclear"
    assert "electricity" in r["question"].lower()


def test_draft_fills_known_payees_and_is_not_active(conn):
    r = grants.draft_grant(conn, "Pay my electricity bill up to ₹5,000 this week")
    assert r["status"] == "ok"
    g = r["grant"]
    assert g["payees"] == ["Sunrise Power"]
    assert g["status"] == "draft"
    assert grants.active_grant(conn, "pay_bill") is None


def test_confirm_then_revoke(conn):
    gid = grants.draft_grant(conn, "Pay my electricity bill up to ₹5,000")["grant"]["id"]
    grants.confirm_grant(conn, gid)
    assert grants.active_grant(conn, "pay_bill")["id"] == gid
    grants.revoke_grant(conn, gid)
    assert grants.active_grant(conn, "pay_bill") is None


def test_expired_grant_not_active(conn):
    gid = grants.draft_grant(conn, "Pay my electricity bill up to ₹5,000 today")["grant"]["id"]
    grants.confirm_grant(conn, gid)
    assert grants.active_grant(conn, "pay_bill", now=time.time() + 2 * 86400) is None


def test_llm_draft_used_only_when_keywords_unclear(conn):
    calls = []

    def fake_llm(text):
        calls.append(text)
        return {"category": "electricity", "max_amount": 5000, "days": 7}

    r = grants.draft_grant(conn, "Pay my electricity bill up to ₹5,000", llm=fake_llm)
    assert r["status"] == "ok" and calls == []
    r = grants.draft_grant(conn, "settle the lights invoice, keep it under five thousand rupees", llm=fake_llm)
    assert r["status"] == "ok" and r["grant"]["max_amount"] == 5000 and len(calls) == 1
    assert r["grant"]["status"] == "draft"


def test_llm_draft_invalid_output_falls_back_to_question(conn):
    r = grants.draft_grant(conn, "sort my bills out", llm=lambda t: {"category": "casino", "max_amount": -1})
    assert r["status"] == "unclear"
