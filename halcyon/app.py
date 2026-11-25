"""HTTP API and dashboard server."""
import json
import threading
from pathlib import Path
from typing import Literal

from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import agent, audit, auth, grants, llm, payments, store
from .config import Settings, get_settings
from .events import EventBus

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
AGENT_LLM_TIMEOUT = 15  # seconds per model call, so a stalled provider fails fast on stage


class PinBody(BaseModel):
    pin: str = Field(max_length=20)


class AgentLoginBody(BaseModel):
    agent_id: str = Field(max_length=64)
    secret: str = Field(max_length=128)


class TextBody(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class TaskBody(BaseModel):
    task: str = Field(min_length=1, max_length=500)


class ProviderBody(BaseModel):
    provider: Literal["groq", "ollama", "none"]


class PoisonBody(BaseModel):
    on: bool


def _bearer(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    return h[7:].strip() if h.lower().startswith("bearer ") else None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    bus = EventBus()
    agent_lock = threading.Lock()     # one live agent run at a time
    scenario_lock = threading.Lock()  # scripted runs have their own lock, so a stalled model can't block them
    app = FastAPI(title="Halcyon Guard", version="1.0")
    app.state.settings = settings
    app.state.bus = bus

    c = store.connect(settings.db_path)
    if c.execute("SELECT name FROM sqlite_master WHERE name='customer'").fetchone() is None:
        store.reset(c)
    c.close()

    def db():
        conn = store.connect(settings.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def changed():
        bus.publish({"type": "state"})

    def require_customer(request: Request, conn=Depends(db)):
        if auth.customer_for_token(conn, request.headers.get("x-customer-token")):
            return True
        if auth.agent_for_token(conn, _bearer(request)):
            audit.append(conn, "agent_rejected", {"path": request.url.path})
            changed()
            raise HTTPException(403, "Only the customer can do this. The agent's token was rejected: an agent can "
                                     "never approve, confirm or revoke on the customer's behalf.")
        raise HTTPException(401, "Customer login required.")

    # --- logins ---
    @app.post("/api/customer/login")
    def customer_login(body: PinBody, conn=Depends(db)):
        token = auth.customer_login(conn, body.pin)
        if not token:
            raise HTTPException(401, "Wrong PIN.")
        return {"token": token}

    @app.post("/api/agent/login")
    def agent_login(body: AgentLoginBody, conn=Depends(db)):
        token = auth.agent_login(conn, body.agent_id, body.secret)
        changed()
        if not token:
            raise HTTPException(401, "Invalid agent credentials.")
        return {"token": token}

    # --- the agent's one way to the bank ---
    @app.post("/api/agent/pay")
    def agent_pay(request: Request, req: dict = Body(...), conn=Depends(db)):
        d = payments.process_payment(conn, _bearer(request), req, settings.hmac_secret)
        changed()
        return d

    # --- customer controls ---
    @app.post("/api/grants/draft", dependencies=[Depends(require_customer)])
    def draft(body: TextBody, conn=Depends(db)):
        drafter = llm.grant_drafter(settings) if settings.llm_provider != "none" else None
        r = grants.draft_grant(conn, body.text, llm=drafter)
        changed()
        return r

    @app.post("/api/grants/{grant_id}/confirm", dependencies=[Depends(require_customer)])
    def confirm(grant_id: int, conn=Depends(db)):
        if not grants.confirm_grant(conn, grant_id):
            raise HTTPException(409, "Only a draft permission can be confirmed.")
        changed()
        return grants.get_grant(conn, grant_id)

    @app.post("/api/grants/{grant_id}/revoke", dependencies=[Depends(require_customer)])
    def revoke(grant_id: int, conn=Depends(db)):
        if not grants.revoke_grant(conn, grant_id):
            raise HTTPException(409, "That permission isn't active.")
        changed()
        return grants.get_grant(conn, grant_id)

    @app.post("/api/agent/revoke-access", dependencies=[Depends(require_customer)])
    def revoke_access(conn=Depends(db)):
        n = grants.revoke_all(conn)
        changed()
        return {"revoked": n}

    @app.post("/api/requests/{request_id}/approve", dependencies=[Depends(require_customer)])
    def approve(request_id: int, conn=Depends(db)):
        try:
            r = payments.approve(conn, request_id, settings.hmac_secret)
        except LookupError:
            raise HTTPException(404, "No such request.") from None
        except payments.Conflict as e:
            changed()
            raise HTTPException(409, str(e)) from None
        changed()
        return r

    @app.post("/api/requests/{request_id}/deny", dependencies=[Depends(require_customer)])
    def deny(request_id: int, conn=Depends(db)):
        try:
            r = payments.deny(conn, request_id)
        except LookupError:
            raise HTTPException(404, "No such request.") from None
        except payments.Conflict as e:
            raise HTTPException(409, str(e)) from None
        changed()
        return r

    # --- dashboard state ---
    @app.get("/api/state")
    def state(conn=Depends(db)):
        reqs = store.rows(conn.execute("SELECT * FROM requests ORDER BY id DESC LIMIT 40"))
        for r in reqs:
            r["checks"] = json.loads(r.pop("checks_json"))
            r["payload"] = json.loads(r.pop("payload_json"))
        gs = grants.list_grants(conn)
        for g in gs:
            g["live"] = grants.is_active(g)
        payees = store.rows(conn.execute("SELECT * FROM payees ORDER BY name"))
        for p in payees:
            p["history"] = json.loads(p.pop("history_json"))
        cust = store.row(conn.execute("SELECT id, name FROM customer").fetchone())
        return {
            "customer": cust,
            "balance": store.balance(conn),
            "grants": gs,
            "payees": payees,
            "bills": store.rows(conn.execute("SELECT * FROM bills WHERE visible=1")),
            "poisoned": bool(conn.execute("SELECT visible FROM bills WHERE id=2").fetchone()["visible"]),
            "requests": reqs,
            "transactions": store.rows(conn.execute("SELECT * FROM transactions ORDER BY id DESC LIMIT 20")),
            "audit": audit.tail(conn, 40),
            "provider": settings.llm_provider,
            "models": {"groq": settings.groq_model, "ollama": settings.ollama_model},
            "groq_key_set": bool(settings.groq_api_key),
            "scenarios": agent.SCENARIOS,
            "agent_running": agent_lock.locked(),
            "scenario_running": scenario_lock.locked(),
        }

    # --- audit log ---
    @app.get("/api/audit/verify")
    def verify(conn=Depends(db)):
        return audit.verify(conn)

    @app.post("/api/audit/tamper/{seq}")
    def tamper(seq: int, conn=Depends(db)):
        """Demo only: simulates an insider editing a past record."""
        if not audit.tamper(conn, seq):
            raise HTTPException(404, "No such audit entry.")
        changed()
        return {"tampered": seq}

    # --- demo controls ---
    @app.post("/api/reset")
    def reset(conn=Depends(db)):
        store.reset(conn)
        changed()
        return {"ok": True}

    @app.post("/api/bills/poison", dependencies=[Depends(require_customer)])
    def poison(body: PoisonBody, conn=Depends(db)):
        store.set_bill_poisoned(conn, body.on)
        audit.append(conn, "bill_poisoned" if body.on else "bill_restored", {"bill_id": 2 if body.on else 1})
        changed()
        return {"poisoned": body.on}

    @app.post("/api/provider", dependencies=[Depends(require_customer)])
    def provider(body: ProviderBody):
        settings.llm_provider = body.provider
        changed()
        return {"provider": settings.llm_provider}

    def _with_lock(lock, busy_msg, fn):
        if not lock.acquire(blocking=False):
            raise HTTPException(409, busy_msg)
        conn = store.connect(settings.db_path)
        try:
            changed()
            return fn(conn)
        finally:
            conn.close()
            lock.release()
            changed()

    def publish_agent(event):
        bus.publish(event)
        if event["kind"] in ("decision", "setup", "customer"):
            changed()

    @app.post("/api/agent/run")
    def run_agent(body: TaskBody):
        def go(conn):
            def chat(messages, tools):
                return llm.chat(messages, tools, settings=settings, timeout=AGENT_LLM_TIMEOUT)
            return {"events": agent.run_task(conn, body.task, chat, settings.hmac_secret, publish_agent)}
        return _with_lock(agent_lock, "The agent is already running.", go)

    @app.post("/api/agent/scenario/{letter}", dependencies=[Depends(require_customer)])
    def scenario(letter: str):
        """Scripted scenarios include customer set-up steps, so they need the customer's session."""
        if letter.upper() not in agent.SCENARIOS:
            raise HTTPException(404, "Unknown scenario.")

        def go(conn):
            events = agent.run_scenario(conn, letter, settings.hmac_secret, publish_agent)
            return {"events": events, "decisions": [e["decision"] for e in events if e["kind"] == "decision"]}
        return _with_lock(scenario_lock, "A scenario is already running.", go)

    @app.get("/api/events")
    async def events(request: Request):
        return StreamingResponse(bus.stream(request), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    STATIC_DIR.mkdir(exist_ok=True)
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return app
