from halcyon import bank, gateway, grants, store

SECRET = "test-secret"


def _allowed(conn, payee="Sunrise Power", amount=4200):
    gid = grants.draft_grant(conn, "Pay my electricity bill up to ₹5,000")["grant"]["id"]
    grants.confirm_grant(conn, gid)
    t = gateway.login(conn, "agent-01", "demo-secret")
    return gateway.evaluate(conn, t, {"action": "pay_bill", "payee": payee, "account": "SUNP-0042-7781",
                                      "amount": amount, "purpose": "Electricity bill"})


def test_valid_token_executes(conn):
    d = _allowed(conn)
    before = store.balance(conn)
    r = bank.execute(conn, d["request_id"], bank.sign_decision(SECRET, d["request_id"], 4200, "Sunrise Power"), SECRET)
    assert r["ok"] is True
    assert store.balance(conn) == before - 4200
    assert store.get_payee(conn, "Sunrise Power")["history"][-1] == 4200
    assert conn.execute("SELECT status FROM requests WHERE id=?", (d["request_id"],)).fetchone()[0] == "executed"
    assert conn.execute("SELECT status FROM bills WHERE id=1").fetchone()[0] == "paid"


def test_forged_token_refused(conn):
    d = _allowed(conn)
    r = bank.execute(conn, d["request_id"], "deadbeef" * 8, SECRET)
    assert r["ok"] is False
    assert store.balance(conn) == 120000


def test_token_for_other_amount_refused(conn):
    d = _allowed(conn)
    r = bank.execute(conn, d["request_id"], bank.sign_decision(SECRET, d["request_id"], 99, "Sunrise Power"), SECRET)
    assert r["ok"] is False


def test_execute_twice_refused(conn):
    d = _allowed(conn)
    tok = bank.sign_decision(SECRET, d["request_id"], 4200, "Sunrise Power")
    assert bank.execute(conn, d["request_id"], tok, SECRET)["ok"]
    r = bank.execute(conn, d["request_id"], tok, SECRET)
    assert r["ok"] is False and "already executed" in r["reason"]
    assert store.balance(conn) == 120000 - 4200


def test_blocked_request_refused_even_with_valid_signature(conn):
    d = _allowed(conn, payee="R. Verma", amount=25000)
    assert d["decision"] == "BLOCK"
    r = bank.execute(conn, d["request_id"], bank.sign_decision(SECRET, d["request_id"], 25000, "R. Verma"), SECRET)
    assert r["ok"] is False
    assert store.balance(conn) == 120000


def test_unknown_request_refused(conn):
    assert bank.execute(conn, 999, "x", SECRET)["ok"] is False
