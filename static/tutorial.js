// Guided tutorial: dims the page, spotlights one part at a time and explains it.
// Opens on a visitor's first sign-in; the "Tutorial" button in the top bar replays it.
"use strict";

(function () {
  const DONE_KEY = "halcyon.tutorialDone";
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const tabs = (live) => { if (typeof selectTab === "function") selectTab(live); };

  const STEPS = [
    {
      title: "Welcome to Halcyon Guard",
      body: "Asha lets an AI agent pay her bills. Halcyon Guard sits between that agent and her bank and checks every payment against what she actually allowed. This tour takes about a minute.",
    },
    {
      target: "#intent-form",
      title: "1. Give the agent a permission",
      body: "Write what the agent may do in plain words, for example “Pay my electricity bill up to ₹5,000 this week”, then press <b>Draft permission</b>. Nothing is active until you press <b>Confirm</b> on the draft below.",
    },
    {
      target: ".agent",
      before: () => tabs(true),
      title: "2. Let the AI agent work",
      body: "<b>Run live agent</b> hands the task to a real AI model. It reads the bill and decides what to pay. It can make mistakes, and it can be tricked.",
    },
    {
      target: ".bill",
      before: () => tabs(true),
      title: "3. Play the attacker",
      body: "Tick <b>Attacker edits the bill</b> to slip a fake instruction into the bill, asking for a ₹25,000 “KYC deposit”. Then run the agent and see whether it falls for it.",
    },
    {
      target: ".gateway",
      title: "4. Watch the gateway decide",
      body: "Each payment travels from the agent to Halcyon Guard and through three checks: who is asking, whether it matches the permission, and whether the behaviour looks normal. It ends in <b>Allowed</b>, <b>Paused</b> or <b>Blocked</b>, with the reason in plain English.",
    },
    {
      target: "#customer",
      title: "5. Asha stays in control",
      body: "Paused payments wait under <b>Waiting for you</b>. Only Asha can approve them, never the agent. <b>Revoke agent access</b> stops the agent at once.",
    },
    {
      target: ".agent",
      before: () => tabs(false),
      title: "6. Try every case",
      body: "Twelve scripted scenarios show different attacks and mistakes, with no AI needed. Click one, or press <b>Run all scenarios</b> to watch them play one after another.",
    },
    {
      target: "#audit-log",
      title: "7. Check the audit log",
      body: "Every request, check and decision is chained with hashes. Press <b>Tamper with a decision</b> to edit an old entry, then <b>Verify chain</b> to see exactly where the record was broken.",
    },
    {
      title: "You're ready",
      body: "Start with step 1: confirm a permission, then run the agent. You can replay this tour any time from <b>Tutorial</b> in the top bar. All data here is fictional.",
      finish: "Start with step 1",
    },
  ];

  let i = 0;
  let root, spot, card, lastFocus;

  function build() {
    root = document.createElement("div");
    root.className = "tut";
    root.innerHTML = `
      <div class="tut-spot" aria-hidden="true"></div>
      <div class="tut-card" role="dialog" aria-modal="true" aria-labelledby="tut-title" aria-describedby="tut-body">
        <p class="tut-count"></p>
        <h2 id="tut-title"></h2>
        <p id="tut-body"></p>
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
    root.querySelector(".tut-next").addEventListener("click", () => (i === STEPS.length - 1 ? close(true, true) : go(i + 1)));
    root.addEventListener("keydown", onKey);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, { passive: true });
  }

  function onKey(ev) {
    if (ev.key === "Escape") close(true);
    else if (ev.key === "ArrowRight") root.querySelector(".tut-next").click();
    else if (ev.key === "ArrowLeft" && i > 0) go(i - 1);
    else if (ev.key === "Tab") { // keep focus inside the card
      const f = [...card.querySelectorAll("button")];
      const first = f[0], last = f[f.length - 1];
      if (ev.shiftKey && document.activeElement === first) { ev.preventDefault(); last.focus(); }
      else if (!ev.shiftKey && document.activeElement === last) { ev.preventDefault(); first.focus(); }
    }
  }

  function target() {
    const s = STEPS[i];
    return s.target ? document.querySelector(s.target) : null;
  }

  function place() {
    if (!root) return;
    const el = target();
    const pad = 8, gap = 14, vw = window.innerWidth, vh = window.innerHeight;
    if (!el) {
      spot.classList.add("none");
      card.classList.add("center");
      card.style.left = card.style.top = "";
      return;
    }
    spot.classList.remove("none");
    card.classList.remove("center");
    const r = el.getBoundingClientRect();
    const top = Math.max(r.top - pad, 4), bottom = Math.min(r.bottom + pad, vh - 4);
    Object.assign(spot.style, { left: `${r.left - pad}px`, top: `${top}px`, width: `${r.width + pad * 2}px`, height: `${Math.max(bottom - top, 24)}px` });
    if (vw < 700) { card.style.left = card.style.top = ""; card.classList.add("dock"); return; }
    card.classList.remove("dock");
    const cw = card.offsetWidth, ch = card.offsetHeight;
    let left, topPos;
    if (r.right + gap + cw < vw - 8) { left = r.right + gap; topPos = r.top; }          // beside, right
    else if (r.left - gap - cw > 8) { left = r.left - gap - cw; topPos = r.top; }       // beside, left
    else { left = r.left + (r.width - cw) / 2; topPos = r.bottom + gap < vh - ch ? r.bottom + gap : r.top - gap - ch; }
    left = Math.min(Math.max(left, 8), vw - cw - 8);
    topPos = Math.min(Math.max(topPos, 72), vh - ch - 8);
    card.style.left = `${left}px`;
    card.style.top = `${topPos}px`;
  }

  function go(n) {
    i = Math.max(0, Math.min(STEPS.length - 1, n));
    const s = STEPS[i];
    if (s.before) s.before();
    root.querySelector(".tut-count").textContent = `Step ${i + 1} of ${STEPS.length}`;
    root.querySelector("#tut-title").textContent = s.title;
    root.querySelector("#tut-body").innerHTML = s.body; // fixed copy above, no user data
    root.querySelector(".tut-back").hidden = i === 0;
    root.querySelector(".tut-next").textContent = s.finish || (i === 0 ? "Show me" : "Next");
    const el = target();
    if (el) {
      const r = el.getBoundingClientRect();
      const fits = r.height < window.innerHeight - 140;
      // jump straight there (no smooth scroll), so the spotlight is placed on the settled layout
      el.scrollIntoView({ behavior: "instant", block: fits ? "center" : "start" });
      if (!fits) window.scrollBy({ top: -80, behavior: "instant" }); // clear the sticky top bar
    } else {
      window.scrollTo({ top: 0, behavior: "instant" });
    }
    place();
    requestAnimationFrame(place);
    card.classList.remove("in");
    void card.offsetWidth;
    card.classList.add("in");
    root.querySelector(".tut-next").focus({ preventScroll: true });
  }

  function open() {
    if (!root) build();
    lastFocus = document.activeElement;
    root.hidden = false;
    document.body.classList.add("tut-open");
    go(0);
  }

  function close(markDone, startNow) {
    if (!root) return;
    root.hidden = true;
    document.body.classList.remove("tut-open");
    if (markDone) { try { localStorage.setItem(DONE_KEY, "1"); } catch { /* storage blocked */ } }
    if (startNow) {
      const intent = document.getElementById("intent");
      intent?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "center" });
      intent?.focus({ preventScroll: true });
    } else if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  window.HalcyonTutorial = { open };
  document.getElementById("tutorial-btn")?.addEventListener("click", open);

  // First visit after signing in: start the tour once the dashboard has loaded.
  let seen = false;
  try { seen = localStorage.getItem(DONE_KEY) === "1"; } catch { seen = true; }
  if (!seen) {
    const wait = setInterval(() => {
      if (document.querySelector("#scenarios .tile")) { clearInterval(wait); open(); }
    }, 300);
    setTimeout(() => clearInterval(wait), 15000);
  }
})();
