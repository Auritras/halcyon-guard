import pytest

from halcyon import bank, gateway, grants

SECRET = "test-secret"


def _grant(conn, text="Pay my electricity bill up to ₹5,000 this week"):
    gid = grants.draft_grant(conn, text)["grant"]["id"]
    grants.confirm_grant(conn, gid)
    return gid


@pytest.fixture
def token(conn):
    return gateway.login(conn, "agent-01", "demo-secret")


def pay(payee, amount, account="", purpose="Electricity bill"):
    return {"action": "pay_bill", "payee": payee, "account": account, "amount": amount, "purpose": purpose}


def check(d, n):
    return next(c for c in d["checks"] if c["n"] == n)


def test_login_rejects_wrong_secret(conn):
    assert gateway.login(conn, "agent-01", "nope") is None
    assert gateway.login(conn, "agent-01", "demo-secret")


def test_allow_known_utility(conn, token):
    _grant(conn)
    d = gateway.evaluate(conn, token, pay("Sunrise Power", 4200))
    assert d["decision"] == "ALLOW", d
    assert [c["result"] for c in d["checks"]] == ["pass", "pass", "pass"]
    assert "Sunrise Power" in d["reason"]


def test_block_over_limit_new_payee(conn, token):
    _grant(conn)
    d = gateway.evaluate(conn, token, pay("R. Verma", 25000, "50100234567"))
    assert d["decision"] == "BLOCK"
    assert check(d, 2)["result"] == "fail"
    assert "₹25,000" in d["reason"]


def test_pause_new_payee_in_category(conn, token):
    _grant(conn, "Pay my water bill up to ₹2,000")
    d = gateway.evaluate(conn, token, pay("CityWater Board", 1800, purpose="Water bill"))
    assert d["decision"] == "PAUSE", d
    assert check(d, 3)["result"] == "warn"
    assert all(c["result"] != "fail" for c in d["checks"])


def test_block_bad_token(conn):
    _grant(conn)
    d = gateway.evaluate(conn, "forged-token", pay("Sunrise Power", 4200))
    assert d["decision"] == "BLOCK"
    assert check(d, 1)["result"] == "fail"
    assert check(d, 2)["result"] == "skip"


def test_block_no_active_grant(conn, token):
    gid = _grant(conn)
    grants.revoke_grant(conn, gid)
    d = gateway.evaluate(conn, token, pay("Sunrise Power", 4200))
    assert d["decision"] == "BLOCK"
    assert check(d, 1)["result"] == "fail"


def test_block_retry_burst(conn, token):
    _grant(conn)
    ds = [gateway.evaluate(conn, token, pay("R. Verma", 25000), now=1000 + i) for i in range(3)]
    assert [d["decision"] for d in ds] == ["BLOCK", "BLOCK", "BLOCK"]
    assert check(ds[0], 3)["result"] != "fail"
    assert check(ds[2], 3)["result"] == "fail"
    assert "retr" in check(ds[2], 3)["detail"].lower()


def test_retry_window_expires(conn, token):
    _grant(conn)
    gateway.evaluate(conn, token, pay("R. Verma", 25000), now=1000)
    gateway.evaluate(conn, token, pay("R. Verma", 25000), now=1001)
    d = gateway.evaluate(conn, token, pay("R. Verma", 25000), now=1100)
    assert check(d, 3)["result"] != "fail"


def test_normal_payments_are_not_a_burst(conn, token):
    _grant(conn, "Pay my electricity bill up to ₹50,000")
    ds = [gateway.evaluate(conn, token, pay("Sunrise Power", 100)) for _ in range(3)]
    assert [d["decision"] for d in ds] == ["ALLOW"] * 3


@pytest.mark.parametrize("amount", ["abc", 0, -5, None, True, float("nan"), "", "4,200.555", 10**12])
def test_invalid_amount(conn, token, amount):
    _grant(conn)
    d = gateway.evaluate(conn, token, pay("Sunrise Power", amount))
    assert d["decision"] == "BLOCK"
    assert "Invalid amount" in d["reason"]


@pytest.mark.parametrize("amount", ["4200", "₹4,200", "Rs. 4200", 4200.0, "4200.00"])
def test_amount_formats_accepted(conn, token, amount):
    _grant(conn)
    assert gateway.evaluate(conn, token, pay("Sunrise Power", amount))["decision"] == "ALLOW"


def test_payee_normalised(conn, token):
    _grant(conn)
    assert gateway.evaluate(conn, token, pay(" sunrise POWER ", 4200))["decision"] == "ALLOW"


def test_cumulative_limit(conn, token):
    _grant(conn)
    for expected in ("ALLOW", "BLOCK"):
        d = gateway.evaluate(conn, token, pay("Sunrise Power", 3000))
        assert d["decision"] == expected, d
        if expected == "ALLOW":
            assert bank.execute(conn, d["request_id"], bank.sign_decision(SECRET, d["request_id"], 3000, "Sunrise Power", "SUNP-0042-7781"), SECRET)["ok"]
    assert check(d, 2)["result"] == "fail"


def test_amount_anomaly_warn(conn, token):
    _grant(conn, "Pay my electricity bill up to ₹10,000")
    assert gateway.evaluate(conn, token, pay("Sunrise Power", 4990))["decision"] == "ALLOW"
    d = gateway.evaluate(conn, token, pay("Sunrise Power", 8000))
    assert d["decision"] == "PAUSE"
    assert check(d, 3)["result"] == "warn"


def test_purpose_mismatch_warns(conn, token):
    _grant(conn)
    d = gateway.evaluate(conn, token, pay("Sunrise Power", 4200, purpose="Water bill"))
    assert d["decision"] == "PAUSE"
    assert check(d, 2)["result"] == "warn"


def test_decision_is_recorded_and_audited(conn, token):
    _grant(conn)
    d = gateway.evaluate(conn, token, pay("R. Verma", 25000))
    r = conn.execute("SELECT * FROM requests WHERE id=?", (d["request_id"],)).fetchone()
    assert r["decision"] == "BLOCK" and r["status"] == "blocked"
    last = conn.execute("SELECT kind, data_json FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
    assert last["kind"] == "gateway_decision" and "BLOCK" in last["data_json"]


def test_wrong_owner_agent_blocked(conn):
    conn.execute("INSERT INTO agents VALUES ('agent-99','s','someone-else')")
    t = gateway.login(conn, "agent-99", "s")
    _grant(conn)
    d = gateway.evaluate(conn, t, pay("Sunrise Power", 4200))
    assert d["decision"] == "BLOCK" and check(d, 1)["result"] == "fail"
