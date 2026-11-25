"""One OpenAI-compatible chat client for Groq (free tier, default) or Ollama (local, offline).

Only the agent and the grant drafter use this. Gateway decisions never do.
"""
import json

import httpx

from .config import GROQ_BASE_URL, OLLAMA_BASE_URL, Settings

TIMEOUT = 30


class LLMUnavailable(Exception):
    """The model can't be used right now: no provider, missing key, network down, rate limit."""


def _endpoint(settings: Settings):
    p = settings.llm_provider
    if p == "groq":
        if not settings.groq_api_key:
            raise LLMUnavailable("No Groq API key is set. Add GROQ_API_KEY to .env (free at console.groq.com)")
        return GROQ_BASE_URL, settings.groq_model, {"Authorization": f"Bearer {settings.groq_api_key}"}, "Groq"
    if p == "ollama":
        return OLLAMA_BASE_URL, settings.ollama_model, {}, "Ollama"
    raise LLMUnavailable("No AI provider is selected")


def chat(messages, tools=None, settings: Settings | None = None, transport=None, json_mode=False) -> dict:
    """Send one chat completion request and return the assistant message dict."""
    settings = settings or Settings()
    base, model, headers, label = _endpoint(settings)
    body = {"model": model, "messages": messages, "temperature": 0.2}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    try:
        with httpx.Client(timeout=TIMEOUT, transport=transport) as client:
            r = client.post(f"{base}/chat/completions", json=body, headers=headers)
    except httpx.TimeoutException:
        raise LLMUnavailable(f"{label} took longer than {TIMEOUT}s to answer") from None
    except httpx.HTTPError as e:
        hint = " Is Ollama running?" if label == "Ollama" else " Check the internet connection."
        raise LLMUnavailable(f"Can't reach {label} ({e.__class__.__name__}).{hint}") from None
    if r.status_code == 429:
        raise LLMUnavailable(f"{label} rate limit reached (429). Wait a minute and try again")
    if r.status_code in (401, 403):
        raise LLMUnavailable(f"{label} rejected the API key ({r.status_code})")
    if r.status_code == 404:
        raise LLMUnavailable(f"{label} doesn't have the model '{model}' (404)")
    if r.status_code >= 400:
        raise LLMUnavailable(f"{label} returned an error {r.status_code}: {r.text[:200]}")
    try:
        return r.json()["choices"][0]["message"]
    except (ValueError, KeyError, IndexError, TypeError):
        raise LLMUnavailable(f"{label} returned a response in an unexpected format") from None


GRANT_PROMPT = (
    "Turn the bank customer's request into JSON with exactly these keys: "
    '"category" (one of "electricity", "water", "gas", "mobile", "internet", or null if unclear), '
    '"max_amount" (the maximum in rupees as a number, or null if not stated), '
    '"days" (how many days the permission should last; 7 if not stated). Reply with JSON only.'
)


def grant_drafter(settings: Settings):
    """Return fn(text) -> dict for grants.draft_grant. Its output is validated there, never trusted."""
    def draft(text: str) -> dict | None:
        msg = chat([{"role": "system", "content": GRANT_PROMPT}, {"role": "user", "content": text}],
                   settings=settings, json_mode=True)
        try:
            return json.loads(msg.get("content") or "")
        except ValueError:
            return None
    return draft
