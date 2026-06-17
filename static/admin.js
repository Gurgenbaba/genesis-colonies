/**
 * Genesis Colonies – Admin Control Center (Premium Operations UI)
 */
(function () {
  "use strict";

  const GC = window.GC || (window.GC = {});
  const LOCALE = window.GC_LOCALE || {};
  let _activeTab = "health";
  let _isProduction = false;
  let _adminPanelBootstrapped = false;
  let _selectedSupportTicketId = null;
  let _selectedAdminMessageId = null;
  let _selectedPlayerId = null;
  let _selectedPlanetId = null;
  let _lootboxAdminState = null;
  let _lootboxSelectedContainer = null;

  function t(key, fallback) {
    return LOCALE[key] || fallback || key;
  }

  function qs(sel, root) {
    return (root || document).querySelector(sel);
  }

  function qsa(sel, root) {
    return Array.from((root || document).querySelectorAll(sel));
  }

  function fmtInt(n) {
    return (Number(n) || 0).toLocaleString("de-DE");
  }

  function fmtTs(ts) {
    if (!ts) return "–";
    try {
      return new Date(Number(ts) * 1000).toLocaleString();
    } catch (_) {
      return String(ts);
    }
  }

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  const ADMIN_SELECT_ATTRS = 'class="admin-input admin-select" data-gc-hud-select';

  function syncAdminHudSelects(root) {
    const scope = root && root.querySelectorAll ? root : adminRoot();
    if (!scope || typeof GC.initHudSelects !== "function") return;
    GC.initHudSelects(scope);
    if (typeof GC.rebuildHudSelect === "function") {
      scope.querySelectorAll("select[data-gc-hud-select]").forEach((sel) => {
        if (sel._gcHudSelect) GC.rebuildHudSelect(sel);
      });
    }
  }

  function playerNameLink(playerId, name) {
    const id = Number(playerId);
    if (!Number.isFinite(id) || id <= 0) return esc(name || "—");
    const label = esc(name || "Commander");
    const title = esc(t("playercard_open", "Profil öffnen"));
    return (
      `<span class="gc-player-name" data-player-id="${id}" data-player-name="${label}" ` +
      `data-player-card="1" role="button" tabindex="0" title="${title}">${label}</span>`
    );
  }

  function notify(msg, kind) {
    if (typeof GC.showNotify === "function") {
      GC.showNotify(msg, kind || "info");
      return;
    }
    console.log("[admin]", kind, msg);
  }

  function showAlert(msg, kind) {
    const host = qs("#admin-alert-host");
    if (!host) {
      notify(msg, kind === "error" ? "error" : "info");
      return;
    }
    if (!msg) {
      host.hidden = true;
      host.textContent = "";
      host.className = "admin-alert-host";
      return;
    }
    host.hidden = false;
    host.className = `admin-alert-host admin-alert-${kind || "error"}`;
    host.textContent = msg;
  }

  /** Dedicated admin fetch – never uses GC.fetchJSON (game auth redirect logic). */
  const ADMIN_API_TIMEOUT_MS = 45000;

  async function adminApi(url, options) {
    const opts = {
      method: "GET",
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json" },
      ...options,
    };
    if (opts.body && typeof opts.body === "object") {
      opts.headers = { ...opts.headers, "Content-Type": "application/json" };
      opts.body = JSON.stringify(opts.body);
    }

    const timeoutCtrl = new AbortController();
    const parentSignal = opts.signal;
    let timedOut = false;
    const timeoutId = setTimeout(() => {
      timedOut = true;
      timeoutCtrl.abort();
    }, ADMIN_API_TIMEOUT_MS);

    if (parentSignal) {
      if (parentSignal.aborted) {
        clearTimeout(timeoutId);
        return { ok: false, error: "aborted", message: "Request aborted", httpStatus: 0 };
      }
      parentSignal.addEventListener("abort", () => timeoutCtrl.abort(), { once: true });
    }

    let res;
    try {
      res = await fetch(url, { ...opts, signal: timeoutCtrl.signal });
    } catch (err) {
      clearTimeout(timeoutId);
      if (timedOut) {
        return {
          ok: false,
          error: "timeout",
          message: t("admin_request_timeout", "Zeitüberschreitung — Server antwortet nicht."),
          httpStatus: 0,
        };
      }
      return { ok: false, error: "network_error", message: err.message, httpStatus: 0 };
    }
    clearTimeout(timeoutId);
    let data = {};
    try {
      data = await res.json();
    } catch (_) {
      return {
        ok: false,
        error: "invalid_json",
        message: `HTTP ${res.status}: invalid JSON response`,
        httpStatus: res.status,
      };
    }
    if (!res.ok || data.ok === false) {
      return {
        ok: false,
        error: data.error || `http_${res.status}`,
        message: data.message || data.error || `HTTP ${res.status}`,
        httpStatus: res.status,
        ...data,
      };
    }
    if (data.ok === undefined) data.ok = true;
    return data;
  }

  function adminGet(url) {
    return adminApi(url);
  }

  function adminPost(url, body) {
    return adminApi(url, { method: "POST", body: body || {} });
  }

  function setBusy(btn, busy) {
    if (!btn) return;
    btn.disabled = !!busy;
    btn.dataset.busy = busy ? "1" : "0";
  }

  function loadingHtml() {
    return `<div class="admin-skeleton"><div class="admin-skeleton-line"></div><div class="admin-skeleton-line"></div><div class="admin-skeleton-line short"></div></div>`;
  }

  function statusBadge(level, label) {
    const cls =
      level === "ok"
        ? "admin-status-ok"
        : level === "warn"
          ? "admin-status-warn"
          : "admin-status-error";
    return `<span class="admin-status-badge ${cls}">${esc(label || level.toUpperCase())}</span>`;
  }

  function healthLevel(status) {
    if (status === "ok") return "ok";
    if (status === "degraded") return "warn";
    return "error";
  }

  function emptyState(msg) {
    return `<div class="admin-empty">${esc(msg || t("admin_empty", "Keine Daten"))}</div>`;
  }

  function errorCard(data) {
    return `<div class="admin-card admin-error-card">
      <h3>${t("admin_error_title", "Fehler")}</h3>
      <p>${esc(data.message || data.error || "unknown")}</p>
      ${data.httpStatus ? `<p class="admin-small-hint">HTTP ${data.httpStatus}</p>` : ""}
    </div>`;
  }

  function switchTab(name) {
    _activeTab = name;
    qsa(".admin-tab-btn, .admin-cc-tab").forEach((btn) => {
      const on = btn.dataset.adminTab === name;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    });
    qsa(".admin-panel, .admin-tab-panel, .admin-cc-panel").forEach((panel) => {
      const pid = panel.dataset.adminPanel || panel.dataset.panel;
      const on = pid === name;
      panel.classList.toggle("is-active", on);
      panel.hidden = !on;
    });
  }

  async function loadTab(name) {
    showAlert("");
    let result;
    switch (name) {
      case "health":
        result = await loadAdminHealth();
        break;
      case "migrations":
        result = await loadAdminMigrations();
        break;
      case "players":
        result = await searchAdminPlayers();
        await loadAdminBans();
        break;
      case "lootboxes":
        result = await loadAdminLootboxes();
        break;
      case "planets":
        result = await searchAdminPlanets();
        break;
      case "queues":
        result = await loadAdminQueues();
        break;
      case "audit":
        result = await loadAuditLog();
        break;
      case "chat":
        result = await loadAdminChat();
        break;
      case "support":
        result = await loadAdminSupport();
        break;
      case "messages":
        result = await loadAdminMessages();
        break;
      case "runtime":
        result = await loadAdminRuntime();
        break;
      case "balance":
        result = await loadAdminBalance();
        break;
      case "server":
        result = await loadAdminServer();
        break;
      default:
        result = null;
    }
    syncAdminHudSelects(qs(`[data-admin-panel="${name}"]`) || adminRoot());
    return result;
  }

  function balanceFieldElements() {
    return qsa("[data-balance-key]");
  }

  function populateBalanceForm(settings) {
    balanceFieldElements().forEach((el) => {
      const key = el.dataset.balanceKey;
      if (!key || settings[key] === undefined || settings[key] === null) return;
      if (el.tagName === "SELECT") {
        el.value = settings[key] ? "1" : "0";
      } else {
        el.value = settings[key];
      }
    });
  }

  function collectBalancePayload() {
    const payload = {};
    balanceFieldElements().forEach((el) => {
      const key = el.dataset.balanceKey;
      if (!key) return;
      payload[key] = el.value;
    });
    const applyStart = qs("#admin-balance-apply-start");
    if (applyStart && applyStart.checked) {
      payload.apply_start_to_existing = 1;
    }
    return payload;
  }

  function setBalanceStatus(msg) {
    const host = qs("#admin-balance-status");
    if (host) host.textContent = msg || "";
  }

  function updateAdminSpeedKpi(settings) {
    const host = qs("#admin-kpi-speed");
    if (!host || !settings) return;
    const prod = settings.production_speed ?? 1;
    const build = settings.build_speed ?? 1;
    const research = settings.research_speed ?? 1;
    host.textContent = `×${prod} / ×${build} / ×${research}`;
  }

  /** Apply HUD snapshot when server returned one (balance save). */
  function applyBalanceHudSnapshot(hud, reason) {
    if (!hud || hud.ok === false) return false;
    if (typeof GC.applyHudFromGameState === "function") {
      return GC.applyHudFromGameState(hud, reason || "admin_balance_save");
    }
    return false;
  }

  function focusAdminDetail(el) {
    if (!el) return;
    if (window.matchMedia("(max-width: 640px)").matches) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  function markSelectedEntityRow(listSelector, attrName, selectedId) {
    const list = qs(listSelector);
    if (!list) return;
    qsa(`tr[${attrName}]`, list).forEach((row) => {
      row.classList.toggle("is-active", String(row.getAttribute(attrName)) === String(selectedId));
    });
  }

  /** Push admin mutations into live game UI immediately (HUD + optional tab reload). */
  async function syncAfterAdminChange(reason, opts) {
    const options = opts || {};
    if (options.settings) updateAdminHeaderKpis(options.settings);
    if (options.hud) applyBalanceHudSnapshot(options.hud, reason || "admin_change");

    if (options.skipGameState !== true) {
      if (typeof GC.refreshGameState === "function") {
        try {
          await GC.refreshGameState(reason || "admin_change");
        } catch (_) {
          /* non-fatal */
        }
      } else if (typeof GC.refreshHudFromGameState === "function") {
        try {
          await GC.refreshHudFromGameState(reason || "admin_change");
        } catch (_) {
          /* non-fatal */
        }
      }
    }

    if (options.reloadTab) {
      await loadTab(_activeTab);
    } else if (_activeTab === "players" && _selectedPlayerId) {
      await loadAdminPlayer(_selectedPlayerId);
    } else if (_activeTab === "planets" && _selectedPlanetId) {
      await loadAdminPlanet(_selectedPlanetId);
    } else if (_activeTab === "queues") {
      await loadAdminQueues();
    }
  }

  async function afterBalanceMutation(settings, reason, extras) {
    updateAdminSpeedKpi(settings || {});
    await syncAfterAdminChange(reason || "admin_balance_save", {
      settings,
      hud: extras && extras.hud,
    });
  }

  async function loadAdminBalance() {
    setBalanceStatus("");
    const data = await adminGet("/api/admin/balance");
    if (!data.ok) {
      showAlert(data.message || t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      return data;
    }
    populateBalanceForm(data.settings || {});
    return data;
  }

  async function saveAdminBalance() {
    setBalanceStatus(t("admin_balance_saving", "Speichern…"));
    const payload = collectBalancePayload();
    const res = await adminPost("/api/admin/balance", payload);
    if (res.ok) {
      populateBalanceForm(res.settings || {});
      if (qs("#admin-balance-apply-start")) qs("#admin-balance-apply-start").checked = false;
      notify(t("admin_balance_saved", "Balance-Einstellungen gespeichert."), "success");
      setBalanceStatus(t("admin_balance_saved", "Balance-Einstellungen gespeichert."));
      await afterBalanceMutation(res.settings, "admin_balance_save", { hud: res.hud });
    } else {
      showAlert(res.message || res.error || t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      setBalanceStatus("");
    }
    return res;
  }

  async function applyBalancePresetB() {
    const res = await adminPost("/api/admin/balance/preset-b", {});
    if (res.ok) {
      populateBalanceForm(res.settings || {});
      notify(t("admin_balance_preset_applied", "Preset B angewendet."), "success");
      setBalanceStatus(t("admin_balance_preset_applied", "Preset B angewendet."));
      await afterBalanceMutation(res.settings, "admin_balance_preset", { hud: res.hud });
    } else {
      showAlert(res.message || res.error, "error");
    }
    return res;
  }

  async function recalculateAdminRankings() {
    const res = await adminPost("/api/admin/rankings/recalculate", {});
    if (res.ok) {
      const n = res.players_updated ?? 0;
      notify(t("admin_balance_recalc_ok", "Ranking neu berechnet.") + ` (${n})`, "success");
      setBalanceStatus(
        `${t("admin_balance_recalc_ok", "Ranking neu berechnet.")} — ${n} ${t("admin_balance_players", "Spieler")}`
      );
    } else {
      showAlert(res.message || res.error, "error");
    }
    return res;
  }

  async function backfillCombatHof() {
    const res = await adminPost("/api/admin/combat-hof/backfill", {});
    if (res.ok) {
      const inserted = res.inserted ?? 0;
      notify(
        t("admin_hof_backfill_ok", "Hall of Fame aus Kampfberichten aufgebaut.") + ` (${inserted})`,
        "success"
      );
      setBalanceStatus(
        `${t("admin_hof_backfill_ok", "Hall of Fame aus Kampfberichten aufgebaut.")} — ${inserted} ${t("admin_hof_backfill_entries", "Einträge")}`
      );
    } else {
      showAlert(res.message || res.error, "error");
    }
    return res;
  }

  function setServerStatus(msg) {
    const host = qs("#admin-server-status");
    if (host) host.textContent = msg || "";
  }

  function populateServerForm(settings) {
    if (!settings) return;
    const un = qs("#universe_name");
    if (un) un.value = settings.universe_name || "";
    const gc = qs("#galaxy_count");
    if (gc) gc.value = settings.galaxy_count != null ? settings.galaxy_count : 1;
    const motd = qs("#motd_text");
    if (motd) motd.value = settings.motd_text || "";
    const motdOn = qs("#motd_enabled");
    if (motdOn) motdOn.checked = !!settings.motd_enabled;
    updateAdminHeaderKpis(settings);
  }

  function updateAdminHeaderKpis(settings) {
    if (!settings) return;
    const universeEl = qs(".admin-kpi-grid .admin-metric-value");
    const cards = qsa(".admin-kpi-card");
    cards.forEach((card) => {
      const label = card.querySelector(".admin-metric-label")?.textContent || "";
      if (label.includes("Universum") || label.toLowerCase().includes("universe")) {
        const val = card.querySelector(".admin-metric-value");
        if (val && settings.universe_name) val.textContent = settings.universe_name;
      }
      if (label.includes("Galaxien") || label.toLowerCase().includes("galax")) {
        const val = card.querySelector(".admin-metric-value");
        if (val && settings.galaxy_count != null) val.textContent = String(settings.galaxy_count);
      }
    });
    updateAdminSpeedKpi(settings);
  }

  function collectServerPayload() {
    return {
      universe_name: (qs("#universe_name")?.value || "").trim(),
      galaxy_count: parseInt(qs("#galaxy_count")?.value, 10) || 1,
      motd_text: (qs("#motd_text")?.value || "").trim(),
      motd_enabled: qs("#motd_enabled")?.checked ? 1 : 0,
    };
  }

  async function loadAdminServer() {
    setServerStatus("");
    const data = await adminGet("/api/admin/server");
    if (!data.ok) {
      showAlert(data.message || t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      return data;
    }
    populateServerForm(data.settings || {});
    return data;
  }

  async function saveAdminServer() {
    setServerStatus(t("admin_balance_saving", "Speichern…"));
    const res = await adminPost("/api/admin/server", collectServerPayload());
    if (res.ok) {
      populateServerForm(res.settings || {});
      notify(t("msg_settings_saved", "Einstellungen gespeichert."), "success");
      setServerStatus(t("msg_settings_saved", "Einstellungen gespeichert."));
      await syncAfterAdminChange("admin_server_save", { settings: res.settings });
    } else {
      showAlert(res.message || res.error, "error");
      setServerStatus("");
    }
    return res;
  }

  async function applyAdminResources() {
    const payload = {
      metal_delta: (qs("#metal_delta")?.value || "").trim(),
      crystal_delta: (qs("#crystal_delta")?.value || "").trim(),
      fuel_cells_delta: (qs("#fuel_cells_delta")?.value || "").trim(),
      resource_player_id: (qs("#resource_player_id")?.value || "").trim(),
      resource_apply_all: qs("#resource_all")?.checked ? 1 : 0,
    };
    const res = await adminPost("/api/admin/resources", payload);
    if (res.ok) {
      notify(t("msg_admin_resources_updated", "Ressourcen angepasst."), "success");
      setServerStatus(t("msg_admin_resources_updated", "Ressourcen angepasst."));
      if (qs("#metal_delta")) qs("#metal_delta").value = "";
      if (qs("#crystal_delta")) qs("#crystal_delta").value = "";
      if (qs("#fuel_cells_delta")) qs("#fuel_cells_delta").value = "";
      await syncAfterAdminChange("admin_resources_apply");
    } else {
      showAlert(res.message || res.error, "error");
    }
    return res;
  }

  async function wipeAdminUniverse() {
    if (!qs("#wipe_confirm")?.checked) {
      showAlert(t("admin_wipe_confirm_required", "Wipe-Bestätigung erforderlich."), "error");
      return null;
    }
    const c = prompt(t("admin_wipe_type_confirm", "Tippe WIPE UNIVERSE"));
    if (c !== "WIPE UNIVERSE") return null;
    const payload = {
      wipe_confirm: 1,
      wipe_reset_research: qs("#wipe_research")?.checked ? 1 : 0,
      wipe_reset_resources: qs("#wipe_resources")?.checked ? 1 : 0,
      wipe_delete_messages: qs("#wipe_messages")?.checked ? 1 : 0,
    };
    const res = await adminPost("/api/admin/wipe", payload);
    if (res.ok) {
      notify(t("msg_admin_wipe", "Universum wurde zurückgesetzt."), "success");
      setServerStatus(t("msg_admin_wipe", "Universum wurde zurückgesetzt."));
      if (qs("#wipe_confirm")) qs("#wipe_confirm").checked = false;
      await syncAfterAdminChange("admin_universe_wipe", { reloadTab: true });
    } else {
      showAlert(res.message || res.error, "error");
    }
    return res;
  }

  function renderAdminBans(bans) {
    const host = qs("#admin-bans-output");
    if (!host) return;
    const rows = (bans || []).map((ban) => {
      const expires = ban.is_permanent
        ? `<span class="ban-permanent">${esc(t("admin_ban_permanent", "permanent"))}</span>`
        : esc(ban.expires_text || "–");
      return `<tr>
        <td>${ban.player_id}</td>
        <td>${ban.player_id && ban.username ? playerNameLink(ban.player_id, ban.username) : esc(ban.username || "–")}</td>
        <td>${esc(ban.player_name || "–")}</td>
        <td>${esc(ban.reason || "–")}</td>
        <td>${esc(ban.created_text || "–")}</td>
        <td>${expires}</td>
        <td class="text-right">
          <button type="button" class="gc-btn gc-btn-outline gc-btn-xs" data-admin-action="player-unban" data-player-id="${ban.player_id}">
            ${esc(t("admin_btn_unban_player", "Aufheben"))}
          </button>
        </td>
      </tr>`;
    });
    if (!rows.length) {
      host.innerHTML = `<p class="admin-small-hint">${esc(t("admin_no_bans", "Keine aktiven Banns."))}</p>`;
      return;
    }
    host.innerHTML = renderTable(
      [
        t("admin_col_id", "ID"),
        t("admin_col_username", "Username"),
        t("admin_col_player_name", "Name"),
        t("admin_label_ban_reason", "Grund"),
        t("admin_col_created", "Erstellt"),
        t("admin_col_expires", "Gültig bis"),
        t("admin_col_action", "Aktion"),
      ],
      rows
    );
  }

  async function loadAdminBans() {
    const data = await adminGet("/api/admin/bans");
    if (!data.ok) {
      showAlert(data.message, "error");
      return data;
    }
    renderAdminBans(data.bans || []);
    return data;
  }

  async function loadAdminHealth() {
    const out = qs("#admin-health-output");
    if (out) out.innerHTML = loadingHtml();
    const data = await adminGet("/api/admin/health");
    if (!data.ok) {
      showAlert(data.message || t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      if (out) out.innerHTML = errorCard(data);
      return data;
    }
    const h = data.health || {};
    const c = h.checks || {};
    const db = c.database || {};
    const mig = c.migrations || {};
    const wr = c.writable || {};
    const cfg = c.config || {};

    if (out) {
      out.innerHTML = `
        <div class="admin-kpi-grid">
          <div class="admin-kpi-card admin-card">
            <div class="admin-metric-label">${t("admin_health_status", "Status")}</div>
            <div class="admin-metric-value">${statusBadge(healthLevel(h.status), h.status || "?")}</div>
          </div>
          <div class="admin-kpi-card admin-card">
            <div class="admin-metric-label">${t("admin_health_version", "Version")}</div>
            <div class="admin-metric-value">${esc(h.version || "–")}</div>
          </div>
          <div class="admin-kpi-card admin-card">
            <div class="admin-metric-label">${t("admin_health_checked", "Geprüft")}</div>
            <div class="admin-metric-value">${esc(fmtTs(h.checked_at))}</div>
          </div>
        </div>
        <div class="admin-kpi-grid">
          <div class="admin-card">
            <h3 class="admin-subtitle">${t("admin_health_db", "Datenbank")}</h3>
            ${statusBadge(db.ok ? "ok" : "error", db.ok ? "OK" : "FAIL")}
            <p class="admin-small-hint">${esc(db.path || "")}</p>
          </div>
          <div class="admin-card">
            <h3 class="admin-subtitle">${t("admin_migrations_title", "Migrationen")}</h3>
            ${statusBadge(mig.ok ? "ok" : "warn", mig.current ? "OK" : "PENDING")}
            <p class="admin-small-hint">${(mig.pending || []).length} pending</p>
          </div>
          <div class="admin-card">
            <h3 class="admin-subtitle">${t("admin_health_writable", "Writable")}</h3>
            ${statusBadge(wr.ok ? "ok" : "error", wr.ok ? "OK" : "FAIL")}
          </div>
          <div class="admin-card">
            <h3 class="admin-subtitle">${t("admin_health_config", "Config")}</h3>
            ${statusBadge(cfg.ok ? "ok" : "warn", cfg.production ? "PROD" : "DEV")}
            ${cfg.debug ? `<p class="admin-small-hint">Debug ON</p>` : ""}
          </div>
        </div>`;
    }
    return data;
  }

  async function loadAdminMigrations() {
    const out = qs("#admin-migrations-output");
    if (out) out.innerHTML = loadingHtml();
    const data = await adminGet("/api/admin/migrations");
    if (!data.ok) {
      showAlert(data.message, "error");
      if (out) out.innerHTML = errorCard(data);
      return data;
    }
    const m = data.migrations || {};
    const runZone = qs("#admin-migrations-run-zone");
    const prodNote = qs("#admin-migrations-prod-note");
    const hasPending = (m.pending || []).length > 0;

    if (runZone) runZone.hidden = _isProduction || !hasPending;
    if (prodNote) prodNote.hidden = !_isProduction;

    if (out) {
      out.innerHTML = `
        <div class="admin-card">
          <p><strong>${t("admin_migrations_db_path", "DB-Pfad")}:</strong> <code>${esc(m.db_path || "")}</code></p>
          <p><strong>${t("admin_migrations_backend", "Backend")}:</strong> ${esc(m.backend || "sqlite")}
            · ${statusBadge(m.current ? "ok" : "warn", m.current ? t("admin_migrations_current", "aktuell") : t("admin_migrations_pending_label", "ausstehend"))}</p>
        </div>
        <div class="admin-kpi-grid">
          <div class="admin-card">
            <h3 class="admin-subtitle">${t("admin_migrations_applied", "Angewendet")} (${(m.applied || []).length})</h3>
            <ul class="admin-list">${(m.applied || []).map((x) => `<li>${esc(x)}</li>`).join("") || `<li>${t("admin_none", "Keine")}</li>`}</ul>
          </div>
          <div class="admin-card">
            <h3 class="admin-subtitle">${t("admin_migrations_pending", "Ausstehend")} (${(m.pending || []).length})</h3>
            <ul class="admin-list admin-list-warn">${(m.pending || []).map((x) => `<li>${esc(x)}</li>`).join("") || `<li>${t("admin_none", "Keine")}</li>`}</ul>
          </div>
        </div>`;
    }
    return data;
  }

  async function runAdminMigrations() {
    const confirmEl = qs("#admin-migrations-confirm");
    const data = await adminPost("/api/admin/migrations/run", {
      confirm_text: confirmEl ? confirmEl.value : "",
    });
    if (data.ok) notify(t("admin_action_success", "Erfolgreich"), "success");
    else showAlert(data.message || t("admin_confirm_required", "Bestätigung erforderlich"), "error");
    await loadAdminMigrations();
    return data;
  }

  function renderTable(headers, rows, opts) {
    if (!rows.length) return emptyState(t("admin_empty", "Keine Einträge"));
    const inline = opts && opts.inline;
    const tableHtml = `<table class="admin-table ban-table table-std${inline ? " admin-table--entity" : ""}">
      <thead><tr>${headers.map((h) => {
        if (typeof h === "string") return `<th>${h}</th>`;
        const cls = h.className ? ` class="${h.className}"` : "";
        return `<th${cls}>${esc(h.label)}</th>`;
      }).join("")}</tr></thead>
      <tbody>${rows.join("")}</tbody></table>`;
    if (inline) return tableHtml;
    return `<div class="admin-table-wrap">${tableHtml}</div>`;
  }

  function buildAdminInventoryGrantUi(containers, { mode, idPrefix = "admin-lootbox" }) {
    const isAll = mode === "all";
    const grantAct = isAll ? "inventory-grant-all" : "player-inventory-grant";
    const quickAct = isAll ? "inventory-grant-all-quick" : "player-inventory-grant-quick";
    const selectId = isAll ? `${idPrefix}-all-inv-key` : `${idPrefix}-player-inv-key`;
    const amountId = isAll ? `${idPrefix}-all-inv-amount` : `${idPrefix}-player-inv-amount`;
    const invOpts = (containers || [])
      .map(
        (c) =>
          `<option value="${esc(c.item_key)}">${esc(t(c.name_key || c.item_key, c.item_key))}</option>`
      )
      .join("");
    const quickChips = (containers || [])
      .map((c) => {
        const label = t(c.name_key || c.item_key, c.item_key);
        return (
          `<button type="button" class="gc-btn gc-btn-outline gc-btn-xs admin-chip-btn" data-admin-action="${quickAct}"` +
          ` data-item-key="${esc(c.item_key)}" data-amount="1" title="${esc(label)}">` +
          `<span class="admin-chip-btn-qty">+1</span><span class="admin-chip-btn-label">${esc(label)}</span></button>`
        );
      })
      .join("");
    const title = isAll
      ? t("admin_inventory_grant_all_title", "Lootboxen an alle Spieler")
      : t("admin_inventory_grant_title", "Lootboxen vergeben");
    const hint = isAll
      ? `<p class="admin-small-hint admin-tool-panel__hint">${esc(t("admin_inventory_grant_all_hint", "Vergibt Container an jeden registrierten Spieler-Account."))}</p>`
      : "";
    const grantBtn = isAll
      ? t("admin_inventory_grant_all_btn", "An alle vergeben")
      : t("admin_inventory_grant_btn", "Vergeben");
    const playerIdRow = isAll
      ? ""
      : `<label class="admin-field admin-field--id">` +
        `<span class="admin-label">${esc(t("admin_lootboxes_player_id", "Spieler-ID"))}</span>` +
        `<input type="number" min="1" class="admin-input admin-input-sm" id="admin-lootbox-player-id" placeholder="ID">` +
        `</label>`;
    return (
      `${hint}` +
      `<div class="admin-field-row">${playerIdRow}` +
      `<label class="admin-field admin-field--grow">` +
      `<span class="admin-label">${esc(t("admin_inventory_item_label", "Container"))}</span>` +
      `<select ${ADMIN_SELECT_ATTRS} id="${selectId}">${invOpts}</select>` +
      `</label>` +
      `<label class="admin-field admin-field--qty">` +
      `<span class="admin-label">${esc(t("admin_inventory_amount", "Anzahl"))}</span>` +
      `<input type="number" min="1" max="999" value="1" class="admin-input admin-input-qty" id="${amountId}">` +
      `</label>` +
      `<div class="admin-field admin-field--action">` +
      `<span class="admin-label admin-label--spacer" aria-hidden="true">&nbsp;</span>` +
      `<button type="button" class="gc-btn gc-btn-primary gc-btn-sm" data-admin-action="${grantAct}">${esc(grantBtn)}</button>` +
      `</div></div>` +
      `<div class="admin-chip-grid">${quickChips}</div>`
    );
  }

  function lootPoolRewardTypeOptions(selected) {
    const types = (_lootboxAdminState && _lootboxAdminState.reward_types) || [
      "resource",
      "item",
      "booster",
      "ship",
      "defense",
    ];
    return types
      .map(
        (tp) =>
          `<option value="${esc(tp)}"${tp === selected ? " selected" : ""}>${esc(tp)}</option>`
      )
      .join("");
  }

  function lootPoolRewardKeyOptions(rewardType, selectedKey) {
    const catalog =
      (_lootboxAdminState && _lootboxAdminState.reward_keys_by_type) || {};
    const keys = catalog[rewardType] || [];
    if (!keys.length) {
      const fallback = selectedKey || "";
      return `<option value="${esc(fallback)}" selected>${esc(fallback || "—")}</option>`;
    }
    let found = false;
    const opts = keys
      .map((entry) => {
        const sel = entry.key === selectedKey;
        if (sel) found = true;
        const label = t(entry.name_key || entry.key, entry.key);
        return `<option value="${esc(entry.key)}"${sel ? " selected" : ""}>${esc(label)}</option>`;
      })
      .join("");
    if (selectedKey && !found) {
      return (
        `<option value="${esc(selectedKey)}" selected>${esc(selectedKey)}</option>` + opts
      );
    }
    return opts;
  }

  function syncLootPoolRowKeySelect(row, rewardType, selectedKey) {
    const keySel = row && row.querySelector('[data-field="reward_key"]');
    if (!keySel) return;
    const current = selectedKey || keySel.value || "";
    keySel.innerHTML = lootPoolRewardKeyOptions(rewardType, current);
    if (!keySel.value && keySel.options.length) {
      keySel.selectedIndex = 0;
    }
    if (typeof GC.rebuildHudSelect === "function") GC.rebuildHudSelect(keySel);
  }

  function persistLootPoolDraft() {
    const key = _lootboxSelectedContainer;
    if (!key || !_lootboxAdminState || !_lootboxAdminState.pools[key]) return;
    _lootboxAdminState.pools[key].entries = collectLootPoolEditorRows();
  }

  function collectLootPoolEditorRows() {
    const tbody = qs("#admin-lootbox-pool-rows");
    if (!tbody) return [];
    return qsa("tr[data-pool-row]", tbody).map((row) => ({
      weight: parseInt(row.querySelector('[data-field="weight"]')?.value || "0", 10),
      reward_type: row.querySelector('[data-field="reward_type"]')?.value || "",
      reward_key: row.querySelector('[data-field="reward_key"]')?.value || "",
      min_amount: parseInt(row.querySelector('[data-field="min_amount"]')?.value || "1", 10),
      max_amount: parseInt(row.querySelector('[data-field="max_amount"]')?.value || "1", 10),
    }));
  }

  function renderLootPoolEditor(containerKey) {
    const host = qs("#admin-lootbox-pools-editor");
    if (!host || !_lootboxAdminState) return;
    const containers = _lootboxAdminState.containers || [];
    const pools = _lootboxAdminState.pools || {};
    const keys = containers.map((c) => c.item_key);
    const key = containerKey && pools[containerKey] ? containerKey : keys[0] || "";
    _lootboxSelectedContainer = key;
    const pool = pools[key] || { entries: [], is_custom: false };
    const entries = pool.entries || [];
    const badge = pool.is_custom
      ? statusBadge("warn", t("admin_lootboxes_pool_custom_badge", "Angepasst"))
      : statusBadge("ok", t("admin_lootboxes_pool_default_badge", "Standard"));
    const containerOpts = containers
      .map(
        (c) =>
          `<option value="${esc(c.item_key)}"${c.item_key === key ? " selected" : ""}>${esc(t(c.name_key || c.item_key, c.item_key))}</option>`
      )
      .join("");
    const rows = entries
      .map(
        (entry, idx) =>
          `<tr data-pool-row="${idx}">` +
          `<td><input type="number" min="1" class="admin-input admin-input-sm" data-field="weight" value="${esc(entry.weight)}"></td>` +
          `<td><select ${ADMIN_SELECT_ATTRS} data-field="reward_type">${lootPoolRewardTypeOptions(entry.reward_type)}</select></td>` +
          `<td><select ${ADMIN_SELECT_ATTRS} data-field="reward_key">${lootPoolRewardKeyOptions(entry.reward_type, entry.reward_key)}</select></td>` +
          `<td><input type="number" min="1" class="admin-input admin-input-sm" data-field="min_amount" value="${esc(entry.min_amount)}"></td>` +
          `<td><input type="number" min="1" class="admin-input admin-input-sm" data-field="max_amount" value="${esc(entry.max_amount)}"></td>` +
          `<td class="text-right"><button type="button" class="gc-btn gc-btn-outline gc-btn-xs" data-admin-action="loot-pool-row-delete" data-row="${idx}">×</button></td>` +
          `</tr>`
      )
      .join("");
    host.innerHTML =
      `<div class="admin-tool-panel admin-loot-pool-editor">` +
      `<div class="admin-field-row admin-field-row-wrap">` +
      `<label class="admin-field admin-field--grow">` +
      `<span class="admin-label">${esc(t("admin_lootboxes_pool_container", "Container"))}</span>` +
      `<select ${ADMIN_SELECT_ATTRS} id="admin-lootbox-pool-container">${containerOpts}</select>` +
      `</label>` +
      `<div class="admin-field admin-field--action">${badge}</div>` +
      `</div>` +
      `<div class="admin-table-wrap"><table class="admin-table table-std">` +
      `<thead><tr>` +
      `<th>${esc(t("admin_lootboxes_pool_col_weight", "Gewicht"))}</th>` +
      `<th>${esc(t("admin_lootboxes_pool_col_type", "Typ"))}</th>` +
      `<th>${esc(t("admin_lootboxes_pool_col_key", "Schlüssel"))}</th>` +
      `<th>${esc(t("admin_lootboxes_pool_col_min", "Min"))}</th>` +
      `<th>${esc(t("admin_lootboxes_pool_col_max", "Max"))}</th>` +
      `<th></th>` +
      `</tr></thead>` +
      `<tbody id="admin-lootbox-pool-rows">${rows}</tbody>` +
      `</table></div>` +
      `<div class="admin-toolbar admin-toolbar--tight">` +
      `<button type="button" class="gc-btn gc-btn-outline gc-btn-sm" data-admin-action="loot-pool-add-row">${esc(t("admin_lootboxes_pool_add_row", "Zeile hinzufügen"))}</button>` +
      `<button type="button" class="gc-btn gc-btn-primary gc-btn-sm" data-admin-action="loot-pool-save">${esc(t("admin_lootboxes_pool_save", "Pool speichern"))}</button>` +
      `<button type="button" class="gc-btn gc-btn-outline gc-btn-sm" data-admin-action="loot-pool-reset">${esc(t("admin_lootboxes_pool_reset", "Standard wiederherstellen"))}</button>` +
      `</div></div>`;
    syncAdminHudSelects(host);
  }

  async function loadAdminLootboxes() {
    const grantAll = qs("#admin-lootbox-grant-all");
    const grantPlayer = qs("#admin-lootbox-grant-player");
    const poolHost = qs("#admin-lootbox-pools-editor");
    if (grantAll) grantAll.innerHTML = loadingHtml();
    if (grantPlayer) grantPlayer.innerHTML = loadingHtml();
    if (poolHost) poolHost.innerHTML = loadingHtml();

    const data = await adminGet("/api/admin/lootboxes/state");
    if (!data.ok) {
      showAlert(data.message || data.error, "error");
      if (grantAll) grantAll.innerHTML = errorCard(data);
      if (grantPlayer) grantPlayer.innerHTML = "";
      if (poolHost) poolHost.innerHTML = "";
      return data;
    }
    _lootboxAdminState = data;
    const containers = data.containers || [];
    if (grantAll) {
      grantAll.innerHTML =
        `<h4 class="admin-tool-panel__title">${esc(t("admin_inventory_grant_all_title", "Lootboxen an alle Spieler"))}</h4>` +
        buildAdminInventoryGrantUi(containers, { mode: "all" });
      syncAdminHudSelects(grantAll);
    }
    if (grantPlayer) {
      grantPlayer.innerHTML =
        `<h4 class="admin-tool-panel__title">${esc(t("admin_inventory_grant_title", "Lootboxen vergeben"))}</h4>` +
        buildAdminInventoryGrantUi(containers, { mode: "player" });
      syncAdminHudSelects(grantPlayer);
    }
    renderLootPoolEditor(_lootboxSelectedContainer);
    return data;
  }

  async function searchAdminPlayers() {
    const q = (qs("#admin-players-search")?.value || "").trim();
    const list = qs("#admin-players-list");
    if (list) list.innerHTML = loadingHtml();
    const data = await adminGet(`/api/admin/players?q=${encodeURIComponent(q)}`);
    if (!data.ok) {
      showAlert(data.message, "error");
      if (list) list.innerHTML = errorCard(data);
      return data;
    }
    const rows = (data.players || []).map(
      (p) => `<tr class="admin-entity-row${_selectedPlayerId === p.id ? " is-active" : ""}" data-admin-player-id="${p.id}" title="${esc(t("admin_btn_details", "Details"))}">
        <td class="col-id">${p.id}</td><td class="col-name">${playerNameLink(p.id, p.username)}</td><td class="col-flag">${p.is_admin ? "✓" : "–"}</td>
        <td class="col-date">${esc(fmtTs(p.last_seen))}</td>
      </tr>`
    );
    if (list) {
      list.innerHTML = renderTable(
        [
          t("admin_col_id", "ID"),
          t("admin_col_username", "Username"),
          t("admin_col_admin", "Admin"),
          t("admin_col_last_seen", "Zuletzt"),
        ],
        rows,
        { inline: true }
      );
      markSelectedEntityRow("#admin-players-list", "data-admin-player-id", _selectedPlayerId);
    }
    return data;
  }

  async function renderPlayerDetail(data) {
    const el = qs("#admin-player-detail");
    if (!el || !data.ok) return;
    const p = data.player || {};
    const hw = data.homeworld || {};
    const score = data.score || {};
    el.innerHTML = `
      <h3 class="admin-subtitle">#${p.id} ${playerNameLink(p.id, p.username)} ${p.is_admin ? statusBadge("ok", "Admin") : ""}</h3>
      <p>${t("admin_col_last_seen", "Zuletzt")}: ${esc(fmtTs(p.last_seen))} · Score: ${fmtInt(score.total)} (#${score.rank || "?"})</p>
      <p>Homeworld: ${esc(hw.name || "–")} · ${t("metal", "Ferronit")}: ${fmtInt(hw.metal)} · ${t("crystal", "Crytite")}: ${fmtInt(hw.crystal)} · ${t("fuel_cells", "Brennzellen")}: ${fmtInt(hw.fuel_cells)}</p>
      <div class="admin-toolbar">
        <button type="button" class="gc-btn gc-btn-outline gc-btn-sm" data-admin-action="player-effects" data-player-id="${p.id}">${t("admin_btn_effects", "Effekte")}</button>
        <button type="button" class="gc-btn gc-btn-outline gc-btn-sm" data-admin-action="player-set-admin" data-player-id="${p.id}" data-is-admin="${p.is_admin ? 0 : 1}">${p.is_admin ? t("admin_btn_remove_admin", "Admin entfernen") : t("admin_btn_grant_admin", "Admin setzen")}</button>
        <button type="button" class="gc-btn gc-btn-outline gc-btn-sm" data-admin-action="player-repair-hw" data-player-id="${p.id}">${t("admin_btn_repair_homeworld", "Homeworld reparieren")}</button>
        <button type="button" class="gc-btn gc-btn-danger gc-btn-sm" data-admin-action="player-ban" data-player-id="${p.id}">${t("admin_btn_ban", "Bannen")}</button>
        <button type="button" class="gc-btn gc-btn-outline gc-btn-sm" data-admin-action="player-unban" data-player-id="${p.id}">${t("admin_btn_unban", "Entbannen")}</button>
      </div>
      <div class="admin-toolbar admin-toolbar--tight">
        <input type="number" min="0" class="admin-input admin-input-sm" id="admin-player-metal" placeholder="${t("metal", "Ferronit")}">
        <input type="number" min="0" class="admin-input admin-input-sm" id="admin-player-crystal" placeholder="${t("crystal", "Crytite")}">
        <input type="number" min="0" class="admin-input admin-input-sm" id="admin-player-fuel" placeholder="${t("fuel_cells", "Brennzellen")}">
        <button type="button" class="gc-btn gc-btn-primary gc-btn-sm" data-admin-action="player-resources-add" data-player-id="${p.id}">${t("admin_btn_apply", "Addieren")}</button>
        <button type="button" class="gc-btn gc-btn-outline gc-btn-sm" data-admin-action="player-resources-set" data-player-id="${p.id}">${t("admin_btn_set_resources", "Setzen")}</button>
      </div>`;
    syncAdminHudSelects(el);
    focusAdminDetail(el);
  }

  async function loadAdminPlayer(id) {
    _selectedPlayerId = parseInt(id, 10) || null;
    markSelectedEntityRow("#admin-players-list", "data-admin-player-id", _selectedPlayerId);
    const data = await adminGet(`/api/admin/player/${id}`);
    if (!data.ok) showAlert(data.message, "error");
    else await renderPlayerDetail(data);
    return data;
  }

  async function searchAdminPlanets() {
    const q = (qs("#admin-planets-search")?.value || "").trim();
    const list = qs("#admin-planets-list");
    if (list) list.innerHTML = loadingHtml();
    const data = await adminGet(`/api/admin/planets?q=${encodeURIComponent(q)}`);
    if (!data.ok) {
      showAlert(data.message, "error");
      if (list) list.innerHTML = errorCard(data);
      return data;
    }
    const rows = (data.planets || []).map(
      (pl) => `<tr class="admin-entity-row${_selectedPlanetId === pl.id ? " is-active" : ""}" data-admin-planet-id="${pl.id}" title="${esc(t("admin_btn_details", "Details"))}">
        <td class="col-id">${pl.id}</td><td class="col-name">${esc(pl.name)}</td><td class="col-name">${pl.player_id ? playerNameLink(pl.player_id, pl.owner_username || pl.player_id) : esc(pl.owner_username || "–")}</td>
        <td class="col-flag">${pl.is_homeworld ? "✓" : "–"}</td>
      </tr>`
    );
    if (list) {
      list.innerHTML = renderTable(
        [
          t("admin_col_id", "ID"),
          t("admin_col_name", "Name"),
          t("admin_col_owner", "Owner"),
          "HW",
        ],
        rows,
        { inline: true }
      );
      markSelectedEntityRow("#admin-planets-list", "data-admin-planet-id", _selectedPlanetId);
    }
    return data;
  }

  function renderPlanetDetail(data) {
    const el = qs("#admin-planet-detail");
    if (!el || !data.ok) return;
    const pl = data.planet || {};
    const b = data.buildings || {};
    const buildingOpts = Object.keys(b)
      .map((k) => `<option value="${esc(k)}">${esc(k)} (${b[k]})</option>`)
      .join("");
    el.innerHTML = `
      <h3 class="admin-subtitle">#${pl.id} ${esc(pl.name || "")}</h3>
      <p>${t("metal", "Ferronit")}: ${fmtInt(pl.metal)} · ${t("crystal", "Crytite")}: ${fmtInt(pl.crystal)} · ${t("fuel_cells", "Brennzellen")}: ${fmtInt(pl.fuel_cells)}</p>
      <details class="admin-buildings-detail"><summary>${t("admin_buildings", "Gebäude")}</summary><pre>${esc(JSON.stringify(b, null, 2))}</pre></details>
      <div class="admin-toolbar admin-toolbar--tight">
        <input type="number" min="0" class="admin-input admin-input-sm" id="admin-planet-metal" placeholder="${t("metal", "Ferronit")}">
        <input type="number" min="0" class="admin-input admin-input-sm" id="admin-planet-crystal" placeholder="${t("crystal", "Crytite")}">
        <input type="number" min="0" class="admin-input admin-input-sm" id="admin-planet-fuel" placeholder="${t("fuel_cells", "Brennzellen")}">
        <button type="button" class="gc-btn gc-btn-primary gc-btn-sm" data-admin-action="planet-resources-set" data-planet-id="${pl.id}">${t("admin_btn_set_resources", "Setzen")}</button>
      </div>
      <div class="admin-toolbar admin-toolbar--tight">
        <select ${ADMIN_SELECT_ATTRS} id="admin-planet-building-type">${buildingOpts}</select>
        <input type="number" min="0" max="100" class="admin-input admin-input-sm" id="admin-planet-building-level" placeholder="Level">
        <button type="button" class="gc-btn gc-btn-outline gc-btn-sm" data-admin-action="planet-building-set" data-planet-id="${pl.id}">${t("admin_btn_set_building", "Gebäude setzen")}</button>
      </div>
      
      <div class="admin-danger-zone">
        <p class="admin-small-hint">${t("admin_planet_reset_hint", "Tippe RESET PLANET zur Bestätigung")}</p>
        <input type="text" class="admin-input" id="admin-planet-reset-confirm" placeholder="RESET PLANET" autocomplete="off">
        <button type="button" class="gc-btn gc-btn-danger gc-btn-sm" data-admin-action="planet-reset" data-planet-id="${pl.id}">${t("admin_btn_reset_planet", "Planet reset")}</button>
      </div>`;
    syncAdminHudSelects(el);
    focusAdminDetail(el);
  }

  async function loadAdminPlanet(id) {
    _selectedPlanetId = parseInt(id, 10) || null;
    markSelectedEntityRow("#admin-planets-list", "data-admin-planet-id", _selectedPlanetId);
    const data = await adminGet(`/api/admin/planet/${id}`);
    if (!data.ok) showAlert(data.message, "error");
    else renderPlanetDetail(data);
    return data;
  }

  async function loadAdminQueues() {
    const out = qs("#admin-queues-output");
    const pid = qs("#admin-queue-player-id")?.value;
    const plid = qs("#admin-queue-planet-id")?.value;
    const status = qs("#admin-queue-status")?.value || "all";
    const params = new URLSearchParams({ status });
    if (pid) params.set("player_id", pid);
    if (plid) params.set("planet_id", plid);
    if (out) out.innerHTML = loadingHtml();
    const data = await adminGet(`/api/admin/queues?${params}`);
    if (!data.ok) {
      showAlert(data.message, "error");
      if (out) out.innerHTML = errorCard(data);
      return data;
    }
    const cancelBtn = (type, id) =>
      `<button type="button" class="gc-btn gc-btn-danger gc-btn-xs" data-admin-action="queue-cancel" data-queue-type="${type}" data-job-id="${id}">${t("admin_btn_cancel", "Abbrechen")}</button>`;
    const bq = data.build_queue || [];
    const rq = data.research_queue || [];
    const sq = data.shipyard_queue || [];
    const dq = data.defense_queue || [];
    if (out) {
      out.innerHTML = `
        <div class="admin-card">
          <h3 class="admin-subtitle">${t("admin_build_queue", "Bau-Queue")} (${bq.length})</h3>
          ${renderTable(
            ["ID", "Planet", "Typ", "Status", ""],
            bq.map(
              (j) =>
                `<tr><td>${j.id}</td><td>${j.planet_id}</td><td>${esc(j.building_type)}</td><td>${esc(j.status)}</td><td>${cancelBtn("build", j.id)}</td></tr>`
            )
          )}
        </div>
        <div class="admin-card">
          <h3 class="admin-subtitle">${t("admin_research_queue", "Forschungs-Queue")} (${rq.length})</h3>
          ${renderTable(
            ["ID", "User", "Tech", "Status", ""],
            rq.map(
              (j) =>
                `<tr><td>${j.id}</td><td>${j.user_id}</td><td>${esc(j.tech_key)}</td><td>${esc(j.status)}</td><td>${cancelBtn("research", j.id)}</td></tr>`
            )
          )}
        </div>
        <div class="admin-card">
          <h3 class="admin-subtitle">${t("admin_shipyard_queue", "Werft-Queue")} (${sq.length})</h3>
          ${renderTable(
            ["ID", "Planet", "Schiff", "Menge", "Status", ""],
            sq.map(
              (j) =>
                `<tr><td>${j.id}</td><td>${j.planet_id}</td><td>${esc(j.ship_key)}</td><td>${j.amount || 1}</td><td>${esc(j.status)}</td><td>${cancelBtn("shipyard", j.id)}</td></tr>`
            )
          )}
        </div>
        <div class="admin-card">
          <h3 class="admin-subtitle">${t("admin_defense_queue", "Verteidigungs-Queue")} (${dq.length})</h3>
          ${renderTable(
            ["ID", "Planet", "Typ", "Menge", "Status", ""],
            dq.map(
              (j) =>
                `<tr><td>${j.id}</td><td>${j.planet_id}</td><td>${esc(j.defense_key)}</td><td>${j.amount || 1}</td><td>${esc(j.status)}</td><td>${cancelBtn("defense", j.id)}</td></tr>`
            )
          )}
        </div>
        <div class="admin-danger-zone">
          <p class="admin-small-hint">${t("admin_queue_clear_hint", "Tippe CLEAR QUEUE")}</p>
          <input type="text" class="admin-input" id="admin-queue-clear-confirm" placeholder="CLEAR QUEUE" autocomplete="off">
          <select ${ADMIN_SELECT_ATTRS} id="admin-queue-clear-scope">
            <option value="planet">${t("admin_filter_planet_id", "Planet")}</option>
            <option value="player">${t("admin_filter_player_id", "Player")}</option>
          </select>
          <button type="button" class="gc-btn gc-btn-danger gc-btn-sm" data-admin-action="queue-clear">${t("admin_btn_clear_queue", "Queue leeren")}</button>
        </div>`;
      syncAdminHudSelects(out);
    }
    return data;
  }

  async function cancelQueueJob(type, id) {
    const data = await adminPost(`/api/admin/queue/${type}/${id}/cancel`, {});
    if (data.ok) {
      notify(t("admin_action_success", "Erfolgreich"), "success");
      await syncAfterAdminChange("admin_queue_cancel");
    } else showAlert(data.message, "error");
    return data;
  }

  async function finishDueQueues() {
    const data = await adminPost("/api/admin/queues/finish-due", {});
    if (data.ok) {
      notify(t("admin_action_success", "Erfolgreich"), "success");
      await syncAfterAdminChange("admin_queues_finish_due");
    } else showAlert(data.message, "error");
    return data;
  }

  function formatTickSummary(finished, playersCount, durationMs) {
    const fin = finished || {};
    const tpl = t(
      "admin_tick_result_summary",
      "Gebäude: %(buildings)s · Forschung: %(research)s · Werft: %(shipyard)s · Verteidigung: %(defense)s · Spieler: %(players)s · Dauer: %(duration)s ms"
    );
    return tpl
      .replace("%(buildings)s", String(fin.buildings != null ? fin.buildings : 0))
      .replace("%(research)s", String(fin.research != null ? fin.research : 0))
      .replace("%(shipyard)s", String(fin.shipyard != null ? fin.shipyard : 0))
      .replace("%(defense)s", String(fin.defense != null ? fin.defense : 0))
      .replace("%(players)s", String(playersCount != null ? playersCount : 0))
      .replace("%(duration)s", String(durationMs != null ? durationMs : 0));
  }

  async function runQueueTick(triggerBtn) {
    const btn = triggerBtn || qs("#admin-btn-queue-tick");
    const resultEl = qs("#admin-queue-tick-result");
    if (resultEl) resultEl.textContent = t("admin_tick_running", "Tick läuft …");
    setBusy(btn, true);
    try {
      const data = await adminPost("/api/admin/queue-tick", {});
      if (!data || data.ok === false) {
        const msg = (data && (data.message || data.error)) || t("admin_tick_failed", "Queue-Tick fehlgeschlagen");
        showAlert(msg, "error");
        if (resultEl) resultEl.textContent = msg;
        return data || { ok: false, error: "tick_failed" };
      }
      const fin = data.finished || {};
      const players = Array.isArray(data.affected_players) ? data.affected_players.length : 0;
      const elapsed = data.tick_elapsed_ms != null ? data.tick_elapsed_ms : data.duration_ms;
      const derivedSync = data.derived_sync_count != null ? Number(data.derived_sync_count) : 0;
      let summary = formatTickSummary(fin, players, elapsed);
      summary += ` · ${t("admin_tick_derived_sync", "Derived sync")}: ${derivedSync}`;
      notify(t("admin_tick_success", "Queue-Tick abgeschlossen"), "success");
      if (resultEl) resultEl.textContent = summary;
      if ((data.errors || []).length) {
        showAlert((data.errors || []).join("\n"), "error");
      }
      await loadAdminRuntime();
      await syncAfterAdminChange("admin_queue_tick");
      return data;
    } catch (err) {
      const msg = err && err.message ? err.message : t("admin_tick_failed", "Queue-Tick fehlgeschlagen");
      showAlert(msg, "error");
      if (resultEl) resultEl.textContent = msg;
      return { ok: false, error: "tick_failed", message: msg };
    } finally {
      setBusy(btn, false);
    }
  }

  async function clearQueues() {
    const confirmText = qs("#admin-queue-clear-confirm")?.value || "";
    const scope = qs("#admin-queue-clear-scope")?.value || "planet";
    const body = { confirm_text: confirmText, scope, queue_type: "both" };
    if (scope === "planet") body.planet_id = qs("#admin-queue-planet-id")?.value;
    else body.player_id = qs("#admin-queue-player-id")?.value;
    const data = await adminPost("/api/admin/queues/clear", body);
    if (data.ok) {
      notify(t("admin_action_success", "Erfolgreich"), "success");
      await syncAfterAdminChange("admin_queue_clear");
    } else showAlert(data.message, "error");
    return data;
  }

  async function loadAuditLog() {
    const out = qs("#admin-audit-output");
    const params = new URLSearchParams();
    const aid = qs("#admin-audit-admin-id")?.value;
    const action = qs("#admin-audit-action")?.value;
    if (aid) params.set("admin_id", aid);
    if (action) params.set("action", action);
    if (out) out.innerHTML = loadingHtml();
    const data = await adminGet(`/api/admin/audit-log?${params}`);
    if (!data.ok) {
      showAlert(data.message, "error");
      if (out) out.innerHTML = errorCard(data);
      return data;
    }
    const rows = (data.entries || []).map(
      (e) => `<tr>
        <td>${e.id}</td><td>${esc(fmtTs(e.created_at))}</td><td>${esc(e.admin_username || e.admin_id)}</td>
        <td>${esc(e.action)}</td><td>${esc(e.target_type || "")} ${esc(e.target_id || "")}</td>
        <td><code class="admin-payload">${esc(JSON.stringify(e.payload || {}))}</code></td>
      </tr>`
    );
    if (out) {
      out.innerHTML = renderTable(
        ["ID", t("admin_col_time", "Zeit"), "Admin", "Action", "Target", "Payload"],
        rows
      );
    }
    return data;
  }

  async function loadAdminRuntime() {
    const out = qs("#admin-runtime-output");
    if (out) out.innerHTML = loadingHtml();
    const data = await adminGet("/api/admin/runtime");
    if (!data.ok) {
      showAlert(data.message, "error");
      if (out) out.innerHTML = errorCard(data);
      return data;
    }
    const r = data.runtime || {};
    const qt = r.queue_tick || {};
    const fin = qt.finished || {};
    const tickAtRaw = qt.last_tick_at != null ? qt.last_tick_at : qt.last_at;
    const tickSource = qt.last_tick_source != null ? qt.last_tick_source : qt.source;
    const tickDuration =
      qt.last_tick_duration_ms != null ? qt.last_tick_duration_ms : qt.duration_ms;
    const playersCount =
      qt.affected_players_count != null
        ? qt.affected_players_count
        : (qt.affected_players || []).length;
    const errorsCount = qt.errors_count != null ? qt.errors_count : (qt.errors || []).length;
    _isProduction = !!r.production;
    if (out) {
      const tickAt = tickAtRaw
        ? new Date(Number(tickAtRaw) * 1000).toLocaleString()
        : t("admin_tick_never", "—");
      const tickOk =
        qt.ok === true
          ? t("admin_tick_ok", "OK")
          : qt.ok === false
            ? t("admin_tick_error", "Fehler")
            : t("admin_tick_unknown", "—");
      out.innerHTML = `
        
        <div class="admin-kpi-grid">
          ${[
            ["Python", r.python],
            ["Version", r.version],
            ["APP_ENV", r.app_env],
            ["Production", r.production ? "yes" : "no"],
            ["Debug", r.debug ? "ON" : "OFF"],
            ["DB Backend", r.db_backend],
            ["DB Path", r.db_path],
          ]
            .map(
              ([k, v]) => `<div class="admin-kpi-card admin-card"><div class="admin-metric-label">${esc(k)}</div><div class="admin-metric-value">${esc(v)}</div></div>`
            )
            .join("")}
        </div>
        <div class="admin-section-title">
          <span class="admin-section-title-text">${esc(t("admin_queue_tick_title", "Queue-Tick (Cron/Worker)"))}</span>
        </div>
        <div class="admin-kpi-grid">
          ${[
            [t("admin_tick_last", "Letzter Queue-Tick"), tickAt],
            [t("admin_tick_status", "Status"), tickOk],
            [t("admin_tick_source", "Quelle"), tickSource || "—"],
            [t("admin_tick_duration", "Dauer"), tickDuration != null ? `${tickDuration} ms` : "—"],
            [t("admin_tick_buildings", "Gebäude"), fin.buildings != null ? fin.buildings : 0],
            [t("admin_tick_research", "Forschung"), fin.research != null ? fin.research : 0],
            [t("admin_tick_shipyard", "Werft"), fin.shipyard != null ? fin.shipyard : 0],
            [t("admin_tick_defense", "Verteidigung"), fin.defense != null ? fin.defense : 0],
            [t("admin_tick_affected_players", "Betroffene Spieler"), playersCount],
            [t("admin_tick_batches", "Batches"), qt.batches != null ? qt.batches : 0],
            [t("admin_tick_errors_count", "Fehler (Anzahl)"), errorsCount],
          ]
            .map(
              ([k, v]) => `<div class="admin-kpi-card admin-card"><div class="admin-metric-label">${esc(k)}</div><div class="admin-metric-value">${esc(v)}</div></div>`
            )
            .join("")}
        </div>
        ${
          (qt.errors || []).length
            ? `<div class="admin-alert admin-alert-error"><strong>${esc(t("admin_tick_errors", "Fehler"))}</strong><pre class="admin-pre">${esc((qt.errors || []).join("\n"))}</pre></div>`
            : ""
        }`;
    }
    return data;
  }

  function renderAdminSupportDetail(ticket) {
    const out = qs("#admin-support-detail");
    if (!out) return;
    if (!ticket) {
      out.innerHTML = `<p class="admin-small-hint">${esc(t("admin_support_select_hint", "Ticket aus der Liste waehlen."))}</p>`;
      return;
    }
    const msgs = (ticket.messages || [])
      .map(
        (m) => `
        <div class="admin-support-msg">
          <div class="admin-support-msg-meta">${esc(m.sender_name || m.sender_role)} · ${esc(fmtTs(m.created_at))}</div>
          <div>${esc(m.message)}</div>
        </div>`
      )
      .join("");
    out.innerHTML = `
      <h3 class="admin-subtitle">#${ticket.id} · ${esc(ticket.subject)}</h3>
      <p class="admin-small-hint">
        ${playerNameLink(ticket.player_id, ticket.player_name)} ·
        ${esc(ticket.status_label || ticket.status)} ·
        ${esc(ticket.priority_label || ticket.priority)} ·
        ${esc(ticket.category_label || ticket.category)}
      </p>
      <div class="admin-support-timeline">${msgs || `<p class="admin-small-hint">${esc(t("admin_support_no_messages", "Keine Nachrichten."))}</p>`}</div>
      <label class="admin-label">${esc(t("admin_support_reply_label", "Antwort an Spieler"))}</label>
      <textarea class="admin-input" id="admin-support-reply-body" rows="3" maxlength="1200"></textarea>
      <div class="admin-toolbar admin-action-row-wrap">
        <button type="button" class="gc-btn gc-btn-primary gc-btn-sm" data-admin-action="support-reply" data-ticket-id="${ticket.id}">
          ${esc(t("admin_support_reply_btn", "Antwort senden"))}
        </button>
        <select ${ADMIN_SELECT_ATTRS} id="admin-support-status-set">
          <option value="open" ${ticket.status === "open" ? "selected" : ""}>${esc(t("admin_support_status_open", "Offen"))}</option>
          <option value="in_progress" ${ticket.status === "in_progress" ? "selected" : ""}>${esc(t("admin_support_status_progress", "In Bearbeitung"))}</option>
          <option value="closed" ${ticket.status === "closed" ? "selected" : ""}>${esc(t("admin_support_status_closed", "Geschlossen"))}</option>
        </select>
        <button type="button" class="gc-btn gc-btn-outline gc-btn-sm" data-admin-action="support-set-status" data-ticket-id="${ticket.id}">
          ${esc(t("admin_support_status_btn", "Status setzen"))}
        </button>
      </div>`;
    syncAdminHudSelects(out);
  }

  async function loadAdminSupport() {
    const listOut = qs("#admin-support-list");
    if (!listOut) return null;
    listOut.innerHTML = loadingHtml();
    const status = (qs("#admin-support-status-filter")?.value || "").trim();
    const q = status ? `?status=${encodeURIComponent(status)}` : "";
    const data = await adminGet(`/api/admin/support/tickets${q}`);
    if (!data.ok) {
      showAlert(data.message || t("admin_action_failed", "Fehler"), "error");
      listOut.innerHTML = errorCard(data);
      return data;
    }
    const tickets = data.data?.tickets || [];
    if (!tickets.length) {
      listOut.innerHTML = `<p class="admin-small-hint">${esc(t("admin_support_empty", "Keine Tickets."))}</p>`;
      renderAdminSupportDetail(null);
      return data;
    }
    listOut.innerHTML = renderTable(
      [
        { label: "ID", className: "col-id" },
        { label: t("admin_support_col_player", "Spieler"), className: "col-name" },
        { label: t("admin_support_col_subject", "Betreff"), className: "col-subject" },
        { label: t("admin_support_col_status", "Status"), className: "col-status" },
        { label: t("admin_support_col_updated", "Aktualisiert"), className: "col-date" },
      ],
      tickets.map(
        (tk) => `<tr class="admin-support-ticket-row${_selectedSupportTicketId === tk.id ? " is-active" : ""}"
                data-admin-support-ticket-id="${tk.id}">
              <td class="col-id">${tk.id}</td>
              <td class="col-name">${playerNameLink(tk.player_id, tk.player_name)}</td>
              <td class="col-subject">${esc(tk.subject)}</td>
              <td class="col-status">${esc(tk.status_label || tk.status)}</td>
              <td class="col-date">${esc(fmtTs(tk.last_message_at || tk.updated_at))}</td>
            </tr>`
      ),
      { inline: true }
    );
    const selected =
      tickets.find((tk) => tk.id === _selectedSupportTicketId) || tickets[0];
    _selectedSupportTicketId = selected?.id || null;
    renderAdminSupportDetail(selected || null);
    return data;
  }

  function renderAdminMessageDetail(msg) {
    const out = qs("#admin-messages-detail");
    if (!out) return;
    if (!msg) {
      out.innerHTML = `<p class="admin-small-hint">${esc(t("admin_messages_select_hint", "Nachricht aus der Liste waehlen."))}</p>`;
      return;
    }
    out.innerHTML = `
      <h3 class="admin-subtitle">#${msg.id} · ${esc(msg.subject)}</h3>
      <p class="admin-small-hint">
        ${esc(t("admin_messages_col_recipient", "Empfaenger"))}:
        ${playerNameLink(msg.recipient_player_id, msg.recipient_name || `#${msg.recipient_player_id}`)}
        · ${esc(t(`messages.category.${msg.category}`, msg.category))}
        · ${esc(msg.is_read ? t("messages.read", "Gelesen") : t("messages.unread", "Ungelesen"))}
        · ${esc(fmtTs(msg.created_at))}
      </p>
      <p class="admin-small-hint">
        ${esc(t("admin_messages_col_sender", "Absender"))}: ${esc(msg.sender_name || "—")}
      </p>
      <div class="admin-support-msg">
        <div class="admin-support-msg-body">${esc(msg.body)}</div>
      </div>`;
  }

  async function loadAdminMessages() {
    const listOut = qs("#admin-messages-list");
    if (!listOut) return null;
    listOut.innerHTML = loadingHtml();

    const playerRaw = (qs("#admin-messages-player-filter")?.value || "").trim();
    const category = (qs("#admin-messages-category-filter")?.value || "").trim();
    const params = new URLSearchParams();
    if (playerRaw) params.set("player_id", playerRaw);
    if (category) params.set("category", category);
    const q = params.toString() ? `?${params.toString()}` : "";

    const data = await adminGet(`/api/admin/messages${q}`);
    if (!data.ok) {
      showAlert(data.error || data.message || t("admin_action_failed", "Fehler"), "error");
      listOut.innerHTML = errorCard(data);
      return data;
    }

    const messages = data.data?.messages || [];
    if (!messages.length) {
      listOut.innerHTML = `<p class="admin-small-hint">${esc(t("admin_messages_empty", "Keine Nachrichten."))}</p>`;
      renderAdminMessageDetail(null);
      return data;
    }

    listOut.innerHTML = renderTable(
      [
        { label: "ID", className: "col-id" },
        { label: t("admin_messages_col_recipient", "Empfaenger"), className: "col-name" },
        { label: t("admin_messages_col_subject", "Betreff"), className: "col-subject" },
        { label: t("messages.category.system", "Kat."), className: "col-cat" },
        { label: t("admin_messages_col_date", "Datum"), className: "col-date" },
      ],
      messages.map(
        (m) => `<tr class="admin-support-ticket-row${_selectedAdminMessageId === m.id ? " is-active" : ""}"
                data-admin-message-id="${m.id}">
              <td class="col-id">${m.id}</td>
              <td class="col-name">${playerNameLink(m.recipient_player_id, m.recipient_name || `#${m.recipient_player_id}`)}</td>
              <td class="col-subject">${esc(m.subject)}</td>
              <td class="col-cat">${esc(t(`messages.category.${m.category}`, m.category))}</td>
              <td class="col-date">${esc(fmtTs(m.created_at))}</td>
            </tr>`
      ),
      { inline: true }
    );

    if (_selectedAdminMessageId) {
      const hit = messages.find((m) => m.id === _selectedAdminMessageId);
      if (hit) {
        renderAdminMessageDetail(hit);
        return data;
      }
    }
    _selectedAdminMessageId = messages[0]?.id || null;
    renderAdminMessageDetail(messages[0] || null);
    return data;
  }

  async function loadAdminMessageDetail(messageId) {
    const data = await adminGet(`/api/admin/messages/${messageId}`);
    if (!data.ok) {
      showAlert(data.error || t("admin_action_failed", "Fehler"), "error");
      return data;
    }
    renderAdminMessageDetail(data.data?.message || null);
    return data;
  }

  async function adminMessagesSend() {
    const recipient = (qs("#admin-messages-send-recipient")?.value || "").trim();
    const subject = (qs("#admin-messages-send-subject")?.value || "").trim();
    const body = (qs("#admin-messages-send-body")?.value || "").trim();
    if (!recipient || !subject || !body) {
      showAlert(t("messages.error_validation", "Eingabe ungueltig."), "error");
      return null;
    }
    const payload = { recipient, subject, body, category: "admin" };
    if (/^\d+$/.test(recipient)) payload.recipient_id = parseInt(recipient, 10);
    const res = await adminPost("/api/admin/messages/send", payload);
    if (res.ok) {
      notify(t("admin_messages_send_ok", "Admin-Nachricht gesendet."), "success");
      if (qs("#admin-messages-send-subject")) qs("#admin-messages-send-subject").value = "";
      if (qs("#admin-messages-send-body")) qs("#admin-messages-send-body").value = "";
      await loadAdminMessages();
    } else {
      showAlert(res.error || res.message || t("admin_action_failed", "Fehler"), "error");
    }
    return res;
  }

  async function adminSupportReply(ticketId) {
    const body = (qs("#admin-support-reply-body")?.value || "").trim();
    if (!body) {
      showAlert(t("admin_support_reply_empty", "Antwort eingeben."), "error");
      return null;
    }
    const res = await adminPost(`/api/admin/support/tickets/${ticketId}/reply`, { message: body });
    if (res.ok) {
      notify(t("admin_support_reply_ok", "Antwort gesendet."), "success");
      _selectedSupportTicketId = ticketId;
      return loadAdminSupport();
    }
    showAlert(res.message, "error");
    return res;
  }

  async function adminSupportSetStatus(ticketId) {
    const status = qs("#admin-support-status-set")?.value || "open";
    const res = await adminPost(`/api/admin/support/tickets/${ticketId}/status`, { status });
    if (res.ok) {
      notify(t("admin_support_status_ok", "Status aktualisiert."), "success");
      _selectedSupportTicketId = ticketId;
      return loadAdminSupport();
    }
    showAlert(res.message, "error");
    return res;
  }

  async function loadAdminChat() {
    const out = qs("#admin-chat-search-output");
    if (out && !out.innerHTML.trim()) {
      out.innerHTML = `<p class="admin-small-hint">${esc(t("admin_chat_search_hint", "Nachrichten durchsuchen…"))}</p>`;
    }
    return null;
  }

  async function searchAdminChatMessages() {
    const out = qs("#admin-chat-search-output");
    const q = (qs("#admin-chat-search-q")?.value || "").trim();
    if (!out) return null;
    if (q.length < 2) {
      showAlert(t("admin_chat_search_min", "Mindestens 2 Zeichen."), "error");
      return null;
    }
    out.innerHTML = loadingHtml();
    const data = await adminGet(`/api/chat/admin/search?q=${encodeURIComponent(q)}&limit=50`);
    if (!data.ok) {
      showAlert(data.message || t("admin_action_failed", "Fehler"), "error");
      out.innerHTML = errorCard(data);
      return data;
    }
    const rows = data.data?.messages || [];
    if (!rows.length) {
      out.innerHTML = `<p class="admin-small-hint">${esc(t("admin_chat_search_empty", "Keine Treffer."))}</p>`;
      return data;
    }
    out.innerHTML = `
      <table class="admin-table">
        <thead><tr>
          <th>ID</th><th>${esc(t("admin_chat_col_room", "Raum"))}</th>
          <th>${esc(t("admin_chat_col_sender", "Sender"))}</th>
          <th>${esc(t("admin_chat_col_message", "Nachricht"))}</th>
          <th></th>
        </tr></thead>
        <tbody>
          ${rows.map((m) => `
            <tr>
              <td>${m.id}</td>
              <td>${esc(m.room_title || m.room_key)}</td>
              <td>${m.sender_id ? playerNameLink(m.sender_id, m.sender_name) : esc("System")}</td>
              <td>${m.is_deleted ? `<em>${esc(t("chat_message_deleted", "Entfernt"))}</em>` : esc(m.message)}</td>
              <td>${m.is_deleted ? "" : `<button type="button" class="gc-btn gc-btn-danger gc-btn-xs" data-admin-action="chat-delete-msg" data-message-id="${m.id}">${esc(t("admin_chat_delete_btn", "Löschen"))}</button>`}</td>
            </tr>`).join("")}
        </tbody>
      </table>`;
    return data;
  }

  async function handleAction(act, btn) {
    if (act === "refresh-health") return loadAdminHealth();
    if (act === "refresh-migrations") return loadAdminMigrations();
    if (act === "run-migrations") return runAdminMigrations();
    if (act === "search-players") return searchAdminPlayers();
    if (act === "search-planets") return searchAdminPlanets();
    if (act === "load-queues") return loadAdminQueues();
    if (act === "finish-due") return finishDueQueues();
    if (act === "load-audit") return loadAuditLog();
    if (act === "chat-search") return searchAdminChatMessages();
    if (act === "support-refresh") return loadAdminSupport();
    if (act === "messages-refresh") return loadAdminMessages();
    if (act === "messages-send") return adminMessagesSend();
    if (act === "support-reply") {
      const tid = parseInt(btn.dataset.ticketId, 10);
      if (!Number.isFinite(tid)) return null;
      return adminSupportReply(tid);
    }
    if (act === "support-set-status") {
      const tid = parseInt(btn.dataset.ticketId, 10);
      if (!Number.isFinite(tid)) return null;
      return adminSupportSetStatus(tid);
    }
    if (act === "chat-system-notice") {
      const body = (qs("#admin-chat-notice-body")?.value || "").trim();
      if (!body) {
        showAlert(t("chat_error_empty_message", "Leere Nachricht."), "error");
        return null;
      }
      const res = await adminPost("/api/chat/admin/system-notice", { body });
      if (res.ok) {
        notify(t("admin_chat_notice_sent", "System-Meldung gesendet."), "success");
        if (qs("#admin-chat-notice-body")) qs("#admin-chat-notice-body").value = "";
      } else showAlert(res.message, "error");
      return res;
    }
    if (act === "chat-mute-player") {
      const pid = parseInt(qs("#admin-chat-mod-player")?.value, 10);
      const mins = parseInt(qs("#admin-chat-mute-minutes")?.value, 10) || 60;
      if (!Number.isFinite(pid) || pid <= 0) {
        showAlert(t("admin_chat_mute_invalid", "Ungültige Spieler-ID."), "error");
        return null;
      }
      const res = await adminPost("/api/chat/admin/mute", {
        player_id: pid,
        scope: qs("#admin-chat-mute-scope")?.value || "global",
        muted_until: Math.floor(Date.now() / 1000) + mins * 60,
        reason: qs("#admin-chat-mod-reason")?.value || "",
      });
      if (res.ok) notify(t("admin_chat_mute_ok", "Spieler stummgeschaltet."), "success");
      else showAlert(res.message, "error");
      return res;
    }
    if (act === "chat-ban-player") {
      const pid = parseInt(qs("#admin-chat-mod-player")?.value, 10);
      if (!Number.isFinite(pid) || pid <= 0) {
        showAlert(t("admin_chat_mute_invalid", "Ungültige Spieler-ID."), "error");
        return null;
      }
      const res = await adminPost("/api/chat/admin/ban", {
        player_id: pid,
        reason: qs("#admin-chat-mod-reason")?.value || "",
      });
      if (res.ok) notify(t("admin_chat_ban_ok", "Spieler aus Chat gebannt."), "success");
      else showAlert(res.message, "error");
      return res;
    }
    if (act === "chat-unban-player") {
      const pid = parseInt(qs("#admin-chat-mod-player")?.value, 10);
      if (!Number.isFinite(pid) || pid <= 0) {
        showAlert(t("admin_chat_mute_invalid", "Ungültige Spieler-ID."), "error");
        return null;
      }
      const res = await adminPost("/api/chat/admin/unban", { player_id: pid });
      if (res.ok) notify(t("admin_chat_unban_ok", "Chat-Ban aufgehoben."), "success");
      else showAlert(res.message, "error");
      return res;
    }
    if (act === "chat-unmute-player") {
      const pid = parseInt(qs("#admin-chat-mod-player")?.value, 10);
      if (!Number.isFinite(pid) || pid <= 0) {
        showAlert(t("admin_chat_mute_invalid", "Ungültige Spieler-ID."), "error");
        return null;
      }
      const res = await adminPost("/api/chat/admin/unmute", { player_id: pid });
      if (res.ok) notify(t("admin_chat_unmute_ok", "Stummschaltung aufgehoben."), "success");
      else showAlert(res.message, "error");
      return res;
    }
    if (act === "chat-delete-msg") {
      const mid = parseInt(btn.dataset.messageId, 10);
      if (!Number.isFinite(mid)) return null;
      const res = await adminPost("/api/chat/admin/delete-message", { message_id: mid });
      if (res.ok) {
        notify(t("admin_chat_deleted", "Nachricht gelöscht."), "success");
        return searchAdminChatMessages();
      }
      showAlert(res.message, "error");
      return res;
    }
    if (act === "refresh-runtime") return loadAdminRuntime();
    if (act === "balance-save") return saveAdminBalance();
    if (act === "balance-preset-b") return applyBalancePresetB();
    if (act === "balance-recalculate") return recalculateAdminRankings();
    if (act === "combat-hof-backfill") return backfillCombatHof();
    if (act === "server-save") return saveAdminServer();
    if (act === "server-resources") return applyAdminResources();
    if (act === "server-wipe") return wipeAdminUniverse();
    if (act === "run-queue-tick") return runQueueTick(btn);
    if (act === "queue-cancel") return cancelQueueJob(btn.dataset.queueType, btn.dataset.jobId);
    if (act === "queue-clear") return clearQueues();

    if (act === "player-set-admin") {
      const body = { is_admin: btn.dataset.isAdmin === "1" ? 1 : 0 };
      if (body.is_admin === 0) {
        const c = prompt(t("admin_confirm_remove_admin", "Tippe REMOVE ADMIN"));
        if (c !== "REMOVE ADMIN") return null;
        body.confirm_text = c;
      }
      const res = await adminPost(`/api/admin/player/${btn.dataset.playerId}/set-admin`, body);
      if (res.ok) {
        notify(t("admin_action_success", "OK"), "success");
        await searchAdminPlayers();
        await syncAfterAdminChange("admin_player_set_admin");
      } else showAlert(res.message, "error");
      return res;
    }
    if (act === "player-ban") {
      const c = prompt(t("admin_confirm_ban", "Tippe BAN PLAYER"));
      if (c !== "BAN PLAYER") return null;
      const res = await adminPost(`/api/admin/player/${btn.dataset.playerId}/ban`, {
        confirm_text: c,
        reason: "admin panel",
        hours: 24,
      });
      if (res.ok) {
        notify(t("admin_action_success", "OK"), "success");
        await loadAdminBans();
        await syncAfterAdminChange("admin_player_ban");
      } else showAlert(res.message, "error");
      return res;
    }
    if (act === "ban-player-form") {
      const playerId = parseInt(qs("#admin-ban-player-id")?.value, 10);
      if (!Number.isFinite(playerId) || playerId <= 0) {
        showAlert(t("admin_ban_invalid_id", "Ungültige Spieler-ID."), "error");
        return null;
      }
      const c = prompt(t("admin_confirm_ban", "Tippe BAN PLAYER"));
      if (c !== "BAN PLAYER") return null;
      const hoursRaw = qs("#admin-ban-hours")?.value;
      const hours = hoursRaw === "" || hoursRaw == null ? 24 : parseInt(hoursRaw, 10);
      const res = await adminPost(`/api/admin/player/${playerId}/ban`, {
        confirm_text: c,
        reason: (qs("#admin-ban-reason")?.value || "").trim(),
        hours: Number.isFinite(hours) ? hours : 24,
      });
      if (res.ok) {
        notify(t("admin_action_success", "OK"), "success");
        await loadAdminBans();
        if (qs("#admin-ban-player-id")) qs("#admin-ban-player-id").value = "";
        await syncAfterAdminChange("admin_player_ban");
      } else showAlert(res.message, "error");
      return res;
    }
    if (act === "player-unban") {
      const res = await adminPost(`/api/admin/player/${btn.dataset.playerId}/unban`, {});
      if (res.ok) {
        notify(t("admin_action_success", "OK"), "success");
        await loadAdminBans();
        await syncAfterAdminChange("admin_player_unban");
      } else showAlert(res.message, "error");
      return res;
    }
    if (act === "player-effects") {
      const pid = btn.dataset.playerId;
      const data = await adminGet(`/api/admin/player/${pid}/effects`);
      if (!data.ok) {
        showAlert(data.message || data.error, "error");
        return data;
      }
      const el = qs("#admin-player-detail");
      if (!el) return data;
      let box = qs("#admin-player-effects", el);
      if (!box) {
        box = document.createElement("details");
        box.id = "admin-player-effects";
        box.className = "admin-buildings-detail";
        box.innerHTML = `<summary>${esc(t("admin_effects_debug", "Effekt-Debug"))}</summary><pre></pre>`;
        el.appendChild(box);
      }
      const pre = box.querySelector("pre");
      if (pre) pre.textContent = JSON.stringify(data.effects || data, null, 2);
      box.open = true;
      return data;
    }
    if (act === "player-repair-hw") {
      const res = await adminPost(`/api/admin/player/${btn.dataset.playerId}/repair-homeworld`, {});
      if (res.ok) {
        notify(t("admin_action_success", "OK"), "success");
        await syncAfterAdminChange("admin_repair_homeworld");
      }
      return res;
    }
    if (act === "player-resources-add" || act === "player-resources-set") {
      const mode = act.endsWith("set") ? "set" : "add";
      const res = await adminPost(`/api/admin/player/${btn.dataset.playerId}/resources`, {
        mode,
        metal: qs("#admin-player-metal")?.value || 0,
        crystal: qs("#admin-player-crystal")?.value || 0,
        fuel_cells: qs("#admin-player-fuel")?.value || 0,
      });
      if (res.ok) {
        notify(t("admin_action_success", "OK"), "success");
        await syncAfterAdminChange("admin_player_resources");
      } else showAlert(res.message, "error");
      return res;
    }
    if (act === "player-inventory-grant" || act === "player-inventory-grant-quick") {
      const playerId = btn.dataset.playerId || qs("#admin-lootbox-player-id")?.value;
      if (!playerId) {
        showAlert(t("admin_lootboxes_player_id_required", "Spieler-ID eingeben."), "error");
        return null;
      }
      const itemKey =
        act === "player-inventory-grant-quick"
          ? btn.dataset.itemKey
          : qs("#admin-lootbox-player-inv-key")?.value || qs("#admin-player-inv-key")?.value;
      const amount =
        act === "player-inventory-grant-quick"
          ? parseInt(btn.dataset.amount || "1", 10)
          : parseInt(
              qs("#admin-lootbox-player-inv-amount")?.value ||
                qs("#admin-player-inv-amount")?.value ||
                "1",
              10
            );
      const useLootboxApi = !!qs("#admin-lootbox-grant-player");
      const res = useLootboxApi
        ? await adminPost("/api/admin/lootboxes/grant-player", {
            player_id: playerId,
            item_key: itemKey,
            amount: Number.isFinite(amount) ? amount : 1,
          })
        : await adminPost(`/api/admin/player/${playerId}/inventory-grant`, {
            item_key: itemKey,
            amount: Number.isFinite(amount) ? amount : 1,
          });
      if (res.ok) {
        notify(t("admin_inventory_grant_ok", "Lootbox vergeben"), "success");
        if (btn.dataset.playerId) return loadAdminPlayer(playerId);
        return res;
      }
      showAlert(res.message || res.error, "error");
      return res;
    }
    if (act === "inventory-grant-all" || act === "inventory-grant-all-quick") {
      const itemKey =
        act === "inventory-grant-all-quick"
          ? btn.dataset.itemKey
          : qs("#admin-lootbox-all-inv-key")?.value || qs("#admin-all-inv-key")?.value;
      const amount =
        act === "inventory-grant-all-quick"
          ? parseInt(btn.dataset.amount || "1", 10)
          : parseInt(
              qs("#admin-lootbox-all-inv-amount")?.value || qs("#admin-all-inv-amount")?.value || "1",
              10
            );
      const selectEl = qs("#admin-lootbox-all-inv-key") || qs("#admin-all-inv-key");
      const safeAmount = Number.isFinite(amount) ? amount : 1;
      const itemLabel =
        selectEl?.querySelector(`option[value="${CSS.escape(itemKey || "")}"]`)?.textContent ||
        itemKey ||
        "?";
      const confirmMsg = t(
        "admin_inventory_grant_all_confirm",
        `Wirklich ${safeAmount}× ${itemLabel} an alle Spieler vergeben?`
      )
        .replace("%(amount)s", String(safeAmount))
        .replace("%(item)s", itemLabel);
      if (!window.confirm(confirmMsg)) return null;
      const grantUrl = qs("#admin-lootbox-grant-all")
        ? "/api/admin/lootboxes/grant-all"
        : "/api/admin/inventory/grant-all";
      const res = await adminPost(grantUrl, {
        item_key: itemKey,
        amount: safeAmount,
      });
      if (res.ok) {
        const okMsg = t("admin_inventory_grant_all_ok", "An %(count)s Spieler vergeben").replace(
          "%(count)s",
          String(res.granted_count || res.player_count || 0)
        );
        notify(okMsg, "success");
        return res;
      }
      showAlert(res.message || res.error, "error");
      return res;
    }
    if (act === "loot-pool-select") {
      return null;
    }
    if (act === "loot-pool-add-row") {
      const tbody = qs("#admin-lootbox-pool-rows");
      if (!tbody) return null;
      const idx = qsa("tr[data-pool-row]", tbody).length;
      const row = document.createElement("tr");
      row.dataset.poolRow = String(idx);
      row.innerHTML =
        `<td><input type="number" min="1" class="admin-input admin-input-sm" data-field="weight" value="10"></td>` +
        `<td><select ${ADMIN_SELECT_ATTRS} data-field="reward_type">${lootPoolRewardTypeOptions("resource")}</select></td>` +
        `<td><select ${ADMIN_SELECT_ATTRS} data-field="reward_key">${lootPoolRewardKeyOptions("resource", "metal")}</select></td>` +
        `<td><input type="number" min="1" class="admin-input admin-input-sm" data-field="min_amount" value="1"></td>` +
        `<td><input type="number" min="1" class="admin-input admin-input-sm" data-field="max_amount" value="1"></td>` +
        `<td class="text-right"><button type="button" class="gc-btn gc-btn-outline gc-btn-xs" data-admin-action="loot-pool-row-delete" data-row="${idx}">×</button></td>`;
      tbody.appendChild(row);
      syncAdminHudSelects(row);
      return null;
    }
    if (act === "loot-pool-row-delete") {
      const tbody = qs("#admin-lootbox-pool-rows");
      const row = btn.closest("tr[data-pool-row]");
      if (tbody && row) row.remove();
      return null;
    }
    if (act === "loot-pool-save") {
      const containerKey = qs("#admin-lootbox-pool-container")?.value || _lootboxSelectedContainer;
      if (!containerKey) return null;
      const res = await adminPost("/api/admin/lootboxes/pools/save", {
        container_key: containerKey,
        entries: collectLootPoolEditorRows(),
      });
      if (res.ok) {
        notify(t("admin_lootboxes_pool_save_ok", "Loot-Pool gespeichert"), "success");
        if (_lootboxAdminState && res.pool) {
          _lootboxAdminState.pools[containerKey] = res.pool;
        }
        renderLootPoolEditor(containerKey);
        return res;
      }
      showAlert(res.message || res.error, "error");
      return res;
    }
    if (act === "loot-pool-reset") {
      const containerKey = qs("#admin-lootbox-pool-container")?.value || _lootboxSelectedContainer;
      if (!containerKey) return null;
      const label =
        qs(`#admin-lootbox-pool-container option[value="${CSS.escape(containerKey)}"]`)?.textContent ||
        containerKey;
      if (
        !window.confirm(
          t("admin_lootboxes_pool_reset_confirm", "Standard-Pool für %(container)s wiederherstellen?").replace(
            "%(container)s",
            label
          )
        )
      ) {
        return null;
      }
      const res = await adminPost("/api/admin/lootboxes/pools/reset", { container_key: containerKey });
      if (res.ok) {
        notify(t("admin_lootboxes_pool_reset_ok", "Standard-Pool wiederhergestellt"), "success");
        if (_lootboxAdminState && res.pool) {
          _lootboxAdminState.pools[containerKey] = res.pool;
        }
        renderLootPoolEditor(containerKey);
        return res;
      }
      showAlert(res.message || res.error, "error");
      return res;
    }
    if (act === "planet-resources-set") {
      const res = await adminPost(`/api/admin/planet/${btn.dataset.planetId}/resources`, {
        mode: "set",
        metal: qs("#admin-planet-metal")?.value || 0,
        crystal: qs("#admin-planet-crystal")?.value || 0,
        fuel_cells: qs("#admin-planet-fuel")?.value || 0,
      });
      if (res.ok) {
        notify(t("admin_action_success", "OK"), "success");
        await searchAdminPlanets();
        await syncAfterAdminChange("admin_planet_resources");
      } else showAlert(res.message, "error");
      return res;
    }
    if (act === "planet-building-set") {
      const res = await adminPost(`/api/admin/planet/${btn.dataset.planetId}/building`, {
        building_type: qs("#admin-planet-building-type")?.value,
        level: qs("#admin-planet-building-level")?.value || 0,
      });
      if (res.ok) {
        notify(t("admin_action_success", "OK"), "success");
        await syncAfterAdminChange("admin_planet_building");
      } else showAlert(res.message, "error");
      return res;
    }
    if (act === "planet-reset") {
      const res = await adminPost(`/api/admin/planet/${btn.dataset.planetId}/reset`, {
        confirm_text: qs("#admin-planet-reset-confirm")?.value || "",
      });
      if (res.ok) {
        notify(t("admin_action_success", "OK"), "success");
        await searchAdminPlanets();
        await syncAfterAdminChange("admin_planet_reset");
      } else showAlert(res.message, "error");
      return res;
    }
    return null;
  }

  function adminRoot() {
    return qs("#admin-control-center");
  }

  function isAdminEvent(e) {
    const root = adminRoot();
    return root && root.contains(e.target);
  }

  function bindAdminPanelOnce() {
    if (window._GC_ADMIN_EVENTS_BOUND) return;
    window._GC_ADMIN_EVENTS_BOUND = true;

    document.addEventListener("click", async (e) => {
      if (!isAdminEvent(e)) return;

      const tab = e.target.closest(".admin-tab-btn, .admin-cc-tab");
      if (tab && tab.dataset.adminTab) {
        switchTab(tab.dataset.adminTab);
        await loadTab(tab.dataset.adminTab);
        return;
      }

      const btn = e.target.closest("[data-admin-action]");
      if (btn) {
        e.preventDefault();
        if (btn.dataset.busy === "1") return;
        setBusy(btn, true);
        try {
          await handleAction(btn.dataset.adminAction, btn);
        } catch (err) {
          console.error("[admin]", err);
          showAlert(err.message || String(err), "error");
        } finally {
          setBusy(btn, false);
        }
        return;
      }

      const pRow = e.target.closest("tr[data-admin-player-id]");
      if (pRow) {
        await loadAdminPlayer(pRow.dataset.adminPlayerId);
        return;
      }
      const plRow = e.target.closest("tr[data-admin-planet-id]");
      if (plRow) {
        await loadAdminPlanet(plRow.dataset.adminPlanetId);
        return;
      }

      const supportRow = e.target.closest("[data-admin-support-ticket-id]");
      if (supportRow) {
        _selectedSupportTicketId = parseInt(supportRow.dataset.adminSupportTicketId, 10);
        await loadAdminSupport();
        return;
      }

      const msgRow = e.target.closest("[data-admin-message-id]");
      if (msgRow) {
        _selectedAdminMessageId = parseInt(msgRow.dataset.adminMessageId, 10);
        await loadAdminMessageDetail(_selectedAdminMessageId);
      }
    });

    document.addEventListener("change", (e) => {
      if (!isAdminEvent(e)) return;
      if (e.target.id === "admin-lootbox-pool-container") {
        persistLootPoolDraft();
        renderLootPoolEditor(e.target.value);
        return;
      }
      if (e.target.dataset.field === "reward_type") {
        const row = e.target.closest("tr[data-pool-row]");
        if (row) syncLootPoolRowKeySelect(row, e.target.value);
      }
    });

    document.addEventListener("keydown", async (e) => {
      if (!isAdminEvent(e) || e.key !== "Enter") return;
      if (e.target.id === "admin-players-search") {
        e.preventDefault();
        await searchAdminPlayers();
      }
      if (e.target.id === "admin-planets-search") {
        e.preventDefault();
        await searchAdminPlanets();
      }
      if (e.target.id === "admin-chat-search-q") {
        e.preventDefault();
        await searchAdminChatMessages();
      }
    });
  }

  function initAdminPanel() {
    const root = adminRoot();
    if (!root) return;

    bindAdminPanelOnce();

    if (!_adminPanelBootstrapped) {
      _adminPanelBootstrapped = true;
      showAlert("");
      const healthOut = qs("#admin-health-output");
      if (healthOut) healthOut.innerHTML = loadingHtml();
      switchTab("health");
      loadAdminRuntime().then(() => loadTab("health"));
    }

    syncAdminHudSelects(adminRoot());
    console.debug("[GC] admin panel initialized");
  }

  GC.teardownAdminPanel = function teardownAdminPanel() {
    _activeTab = "health";
    _adminPanelBootstrapped = false;
  };

  GC.modules = GC.modules || {};
  GC.modules.admin = initAdminPanel;
  GC.initAdminPanel = initAdminPanel;
  GC.loadAdminHealth = loadAdminHealth;
  GC.loadAdminMigrations = loadAdminMigrations;
  GC.searchAdminPlayers = searchAdminPlayers;
  GC.loadAdminPlayer = loadAdminPlayer;
  GC.searchAdminPlanets = searchAdminPlanets;
  GC.loadAdminQueues = loadAdminQueues;
  GC.cancelQueueJob = cancelQueueJob;
  GC.loadAuditLog = loadAuditLog;

  if (typeof GC.registerCleanup === "function") {
    GC.registerCleanup(function adminPanelCleanup() {
      _activeTab = "health";
      _adminPanelBootstrapped = false;
    }, { persistent: true });
  }

  bindAdminPanelOnce();
})();
