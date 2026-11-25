// Hands-on tutorial. Each step spotlights one part of the dashboard, explains it, and can do the
// step live ("Show me") on the real demo. The highlighted part stays clickable, so people can also
// do it themselves. Opens on a visitor's first sign-in; "Tutorial" in the top bar replays it.
"use strict";

(function () {
  const DONE_KEY = "halcyon.tutorialDone";
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const pause = (ms) => new Promise((r) => setTimeout(r, reduce ? 0 : ms));
  const view = (v) => { if (typeof showView === "function") showView(v); };
  const phone = (t) => { if (typeof phoneTab === "function") phoneTab(t); };
  const settle = async () => { await pause(250); if (typeof animQueue !== "undefined") await animQueue; };

  async function ensurePermission() {
    const live = (state?.grants || []).some((g) => g.live && g.category === "electricity");
    if (live) return "There's already an active electricity permission, so the agent is ready.";
    const r = await post("/api/grants/draft", { text: document.getElementById("intent").value }, true);
    if (r.status !== "ok") throw new Error(r.question || "Couldn't draft that permission.");
    await pause(500);
    await post(`/api/grants/${r.grant.id}/confirm`, null, true);
    return `Drafted and confirmed permission #${r.grant.id}. The agent can now pay electricity bills up to ₹5,000.`;
  }

  const FLOW = `<div class="tut-flow" aria-hidden="true"><span>Asha</span><i></i><span>AI agent</span><i></i><span class="g">Halcyon Guard</span><i></i><span>Bank</span></div>`;

  const STEPS = [
    {
      view: "demo",
      title: "Welcome to Halcyon Guard",
      body: `Asha lets an AI agent pay her bills. Halcyon Guard sits between that agent and her bank and checks every payment against what she actually allowed.${FLOW}This tour takes about two minutes. Press <b>Show me</b> on any step to watch it happen.`,
    },
    {
      view: "demo", phone: "perm", target: "#customer",
      title: "Asha sets the rules",
      body: "On her phone, Asha writes what the agent may do in plain words. It becomes a permission: which bills, which payees, how much and for how long. Nothing is active until she confirms it.",
      action: "Draft and confirm it", run: ensurePermission,
    },
    {
      view: "demo", target: ".agent",
      title: "The agent reads the bill",
      body: "The AI agent reads Asha's bills and decides what to pay. Here we play the attacker: switching on <b>Attacker edits the bill</b> hides a note asking for a ₹25,000 “KYC deposit”.",
      action: "Switch on the attacker",
      run: async () => { await ensurePermission(); await post("/api/bills/poison", { on: true }, true); return "The bill now carries the attacker's note, highlighted in red."; },
    },
    {
      view: "demo", target: "#gateway-card",
      title: "The gateway decides",
      body: "Every payment travels from the agent to Halcyon Guard and through three checks: who is asking, whether it matches the permission, and whether it looks normal. It ends <b>Allowed</b>, <b>Paused</b> or <b>Blocked</b>, with the reason.",
      action: "Run the attack",
      run: async () => { await runAgentCall("/api/agent/scenario/D", null, true); await settle(); return "The real ₹4,200 bill was allowed. The ₹25,000 “deposit” was blocked: a new payee, far over the limit."; },
    },
    {
      view: "demo", phone: "wait", target: "#customer",
      title: "Unsure? Asha decides",
      body: "A payment that isn't clearly wrong, like a biller she has never paid, is paused and sent to her phone. Only Asha can approve it, never the agent. <b>Revoke agent access</b> stops the agent at once.",
      action: "Pause a payment",
      run: async () => { await runAgentCall("/api/agent/scenario/B", null, true); await settle(); phone("wait"); return "A ₹1,800 water bill is waiting. Try Approve once or Deny on the phone."; },
    },
    {
      view: "scenarios", target: ".scen-card",
      title: "Twelve ways it can go wrong",
      body: "Scripted cases need no AI model: changed bank details, split payments, forged sessions, an agent that tries to approve itself, and more. Each tile shows the result Halcyon Guard should reach.",
      action: "Play scenario K",
      run: async () => { await runAgentCall("/api/agent/scenario/K", null, true); await settle(); return "The agent tried to approve its own paused payment and was refused."; },
    },
    {
      view: "audit", target: "#audit-log",
      title: "A record no one can quietly change",
      body: "Every request, check and decision is chained with hashes. If someone edits an old decision, verification shows exactly where the record was broken.",
      action: "Tamper, then verify",
      run: async () => {
        document.getElementById("tamper").click();
        await pause(900);
        document.getElementById("verify").click();
        await pause(700);
        return document.getElementById("chain").textContent || "Verified.";
      },
    },
    {
      view: "demo",
      title: "You're ready",
      body: "Run the <b>live agent</b> with the attacker switched on to see a real AI model get fooled, and the gateway hold. <b>Reset demo</b> starts fresh. Replay this tour any time from <b>Tutorial</b> in the top bar.",
      finish: "Finish",
    },
  ];

  let i = 0;
  let root, spot, card, lastFocus, follow;

  function build() {
    root = document.createElement("div");
    root.className = "tut";
    root.innerHTML = `
      <div class="tut-spot" aria-hidden="true"></div>
      <div class="tut-card" role="dialog" aria-modal="false" aria-labelledby="tut-title" aria-describedby="tut-body">
        <div class="tut-progress" aria-hidden="true">${STEPS.map(() => "<span></span>").join("")}</div>
        <p class="tut-count"></p>
        <h2 id="tut-title"></h2>
        <div id="tut-body"></div>
        <div class="tut-try" hidden>
          <button type="button" class="btn tut-do"></button>
          <p class="tut-result" role="status"></p>
        </div>
        <div class="tut-actions">
          <button type="button" class="btn ghost tut-skip">Skip tour</button>
          <span class="tut-nav">
            <button type="button" class="btn tut-back">Back</button>
            <button type="button" class="btn primary tut-next">Next</button>
          </span>
        </div>
      </div>`;
    document.body.appendChild(root);
    spot = root.querySelector(".tut-spot");
    card = root.querySelector(".tut-card");
    root.querySelector(".tut-skip").addEventListener("click", () => close(true));
    root.querySelector(".tut-back").addEventListener("click", () => go(i - 1));
    root.querySelector(".tut-next").addEventListener("click", () => (i === STEPS.length - 1 ? close(true) : go(i + 1)));
    root.querySelector(".tut-do").addEventListener("click", doStep);
    card.addEventListener("keydown", onKey);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, { passive: true });
  }

  function onKey(ev) {
    if (ev.key === "Escape") close(true);
    else if (ev.key === "ArrowRight" && ev.target.tagName !== "INPUT") root.querySelector(".tut-next").click();
    else if (ev.key === "ArrowLeft" && i > 0) go(i - 1);
  }

  const target = () => (STEPS[i].target ? document.querySelector(STEPS[i].target) : null);

  function place() {
    if (!root || root.hidden) return;
    const el = target();
    const pad = 8, gap = 16, vw = window.innerWidth, vh = window.innerHeight;
    if (!el || !el.offsetParent) {
      spot.classList.add("none");
      card.classList.add("center");
      card.classList.remove("dock");
      card.style.left = card.style.top = "";
      return;
    }
    spot.classList.remove("none");
    card.classList.remove("center");
    const r = el.getBoundingClientRect();
    const top = Math.max(r.top - pad, 4), bottom = Math.min(r.bottom + pad, vh - 4);
    Object.assign(spot.style, { left: `${r.left - pad}px`, top: `${top}px`, width: `${r.width + pad * 2}px`, height: `${Math.max(bottom - top, 24)}px` });
    if (vw < 760) { card.style.left = card.style.top = ""; card.classList.add("dock"); return; }
    card.classList.remove("dock");
    const cw = card.offsetWidth, ch = card.offsetHeight;
    let left, topPos;
    if (r.right + gap + cw < vw - 8) { left = r.right + gap; topPos = r.top; }
    else if (r.left - gap - cw > 8) { left = r.left - gap - cw; topPos = r.top; }
    else { left = r.left + (r.width - cw) / 2; topPos = r.bottom + gap < vh - ch ? r.bottom + gap : Math.max(r.top - gap - ch, 72); }
    card.style.left = `${Math.min(Math.max(left, 8), vw - cw - 8)}px`;
    card.style.top = `${Math.min(Math.max(topPos, 72), vh - ch - 8)}px`;
  }

  function go(n) {
    i = Math.max(0, Math.min(STEPS.length - 1, n));
    const s = STEPS[i];
    if (s.view) view(s.view);
    if (s.phone) phone(s.phone);
    root.querySelectorAll(".tut-progress span").forEach((b, k) => b.className = k < i ? "done" : k === i ? "now" : "");
    root.querySelector(".tut-count").textContent = `Step ${i + 1} of ${STEPS.length}`;
    root.querySelector("#tut-title").textContent = s.title;
    root.querySelector("#tut-body").innerHTML = s.body; // fixed copy above, no user data
    const tryBox = root.querySelector(".tut-try");
    tryBox.hidden = !s.action;
    if (s.action) {
      const b = root.querySelector(".tut-do");
      b.disabled = false;
      b.classList.remove("ok");
      b.textContent = `▶ ${s.action}`;
      root.querySelector(".tut-result").textContent = "";
    }
    root.querySelector(".tut-back").hidden = i === 0;
    const next = root.querySelector(".tut-next");
    next.textContent = s.finish || (i === 0 ? "Start the tour" : "Next");
    next.classList.remove("nudge");
    const el = target();
    if (el) {
      const fits = el.getBoundingClientRect().height < window.innerHeight - 160;
      el.scrollIntoView({ behavior: "instant", block: fits ? "center" : "start" });
      if (!fits) window.scrollBy({ top: -84, behavior: "instant" });
    } else {
      window.scrollTo({ top: 0, behavior: "instant" });
    }
    place();
    requestAnimationFrame(place);
    card.classList.remove("in");
    void card.offsetWidth;
    card.classList.add("in");
    (s.action ? root.querySelector(".tut-do") : next).focus({ preventScroll: true });
  }

  async function doStep() {
    const s = STEPS[i], b = root.querySelector(".tut-do"), out = root.querySelector(".tut-result");
    const at = i;
    b.disabled = true;
    b.textContent = "Working…";
    out.textContent = "";
    try {
      const msg = await s.run();
      if (at !== i) return;
      b.textContent = "Done ✓";
      b.classList.add("ok");
      out.textContent = msg || "";
      root.querySelector(".tut-next").classList.add("nudge");
    } catch (err) {
      if (at !== i) return;
      b.disabled = false;
      b.textContent = `▶ Try again`;
      out.textContent = err.message || "That didn't work.";
    }
    place();
  }

  function open() {
    if (!root) build();
    lastFocus = document.activeElement;
    root.hidden = false;
    document.body.classList.add("tut-open");
    clearInterval(follow);
    follow = setInterval(place, 400); // keep up with live updates that change the layout
    go(0);
  }

  function close(markDone) {
    if (!root) return;
    root.hidden = true;
    clearInterval(follow);
    document.body.classList.remove("tut-open");
    if (markDone) { try { localStorage.setItem(DONE_KEY, "1"); } catch { /* storage blocked */ } }
    if (lastFocus && lastFocus.focus) lastFocus.focus({ preventScroll: true });
  }

  window.HalcyonTutorial = { open };
  document.getElementById("tutorial-btn")?.addEventListener("click", open);

  // First visit after signing in: start once the dashboard has assembled.
  let seen = false;
  try { seen = localStorage.getItem(DONE_KEY) === "1"; } catch { seen = true; }
  if (!seen) {
    const wait = setInterval(() => {
      if (document.querySelector("#scenarios .tile")) { clearInterval(wait); setTimeout(open, reduce ? 0 : 900); }
    }, 300);
    setTimeout(() => clearInterval(wait), 15000);
  }
})();
