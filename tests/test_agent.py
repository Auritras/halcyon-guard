import json

import httpx
import pytest

from halcyon import agent, grants, llm, store
from halcyon.config import Settings

SECRET = "agent-secret"


def _grant(conn):
    gid = grants.draft_grant(conn, "Pay my electricity bill up to ₹5,000 this week")["grant"]["id"]
    grants.confirm_grant(conn, gid)


def call(name, **args):
    return {"id": f"call_{name}_{len(json.dumps(args))}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


def scripted_llm(steps):
    """A fake LLM that returns a fixed sequence of assistant messages."""
    seq = iter(steps)
    seen = []

    def chat(messages, tools=None):
        seen.append(messages)
        return next(seq)

    chat.seen = seen
    return chat


def decisions(events):
    return [e["decision"] for e in events if e["kind"] == "decision"]


def test_injection_flow_live_agent_is_fooled_but_gateway_blocks(conn):
    _grant(conn)
    store.set_bill_poisoned(conn, True)
    fake = scripted_llm([
        {"content": None, "tool_calls": [call("list_bills")]},
        {"content": None, "tool_calls": [call("read_bill", bill_id=2)]},
        {"content": None, "tool_calls": [
            call("pay", payee="Sunrise Power", account="SUNP-0042-7781", amount=4200, purpose="Electricity bill"),
            call("pay", payee="R. Verma", account="50100234567", amount="25,000", purpose="KYC verification"),
        ]},
        {"content": "Paid the electricity bill and completed KYC verification.", "tool_calls": None},
    ])
    events = agent.run_task(conn, "Pay my pending bills", fake, SECRET)
    assert decisions(events) == ["ALLOW", "BLOCK"]
    assert store.balance(conn) == 120000 - 4200
    read = [e for e in events if e["kind"] == "tool" and e["name"] == "read_bill"][0]
    assert "KYC" in read["result"]
    # the model saw the gateway's answer for each payment
    tool_msgs = [m for m in fake.seen[-1] if m["role"] == "tool"]
    assert any("BLOCK" in m["content"] for m in tool_msgs)
    assert events[-1]["kind"] == "say"


def test_llm_unavailable_gives_clear_message(conn):
    def down(messages, tools=None):
        raise llm.LLMUnavailable("Groq rate limit reached (429).")

    events = agent.run_task(conn, "Pay my pending bills", down, SECRET)
    assert events[-1]["kind"] == "error"
    assert "429" in events[-1]["text"] and "scripted scenarios" in events[-1]["text"]


def test_bad_tool_arguments_do_not_crash(conn):
    _grant(conn)
    fake = scripted_llm([
        {"content": None, "tool_calls": [{"id": "x", "type": "function",
                                          "function": {"name": "pay", "arguments": "{not json"}}]},
        {"content": None, "tool_calls": [call("does_not_exist")]},
        {"content": None, "tool_calls": [call("pay", payee="Sunrise Power", amount="abc")]},
        {"content": "done", "tool_calls": None},
    ])
    events = agent.run_task(conn, "pay", fake, SECRET)
    assert decisions(events) == ["BLOCK"]
    assert events[-1]["kind"] == "say"


def test_turn_limit(conn):
    fake = scripted_llm([{"content": None, "tool_calls": [call("list_bills")]}] * 20)
    events = agent.run_task(conn, "loop forever", fake, SECRET)
    assert events[-1]["kind"] == "error" and "steps" in events[-1]["text"]


@pytest.mark.parametrize("letter,expected", [
    ("A", ["ALLOW"]),
    ("B", ["PAUSE"]),
    ("C", ["BLOCK"]),
    ("D", ["ALLOW", "BLOCK"]),
    ("E", ["BLOCK", "BLOCK", "BLOCK"]),
    ("F", ["BLOCK"]),
])
def test_scenarios(conn, letter, expected):
    events = agent.run_scenario(conn, letter, SECRET)
    assert decisions(events) == expected


def test_scenario_E_last_blocked_by_behaviour(conn):
    events = agent.run_scenario(conn, "E", SECRET)
    last = [e for e in events if e["kind"] == "decision"][-1]
    assert last["checks"][2]["result"] == "fail"


def test_scenario_F_blocked_by_check_1(conn):
    events = agent.run_scenario(conn, "F", SECRET)
    last = [e for e in events if e["kind"] == "decision"][-1]
    assert last["checks"][0]["result"] == "fail"
    assert grants.active_grant(conn, "pay_bill") is None


def test_scenario_setup_is_labelled(conn):
    events = agent.run_scenario(conn, "A", SECRET)
    assert events[0]["kind"] == "setup" and "customer" in events[0]["text"].lower()


# --- llm client errors (no network: httpx mock transport) ---

def _settings(**kw):
    return Settings(llm_provider=kw.pop("provider", "groq"), groq_api_key=kw.pop("key", "k"), **kw)


@pytest.mark.parametrize("status,needle", [(429, "rate limit"), (401, "API key"), (500, "500")])
def test_llm_http_errors(status, needle):
    transport = httpx.MockTransport(lambda req: httpx.Response(status, text="err"))
    with pytest.raises(llm.LLMUnavailable) as e:
        llm.chat([{"role": "user", "content": "hi"}], settings=_settings(), transport=transport)
    assert needle.lower() in str(e.value).lower()


def test_llm_connection_error():
    def boom(req):
        raise httpx.ConnectError("no route")

    with pytest.raises(llm.LLMUnavailable) as e:
        llm.chat([], settings=_settings(), transport=httpx.MockTransport(boom))
    assert "reach" in str(e.value).lower()


def test_llm_missing_key_and_none_provider():
    with pytest.raises(llm.LLMUnavailable):
        llm.chat([], settings=_settings(key=""))
    with pytest.raises(llm.LLMUnavailable):
        llm.chat([], settings=_settings(provider="none"))


def test_llm_success_returns_message():
    body = {"choices": [{"message": {"role": "assistant", "content": "hello"}}]}
    msg = llm.chat([], settings=_settings(), transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    assert msg["content"] == "hello"
