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
    if (typeof GC.initOptionsAccountSafety === "function") {
      GC.initOptionsAccountSafety();
    }
  }

  GC.handleOptionsFormSubmit = handleOptionsFormSubmit;
  GC.initOptionsPage = initOptionsPage;

  const SAFETY_ACTIONS = {
    vacation_enable: {
      url: "/api/options/vacation/enable",
      phraseKey: "vacation_enable",
      titleKey: "options_vacation_modal_title",
      leadKey: "options_vacation_modal_lead",
      needsPassword: false,
      reloadOnSuccess: false,
    },
    vacation_disable: {
      url: "/api/options/vacation/disable",
      phraseKey: "vacation_disable",
      titleKey: "options_vacation_disable_modal_title",
      leadKey: "options_vacation_disable_modal_lead",
      needsPassword: false,
      reloadOnSuccess: true,
    },
    deletion_request: {
      url: "/api/options/account-deletion/request",
      phraseKey: "account_delete",
      titleKey: "options_deletion_modal_title",
      leadKey: "options_deletion_modal_lead",
      needsPassword: false,
      reloadOnSuccess: true,
    },
    deletion_cancel: {
      url: "/api/options/account-deletion/cancel",
      phraseKey: null,
      titleKey: "options_deletion_cancel_modal_title",
      leadKey: "options_deletion_cancel_modal_lead",
      needsPassword: false,
      reloadOnSuccess: true,
      skipPhrase: true,
    },
    account_reset: {
      url: "/api/options/account-reset",
      phraseKey: "account_reset",
      titleKey: "options_reset_modal_title",
      leadKey: "options_reset_modal_lead",
      needsPassword: true,
      reloadOnSuccess: true,
    },
  };

  const CONFIRM_PHRASES = {
    vacation_enable: "ENABLE VACATION",
    vacation_disable: "DISABLE VACATION",
    account_delete: "DELETE ACCOUNT",
    account_reset: "RESET ACCOUNT",
  };

  function setSafetyHint(id, text, isError) {
    const hint = document.getElementById(id);
    if (!hint) return;
    hint.textContent = text || "";
    hint.hidden = !text;
    hint.classList.toggle("gc-options-hint-error", Boolean(isError));
    hint.classList.toggle("gc-options-hint-success", Boolean(text) && !isError);
  }

  function applySafetySnapshot(safety) {
    const page = document.getElementById("options-page");
    if (!page || !safety) return;
    page.setAttribute("data-vacation-active", safety.vacation_active ? "1" : "0");
    page.setAttribute("data-deletion-pending", safety.deletion_pending ? "1" : "0");
    page.setAttribute(
      "data-vacation-locked-until",
      safety.vacation_locked_until ? String(safety.vacation_locked_until) : ""
    );
    page.setAttribute(
      "data-deletion-due",
      safety.deletion_due_at ? String(safety.deletion_due_at) : ""
    );

    const vacStatus = document.getElementById("options-vacation-status");
    if (vacStatus) {
      vacStatus.textContent = safety.vacation_active
        ? t("options_vacation_status_active")
        : t("options_vacation_status_inactive");
    }
    const delStatus = document.getElementById("options-deletion-status");
    if (delStatus) {
      delStatus.textContent = safety.deletion_pending
        ? t("options_deletion_status_pending")
        : t("options_deletion_status_none");
    }
  }

  function bindOptionsAccountSafety() {
    const modal = document.getElementById("options-safety-modal");
    const form = document.getElementById("options-safety-modal-form");
    const titleEl = document.getElementById("options-safety-modal-title");
    const leadEl = document.getElementById("options-safety-modal-lead");
    const phraseLabel = document.getElementById("options-safety-modal-phrase-label");
    const confirmInput = document.getElementById("options-safety-modal-confirm");
    const pwdWrap = document.getElementById("options-safety-modal-password-wrap");
    const pwdInput = document.getElementById("options-safety-modal-password");
    const cancelBtn = document.getElementById("options-safety-modal-cancel");
    const submitBtn = document.getElementById("options-safety-modal-submit");
    if (!modal || modal.dataset.gcBound === "1") return;
    modal.dataset.gcBound = "1";

    let pendingAction = null;

    function closeModal() {
      pendingAction = null;
      modal.hidden = true;
      modal.close();
      if (confirmInput) confirmInput.value = "";
      if (pwdInput) pwdInput.value = "";
      if (pwdWrap) pwdWrap.hidden = true;
    }

    function openModal(actionKey) {
      const cfg = SAFETY_ACTIONS[actionKey];
      if (!cfg) return;
      pendingAction = actionKey;
      if (titleEl) titleEl.textContent = t(cfg.titleKey);
      if (leadEl) leadEl.textContent = t(cfg.leadKey);
      if (phraseLabel) {
        if (cfg.skipPhrase) {
          phraseLabel.textContent = "";
          phraseLabel.hidden = true;
        } else {
          phraseLabel.hidden = false;
          const phrase = CONFIRM_PHRASES[cfg.phraseKey] || "";
          phraseLabel.textContent = t("options_safety_phrase_label", "Tippe {phrase} zur Bestätigung").replace(
            "{phrase}",
            phrase
          );
        }
      }
      if (confirmInput) {
        confirmInput.hidden = Boolean(cfg.skipPhrase);
        confirmInput.value = "";
        confirmInput.placeholder = cfg.skipPhrase ? "" : CONFIRM_PHRASES[cfg.phraseKey] || "";
      }
      if (pwdWrap) pwdWrap.hidden = !cfg.needsPassword;
      modal.hidden = false;
      if (typeof modal.showModal === "function") modal.showModal();
      else modal.setAttribute("open", "");
      if (confirmInput && !cfg.skipPhrase) confirmInput.focus();
      else if (submitBtn) submitBtn.focus();
    }

    document.querySelectorAll(".gc-options-safety-btn[data-action]").forEach((btn) => {
      if (btn.dataset.gcSafetyBound === "1") return;
      btn.dataset.gcSafetyBound = "1";
      btn.addEventListener("click", () => {
        const action = btn.getAttribute("data-action");
        if (!action) return;
        openModal(action);
      });
    });

    if (cancelBtn) {
      cancelBtn.addEventListener("click", (ev) => {
        ev.preventDefault();
        closeModal();
      });
    }

    if (form) {
      form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        if (!pendingAction) return;
        const cfg = SAFETY_ACTIONS[pendingAction];
        if (!cfg) return;

        const payload = {};
        if (!cfg.skipPhrase) {
          payload.confirm_text = confirmInput ? String(confirmInput.value || "").trim() : "";
        }
        if (cfg.needsPassword) {
          const inlinePwd = document.getElementById("options-reset-password");
          payload.current_password = String(
            (pwdInput && pwdInput.value) || (inlinePwd && inlinePwd.value) || ""
          );
        }

        if (submitBtn) submitBtn.disabled = true;
        try {
          const data = await postOptionsJson(cfg.url, payload);
          const hintMap = {
            vacation_enable: "options-vacation-hint",
            vacation_disable: "options-vacation-hint",
            deletion_request: "options-deletion-hint",
            deletion_cancel: "options-deletion-hint",
            account_reset: "options-reset-hint",
          };
          const hintId = hintMap[pendingAction];
          if (!data || data.ok !== true) {
            if (hintId) setSafetyHint(hintId, msgKey(data && data.error), true);
            return;
          }
          if (data.data && data.data.account_safety) {
            applySafetySnapshot(data.data.account_safety);
          } else if (data.data && data.data.vacation_active !== undefined) {
            applySafetySnapshot(data.data);
          }
          if (hintId) setSafetyHint(hintId, msgKey(data.message || data.error), false);
          closeModal();
          if (cfg.reloadOnSuccess && typeof GC.reloadCurrentPage === "function") {
            GC.reloadCurrentPage("options_account_safety");
          } else if (typeof GC.refreshGameState === "function") {
            GC.refreshGameState("options_account_safety");
          }
        } catch (err) {
          if (err && err.name === "AuthError") return;
        } finally {
          if (submitBtn) submitBtn.disabled = false;
        }
      });
    }
  }

  GC.initOptionsAccountSafety = bindOptionsAccountSafety;
})();
