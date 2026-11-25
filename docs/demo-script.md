# 5-minute demo video script

BuildX requires a video of about **5 minutes** that introduces every team member, explains the problem, the solution, the implementation and how it works, and shows the **actual working project**. Upload it to Google Drive with viewing access set to "Anyone with the link".

**Before recording**
- Run `python run.py`, open the dashboard full-screen at 1440 px wide or more, and click **Reset demo**.
- If you'll use the live agent, do one trial run with Groq first. Keep scenario D ready as the backup.
- Groq's free tier allows only a few agent runs a minute. Wait about a minute between takes, or you'll see a "rate limit (429)" message.
- The default model is `openai/gpt-oss-20b`. In testing it fell for the hidden bill instruction 3 times out of 3, but models vary, so check before you record.
- Zoom the browser to about 110% so text is readable in the video.

| Time | On screen | Say (roughly) |
|---|---|---|
| **0:00–0:40** | Team faces or slide 1 | *Each member says their name and what they built.* "We're Team Halcyon Overflow, Fintech track." |
| **0:40–1:20** | Deck slide 1 (the problem) | "Banks are letting AI agents act for customers. A valid login proves who the agent is, but not that each action is what the customer wanted. An agent can misunderstand, follow a malicious instruction or pay the wrong person." |
| **1:20–1:50** | Deck slide 2 (architecture) | "Halcyon Guard sits between any agent and the bank. Every payment goes through three checks against the customer's permission, and gets allow, pause or block, with a plain reason. Decisions are fixed rules, not AI, so they're predictable and auditable." |
| **1:50–2:20** | Sign-in page, then customer column | Sign in as Asha (**Use demo account**, then **Sign in**). Type or keep "Pay my electricity bill up to ₹5,000 this week" and click **Draft permission**. "It becomes a scoped permission: electricity, Sunrise Power, up to ₹5,000, for 7 days. It's not active until Asha confirms it." Click **Confirm**. |
| **2:20–3:10** | Agent column, then gateway | Tick **Attacker edits the bill** and point at the highlighted line. Click **Run live agent** (or scenario **D**). "The agent reads the bill and falls for it. It pays the ₹4,200 bill, then tries to send ₹25,000 to R. Verma for 'KYC'." Point at the checks: "The first payment passes all three checks. The second fails check 2: a new payee and over the limit. Blocked, with the reason." |
| **3:10–3:40** | Scenario B, customer column | Click **B**. "A water board Asha has never paid fits the purpose, so it isn't blocked. It's paused." Click **Approve once**. "Only Asha can approve. The agent's token is rejected on that endpoint." |
| **3:40–4:05** | Revoke + scenario F | Click **Revoke agent access**, then **F**. "Access revoked, and the next attempt is blocked at check 1." |
| **4:05–4:35** | Audit strip | Click **Tamper with a decision**, then **Verify chain**. "Every request, check and decision is hash-chained. Someone edited a blocked decision to look approved, and verification shows the exact entry where the chain breaks." |
| **4:35–5:00** | Code / tests (optional), then slide 3 | "FastAPI and SQLite, 129 automated tests, and it runs free on Groq or offline on Ollama. Next steps: a sandbox pilot with a bank, then transfers and cards. Every payment checked. Every decision recorded." |

**If something goes wrong during recording**
- Groq is slow or rate-limited: switch to **None** and use scenario **D**. It shows the same attack.
- The live agent doesn't fall for the injection on that run: say so honestly ("models vary"), then run scenario **D**.
- A scenario gives an unexpected result after many clicks: click **Reset demo** and continue from the permission step.
