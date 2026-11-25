// Sign-in page: customer ID + PIN -> session token -> dashboard.
"use strict";

const KEY = "halcyon.customerToken";
const store = {
  get() { try { return localStorage.getItem(KEY) || sessionStorage.getItem(KEY); } catch { return null; } },
  set(v) { try { localStorage.setItem(KEY, v); } catch { try { sessionStorage.setItem(KEY, v); } catch { /* storage blocked */ } } },
};
const $ = (id) => document.getElementById(id);

function showError(msg) {
  const e = $("login-error");
  e.textContent = msg;
  e.hidden = !msg;
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
      $("pin").focus();
      return;
    }
    store.set(data.token);
    location.replace("/");
  } catch {
    showError("Can't reach the server. Check that it's running, then try again.");
  } finally {
    btn.disabled = false;
    btn.textContent = "Sign in";
  }
});

$("customer-id").focus();
