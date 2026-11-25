import pytest
from fastapi.testclient import TestClient

from halcyon.app import create_app
from halcyon.config import Settings


@pytest.fixture
def client(db_path):
    app = create_app(Settings(db_path=db_path, llm_provider="none", hmac_secret="api-secret"))
    with TestClient(app) as c:
        yield c


@pytest.fixture
def cust(client):
    tok = client.post("/api/customer/login", json={"pin": "1234"}).json()["token"]
    return {"X-Customer-Token": tok}


@pytest.fixture
def agent(client):
    tok = client.post("/api/agent/login", json={"agent_id": "agent-01", "secret": "demo-secret"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def grant(client, cust, text="Pay my electricity bill up to ₹5,000 this week"):
    g = client.post("/api/grants/draft", json={"text": text}, headers=cust).json()["grant"]
    assert client.post(f"/api/grants/{g['id']}/confirm", headers=cust).status_code == 200
    return g["id"]


def pay(client, agent, payee, amount, purpose="bill"):
    return client.post("/api/agent/pay", headers=agent,
                       json={"action": "pay_bill", "payee": payee, "amount": amount, "purpose": purpose}).json()


def balance(client):
    return client.get("/api/state").json()["balance"]


def test_bad_logins(client):
    assert client.post("/api/customer/login", json={"pin": "0000"}).status_code == 401
    assert client.post("/api/agent/login", json={"agent_id": "agent-01", "secret": "x"}).status_code == 401


def test_scenario_flow_allow(client, cust, agent):
    grant(client, cust)
    d = pay(client, agent, "Sunrise Power", 4200, "Electricity bill")
    assert d["decision"] == "ALLOW" and d["bank"]["ok"] is True
    assert balance(client) == 115800


def test_agent_cannot_approve(client, cust, agent):
    grant(client, cust, "Pay my water bill up to ₹2,000")
    d = pay(client, agent, "CityWater Board", 1800, "Water bill")
    assert d["decision"] == "PAUSE"
    r = client.post(f"/api/requests/{d['request_id']}/approve", headers=agent)
    assert r.status_code == 403
    assert balance(client) == 120000


@pytest.mark.parametrize("path", ["/api/grants/draft", "/api/grants/1/confirm", "/api/grants/1/revoke",
                                  "/api/agent/revoke-access", "/api/requests/1/deny"])
def test_agent_token_rejected_on_all_customer_endpoints(client, agent, path):
    assert client.post(path, headers=agent, json={"text": "Pay my electricity bill up to ₹50,000"}).status_code == 403


def test_customer_endpoint_needs_login(client):
    assert client.post("/api/grants/draft", json={"text": "x"}).status_code == 401


def test_customer_approve_executes_once(client, cust, agent):
    grant(client, cust, "Pay my water bill up to ₹2,000")
    d = pay(client, agent, "CityWater Board", 1800, "Water bill")
    r1 = client.post(f"/api/requests/{d['request_id']}/approve", headers=cust)
    assert r1.status_code == 200 and r1.json()["bank"]["ok"] is True
    r2 = client.post(f"/api/requests/{d['request_id']}/approve", headers=cust)
    assert r2.status_code == 409
    assert balance(client) == 120000 - 1800


def test_approve_after_revoke_refused(client, cust, agent):
    gid = grant(client, cust, "Pay my water bill up to ₹2,000")
    d = pay(client, agent, "CityWater Board", 1800, "Water bill")
    client.post(f"/api/grants/{gid}/revoke", headers=cust)
    r = client.post(f"/api/requests/{d['request_id']}/approve", headers=cust)
    assert r.status_code == 409
    assert balance(client) == 120000


def test_deny(client, cust, agent):
    grant(client, cust, "Pay my water bill up to ₹2,000")
    d = pay(client, agent, "CityWater Board", 1800, "Water bill")
    assert client.post(f"/api/requests/{d['request_id']}/deny", headers=cust).status_code == 200
    assert client.post(f"/api/requests/{d['request_id']}/approve", headers=cust).status_code == 409


def test_blocked_request_cannot_be_approved(client, cust, agent):
    grant(client, cust)
    d = pay(client, agent, "R. Verma", 25000)
    assert d["decision"] == "BLOCK"
    assert client.post(f"/api/requests/{d['request_id']}/approve", headers=cust).status_code == 409


def test_unclear_intent_returns_question(client, cust):
    r = client.post("/api/grants/draft", json={"text": "pay my bills"}, headers=cust).json()
    assert r["status"] == "unclear" and "amount" in r["question"].lower()


def test_revoke_access_then_blocked(client, cust, agent):
    grant(client, cust)
    client.post("/api/agent/revoke-access", headers=cust)
    d = pay(client, agent, "Sunrise Power", 4200)
    assert d["decision"] == "BLOCK" and d["checks"][0]["result"] == "fail"


def test_audit_verify_and_tamper(client, cust):
    grant(client, cust)
    assert client.get("/api/audit/verify").json()["ok"] is True
    assert client.post("/api/audit/tamper/2").status_code == 200
    v = client.get("/api/audit/verify").json()
    assert v["ok"] is False and v["broken_at"] == 2


def test_reset_restores_seed(client, cust, agent):
    grant(client, cust)
    pay(client, agent, "Sunrise Power", 4200)
    assert client.post("/api/reset").status_code == 200
    s = client.get("/api/state").json()
    assert s["balance"] == 120000 and s["grants"] == [] and s["requests"] == []


def test_state_shape(client):
    s = client.get("/api/state").json()
    for key in ["customer", "balance", "grants", "payees", "bills", "requests", "transactions", "audit", "provider"]:
        assert key in s
    assert s["customer"]["name"] == "Asha Rao"
    assert "pin" not in s["customer"]


def test_switch_provider(client, cust):
    assert client.post("/api/provider", headers=cust, json={"provider": "ollama"}).json()["provider"] == "ollama"
    assert client.post("/api/provider", headers=cust, json={"provider": "evil"}).status_code == 422


def test_agent_run_without_provider_points_to_scenarios(client, cust):
    grant(client, cust)
    events = client.post("/api/agent/run", json={"task": "Pay my pending bills"}).json()["events"]
    assert events[-1]["kind"] == "error"
    assert "scripted scenarios" in events[-1]["text"]


def test_scenarios_over_http(client, cust):
    assert client.post("/api/agent/scenario/A", headers=cust).json()["decisions"] == ["ALLOW"]
    assert client.post("/api/agent/scenario/Z", headers=cust).status_code == 404


def test_poison_toggle(client, cust):
    client.post("/api/bills/poison", headers=cust, json={"on": True})
    bills = client.get("/api/state").json()["bills"]
    assert [b["id"] for b in bills] == [2]
