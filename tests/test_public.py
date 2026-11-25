"""Settings used by the public (Render) deployment."""
from fastapi.testclient import TestClient

from halcyon.app import create_app
from halcyon.config import Settings


def _client(db_path, **kw):
    return TestClient(create_app(Settings(db_path=db_path, llm_provider="none", hmac_secret="s", **kw)))


def test_health(db_path):
    with _client(db_path) as c:
        assert c.get("/api/health").json() == {"ok": True}


def test_public_flag_in_state(db_path):
    with _client(db_path, public_demo=True) as c:
        assert c.get("/api/state").json()["public_demo"] is True
    with _client(db_path) as c:
        assert c.get("/api/state").json()["public_demo"] is False


def test_live_agent_cooldown(db_path):
    with _client(db_path, agent_cooldown=60) as c:
        assert c.post("/api/agent/run", json={"task": "pay"}).status_code == 200
        r = c.post("/api/agent/run", json={"task": "pay"})
        assert r.status_code == 429
        assert "seconds" in r.json()["detail"]


def test_no_cooldown_by_default(db_path):
    with _client(db_path) as c:
        assert c.post("/api/agent/run", json={"task": "pay"}).status_code == 200
        assert c.post("/api/agent/run", json={"task": "pay"}).status_code == 200


def test_settings_from_env(monkeypatch):
    from halcyon.config import get_settings
    monkeypatch.setenv("PUBLIC_DEMO", "1")
    monkeypatch.setenv("AGENT_COOLDOWN", "20")
    s = get_settings()
    assert s.public_demo is True and s.agent_cooldown == 20
