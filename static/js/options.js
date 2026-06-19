/**
 * Account options page – form handlers (PJAX-safe).
 * Submit is also wired from main.js capture (initOptionsFormsCapture) so saves work
 * even when initPage/PJAX timing skips bindOptionsForm.
 */
(function () {
  "use strict";

  const GC = window.GC = window.GC || {};

  const FORM_ROUTES = {
    "options-form-player-name": {
      url: "/api/options/player-name",
      payload(form) {
        return { player_name: fieldValue(form, "player_name") };
      },
      onSuccess(form, data, page, emptyLabel) {
        const name = data.player_name || "";
        const out = document.getElementById("options-current-player-name");
        if (out) out.textContent = name || emptyLabel;
        setFieldValue(form, "player_name", name);
        updateCommanderInChrome(name);
      },
    },
    "options-form-email": {
      url: "/api/options/email",
      payload(form) {
        return { email: fieldValue(form, "email") };
      },
      onSuccess(form, data, page) {
        const email = data.email || "";
        const out = document.getElementById("options-current-email");
        const emptyLabel = t("options_not_set");
        if (out) out.textContent = email || emptyLabel;
        setFieldValue(form, "email", email);
        if (page) page.setAttribute("data-email", email);
        updateEmailVerifyUi(Boolean(data.email_verified));
      },
    },
    "options-form-password": {
      url: "/api/options/password",
      payload(form) {
        return {
          current_password: fieldValue(form, "current_password"),
          new_password: fieldValue(form, "new_password"),
          confirm_password: fieldValue(form, "confirm_password"),
        };
      },
      onSuccess(form) {
        form.reset();
      },
    },
  };

  function t(key) {
    const loc = window.GC_LOCALE || {};
    return Object.prototype.hasOwnProperty.call(loc, key) ? loc[key] : key;
  }

  function msgKey(err) {
    if (!err) return t("options_saved");
    return t(err);
  }

  function setHint(form, text, isError) {
    const hint = form && form.querySelector(".gc-options-form-hint");
    if (!hint) return;
    hint.textContent = text || "";
    hint.hidden = !text;
    hint.classList.toggle("gc-options-hint-error", Boolean(isError));
    hint.classList.toggle("gc-options-hint-success", Boolean(text) && !isError);
  }

  function fieldValue(form, name) {
    if (!form) return "";
    const el = form.elements && form.elements[name];
    if (el) return String(el.value || "").trim();
    const input = form.querySelector(`[name="${name}"]`);
    return input ? String(input.value || "").trim() : "";
  }

  function setFieldValue(form, name, value) {
    if (!form) return;
    const el = form.elements && form.elements[name];
    if (el) el.value = value;
    else {
      const input = form.querySelector(`[name="${name}"]`);
      if (input) input.value = value;
    }
  }

  function updateCommanderInChrome(playerName) {
    const page = document.getElementById("options-page");
    const pid = page && page.getAttribute("data-player-id");
    const display = String(playerName || "").trim();
    if (!pid || !display) return;

    const idSel = CSS.escape(String(pid));
    document.querySelectorAll(`.gc-player-name[data-player-id="${idSel}"]`).forEach((el) => {
      el.textContent = display;
      el.setAttribute("data-player-name", display);
    });

    const hud = document.querySelector(".gc-hud-panel-user .gc-user-name");
    if (hud) {
      hud.textContent = display;
      hud.setAttribute("data-player-name", display);
    }

    if (page) page.setAttribute("data-player-name", display);

    if (typeof GC.refreshGameState === "function") {
      GC.refreshGameState("options_name_change");
    }
  }

  function updateEmailVerifyUi(verified) {
    const row = document.getElementById("options-email-verify-row");
    const page = document.getElementById("options-page");
    if (page) page.setAttribute("data-email-verified", verified ? "1" : "0");
    if (!row) return;

    if (verified) {
      row.dataset.verified = "1";
      row.innerHTML =
        `<span class="gc-options-verify-badge gc-options-verify-badge-ok" id="options-email-verify-badge">` +
        `<span class="gc-options-verify-icon" aria-hidden="true">✓</span>${t("options_email_verified")}</span>`;
      return;
    }

    row.dataset.verified = "0";
    row.innerHTML =
      `<span class="gc-options-verify-badge gc-options-verify-badge-warn" id="options-email-verify-badge">` +
      `<span class="gc-options-verify-icon" aria-hidden="true">⚠</span>${t("options_email_unverified")}</span>` +
      `<button type="button" class="gc-btn gc-btn-outline gc-btn-sm" id="options-resend-verify">${t("options_resend_verification")}</button>` +
      `<p class="gc-options-resend-hint" id="options-resend-hint" role="status" aria-live="polite" hidden></p>`;
    bindResendVerification();
  }

  function bindResendVerification() {
    const btn = document.getElementById("options-resend-verify");
    const hint = document.getElementById("options-resend-hint");
    if (!btn || btn.dataset.gcBound === "1") return;
    btn.dataset.gcBound = "1";

    btn.addEventListener("click", async () => {
      if (btn.disabled) return;
      btn.disabled = true;
      if (hint) {
        hint.hidden = true;
        hint.textContent = "";
        hint.classList.remove("gc-options-hint-error", "gc-options-hint-success");
      }
      try {
        const data = await postOptionsJson("/api/options/resend-verification", {});
        if (!data || data.ok !== true) {
          if (hint) {
            hint.textContent = msgKey(data && data.error);
            hint.hidden = false;
            hint.classList.add("gc-options-hint-error");
          }
          return;
        }
        if (hint) {
          hint.textContent = msgKey("account_email_verify_sent");
          hint.hidden = false;
          hint.classList.add("gc-options-hint-success");
        }
        if (typeof GC.showNotify === "function") {
          GC.showNotify(msgKey("account_email_verify_sent"), "success");
        }
      } catch (err) {
        if (err && err.name === "AuthError") return;
      } finally {
        btn.disabled = false;
      }
    });
  }

  function setFormBusy(form, busy) {
    if (!form) return;
    form.dataset.gcSubmitting = busy ? "1" : "0";
    form.querySelectorAll('button[type="submit"]').forEach((btn) => {
      btn.disabled = busy;
    });
  }

  async function postOptionsJson(url, payload) {
    if (typeof GC.fetchGameAction !== "function") {
      throw new Error("fetchGameAction missing");
    }
    return GC.fetchGameAction(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(payload || {}),
    });
  }

  async function handleOptionsFormSubmit(form, ev) {
    if (typeof GC.runOptionsFormSave === "function") {
      return GC.runOptionsFormSave(form, ev);
    }
    if (ev && typeof ev.preventDefault === "function") ev.preventDefault();
    return false;
  }

  function bindOptionsForm(form) {
    if (!form || !form.id || !FORM_ROUTES[form.id]) return;
    form._gcOptionsSubmit = (ev) => handleOptionsFormSubmit(form, ev);
  }

  function bindDiscordUnlink() {
    const btn = document.getElementById("options-discord-unlink-btn");
    const hint = document.getElementById("options-discord-hint");
    const block = document.getElementById("options-discord-block");
    const pwd = document.getElementById("options-discord-unlink-password");
    if (!btn || btn.dataset.gcBound === "1") return;
    btn.dataset.gcBound = "1";

    btn.addEventListener("click", async () => {
      if (btn.disabled) return;
      btn.disabled = true;
      if (hint) {
        hint.hidden = true;
        hint.textContent = "";
        hint.classList.remove("gc-options-hint-error", "gc-options-hint-success");
      }

      const payload = {};
      if (block && block.getAttribute("data-unlink-needs-password") === "1" && pwd) {
        payload.current_password = String(pwd.value || "");
      }

      try {
        const data = await postOptionsJson("/api/account/unlink-discord", payload);
        if (!data || data.ok !== true) {
          if (hint) {
            hint.textContent = msgKey(data && data.error);
            hint.hidden = false;
            hint.classList.add("gc-options-hint-error");
          }
          return;
        }
        if (typeof GC.reloadCurrentPage === "function") {
          GC.reloadCurrentPage("discord_unlink");
        } else if (typeof GC.navigateTo === "function") {
          GC.navigateTo("/options");
        } else {
          window.location.href = "/options";
        }
      } catch (err) {
        if (err && err.name === "AuthError") return;
        if (hint) {
          hint.textContent = msgKey("discord_unlink_failed");
          hint.hidden = false;
          hint.classList.add("gc-options-hint-error");
        }
      } finally {
        btn.disabled = false;
      }
    });
  }

  function initOptionsPage() {
    if (!document.getElementById("options-page")) return;

    document.querySelectorAll("form.gc-options-form").forEach((form) => {
      delete form.dataset.gcOptionsBound;
      delete form.dataset.gcSubmitting;
      bindOptionsForm(form);
      form.dataset.gcOptionsBound = "1";
    });

    bindResendVerification();
    bindDiscordUnlink();
  }

  GC.handleOptionsFormSubmit = handleOptionsFormSubmit;
  GC.initOptionsPage = initOptionsPage;
  GC.modules = GC.modules || {};
  GC.modules.options = initOptionsPage;
})();
