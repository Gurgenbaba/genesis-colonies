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

  function t(key, fallback) {
    if (typeof GC.t === "function") return GC.t(key, fallback);
    const loc = window.GC_LOCALE || {};
    if (Object.prototype.hasOwnProperty.call(loc, key)) return loc[key];
    return arguments.length > 1 ? String(fallback ?? "") : key;
  }

  function tf(key, vars, fallback) {
    if (typeof GC.tf === "function") return GC.tf(key, vars, fallback);
    let s = t(key, fallback || key);
    if (typeof s !== "string") return fallback || "";
    s = String(s);
    const v = vars && typeof vars === "object" ? vars : {};
    s = s.replace(/%\(([^)]+)\)s/g, (_, k) => (
      Object.prototype.hasOwnProperty.call(v, k) ? String(v[k] ?? "") : `%(${k})s`
    ));
    s = s.replace(/\{([^}]+)\}/g, (_, k) => (
      Object.prototype.hasOwnProperty.call(v, k) ? String(v[k] ?? "") : `{${k}}`
    ));
    return s;
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

  const SOUND_KIND_ATTR = {
    attack: "data-notify-attack-sound",
    message: "data-notify-message-sound",
    ui: "data-sfx-ui-sound",
    combat: "data-sfx-combat-sound",
  };
  const SOUND_KIND_PAYLOAD = {
    attack: "notify_attack_sound",
    message: "notify_message_sound",
    ui: "sfx_ui_sound",
    combat: "sfx_combat_sound",
  };

  function readNotifySoundVolume(page, kind) {
    if (!page) return 0.1;
    const attr = SOUND_KIND_ATTR[kind] || "data-notify-attack-sound";
    const raw = page.getAttribute(attr);
    if (typeof GC.normalizeSoundVolume === "function") {
      return GC.normalizeSoundVolume(raw, 0.1);
    }
    const n = Number(raw);
    if (!Number.isFinite(n)) return 0.1;
    if (n < 0) return 0;
    if (n > 1) return 1;
    return n;
  }

  function setNotifySoundSliderUi(kind, volume) {
    const scale =
      typeof GC.normalizeSoundVolume === "function"
        ? GC.normalizeSoundVolume(volume, 0.1)
        : Math.max(0, Math.min(1, Number(volume) || 0));
    const pct = Math.round(scale * 100);
    const input = document.querySelector(
      `#options-notify-sounds input[data-notify-sound="${kind}"]`
    );
    if (input) input.value = String(pct);
    const label = document.querySelector(`[data-notify-sound-pct="${kind}"]`);
    if (label) label.textContent = `${pct}%`;
  }

  function applySavedSoundSettings(page, saved) {
    if (!page || !saved || typeof saved !== "object") return;
    Object.keys(SOUND_KIND_PAYLOAD).forEach((kind) => {
      const key = SOUND_KIND_PAYLOAD[kind];
      if (saved[key] === undefined || saved[key] === null) return;
      const vol =
        typeof GC.normalizeSoundVolume === "function"
          ? GC.normalizeSoundVolume(saved[key], 0.1)
          : Number(saved[key]);
      page.setAttribute(SOUND_KIND_ATTR[kind], String(vol));
      setNotifySoundSliderUi(kind, vol);
    });
  }

  function bindNotifySoundSliders() {
    const block = document.getElementById("options-notify-sounds");
    const page = document.getElementById("options-page");
    const hint = document.getElementById("options-notify-hint");
    if (!block || !page || block.dataset.gcBound === "1") return;
    block.dataset.gcBound = "1";

    block.querySelectorAll("input[data-notify-sound]").forEach((input) => {
      if (input.dataset.gcBound === "1") return;
      input.dataset.gcBound = "1";

      input.addEventListener("input", () => {
        const kind = String(input.getAttribute("data-notify-sound") || "");
        const pct = Math.max(0, Math.min(100, parseInt(input.value, 10) || 0));
        const label = block.querySelector(`[data-notify-sound-pct="${kind}"]`);
        if (label) label.textContent = `${pct}%`;
      });

      input.addEventListener("change", async () => {
        const kind = String(input.getAttribute("data-notify-sound") || "");
        const payloadKey = SOUND_KIND_PAYLOAD[kind];
        if (!payloadKey) return;
        const pct = Math.max(0, Math.min(100, parseInt(input.value, 10) || 0));
        const volume = pct / 100;
        if (Math.abs(readNotifySoundVolume(page, kind) - volume) < 1e-9) {
          if (typeof GC.playSoundPreview === "function") {
            GC.playSoundPreview(kind);
          }
          return;
        }

        block.querySelectorAll("input[data-notify-sound]").forEach((el) => {
          el.disabled = true;
        });
        if (hint) {
          hint.hidden = true;
          hint.textContent = "";
          hint.classList.remove("gc-options-hint-error", "gc-options-hint-success");
        }

        const payload = { [payloadKey]: volume };

        try {
          const data = await postOptionsJson("/api/options/notify-sounds", payload);
          if (!data || data.ok !== true) {
            if (hint) {
              hint.textContent = msgKey(data && data.error);
              hint.hidden = false;
              hint.classList.add("gc-options-hint-error");
            }
            setNotifySoundSliderUi(kind, readNotifySoundVolume(page, kind));
            return;
          }
          const saved = data.data || {};
          applySavedSoundSettings(page, saved);
          if (typeof GC.applyNotifySoundSettings === "function") {
            GC.applyNotifySoundSettings(saved);
          }
          if (typeof GC.playSoundPreview === "function") {
            GC.playSoundPreview(kind);
          }
          if (hint) {
            hint.textContent = msgKey("options_saved");
            hint.hidden = false;
            hint.classList.add("gc-options-hint-success");
          }
        } catch (err) {
          if (err && err.name === "AuthError") return;
          setNotifySoundSliderUi(kind, readNotifySoundVolume(page, kind));
        } finally {
          block.querySelectorAll("input[data-notify-sound]").forEach((el) => {
            el.disabled = false;
          });
        }
      });
    });
  }

  function readSpyProbeCount(page) {
    if (!page) return 5;
    const raw = parseInt(page.getAttribute("data-default-spy-probes") || "5", 10);
    return Number.isFinite(raw) && raw > 0 ? raw : 5;
  }

  function setSpyProbeInputUi(count) {
    const n = Math.max(1, parseInt(count, 10) || 5);
    const input = document.querySelector("[data-spy-probes-input]");
    if (input) input.value = String(n);
  }

  async function saveSpyProbeCount(page, count, hint) {
    const block = document.getElementById("options-galaxy-settings");
    if (!page || !block) return;
    const saveBtn = block.querySelector("[data-spy-probes-save]");
    const input = block.querySelector("[data-spy-probes-input]");
    if (saveBtn) saveBtn.disabled = true;
    if (input) input.disabled = true;
    if (hint) {
      hint.hidden = true;
      hint.textContent = "";
      hint.classList.remove("gc-options-hint-error", "gc-options-hint-success");
    }
    try {
      const data = await postOptionsJson("/api/options/spy-probes", {
        default_spy_probes: count,
      });
      if (!data || data.ok !== true) {
        if (hint) {
          hint.textContent = msgKey(data && data.error);
          hint.hidden = false;
          hint.classList.add("gc-options-hint-error");
        }
        return;
      }
      const saved = data.data || {};
      const next = parseInt(saved.default_spy_probes, 10) || count;
      page.setAttribute("data-default-spy-probes", String(next));
      setSpyProbeInputUi(next);
      if (typeof GC.applySpyProbeSettings === "function") {
        GC.applySpyProbeSettings(saved);
      }
      if (hint) {
        hint.textContent = msgKey("options_saved");
        hint.hidden = false;
        hint.classList.add("gc-options-hint-success");
      }
    } catch (err) {
      if (err && err.name === "AuthError") return;
    } finally {
      if (saveBtn) saveBtn.disabled = false;
      if (input) input.disabled = false;
    }
  }

  function bindSpyProbeControls() {
    const block = document.getElementById("options-galaxy-settings");
    const page = document.getElementById("options-page");
    const hint = document.getElementById("options-spy-probes-hint");
    if (!block || !page || block.dataset.gcBound === "1") return;
    block.dataset.gcBound = "1";

    const saveBtn = block.querySelector("[data-spy-probes-save]");
    const input = block.querySelector("[data-spy-probes-input]");
    if (saveBtn && input && saveBtn.dataset.gcBound !== "1") {
      saveBtn.dataset.gcBound = "1";
      const submit = async () => {
        const count = parseInt(input.value || "0", 10);
        if (!Number.isFinite(count) || count < 1) {
          if (hint) {
            hint.textContent = msgKey("options_error_invalid_spy_probes");
            hint.hidden = false;
            hint.classList.add("gc-options-hint-error");
          }
          return;
        }
        if (readSpyProbeCount(page) === count) return;
        await saveSpyProbeCount(page, count, hint);
      };
      saveBtn.addEventListener("click", submit);
      input.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
          submit();
        }
      });
    }
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

  const OPTIONS_TAB_LS_KEY = "gc_options_active_tab";
  const OPTIONS_TABS = ["profile", "account", "notify", "galaxy", "vacation", "security"];

  function initOptionsTabs() {
    const module = document.querySelector(".gc-options-control-module");
    if (!module || module.dataset.gcTabsBound === "1") return;
    module.dataset.gcTabsBound = "1";

    const tabBtns = module.querySelectorAll("[data-options-tab-btn]");
    const panels = module.querySelectorAll("[data-options-tab-panel]");
    if (!tabBtns.length || !panels.length) return;

    function activateTab(name) {
      const tab = OPTIONS_TABS.includes(name) ? name : "profile";
      tabBtns.forEach((btn) => {
        const on = btn.getAttribute("data-options-tab-btn") === tab;
        btn.classList.toggle("is-active", on);
        btn.setAttribute("aria-selected", on ? "true" : "false");
      });
      panels.forEach((panel) => {
        const on = panel.getAttribute("data-options-tab-panel") === tab;
        panel.classList.toggle("is-active", on);
        panel.hidden = !on;
      });
      try {
        localStorage.setItem(OPTIONS_TAB_LS_KEY, tab);
      } catch (_err) {
        /* ignore storage errors */
      }
    }

    let initial = "profile";
    try {
      const saved = localStorage.getItem(OPTIONS_TAB_LS_KEY);
      if (saved && OPTIONS_TABS.includes(saved)) initial = saved;
    } catch (_err) {
      /* ignore storage errors */
    }
    activateTab(initial);

    tabBtns.forEach((btn) => {
      if (btn.dataset.gcTabBound === "1") return;
      btn.dataset.gcTabBound = "1";
      btn.addEventListener("click", () => {
        const tab = btn.getAttribute("data-options-tab-btn");
        if (tab) activateTab(tab);
      });
    });

    if (typeof GC.registerCleanup === "function") {
      GC.registerCleanup(() => {
        delete module.dataset.gcTabsBound;
        tabBtns.forEach((btn) => {
          delete btn.dataset.gcTabBound;
        });
      });
    }
  }

  function initOptionsPage() {
    if (!document.getElementById("options-page")) return;

    const page = document.getElementById("options-page");
    if (page) delete page.dataset.gcSafetyBound;

    initOptionsTabs();

    document.querySelectorAll("form.gc-options-form").forEach((form) => {
      delete form.dataset.gcOptionsBound;
      delete form.dataset.gcSubmitting;
      bindOptionsForm(form);
      form.dataset.gcOptionsBound = "1";
    });

    const notifyBlock = document.getElementById("options-notify-sounds");
    if (notifyBlock) {
      delete notifyBlock.dataset.gcBound;
      notifyBlock.querySelectorAll("input[data-notify-sound]").forEach((el) => {
        delete el.dataset.gcBound;
      });
    }

    bindNotifySoundSliders();
    const spyBlock = document.getElementById("options-galaxy-settings");
    if (spyBlock) {
      delete spyBlock.dataset.gcBound;
      const saveBtn = spyBlock.querySelector("[data-spy-probes-save]");
      if (saveBtn) delete saveBtn.dataset.gcBound;
    }
    bindSpyProbeControls();
    if (page) {
      setNotifySoundToggleUi("attack", readNotifySoundMode(page, "attack"));
      setNotifySoundToggleUi("message", readNotifySoundMode(page, "message"));
      setSpyProbeInputUi(readSpyProbeCount(page));
    }
    bindResendVerification();
    bindDiscordUnlink();
    const safetyFromPage = readOptionsSafetyFromPage(page);
    syncSafetyCountdownTimers(safetyFromPage);
    publishAccountSafetyToShell(safetyFromPage);
    syncVacationRepairVisibility();
    if (typeof GC.registerCleanup === "function") {
      GC.registerCleanup(() => {
        if (page) delete page.dataset.gcSafetyBound;
      });
    }
    if (typeof GC.initOptionsAccountSafety === "function") {
      GC.initOptionsAccountSafety();
    }
  }

  GC.handleOptionsFormSubmit = handleOptionsFormSubmit;
  GC.initOptionsPage = initOptionsPage;
  GC.syncSafetyCountdownTimers = syncSafetyCountdownTimers;

  GC.syncVacationRepairVisibility = syncVacationRepairVisibility;

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

  const BLOCKER_LINKS = {
    fleet_movements: { href: "/fleet", key: "options_blocker_fleet_movements" },
    auction_bids: { href: "/auction-house", key: "options_blocker_auction_bids" },
    build_queue: { href: "/buildings", key: "options_blocker_build_queue" },
    research_queue: { href: "/research", key: "options_blocker_research_queue" },
    shipyard_queue: { href: "/shipyard", key: "options_blocker_shipyard_queue" },
    defense_queue: { href: "/defense", key: "options_blocker_defense_queue" },
    planet_evolution_queue: { href: "/planet-evolution", key: "options_blocker_planet_evolution_queue" },
  };

  function blockerLabel(key, count) {
    const cfg = BLOCKER_LINKS[key];
    const template = cfg ? t(cfg.key) : key;
    return String(template || key).replace("{count}", String(count || 0));
  }

  function renderSafetyBlockers(details) {
    const wrap = document.getElementById("options-safety-blockers-wrap");
    const list = document.getElementById("options-safety-blockers");
    if (!wrap || !list) return;
    const src = details && typeof details === "object" ? details : {};
    const items = Object.keys(BLOCKER_LINKS)
      .map((key) => ({ key, count: Math.floor(Number(src[key] || 0)) }))
      .filter((row) => row.count > 0);
    list.replaceChildren();
    if (!items.length) {
      wrap.hidden = true;
      return;
    }
    wrap.hidden = false;
    items.forEach(({ key, count }) => {
      const cfg = BLOCKER_LINKS[key];
      const li = document.createElement("li");
      const a = document.createElement("a");
      a.href = cfg.href;
      a.setAttribute("data-pjax-link", "");
      a.textContent = blockerLabel(key, count);
      li.appendChild(a);
      list.appendChild(li);
    });
  }

  function formatSafetyBlockerError(data) {
    const details = (data && data.data && data.data.blocker_details) || (data && data.blocker_details);
    if (details) renderSafetyBlockers(details);
    const items = details && typeof details === "object"
      ? Object.keys(BLOCKER_LINKS)
          .map((key) => ({ key, count: Math.floor(Number(details[key] || 0)) }))
          .filter((row) => row.count > 0)
          .map(({ key, count }) => blockerLabel(key, count))
      : [];
    const base = msgKey(data && data.error);
    return items.length ? `${base} ${items.join(" · ")}` : base;
  }

  function safetyServerNowSec() {
    if (typeof GC.getServerNow === "function") return Math.floor(GC.getServerNow());
    if (typeof GC.serverNow === "function") return Math.floor(GC.serverNow());
    return Math.floor(Date.now() / 1000);
  }

  function safetyFormatRemain(seconds) {
    if (typeof GC.formatCountdownRemain === "function") return GC.formatCountdownRemain(seconds);
    const s = Math.max(0, Math.floor(Number(seconds) || 0));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const secR = s % 60;
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${secR}s`;
    return `${secR}s`;
  }

  function readOptionsSafetyFromPage(page) {
    const now = safetyServerNowSec();
    const lockedUntil = Math.floor(Number(page?.getAttribute("data-vacation-locked-until") || 0));
    const deletionDue = Math.floor(Number(page?.getAttribute("data-deletion-due") || 0));
    const vacationActive = page?.getAttribute("data-vacation-active") === "1";
    return {
      vacation_active: vacationActive,
      vacation_locked_until: lockedUntil || null,
      vacation_can_disable: !vacationActive || !lockedUntil || lockedUntil <= now,
      deletion_pending: page?.getAttribute("data-deletion-pending") === "1",
      deletion_due_at: deletionDue || null,
    };
  }

  function publishAccountSafetyToShell(safety) {
    if (!safety || typeof safety !== "object") return;
    if (typeof GC.mergeLastState === "function") {
      GC.mergeLastState({ account_safety: safety }, "options_account_safety");
      return;
    }
    if (GC.lastState && typeof GC.lastState === "object") {
      GC.lastState.account_safety = { ...(GC.lastState.account_safety || {}), ...safety };
    }
    if (typeof GC.syncHeaderVacationBanner === "function") {
      GC.syncHeaderVacationBanner(safety);
    }
    if (typeof GC.syncFleetVacationNotice === "function") {
      GC.syncFleetVacationNotice(safety);
    }
  }

  function syncSafetyCountdownTimers(safety) {
    const now = safetyServerNowSec();
    const vacTimer = document.getElementById("options-vacation-timer");
    if (vacTimer) {
      const until = Math.floor(Number(safety?.vacation_locked_until || vacTimer.getAttribute("data-until") || 0));
      const active = !!safety?.vacation_active;
      const canDisable = safety?.vacation_can_disable !== false;
      if (active && until > now && !canDisable) {
        vacTimer.hidden = false;
        vacTimer.setAttribute("data-until", String(until));
        vacTimer.textContent = tf(
          "options_vacation_timer",
          { time: safetyFormatRemain(until - now) },
          `Deaktivierung in ${safetyFormatRemain(until - now)}`
        );
      } else {
        vacTimer.hidden = true;
      }
    }
    const delTimer = document.getElementById("options-deletion-timer");
    if (delTimer) {
      const until = Math.floor(Number(safety?.deletion_due_at || delTimer.getAttribute("data-until") || 0));
      const pending = !!safety?.deletion_pending;
      if (pending && until > now) {
        delTimer.hidden = false;
        delTimer.setAttribute("data-until", String(until));
        delTimer.textContent = tf(
          "options_deletion_timer",
          { time: safetyFormatRemain(until - now) },
          `Löschung in ${safetyFormatRemain(until - now)}`
        );
      } else {
        delTimer.hidden = true;
      }
    }
    if (typeof GC.startProgressTicker === "function" && (vacTimer?.hidden === false || delTimer?.hidden === false)) {
      GC.startProgressTicker();
    }
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
    renderSafetyBlockers(safety.blocker_details);
    syncSafetyCountdownTimers(safety);
    publishAccountSafetyToShell(safety);
    syncVacationRepairVisibility();
  }

  function syncVacationRepairVisibility() {
    const btn = document.getElementById("options-vacation-repair-btn");
    const page = document.getElementById("options-page");
    if (!btn || !page) return;
    const pageInactive = page.getAttribute("data-vacation-active") !== "1";
    const notice = document.querySelector("[data-fleet-vacation-notice]");
    const shellActive = !!(notice && !notice.hidden);
    const stateActive = !!(GC.lastState?.account_safety?.vacation_active);
    const showRepair = pageInactive && (shellActive || stateActive);
    btn.hidden = !showRepair;
    const lead = document.getElementById("options-vacation-repair-lead");
    if (lead) lead.hidden = !showRepair;
  }

  async function runVacationRepair() {
    const btn = document.getElementById("options-vacation-repair-btn");
    if (btn) btn.disabled = true;
    try {
      const data = await postOptionsJson("/api/options/account-safety/repair", {});
      if (!data || data.ok !== true) {
        setSafetyHint("options-vacation-hint", msgKey(data && data.error), true);
        return;
      }
      const safety = (data.data && data.data.account_safety) || null;
      if (safety) applySafetySnapshot(safety);
      if (data.data && data.data.state && typeof GC.applyActionState === "function") {
        GC.applyActionState({ ok: true, state: data.data.state }, "options_vacation_repair");
      } else if (safety) {
        publishAccountSafetyToShell(safety);
      }
      setSafetyHint(
        "options-vacation-hint",
        msgKey(data.message || "options_vacation_repaired"),
        false
      );
      syncVacationRepairVisibility();
    } catch (err) {
      if (err && err.name === "AuthError") return;
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function bindOptionsAccountSafety() {
    const page = document.getElementById("options-page");
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
    if (!page || !modal || page.dataset.gcSafetyBound === "1") return;
    page.dataset.gcSafetyBound = "1";

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
        if (action === "vacation_repair") {
          void runVacationRepair();
          return;
        }
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
            const errText =
              data && data.error === "options_error_safety_blockers"
                ? formatSafetyBlockerError(data)
                : msgKey(data && data.error);
            if (hintId) setSafetyHint(hintId, errText, true);
            return;
          }
          if (data.data && data.data.account_safety) {
            applySafetySnapshot(data.data.account_safety);
          } else if (data.data && data.data.vacation_active !== undefined) {
            applySafetySnapshot(data.data);
          } else if (data.data && data.data.blocker_details) {
            renderSafetyBlockers(data.data.blocker_details);
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
