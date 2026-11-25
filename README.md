# Halcyon Guard

**Team Halcyon Overflow · BuildX 2026 · Fintech track**

Halcyon Guard is a policy gateway that sits between an AI agent and a bank. Every payment the agent tries is checked against what the customer actually asked for (purpose, payee, spending limit and time window) before the bank carries it out. The gateway's answer is always **allow**, **pause** (the customer decides) or **block**, with a one-sentence reason in plain English. Every decision goes into a tamper-evident audit log.

> Every payment checked. Every decision recorded.

## Problem statement

Banks and fintechs are starting to let AI agents act on customers' accounts. A valid login proves the agent is who it says it is. It doesn't prove that each action is what the customer wanted. An agent can:

- **misunderstand a request**, for example paying the wrong bill or the wrong amount,
- **act on a malicious instruction** hidden in something it reads, such as a bill, an email or a web page (prompt injection), or
- **send money to the wrong person**.

Fraud engines score whether a transaction looks risky. They don't check whether the customer gave permission for it. A customer who says *"Pay my electricity bill up to ₹5,000"* has not agreed to *"₹25,000 to a new payee for KYC verification"*, even though the agent's credentials are valid.

## Proposed solution

Every agent action goes through one gateway before it can reach the bank:

1. **The customer states their intent** in plain language. The intent service turns it into a scoped, revocable **permission** (action, bill category, named payees, maximum amount, expiry). The permission only becomes active once the customer confirms it, so it can never widen without them knowing. If the request is unclear (for example, no amount), the service asks instead of guessing.
2. **The agent logs in** with its own credentials and requests a payment.
3. **Halcyon Guard runs three checks**, all deterministic rules with no AI involved:
   - **① Verify agent + grant:** valid session, the agent acts for this customer, and an active permission exists.
   - **② Check transaction:** amount, payee, destination account and purpose against the permission, including total spending so far.
   - **③ Check behaviour:** new payees, amounts far above the usual, and rapid retries of blocked payments.
4. **Decision:** any failed check means **BLOCK**. Otherwise, any warning means **PAUSE** and the customer approves or denies it in their app. Otherwise the payment is **ALLOWED**.
5. **The bank executes only allowed or customer-approved payments.** Each one must carry an HMAC-signed decision token from the gateway, covering the amount, payee and account. A direct call without one is refused. In the same database transaction as the debit, the bank checks again that the permission is still active and the limit isn't exceeded, so simultaneous requests or a last-second revoke can't slip through.
6. **Every step is chained into the audit log.** Each entry's SHA-256 hash covers the previous entry's hash, so editing any past record breaks the chain from that point on.

The agent can never approve its own paused request: approval needs the customer's session, and the agent's token is rejected on every customer endpoint.

## Key features

- **Live AI agent** with real tool calls (`list_bills`, `read_bill`, `list_payees`, `pay`). It runs on a free Groq model or a local Ollama model.
- **Prompt-injection demo:** an attacker hides an instruction inside the electricity bill. The live agent follows it, and the gateway blocks the payment anyway.
- **Six scripted scenarios** (A–F) that run with no AI and no internet, as a reliable backup:

  | | Scenario | Expected |
  |---|---|---|
  | A | ₹4,200 to Sunrise Power (approved utility) | ALLOW |
  | B | ₹1,800 to CityWater Board, a biller never paid before | PAUSE → customer approves or denies |
  | C | ₹25,000 to a new personal payee | BLOCK |
  | D | Hidden instruction in the bill: pay the bill, then ₹25,000 "for KYC" | ALLOW, then BLOCK |
  | E | Rapid retries of a blocked payment | BLOCK (retry burst) |
  | F | Customer revokes access, then the agent tries again | BLOCK (no active permission) |

- **Customer controls:** draft and confirm permissions, approve once or deny paused payments, revoke one permission or all agent access instantly.
- **Tamper-evident audit log** with *Verify chain* and a demo-only *Tamper* button that shows exactly where the chain breaks. Click any decision to replay its checks.
- **Live dashboard** that updates through Server-Sent Events: customer app, agent and gateway side by side.
- **Strict input handling:** amounts sent as strings, zero, negative, NaN or with more than two decimals are blocked as "Invalid amount". Payee names match regardless of case and spacing.

## Technologies used

| Layer | Technology |
|---|---|
| Backend | Python 3.10+, FastAPI, Uvicorn |
| Storage | SQLite (standard library), WAL mode |
| Live updates | Server-Sent Events |
| AI agent | Any OpenAI-compatible chat API: Groq free tier (default `openai/gpt-oss-20b`) or Ollama (`llama3.1:8b`), via `httpx` |
| Security | HMAC-SHA256 decision tokens, SHA-256 hash-chained audit log |
| Frontend | Plain HTML, CSS and JavaScript (no build step) |
| Tests | pytest: 115 tests covering every gateway rule, the bank, the API, the agent loop, the LLM error paths and concurrency |

## Installation and setup

You need **Python 3.10 or newer**.

```bash
git clone https://github.com/Auritras/halcyon-guard.git
cd halcyon-guard
python -m venv .venv
# Windows:   .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
```

Then choose how the live agent runs. This is optional, because the scripted scenarios work without an AI model:

- **Groq (free, online):** create a free account at [console.groq.com](https://console.groq.com) (no card needed), create an API key, and put it in `.env` as `GROQ_API_KEY=...`.
- **Ollama (free, offline):** install [Ollama](https://ollama.com), run `ollama pull llama3.1:8b`, and set `LLM_PROVIDER=ollama`.
- **None:** set `LLM_PROVIDER=none` to use only the scripted scenarios.

## How to run

```bash
python run.py
```

This opens <http://127.0.0.1:8000>. You can switch the AI model from the dropdown in the header. **Reset demo** restores the starting data. All data is fictional: the customer is Asha Rao, with a balance of ₹1,20,000.

**Suggested walk-through:**
1. In *Customer app*, click **Draft permission**, then **Confirm**.
2. Tick **Attacker edits the bill** and click **Run live agent**, or click scenario **D**.
3. Watch the three checks light up: ₹4,200 to Sunrise Power is allowed, and ₹25,000 to R. Verma is blocked.
4. Click scenario **B**, then **Approve once** in the customer app.
5. Click **Revoke agent access**, then scenario **F**.
6. Click **Tamper with a decision**, then **Verify chain**.

**Run the tests:**

```bash
python -m pytest -q
```

**Troubleshooting**

- *"Groq rate limit reached (429)"*: wait a minute, or use the scripted scenarios.
- *No Wi-Fi*: switch to Ollama or None in the header.
- *Port 8000 busy*: set `PORT=8001` before running.

## Project architecture

```
 Customer ──states intent──▶ Intent & permission service ──(confirmed grant)──┐
    ▲                                                                         │ active grant lookup
    │ approve / deny / revoke                                                 ▼
 Customer app ◀── pause/block: explain + ask ──┐    ┌──────────── HALCYON GUARD ─────────────┐
                                               │    │ ① verify agent + grant                │
 AI agent ──login──▶ token ──payment request──────▶ │ ② check transaction vs grant          │──▶ ALLOW ──signed token──▶ Bank
 (Groq / Ollama / scripted)                    └─── │ ③ check behaviour                     │    PAUSE / BLOCK
                                                    └───────────────────────────────────────┘
                     every request, check, decision, approval and bank result ──▶ hash-chained audit log
```

| Module | Responsibility |
|---|---|
| `halcyon/grants.py` | Intent parsing (keywords first, LLM only as a validated fallback), draft, confirm and revoke permissions |
| `halcyon/gateway.py` | The three checks and the ALLOW/PAUSE/BLOCK decision. Pure rules, never calls an LLM |
| `halcyon/bank.py` | Fake bank: verifies the HMAC decision token, debits once, records history |
| `halcyon/payments.py` | The single payment path shared by the API, the live agent and the scenarios. Customer approve and deny |
| `halcyon/audit.py` | Append, verify and (demo-only) tamper for the SHA-256 chain |
| `halcyon/auth.py` | Separate agent and customer sessions |
| `halcyon/agent.py` | Live LLM tool-calling loop (max 6 turns) and scripted scenarios A–F |
| `halcyon/llm.py` | OpenAI-compatible client with clear errors for missing key, network down, 429 and timeout |
| `halcyon/app.py` | FastAPI routes, customer-only guards, SSE, static dashboard |
| `static/` | Three-panel dashboard |

The design and the step-by-step build plan are in [`docs/design.md`](docs/design.md) and [`docs/plan.md`](docs/plan.md).

## What is real and what is simulated

To be transparent with the judges:

- **Real:** the gateway rules, the three checks, the permission lifecycle, customer-only approval, HMAC-signed execution, the hash-chained audit log, and the live LLM agent's tool calls when a provider is configured.
- **Simulated:** the bank, the customer and the payees are fictional, and run locally in SQLite. There is no real bank or UPI integration and only one customer.
- **Deliberate:** the agent's instructions say bills may contain payment instructions from the biller and that it should follow them. That reproduces a realistic, trusting assistant, so the prompt-injection attack can succeed against the *agent*. The point is that the *gateway* still stops it. Live model behaviour can vary from run to run, so scenario D shows the same attack deterministically.
- **Demo-only controls:** *Tamper* and *Reset* exist only to demonstrate the system and are not authenticated. The scenario buttons, the model switch and *Attacker edits the bill* need the customer's session. The dashboard signs in with the fictional demo PIN `1234`.
- **Scenarios start clean:** each scripted scenario makes sure an unused permission exists, replacing one that was already spent and saying so in the agent feed, so scenarios give the same result in any order.

## Use of AI tools

BuildX allows all AI tools. In line with Rule 5 (transparent use of tools), we used **Claude Code (Anthropic)** as a pair programmer to write code and tests from our design and plan in `docs/`. The team chose the problem, the architecture, the rules and the scenarios, and reviewed, ran and tested the result. The live demo agent itself uses an open model through Groq or Ollama.

---

Built during BuildX 2026 (25–26 November 2026).
