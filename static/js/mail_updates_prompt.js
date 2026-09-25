/**
 * Lightweight, PJAX-safe legacy-player opt-in prompt.
 * Consent itself lives in the central Mail Hub; localStorage only remembers
 * "later" so we do not nag the player on every page.
 */
(function () {
  "use strict";

  const GC = window.GC = window.GC || {};
  const DISMISS_KEY = "gc_mail_updates_prompt_dismissed_at";
  const DISMISS_MS = 14 * 24 * 60 * 60 * 1000;

  function tr(key, fallback) {
    const value = window.GC_LOCALE && window.GC_LOCALE[key];
    return value && value !== key ? String(value) : fallback;
  }

  function dismissedRecently() {
    try {
      const ts = Number(localStorage.getItem(DISMISS_KEY) || 0);
      return ts > 0 && Date.now() - ts < DISMISS_MS;
    } catch (_) {
      return false;
    }
  }

  function rememberDismissal() {
    try {
      localStorage.setItem(DISMISS_KEY, String(Date.now()));
    } catch (_) {}
  }

  async function requestJson(url, options) {
    if (typeof GC.fetchGameAction === "function") {
      return GC.fetchGameAction(url, options || {});
    }
    const response = await fetch(url, {
      credentials: "same-origin",
      ...(options || {}),
    });
    return response.json();
  }

  function hidePrompt(prompt, remember) {
    if (!prompt) return;
    prompt.hidden = true;
    if (remember) rememberDismissal();
  }

  async function initMailUpdatesPrompt() {
    const prompt = document.getElementById("gc-mail-updates-prompt");
    if (!prompt || prompt.dataset.gcBound === "1") return;
    prompt.dataset.gcBound = "1";

    // Options already contains the full controls; do not show a duplicate prompt.
    if (document.getElementById("options-mail-updates") || dismissedRecently()) return;

    const statusEl = prompt.querySelector("[data-mail-updates-status]");
    const enableBtn = prompt.querySelector("[data-mail-updates-enable]");
    const dismissBtns = prompt.querySelectorAll("[data-mail-updates-dismiss]");

    dismissBtns.forEach((btn) => {
      btn.addEventListener("click", () => hidePrompt(prompt, true));
    });

    let state;
    try {
      const res = await requestJson("/api/options/mail-updates/status", {
        method: "GET",
        headers: { Accept: "application/json" },
      });
      if (!res || res.ok !== true) return;
      state = res.data || {};
    } catch (_) {
      return;
    }

    if (!state.configured || !state.eligible || state.status === "confirmed") return;

    prompt.hidden = false;
    if (state.status === "pending") {
      if (statusEl) statusEl.textContent = tr("options_mail_updates_pending", "Bestätigung ausstehend");
      if (enableBtn) enableBtn.textContent = tr("options_mail_updates_resend", "Bestätigung erneut senden");
    }

    if (enableBtn) {
      enableBtn.addEventListener("click", async () => {
        if (enableBtn.disabled) return;
        enableBtn.disabled = true;
        if (statusEl) statusEl.textContent = tr("options_mail_updates_loading", "Wird gesendet …");
        try {
          const res = await requestJson("/api/options/mail-updates/enable", {
            method: "POST",
            headers: { "Content-Type": "application/json", Accept: "application/json" },
            body: "{}",
          });
          if (!res || res.ok !== true) {
            if (statusEl) statusEl.textContent =
              (res && res.error === "options_mail_updates_verify_first")
                ? "Bitte bestätige zuerst deine Account-E-Mail."
                : "Gerade nicht verfügbar. Versuch es später erneut.";
            return;
          }
          if (statusEl) statusEl.textContent = tr("options_mail_updates_confirmation_sent", "Bestätigungs-E-Mail wurde gesendet.");
          if (typeof GC.showNotify === "function") {
            GC.showNotify(tr("options_mail_updates_confirmation_sent", "Bestätigungs-E-Mail wurde gesendet."), "success");
          }
          window.setTimeout(() => hidePrompt(prompt, false), 2600);
        } catch (_) {
          if (statusEl) statusEl.textContent = tr("options_mail_updates_unavailable", "E-Mail-Updates sind gerade nicht verfügbar.");
        } finally {
          enableBtn.disabled = false;
        }
      });
    }

    if (typeof GC.registerCleanup === "function") {
      GC.registerCleanup(() => {
        delete prompt.dataset.gcBound;
      });
    }
  }

  GC.initMailUpdatesPrompt = initMailUpdatesPrompt;
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initMailUpdatesPrompt, { once: true });
  } else {
    initMailUpdatesPrompt();
  }
})();
