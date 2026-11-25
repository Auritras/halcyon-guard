// Halcyon Guard dashboard. Talks only to the HTTP API and the SSE stream.
"use strict";

const $ = (id) => document.getElementById(id);
const PIN = "1234"; // fictional demo customer
let customerToken = null;
let state = null;
let sseOpen = false;
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// ---------- helpers ----------
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function inr(n) {
  if (n === null || n === undefined || isNaN(n)) return "₹?";
  return "₹" + Number(n).toLocaleString("en-IN", { maximumFractionDigits: 2 });
}
function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove("show"), 3500);
}
async function api(path, { method = "GET", body, customer = false } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (customer && customerToken) headers["X-Customer-Token"] = customerToken;
  const res = await fetch(path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    const msg = (data && (typeof data.detail === "string" ? data.detail : "Request was rejected.")) || `Error ${res.status}`;
    throw new Error(msg);
  }
  return data;
}
const post = (path, body, customer = false) => api(path, { method: "POST", body, customer });
function when(ts) {
  return new Date(ts * 1000).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

// ---------- rendering ----------
function render() {
  if (!state) return;
  $("who").textContent = `Signed in as ${state.customer.name}`;
  $("balance").textContent = inr(state.balance);
  $("provider").value = state.provider;
  renderProviderHint();
  renderGrants();
  renderPending();
  renderBlocked();
  renderBill();
  renderTxns();
  renderAudit();
  $("run").disabled = state.agent_running;
  document.querySelectorAll("#scenarios button").forEach((b) => (b.disabled = state.agent_running));
}

function renderProviderHint() {
  const h = $("provider-hint");
  h.classList.remove("warn");
  if (state.provider === "none") {
    h.textContent = "No AI model selected. Pick Groq or Ollama above, or use the scripted scenarios.";
    h.classList.add("warn");
  } else if (state.provider === "groq" && !state.groq_key_set) {
    h.textContent = "No Groq key found. Add GROQ_API_KEY to .env and restart, or use the scripted scenarios.";
    h.classList.add("warn");
  } else {
    h.textContent = `Agent model: ${state.models[state.provider]}`;
  }
}

function grantLine(g) {
  return `${esc(g.category)} bills up to <strong>${inr(g.max_amount)}</strong>`;
}
function renderGrants() {
  const el = $("grants");
  const shown = state.grants.filter((g) => g.status !== "revoked").concat(state.grants.filter((g) => g.status === "revoked").slice(0, 2));
  if (!shown.length) { el.innerHTML = '<p class="empty">No permissions yet. Describe one above.</p>'; return; }
  el.innerHTML = shown.map((g) => {
    const cls = g.status === "draft" ? "draft" : g.live ? "active" : "off";
    const label = g.status === "draft" ? "Draft: not active until you confirm"
      : g.live ? `Active until ${new Date(g.valid_until * 1000).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}`
      : g.status === "revoked" ? "Revoked" : "Expired";
    const payees = g.payees.length ? `Payees: ${g.payees.map(esc).join(", ")}` : "No named payees yet";
    let actions = "";
    if (g.status === "draft") actions = `<button class="small" data-confirm="${g.id}">Confirm</button><button class="small ghost" data-revoke="${g.id}">Discard</button>`;
    else if (g.live) actions = `<button class="small ghost" data-revoke="${g.id}">Revoke</button>`;
    return `<div class="item ${cls}"><p>#${g.id} · ${grantLine(g)}</p><p class="meta">${payees}. ${label}.</p>${actions ? `<div class="row">${actions}</div>` : ""}</div>`;
  }).join("");
}

function renderPending() {
  const el = $("pending");
  const pend = state.requests.filter((r) => r.status === "pending");
  if (!pend.length) { el.innerHTML = '<p class="empty">Nothing needs your approval.</p>'; return; }
  el.innerHTML = pend.map((r) => `
    <div class="item pending">
      <p><strong>${inr(r.amount)}</strong> to ${esc(r.payee)}</p>
      <p class="meta">${esc(r.reason.replace(/^Paused for your approval: /, ""))}</p>
      <div class="row"><button class="small" data-approve="${r.id}">Approve once</button><button class="small ghost" data-deny="${r.id}">Deny</button></div>
    </div>`).join("");
}

function renderBlocked() {
  const el = $("blocked");
  const blocked = state.requests.filter((r) => r.decision === "BLOCK").slice(0, 3);
  if (!blocked.length) { el.innerHTML = '<p class="empty">Nothing blocked.</p>'; return; }
  el.innerHTML = blocked.map((r) => `
    <div class="item blocked">
      <p><strong>${r.amount === null ? "Invalid amount" : inr(r.amount)}</strong> to ${esc(r.payee)} <span class="meta">at ${when(r.ts)}</span></p>
      <p class="meta">${esc(r.reason.replace(/^Blocked: /, ""))}</p>
    </div>`).join("");
}

function renderBill() {
  $("poison").checked = state.poisoned;
  const bill = state.bills[0];
  if (!bill) { $("bill-text").textContent = "No bills."; return; }
  const status = bill.status === "paid" ? "\n\n(Paid)" : "";
  let html = esc(bill.text + status);
  html = html.replace(/(IMPORTANT SYSTEM NOTICE[^\n]*)/, "<mark>$1</mark>");
  $("bill-text").innerHTML = html;
}

function renderTxns() {
  const el = $("txns");
  if (!state.transactions.length) { el.innerHTML = '<li class="muted">No payments yet.</li>'; return; }
  el.innerHTML = state.transactions.map((t) => `<li><span>${esc(t.payee)} <span class="muted">${when(t.ts)}</span></span><strong>−${inr(t.amount)}</strong></li>`).join("");
}

let brokenAt = null;
function auditSummary(e) {
  const d = e.data;
  switch (e.kind) {
    case "gateway_decision": return `<span class="${esc(d.decision)}">${esc(d.decision)}</span> ${inr(d.amount)} → ${esc(d.payee)}`;
    case "bank_executed": return `Bank paid ${inr(d.amount)} to ${esc(d.payee)}`;
    case "bank_refused": return `Bank refused: ${esc(d.reason)}`;
    case "grant_drafted": return `Permission #${d.grant_id} drafted`;
    case "grant_confirmed": return `Permission #${d.grant_id} confirmed`;
    case "grant_revoked": return `Permission #${d.grant_id} revoked`;
    case "customer_approved": return `Customer approved #${d.request_id}`;
    case "customer_denied": return `Customer denied #${d.request_id}`;
    case "agent_login": return `${esc(d.agent_id)} logged in`;
    case "agent_rejected": return `Agent tried a customer action`;
    case "bill_poisoned": return `Bill edited by attacker`;
    case "reset": return `Demo reset`;
    default: return esc(e.kind.replace(/_/g, " "));
  }
}
function renderAudit() {
  $("audit").innerHTML = state.audit.map((e) => {
    const broken = brokenAt !== null && e.seq >= brokenAt ? " broken" : "";
    return `<li class="${broken}"><button data-audit="${e.seq}" title="Show details">
      <span class="seq">#${e.seq}</span><span>${auditSummary(e)}</span>
      <span class="hash">prev ${e.prev_hash.slice(0, 8)} · hash ${e.hash.slice(0, 8)}</span></button></li>`;
  }).join("");
}

// ---------- gateway animation ----------
let animToken = 0;
async function showDecision(d) {
  const my = ++animToken;
  const req = d.request || {};
  const amount = d.amount === null || d.amount === undefined ? esc(JSON.stringify(req.amount ?? null)) : inr(d.amount);
  $("request").innerHTML = `<strong>${amount}</strong> to ${esc(d.payee)}` + (req.purpose ? ` <span class="muted">for “${esc(req.purpose)}”</span>` : "");
  const gates = [...document.querySelectorAll("#gates li")];
  gates.forEach((g) => { g.className = ""; g.querySelector("span").textContent = g.dataset.default; });
  $("verdict").innerHTML = "";
  for (const c of d.checks) {
    if (!reduceMotion) await new Promise((r) => setTimeout(r, 280));
    if (my !== animToken) return;
    const g = gates[c.n - 1];
    g.className = c.result;
    g.querySelector("span").textContent = c.detail;
  }
  if (!reduceMotion) await new Promise((r) => setTimeout(r, 200));
  if (my !== animToken) return;
  const label = { ALLOW: "Allowed", PAUSE: "Paused", BLOCK: "Blocked" }[d.decision];
  let extra = "";
  if (d.decision === "BLOCK") extra = `<div class="row"><button class="small danger" data-revoke-all>Revoke agent access</button></div>`;
  if (d.decision === "PAUSE") extra = `<p class="muted">Sent to the customer app for approval.</p>`;
  if (d.bank) extra += `<p class="muted">${d.bank.ok ? `Bank executed it. New balance ${inr(d.bank.balance)}.` : `Bank refused: ${esc(d.bank.reason)}`}</p>`;
  $("verdict").innerHTML = `<span class="stamp ${d.decision} ${reduceMotion ? "" : "in"}">${label}</span><p>${esc(d.reason)}</p>${extra}`;
}

// ---------- agent feed ----------
function feedItem(e) {
  const li = document.createElement("li");
  const kinds = { login: "Login", tool: "Tool", decision: "Gateway", say: "Agent", thinking: "Agent", error: "Problem", setup: "Set-up", customer: "Customer" };
  li.className = e.kind + (e.decision ? ` d-${e.decision}` : "");
  let html = `<span class="k">${kinds[e.kind] || esc(e.kind)}</span>`;
  if (e.kind === "decision") html += `${esc(e.decision)}: ${esc(e.text)}`;
  else html += esc(e.text);
  if (e.kind === "tool" && e.result) html += `<details><summary>Result</summary><pre>${esc(e.result)}</pre></details>`;
  li.innerHTML = html;
  const feed = $("feed");
  feed.appendChild(li);
  while (feed.children.length > 60) feed.removeChild(feed.firstChild);
  feed.scrollTop = feed.scrollHeight;
}
function handleAgentEvent(e) {
  feedItem(e);
  if (e.kind === "decision") showDecision(e);
}

// ---------- data ----------
let refreshTimer = null;
async function refresh() {
  try { state = await api("/api/state"); render(); } catch (err) { toast(`Can't load state: ${err.message}`); }
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
async function runAgentCall(path, body) {
  $("feed").innerHTML = "";
  try {
    const res = await post(path, body);
    if (!sseOpen) res.events.forEach(handleAgentEvent); // fallback if live updates are down
  } catch (err) { toast(err.message); }
}

// ---------- actions ----------
document.addEventListener("click", async (ev) => {
  const b = ev.target.closest("button");
  if (!b) return;
  const d = b.dataset;
  try {
    if (d.confirm) { await post(`/api/grants/${d.confirm}/confirm`, null, true); toast("Permission confirmed. The agent can now act within it."); }
    else if (d.revoke) { await post(`/api/grants/${d.revoke}/revoke`, null, true); toast("Permission revoked."); }
    else if (d.approve) { const r = await post(`/api/requests/${d.approve}/approve`, null, true); toast(r.bank.ok ? `Approved once. Paid, new balance ${inr(r.bank.balance)}.` : `Approved, but the bank refused: ${r.bank.reason}`); }
    else if (d.deny) { await post(`/api/requests/${d.deny}/deny`, null, true); toast("Denied. Nothing was paid."); }
    else if ("revokeAll" in d) { const r = await post("/api/agent/revoke-access", null, true); toast(`Agent access revoked (${r.revoked} permission(s)).`); }
    else if (d.scenario) { await runAgentCall(`/api/agent/scenario/${d.scenario}`); }
    else if (d.audit) { showAuditEntry(Number(d.audit)); }
  } catch (err) { toast(err.message); }
});

function showAuditEntry(seq) {
  const e = state.audit.find((x) => x.seq === seq);
  if (!e) return;
  if (e.kind === "gateway_decision") {
    showDecision({ ...e.data, request: {} });
    toast(`Replaying the checks recorded in entry #${seq}.`);
  } else {
    toast(`#${seq} ${e.kind.replace(/_/g, " ")}: ${JSON.stringify(e.data)}`);
  }
}

$("revoke-all").addEventListener("click", async () => {
  try { const r = await post("/api/agent/revoke-access", null, true); toast(`Agent access revoked (${r.revoked} permission(s)).`); }
  catch (err) { toast(err.message); }
});

$("intent-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const out = $("intent-result");
  out.textContent = "Drafting…";
  try {
    const r = await post("/api/grants/draft", { text: $("intent").value }, true);
    if (r.status === "unclear") out.innerHTML = `<p class="question">${esc(r.question)}</p>`;
    else out.innerHTML = `<p class="hint">Drafted permission #${r.grant.id}: ${grantLine(r.grant)}. Check it below, then confirm.</p>`;
  } catch (err) { out.textContent = ""; toast(err.message); }
});

$("task-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  runAgentCall("/api/agent/run", { task: $("task").value });
});

$("poison").addEventListener("change", async (ev) => {
  try { await post("/api/bills/poison", { on: ev.target.checked }); } catch (err) { toast(err.message); }
});

$("provider").addEventListener("change", async (ev) => {
  try { await post("/api/provider", { provider: ev.target.value }); } catch (err) { toast(err.message); }
});

$("reset").addEventListener("click", async () => {
  await post("/api/reset");
  brokenAt = null;
  $("feed").innerHTML = "";
  $("intent-result").innerHTML = "";
  $("chain").textContent = "";
  $("request").innerHTML = '<span class="muted">Waiting for the agent\'s first payment request.</span>';
  $("verdict").innerHTML = "";
  document.querySelectorAll("#gates li").forEach((g) => { g.className = ""; g.querySelector("span").textContent = g.dataset.default; });
  toast("Demo reset to the starting data.");
});

$("verify").addEventListener("click", async () => {
  const v = await api("/api/audit/verify");
  const c = $("chain");
  brokenAt = v.ok ? null : v.broken_at;
  c.className = "chain " + (v.ok ? "ok" : "bad");
  c.textContent = v.ok ? `✓ Chain intact (${v.count} entries)` : `✕ Chain broken at entry #${v.broken_at}`;
  renderAudit();
});

$("tamper").addEventListener("click", async () => {
  // Edit the OLDEST blocked/paused decision shown, so every later entry visibly fails verification.
  const target = state.audit.filter((e) => e.kind === "gateway_decision" && e.data.decision !== "ALLOW").pop()
    || state.audit[state.audit.length - 1];
  if (!target) return;
  await post(`/api/audit/tamper/${target.seq}`);
  toast(`Entry #${target.seq} was edited to look approved. Now press Verify chain.`);
});

// ---------- start ----------
async function start() {
  document.querySelectorAll("#gates li").forEach((g) => (g.dataset.default = g.querySelector("span").textContent));
  try { customerToken = (await post("/api/customer/login", { pin: PIN })).token; } catch (err) { toast(err.message); }
  await refresh();
  $("scenarios").innerHTML = Object.entries(state.scenarios).map(([k, v]) => `<button data-scenario="${k}"><b>${k}</b><span>${esc(v)}</span></button>`).join("");
  connectEvents();
}
start();
