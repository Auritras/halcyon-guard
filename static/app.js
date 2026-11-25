// Halcyon Guard dashboard. Talks only to the HTTP API and the SSE stream.
"use strict";

const $ = (id) => document.getElementById(id);
// The customer signs in on login.html; the session token is kept in browser storage.
const TOKEN_KEY = "halcyon.customerToken";
const tokenStore = {
  get() { try { return localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(TOKEN_KEY); } catch { return null; } },
  clear() { try { localStorage.removeItem(TOKEN_KEY); sessionStorage.removeItem(TOKEN_KEY); } catch { /* storage blocked */ } },
};
const LABEL = { ALLOW: "Allowed", PAUSE: "Paused", BLOCK: "Blocked" };
const RESULT = { pass: "Pass", warn: "Warning", fail: "Fail", skip: "Not checked" };
const EXPECT = { A: "ALLOW", B: "PAUSE", C: "BLOCK", D: "BLOCK", E: "BLOCK", F: "BLOCK", G: "BLOCK", H: "BLOCK", I: "BLOCK", J: "BLOCK", K: "PAUSE", L: "BLOCK" };
const EXPECT_TEXT = { A: "Allow", B: "Pause", C: "Block", D: "Allow, then block", E: "Block", F: "Block",
  G: "Block", H: "Allow, then block", I: "Block", J: "Block", K: "Pause, agent refused", L: "Block" };
let customerToken = tokenStore.get();
let state = null;
let sseOpen = false;
let brokenAt = null;
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// ---------- helpers ----------
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function inr(n) {
  if (n === null || n === undefined || isNaN(n)) return "₹?";
  return "₹" + Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 });
}
function when(ts) {
  return new Date(ts * 1000).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove("show"), 3800);
}
async function api(path, { method = "GET", body, customer = false } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (customer && customerToken) headers["X-Customer-Token"] = customerToken;
  const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (customer && res.status === 401) toLogin(); // session ended (signed out, or the server restarted)
  if (!res.ok) throw new Error((data && typeof data.detail === "string" && data.detail) || `Request failed (${res.status}).`);
  return data;
}
const post = (path, body, customer = false) => api(path, { method: "POST", body, customer });

// ---------- rendering ----------
function render() {
  if (!state) return;
  $("who").textContent = state.customer.name.split(" ")[0];
  $("who").title = `Signed in as ${state.customer.name}`;
  $("public-note").hidden = !state.public_demo;
  $("provider").value = state.provider;
  renderSummary();
  renderProviderHint();
  renderGrants();
  renderPending();
  renderBlocked();
  renderBill();
  renderTxns();
  renderAudit();
  $("run").disabled = state.agent_running;
  document.querySelectorAll("#scenarios .tile").forEach((b) => (b.disabled = state.scenario_running));
}

let shownBalance = null;
function countTo(el, target) {
  const from = shownBalance;
  shownBalance = target;
  if (from === null || from === target || reduceMotion) { el.textContent = inr(target); return; }
  const t0 = performance.now(), dur = 700;
  el.classList.add(target < from ? "down" : "up");
  const step = (t) => {
    const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
    el.textContent = inr(Math.round(from + (target - from) * e));
    if (k < 1 && shownBalance === target) requestAnimationFrame(step);
    else { el.textContent = inr(shownBalance); setTimeout(() => el.classList.remove("down", "up"), 400); }
  };
  requestAnimationFrame(step);
}

function renderSummary() {
  const reqs = state.requests;
  const n = { ALLOW: 0, PAUSE: 0, BLOCK: 0 };
  reqs.forEach((r) => { n[r.decision] = (n[r.decision] || 0) + 1; });
  const waiting = reqs.filter((r) => r.status === "pending").length;
  countTo($("balance"), state.balance);
  $("n-allow").textContent = n.ALLOW;
  $("n-pause").textContent = n.PAUSE;
  $("n-block").textContent = n.BLOCK;
  // The ring shows the number the sentence beside it is about: waiting, else blocked, else allowed.
  const ring = $("ring");
  const total = reqs.length || 1;
  const [count, colour] = waiting ? [waiting, "var(--accent)"] : n.BLOCK ? [n.BLOCK, "var(--block)"] : [n.ALLOW, "var(--allow)"];
  $("ring-n").textContent = reqs.length ? count : "–";
  ring.style.setProperty("--p", reqs.length ? Math.max(8, Math.round((count / total) * 100)) : 0);
  ring.style.setProperty("--c", colour);
  const bar = $("summary");
  bar.className = "summary " + (waiting ? "attn" : n.BLOCK ? "bad" : reqs.length ? "good" : "");
  const live = state.grants.some((g) => g.live);
  let text;
  if (!reqs.length) text = live ? "Permission active. Run the agent to see the gateway check each payment." : "No payments yet. Give the agent a permission in the customer app, then run it.";
  else if (waiting) text = `${waiting} payment${waiting > 1 ? "s" : ""} waiting for Asha. Approve or deny in the customer app.`;
  else if (n.BLOCK) text = `${n.BLOCK} payment${n.BLOCK > 1 ? "s" : ""} stopped before reaching the bank. Every decision is in the audit log.`;
  else text = "Every payment so far matched what Asha allowed.";
  $("summary-text").textContent = text;
}

function renderProviderHint() {
  const h = $("provider-hint");
  const dot = $("model-dot");
  h.classList.remove("warn");
  let ok = true;
  if (state.provider === "none") {
    h.textContent = "No AI model selected. Pick Groq or Ollama in the top bar, or use the scripted scenarios.";
    ok = false;
  } else if (state.provider === "groq" && !state.groq_key_set) {
    h.textContent = "No Groq key found. Add GROQ_API_KEY to .env and restart, or use the scripted scenarios.";
    ok = false;
  } else {
    h.textContent = `The agent runs on ${state.models[state.provider]}. It decides what to pay; the gateway decides what's allowed.`;
  }
  if (!ok) h.classList.add("warn");
  dot.className = "dot " + (ok ? "on" : "off");
}

function grantLine(g) {
  return `${esc(g.category[0].toUpperCase() + g.category.slice(1))} bills up to ${inr(g.max_amount)}`;
}
function renderGrants() {
  const el = $("grants");
  const shown = state.grants.filter((g) => g.status === "draft" || g.live);
  const ended = state.grants.length - shown.length;
  const endedNote = ended ? `<p class="empty">${ended} earlier permission${ended > 1 ? "s" : ""} revoked or expired.</p>` : "";
  if (!shown.length) { el.innerHTML = (state.grants.length ? '<p class="empty">No active permission. The agent can\'t pay anything.</p>' : '<p class="empty">No permissions yet. Describe one above.</p>') + endedNote; return; }
  el.innerHTML = shown.map((g) => {
    const draft = g.status === "draft";
    const pill = draft ? '<span class="pill pause">Draft</span>'
      : g.live ? '<span class="pill allow">Active</span>'
      : `<span class="pill">${g.status === "revoked" ? "Revoked" : "Expired"}</span>`;
    const until = new Date(g.valid_until * 1000).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
    const payees = g.payees.length ? g.payees.map(esc).join(", ") : "no named payees yet";
    const meta = draft ? `Payees: ${payees}. Not active until you confirm.` : `Payees: ${payees}.${g.live ? ` Until ${until}.` : ""}`;
    let actions = "";
    if (draft) actions = `<button class="btn small primary" data-confirm="${g.id}">Confirm</button><button class="btn small ghost" data-revoke="${g.id}">Discard</button>`;
    else if (g.live) actions = `<button class="btn small" data-revoke="${g.id}">Revoke</button>`;
    return `<div class="item ${draft ? "needs" : g.live ? "" : "off"}">
      <div class="top"><span class="title">#${g.id} · ${grantLine(g)}</span>${pill}</div>
      <p class="meta">${meta}</p>${actions ? `<div class="actions">${actions}</div>` : ""}</div>`;
  }).join("") + endedNote;
}

let lastPendingIds = null;
function renderPending() {
  const el = $("pending");
  const pend = state.requests.filter((r) => r.status === "pending");
  const badge = $("wait-badge");
  badge.textContent = pend.length;
  badge.hidden = !pend.length;
  const ids = pend.map((r) => r.id);
  if (lastPendingIds !== null && ids.some((id) => !lastPendingIds.includes(id))) {
    phoneTab("wait");
    badge.classList.remove("bump"); void badge.offsetWidth; badge.classList.add("bump");
  }
  lastPendingIds = ids;
  if (!pend.length) { el.innerHTML = '<p class="empty">Nothing needs your approval.</p>'; return; }
  el.innerHTML = pend.map((r) => `
    <div class="item needs">
      <div class="top"><span class="title">${inr(r.amount)} to ${esc(r.payee)}</span><span class="pill pause">Paused</span></div>
      <p class="meta">${esc(r.reason.replace(/^Paused for your approval: /, ""))}</p>
      <div class="actions"><button class="btn small primary" data-approve="${r.id}">Approve once</button><button class="btn small" data-deny="${r.id}">Deny</button></div>
    </div>`).join("");
}

function renderBlocked() {
  const el = $("blocked");
  const blocked = state.requests.filter((r) => r.decision === "BLOCK").slice(0, 3);
  if (!blocked.length) { el.innerHTML = '<p class="empty">Nothing blocked.</p>'; return; }
  el.innerHTML = blocked.map((r) => `
    <div class="item blocked">
      <div class="top"><span class="title">${r.amount === null ? "Invalid amount" : inr(r.amount)} to ${esc(r.payee)}</span><span class="meta">${when(r.ts)}</span></div>
      <p class="meta">${esc(r.reason.replace(/^Blocked: /, ""))}</p>
    </div>`).join("");
}

function renderBill() {
  $("poison").checked = state.poisoned;
  const bill = state.bills[0];
  if (!bill) { $("bill-text").textContent = "No bills."; return; }
  let html = esc(bill.text).replace(/(Note from Sunrise Power billing[^\n]*)/, "<mark>$1</mark>");
  if (bill.status === "paid") html += '\n<span class="pill allow paid">Paid</span>';
  $("bill-text").innerHTML = html;
}

function renderTxns() {
  const el = $("txns");
  if (!state.transactions.length) { el.innerHTML = '<li class="empty">No payments yet.</li>'; return; }
  el.innerHTML = state.transactions.map((t) => `<li><span>${esc(t.payee)} <span class="muted">${when(t.ts)}</span></span><strong>−${inr(t.amount)}</strong></li>`).join("");
}

function auditSummary(e) {
  const d = e.data;
  switch (e.kind) {
    case "gateway_decision": return `<span class="${esc(d.decision)}">${esc(LABEL[d.decision] || d.decision)}</span> ${inr(d.amount)} to ${esc(d.payee)}`;
    case "bank_executed": return `Bank paid ${inr(d.amount)} to ${esc(d.payee)}`;
    case "bank_refused": return `Bank refused: ${esc(d.reason)}`;
    case "grant_drafted": return `Permission #${d.grant_id} drafted`;
    case "grant_confirmed": return `Permission #${d.grant_id} confirmed`;
    case "grant_revoked": return `Permission #${d.grant_id} revoked`;
    case "customer_approved": return `Asha approved request #${d.request_id}`;
    case "customer_denied": return `Asha denied request #${d.request_id}`;
    case "approval_refused": return `Approval refused for #${d.request_id}`;
    case "agent_login": return `${esc(d.agent_id)} logged in`;
    case "agent_rejected": return "Agent tried a customer action";
    case "bill_poisoned": return "Bill edited by attacker";
    case "bill_restored": return "Bill restored";
    case "intent_unclear": return "Unclear request: asked a question";
    case "reset": return "Demo reset";
    default: return esc(e.kind.replace(/_/g, " "));
  }
}
let lastAuditSeq = null;
function renderAudit() {
  const newest = state.audit.length ? state.audit[0].seq : 0;
  const seen = lastAuditSeq;
  lastAuditSeq = newest;
  $("audit").innerHTML = state.audit.map((e) => {
    const cls = [];
    if (brokenAt !== null && e.seq >= brokenAt) cls.push("broken");
    if (seen !== null && e.seq > seen) cls.push("fresh");
    const i = brokenAt !== null ? Math.max(0, e.seq - brokenAt) : 0;
    return `<li class="${cls.join(" ")}" style="--i:${i}"><button data-audit="${e.seq}" title="Show details">
      <span class="seq">#${e.seq}</span><span>${auditSummary(e)}</span>
      <span class="hash">prev ${e.prev_hash.slice(0, 8)} · hash ${e.hash.slice(0, 8)}</span></button></li>`;
  }).join("");
}

function tile(k) {
  const cls = (EXPECT[k] || "").toLowerCase();
  return `<button class="tile" data-scenario="${k}">
      <span class="tile-top"><span class="letter">${k}</span><span class="pill ${cls}">${EXPECT_TEXT[k] || ""}</span></span>
      <span class="t">${esc(state.scenarios[k])}</span></button>`;
}
function renderScenarios() {
  const groups = state.scenario_groups || { Scenarios: Object.keys(state.scenarios) };
  $("scenarios").innerHTML = Object.entries(groups).map(([name, keys]) =>
    `<h3 class="group-title">${esc(name)}</h3><div class="tiles">${keys.map(tile).join("")}</div>`).join("");
}

// Play every scenario in turn: a hands-free tour for the video.
let tourRunning = false;
async function runAll() {
  if (tourRunning) { tourRunning = false; return; }
  const btn = $("run-all");
  const order = Object.values(state.scenario_groups || {}).flat();
  tourRunning = true;
  btn.textContent = "Stop the tour";
  try {
    for (const k of order) {
      if (!tourRunning) break;
      document.querySelectorAll(".tile").forEach((t) => t.classList.toggle("playing", t.dataset.scenario === k));
      $("tour-status").textContent = `Playing ${k}: ${state.scenarios[k]}`;
      await runAgentCall(`/api/agent/scenario/${k}`, null, true);
      await new Promise((r) => setTimeout(r, 250));
      await animQueue;
      await sleep(1200);
    }
  } finally {
    tourRunning = false;
    btn.textContent = "Run all scenarios";
    $("tour-status").textContent = "";
    document.querySelectorAll(".tile.playing").forEach((t) => t.classList.remove("playing"));
  }
}

// ---------- gateway animation ----------
// Decisions play one after another, so a two-payment run (e.g. scenario D) shows both.
let animToken = 0;
let animQueue = Promise.resolve();
const sleep = (ms) => new Promise((r) => setTimeout(r, reduceMotion ? 0 : ms));
function showDecision(d) {
  const my = animToken;
  animQueue = animQueue.then(() => playDecision(d, my)).then(() => sleep(900));
  return animQueue;
}
function clearDecisions() {
  animToken++;
  animQueue = Promise.resolve();
}
function setFlow(stage) {
  const f = $("flow");
  if (!f) return;
  f.className = "flow" + (stage ? " " + stage : "");
}
function resetGates() {
  document.querySelectorAll("#gates li").forEach((g) => {
    g.className = "";
    g.querySelector("p").textContent = g.dataset.default;
    g.querySelector(".res").textContent = "";
    g.querySelector(".res").className = "pill res";
  });
}
async function playDecision(d, my) {
  if (my !== animToken) return;
  const req = d.request || {};
  const amount = d.amount === null || d.amount === undefined ? esc(JSON.stringify(req.amount ?? null)) : inr(d.amount);
  $("request").innerHTML = `<strong>${amount}</strong> to ${esc(d.payee)}` + (req.purpose ? ` <span class="muted">for “${esc(req.purpose)}”</span>` : "");
  resetGates();
  $("verdict").innerHTML = "";
  setFlow("");
  void $("flow")?.offsetWidth; // restart the travel animation
  setFlow("to-guard");
  await sleep(550);
  const gates = [...document.querySelectorAll("#gates li")];
  for (const c of d.checks) {
    if (my !== animToken) return;
    const g = gates[c.n - 1];
    if (c.result !== "skip") { g.className = "checking"; await sleep(420); }
    else await sleep(120);
    if (my !== animToken) return;
    g.className = c.result;
    g.querySelector("p").textContent = c.detail;
    const pill = g.querySelector(".res");
    pill.className = `pill res ${c.result}`;
    pill.textContent = RESULT[c.result] || c.result;
  }
  await sleep(220);
  if (my !== animToken) return;
  setFlow({ ALLOW: "to-bank", PAUSE: "to-customer", BLOCK: "stopped" }[d.decision]);
  let extra = "";
  if (d.decision === "PAUSE") extra = '<p class="hint">Sent to the customer app. Only Asha can approve it.</p>';
  if (d.bank) extra += `<p class="hint">${d.bank.ok ? `The bank executed it. New balance ${inr(d.bank.balance)}.` : `The bank refused: ${esc(d.bank.reason)}`}</p>`;
  if (d.decision === "BLOCK") extra += '<button class="btn small danger" data-revoke-all>Revoke agent access</button>';
  $("verdict").innerHTML = `<span class="stamp ${d.decision} ${reduceMotion ? "" : "in"}">${LABEL[d.decision]}</span>
    <div class="verdict-text"><p>${esc(d.reason)}</p>${extra}</div>`;
}

// ---------- agent feed ----------
function feedItem(e) {
  const kinds = { login: "Login", tool: "Tool", decision: "", say: "Agent", thinking: "Agent", error: "Problem", setup: "Set-up", customer: "Customer", refused: "Refused" };
  const li = document.createElement("li");
  li.className = e.kind + (e.decision ? ` d-${e.decision}` : "");
  const tag = e.kind === "decision" ? LABEL[e.decision] : kinds[e.kind] || e.kind;
  let body = esc(e.text);
  if (e.kind === "decision") body = `Pay ${esc(e.text.replace(/^pay /, ""))}`;
  if (e.kind === "tool" && e.result) body += `<details><summary>Result</summary><pre>${esc(e.result)}</pre></details>`;
  li.innerHTML = `<span class="k">${esc(tag)}</span><span class="body">${body}</span>`;
  const feed = $("feed");
  feed.querySelector(".empty")?.remove();
  feed.appendChild(li);
  while (feed.children.length > 60) feed.removeChild(feed.firstChild);
  feed.scrollTop = feed.scrollHeight;
}
function handleAgentEvent(e) {
  feedItem(e);
  if (e.kind === "decision") showDecision(e);
  if (e.kind === "refused") {
    animQueue = animQueue.then(() => {
      const v = $("verdict").querySelector(".verdict-text");
      if (v) v.insertAdjacentHTML("beforeend", `<p class="refused-note">${esc(e.text)}</p>`);
    });
  }
}

// ---------- data ----------
let refreshTimer = null;
async function refresh() {
  try { state = await api("/api/state"); render(); } catch (err) { toast(`Can't load the dashboard: ${err.message}`); }
}
function scheduleRefresh() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(refresh, 120);
}
function connectEvents() {
  const es = new EventSource("/api/events");
  es.onopen = () => { sseOpen = true; };
  es.onerror = () => { sseOpen = false; };
  es.onmessage = (m) => {
    const e = JSON.parse(m.data);
    if (e.type === "state") scheduleRefresh();
    else if (e.type === "agent") handleAgentEvent(e);
  };
}
async function runAgentCall(path, body, customer = false) {
  $("feed").innerHTML = "";
  clearDecisions();
  try {
    const res = await post(path, body, customer);
    if (!sseOpen) res.events.forEach(handleAgentEvent); // fallback if live updates are down
  } catch (err) { toast(err.message); }
}
function toLogin(signedOut = false) {
  tokenStore.clear();
  location.replace(signedOut ? "/login.html?signedout=1" : "/login.html");
}
async function signOut() {
  // the dashboard folds away, the shield closes, then we land on the sign-in page
  document.body.classList.add("leaving-now");
  $("leaving").hidden = false;
  const done = new Promise((r) => setTimeout(r, reduceMotion ? 0 : 750));
  try { await post("/api/customer/logout", null, true); } catch { /* signing out anyway */ }
  await done;
  toLogin(true);
}

// ---------- actions ----------
document.addEventListener("click", async (ev) => {
  const b = ev.target.closest("button");
  if (!b) return;
  const d = b.dataset;
  try {
    if (d.confirm) { await post(`/api/grants/${d.confirm}/confirm`, null, true); $("intent-result").innerHTML = ""; toast("Permission confirmed. The agent can now act within it."); }
    else if (d.revoke) { await post(`/api/grants/${d.revoke}/revoke`, null, true); toast("Permission revoked."); }
    else if (d.approve) { const r = await post(`/api/requests/${d.approve}/approve`, null, true); toast(r.bank.ok ? `Approved once. Paid, new balance ${inr(r.bank.balance)}.` : `Approved, but the bank refused: ${r.bank.reason}`); }
    else if (d.deny) { await post(`/api/requests/${d.deny}/deny`, null, true); toast("Denied. Nothing was paid."); }
    else if ("revokeAll" in d) { const r = await post("/api/agent/revoke-access", null, true); toast(`Agent access revoked (${r.revoked} permission${r.revoked === 1 ? "" : "s"}).`); }
    else if (d.scenario) { await runAgentCall(`/api/agent/scenario/${d.scenario}`, null, true); }
    else if (d.audit) { showAuditEntry(Number(d.audit)); }
  } catch (err) { toast(err.message); }
});

function showAuditEntry(seq) {
  const e = state.audit.find((x) => x.seq === seq);
  if (!e) return;
  if (e.kind === "gateway_decision") {
    clearDecisions();
    showDecision({ ...e.data, request: {} });
    $("gateway-card").scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "nearest" });
    toast(`Replaying the checks recorded in entry #${seq}.`);
  } else {
    toast(`#${seq} ${e.kind.replace(/_/g, " ")}: ${JSON.stringify(e.data)}`);
  }
}

$("revoke-all").addEventListener("click", async () => {
  try { const r = await post("/api/agent/revoke-access", null, true); toast(`Agent access revoked (${r.revoked} permission${r.revoked === 1 ? "" : "s"}).`); }
  catch (err) { toast(err.message); }
});

$("intent-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const out = $("intent-result");
  out.innerHTML = '<p class="hint drafted">Drafting…</p>';
  try {
    const r = await post("/api/grants/draft", { text: $("intent").value }, true);
    if (r.status === "unclear") out.innerHTML = `<p class="question">${esc(r.question)}</p>`;
    else out.innerHTML = `<p class="hint drafted">Drafted permission #${r.grant.id}: ${grantLine(r.grant)}. Check it below, then confirm.</p>`;
  } catch (err) { out.innerHTML = ""; toast(err.message); }
});

$("task-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  runAgentCall("/api/agent/run", { task: $("task").value });
});

$("poison").addEventListener("change", async (ev) => {
  try { await post("/api/bills/poison", { on: ev.target.checked }, true); } catch (err) { toast(err.message); }
});

$("provider").addEventListener("change", async (ev) => {
  try { await post("/api/provider", { provider: ev.target.value }, true); } catch (err) { toast(err.message); }
});

$("reset").addEventListener("click", async () => {
  try { await post("/api/reset"); } catch (err) { toast(err.message); return; }
  clearDecisions();
  brokenAt = null;
  $("feed").innerHTML = '<li class="empty">Nothing yet. Run the agent or a scenario.</li>';
  phoneTab("perm");
  $("intent-result").innerHTML = "";
  $("chain").textContent = "";
  $("chain").className = "pill";
  $("request").innerHTML = '<span class="muted">Waiting for the agent\'s first payment request.</span>';
  $("verdict").innerHTML = "";
  resetGates();
  toast("Demo reset to the starting data.");
});

$("verify").addEventListener("click", async () => {
  try {
    const v = await api("/api/audit/verify");
    brokenAt = v.ok ? null : v.broken_at;
    $("chain").className = "pill " + (v.ok ? "ok" : "bad");
    $("chain").textContent = v.ok ? `Chain intact · ${v.count} entries` : `Chain broken at entry #${v.broken_at}`;
    renderAudit();
  } catch (err) { toast(err.message); }
});

$("tamper").addEventListener("click", async () => {
  // Edit the OLDEST blocked/paused decision shown, so every later entry visibly fails verification.
  const target = state.audit.filter((e) => e.kind === "gateway_decision" && e.data.decision !== "ALLOW").pop()
    || state.audit[state.audit.length - 1];
  if (!target) return;
  try {
    await post(`/api/audit/tamper/${target.seq}`);
    toast(`Entry #${target.seq} was edited to look approved. Now press Verify chain.`);
  } catch (err) { toast(err.message); }
});

// ---------- screens ----------
// One page, three screens. The gateway and activity cards are shared: each screen has slots they move into.
const VIEWS = {
  demo: { title: "Live demo", lede: "Give the agent a permission, let it work, and watch Halcyon Guard check every payment before Asha's bank carries it out.",
          slots: { "gateway-card": "slot-gateway-demo", "feed-card": "slot-feed-demo" } },
  scenarios: { title: "Scenarios", lede: "Twelve scripted cases: everyday payments, attacks, agent mistakes and an agent pushing its limits. No AI model needed.",
               slots: { "gateway-card": "slot-gateway-scen", "feed-card": "slot-feed-scen" } },
  audit: { title: "Audit log", lede: "Every request, check and decision is chained with hashes, so the record can be verified and any later edit is caught.",
           slots: { "gateway-card": "slot-gateway-audit" } },
};
let currentView = null;
function showView(name, { push = true } = {}) {
  if (!VIEWS[name]) name = "demo";
  const v = VIEWS[name];
  const changed = currentView !== name;
  currentView = name;
  document.querySelectorAll(".view").forEach((el) => (el.hidden = el.dataset.view !== name));
  document.querySelectorAll(".view-tab").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.view === name)));
  for (const [card, slot] of Object.entries(v.slots)) $(slot).appendChild($(card));
  if (!v.slots["feed-card"]) document.querySelector(".parking").appendChild($("feed-card"));
  $("view-title").textContent = v.title;
  $("view-lede").textContent = v.lede;
  if (changed) {
    const el = $(`view-${name}`);
    el.classList.remove("view-in");
    void el.offsetWidth;
    el.classList.add("view-in");
  }
  if (push && location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
}
document.querySelectorAll(".view-tab").forEach((t) => t.addEventListener("click", () => showView(t.dataset.view)));
window.addEventListener("hashchange", () => showView(location.hash.slice(1), { push: false }));

// Asha's phone has three tabs
function phoneTab(name) {
  document.querySelectorAll(".phone-tabs [data-ptab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.ptab === name)));
  ["perm", "wait", "hist"].forEach((k) => ($(`pane-${k}`).hidden = k !== name));
}
document.querySelectorAll(".phone-tabs [data-ptab]").forEach((b) => b.addEventListener("click", () => phoneTab(b.dataset.ptab)));
$("ring").addEventListener("click", () => { showView("demo"); phoneTab("wait"); $("customer").scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "nearest" }); });

// ---------- start ----------
async function start() {
  document.querySelectorAll("#gates li").forEach((g) => (g.dataset.default = g.querySelector("p").textContent));
  if (!customerToken) { toLogin(); return; }
  try {
    const me = await fetch("/api/customer/me", { headers: { "X-Customer-Token": customerToken } });
    if (me.status === 401) { toLogin(); return; }
  } catch { /* server unreachable: refresh() below reports it */ }
  $("signout").addEventListener("click", signOut);
  $("run-all").addEventListener("click", runAll);
  showView(location.hash.slice(1) || "demo", { push: false });
  await refresh();
  if (state) renderScenarios();
  // the dashboard assembles itself once, after sign-in
  const arrive = () => document.body.classList.remove("entering");
  requestAnimationFrame(arrive);
  setTimeout(arrive, 60); // fallback: never leave the page hidden
  connectEvents();
}
start();
