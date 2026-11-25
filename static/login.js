// Sign-in page: customer ID + PIN -> session token -> dashboard.
"use strict";

const KEY = "halcyon.customerToken";
const store = {
  get() { try { return localStorage.getItem(KEY) || sessionStorage.getItem(KEY); } catch { return null; } },
  set(v) { try { localStorage.setItem(KEY, v); } catch { try { sessionStorage.setItem(KEY, v); } catch { /* storage blocked */ } } },
};
const $ = (id) => document.getElementById(id);

const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const wait = (ms) => new Promise((r) => setTimeout(r, reduce ? 0 : ms));

function showError(msg) {
  const e = $("login-error");
  e.textContent = msg;
  e.hidden = !msg;
  if (msg) { // the card shakes, like a wrong PIN on a phone
    const card = document.querySelector(".login-card");
    card.classList.remove("shake"); void card.offsetWidth; card.classList.add("shake");
  }
}

// arriving: the sheet rises in; after signing out, say so
const arrive = () => document.body.classList.remove("arriving");
requestAnimationFrame(arrive);
setTimeout(arrive, 60); // fallback: never leave the page hidden
if (new URLSearchParams(location.search).get("signedout")) {
  $("signed-out").hidden = false;
  history.replaceState(null, "", "/login.html");
}

// Already signed in? Go straight to the dashboard.
(async () => {
  const tok = store.get();
  if (!tok) return;
  try {
    const r = await fetch("/api/customer/me", { headers: { "X-Customer-Token": tok } });
    if (r.ok) location.replace("/");
  } catch { /* stay here */ }
})();

$("use-demo").addEventListener("click", () => {
  $("customer-id").value = "asha";
  $("pin").value = "1234";
  showError("");
  $("signin").focus();
});

$("login-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const customer_id = $("customer-id").value.trim();
  const pin = $("pin").value;
  if (!customer_id || !pin) { showError("Enter your customer ID and PIN."); return; }
  const btn = $("signin");
  btn.disabled = true;
  btn.textContent = "Signing in…";
  try {
    const r = await fetch("/api/customer/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ customer_id, pin }),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      showError(typeof data.detail === "string" ? data.detail : "Sign-in failed. Try again.");
      $("pin").value = "";
      btn.disabled = false;
      btn.textContent = "Sign in";
      $("pin").focus();
      return;
    }
    store.set(data.token);
    // unlocked: the shield turns into a tick, then the page lifts away into the dashboard
    $("lock").classList.add("ok");
    btn.textContent = "Signed in";
    btn.classList.add("done");
    await wait(550);
    document.body.classList.add("departing");
    await wait(380);
    location.replace("/");
    return; // keep the "Signed in" state while the page changes
  } catch {
    showError("Can't reach the server. Check that it's running, then try again.");
  }
  btn.disabled = false;
  btn.textContent = "Sign in";
});

$("customer-id").focus();
