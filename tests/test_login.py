"""Customer sign-in: customer ID + PIN, session check, sign-out and a per-address lockout."""
import pytest
from fastapi.testclient import TestClient

from halcyon.app import LOGIN_LIMIT, create_app
from halcyon.config import Settings


@pytest.fixture
def client(db_path):
    with TestClient(create_app(Settings(db_path=db_path, llm_provider="none", hmac_secret="s"))) as c:
        yield c


def login(client, customer_id="asha", pin="1234"):
    return client.post("/api/customer/login", json={"customer_id": customer_id, "pin": pin})


def test_login_with_id_and_pin(client):
    r = login(client)
    assert r.status_code == 200
    assert r.json()["name"] == "Asha Rao" and r.json()["token"]


def test_customer_id_is_case_insensitive(client):
    assert login(client, customer_id=" ASHA ").status_code == 200


def test_wrong_id_or_pin_rejected_with_same_message(client):
    a, b = login(client, customer_id="someone"), login(client, pin="0000")
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"]


def test_me_needs_a_valid_session(client):
    assert client.get("/api/customer/me").status_code == 401
    tok = login(client).json()["token"]
    r = client.get("/api/customer/me", headers={"X-Customer-Token": tok})
    assert r.status_code == 200 and r.json()["name"] == "Asha Rao"


def test_agent_token_is_not_a_customer_session(client):
    agent = client.post("/api/agent/login", json={"agent_id": "agent-01", "secret": "demo-secret"}).json()["token"]
    assert client.get("/api/customer/me", headers={"X-Customer-Token": agent}).status_code == 401


def test_logout_ends_the_session(client):
    tok = login(client).json()["token"]
    h = {"X-Customer-Token": tok}
    assert client.post("/api/customer/logout", headers=h).status_code == 200
    assert client.get("/api/customer/me", headers=h).status_code == 401
    assert client.post("/api/grants/draft", headers=h, json={"text": "Pay my electricity bill up to ₹5,000"}).status_code == 401


def test_lockout_after_repeated_wrong_pins(client):
    for _ in range(LOGIN_LIMIT):
        assert login(client, pin="0000").status_code == 401
    r = login(client)  # even the right PIN is refused while locked
    assert r.status_code == 429
    assert "minute" in r.json()["detail"]


def test_successful_login_clears_failures(client):
    for _ in range(LOGIN_LIMIT - 1):
        login(client, pin="0000")
    assert login(client).status_code == 200
    assert login(client, pin="0000").status_code == 401  # counter restarted, not locked


def test_login_page_is_served(client):
    r = client.get("/login.html")
    assert r.status_code == 200 and "Sign in" in r.text
