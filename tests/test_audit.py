from halcyon import audit


def _fresh(conn):
    conn.execute("DELETE FROM audit")


def test_chain_verifies_after_appends(conn):
    _fresh(conn)
    for i in range(3):
        audit.append(conn, "test", {"i": i})
    assert audit.verify(conn) == {"ok": True, "broken_at": None, "count": 3}


def test_hash_links_prev(conn):
    _fresh(conn)
    e1 = audit.append(conn, "test", {"i": 1})
    e2 = audit.append(conn, "test", {"i": 2})
    assert e1["prev_hash"] == "0" * 64
    assert e2["prev_hash"] == e1["hash"]


def test_tamper_detected(conn):
    _fresh(conn)
    entries = [audit.append(conn, "test", {"i": i}) for i in range(3)]
    second = entries[1]["seq"]
    audit.tamper(conn, second)
    result = audit.verify(conn)
    assert result["ok"] is False
    assert result["broken_at"] == second


def test_seed_is_audited_and_valid(conn):
    assert audit.verify(conn)["ok"] is True
    assert audit.tail(conn, 5)[0]["kind"] == "reset"
