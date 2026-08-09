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
  let _adminMessagesExpanded = false;
  const ADMIN_MESSAGES_PREVIEW = 5;
  let _selectedPlayerId = null;
  let _selectedPlanetId = null;
  let _lootboxAdminState = null;
  let _lootboxSelectedContainer = null;
  let _diplomacyOptions = null;

  const ADMIN_TAB_GROUPS = {
    liveops: ["world_boss", "pirates", "inactive_autoplay", "events", "diplomacy", "votes"],
    players: ["players", "planets"],
    economy: ["balance", "lootboxes", "queues", "fleets", "promos"],
    moderation: ["chat", "support", "messages"],
    system: ["health", "server", "runtime", "performance", "migrations", "audit"],
  };
  const ADMIN_TAB_TO_GROUP = {};
  Object.keys(ADMIN_TAB_GROUPS).forEach((group) => {
    ADMIN_TAB_GROUPS[group].forEach((tab) => {
      ADMIN_TAB_TO_GROUP[tab] = group;
    });
  });
  const ADMIN_LAST_TAB_KEY = "gc_admin_last_tab";

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

  function adminDestructiveConfirmed(messageKey, fallbackMessage) {
    return window.confirm(t(messageKey, fallbackMessage));
  }

  const ADMIN_SELECT_ATTRS = 'class="admin-input admin-select" data-gc-hud-select';

  function syncAdminHudSelects(root) {
    const scope = root && root.querySelectorAll ? root : adminRoot();
    if (!scope || typeof GC.initHudSelects !== "function") return;
    // Portaled menus live on document.body — wrap.querySelector misses them and
    // leaves pointer-events:auto orphans that freeze the shell after Admin.
    if (typeof GC.teardownHudSelectPortals === "function") {
      GC.teardownHudSelectPortals();
    } else if (typeof GC.closeAllHudSelects === "function") {
      GC.closeAllHudSelects();
    }
    GC.initHudSelects(scope);
    if (typeof GC.rebuildHudSelect === "function") {
      scope.querySelectorAll("select[data-gc-hud-select]").forEach((sel) => {
        if (sel._gcHudSelect) GC.rebuildHudSelect(sel);
        else if (typeof GC.syncHudSelect === "function") GC.syncHudSelect(sel);
      });
    }
  }

  function adminLeaveShellCleanup() {
    _activeTab = "health";
    _adminPanelBootstrapped = false;
    if (typeof GC.releaseShellNavigationBlockers === "function") {
      GC.releaseShellNavigationBlockers("admin_panel_cleanup");
    } else if (typeof GC.teardownHudSelectPortals === "function") {
      GC.teardownHudSelectPortals();
    }
  }

  function playerNameLink(playerId, name, nameStyle) {
    const id = Number(playerId);
    if (!Number.isFinite(id) || id <= 0) return esc(name || "—");
    if (typeof GC.playerNameHtml === "function") {
      return GC.playerNameHtml({
        id,
        name: name || "Commander",
        nameStyle: nameStyle || "none",
        enableCard: true,
      });
    }
    const label = esc(name || "Commander");
    const title = esc(t("playercard_open", "Profil öffnen"));
    const style = esc(String(nameStyle || "none"));
    return (
      `<span class="gc-player-name" data-player-id="${id}" data-player-name="${label}" ` +
      `data-name-style="${style}" data-player-card="1" role="button" tabindex="0" title="${title}">${label}</span>`
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

  /** Panel alert + global toast for failed admin API actions. */
  function adminFail(res, fallback) {
    const msg = res?.message || res?.error || fallback || t("admin_action_failed", "Aktion fehlgeschlagen");
    showAlert(msg, "error");
    notify(msg, "error");
    return msg;
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
        message:
          res.status === 404
            ? t(
                "admin_http_404_json",
                "HTTP 404 — Route fehlt (Server neu starten / Hard-Reload)."
              )
            : `HTTP ${res.status}: invalid JSON response`,
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

  function adminDelete(url) {
    return adminApi(url, { method: "DELETE" });
  }

  function adminPatch(url, body) {
    return adminApi(url, { method: "PATCH", body: body || {} });
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

  function renderMetricGrid(cards) {
    const list = Array.isArray(cards) ? cards : [];
    return (
      `<div class="admin-metrics-grid">` +
      list
        .map(
          (c) =>
            `<div class="admin-metric-card"><span class="admin-metric-label">${esc(c.label)}</span><strong class="admin-metric-value gc-mono">${c.value}</strong>${
              c.sub ? `<span class="admin-metric-sub">${esc(c.sub)}</span>` : ""
            }</div>`
        )
        .join("") +
      `</div>`
    );
  }

  function renderAdminTable(headers, rowsHtml) {
    const cols = Array.isArray(headers) ? headers : [];
    return `<div class="admin-table-wrap"><table class="admin-table admin-table-compact"><thead><tr>${cols
      .map((h) => `<th>${esc(h)}</th>`)
      .join("")}</tr></thead><tbody>${rowsHtml || `<tr><td colspan="${cols.length}">—</td></tr>`}</tbody></table></div>`;
  }

  function adminConfirmDanger(message) {
    return window.confirm(String(message || ""));
  }

  function errorCard(data) {
    return `<div class="admin-card admin-error-card">
      <h3>${t("admin_error_title", "Fehler")}</h3>
      <p>${esc(data.message || data.error || "unknown")}</p>
      ${data.httpStatus ? `<p class="admin-small-hint">HTTP ${data.httpStatus}</p>` : ""}
    </div>`;
  }

  function persistAdminLastTab(name) {
    try {
      sessionStorage.setItem(ADMIN_LAST_TAB_KEY, name);
      const group = ADMIN_TAB_TO_GROUP[name];
      if (group) sessionStorage.setItem(ADMIN_LAST_TAB_KEY + "_" + group, name);
    } catch (_) {}
  }

  function readAdminLastTab() {
    try {
      return sessionStorage.getItem(ADMIN_LAST_TAB_KEY);
    } catch (_) {
      return null;
    }
  }

  function readAdminLastTabForGroup(group) {
    try {
      return sessionStorage.getItem(ADMIN_LAST_TAB_KEY + "_" + group);
    } catch (_) {
      return null;
    }
  }

  function applyGroupVisibility(group) {
    const tabs = ADMIN_TAB_GROUPS[group] || [];
    qsa(".admin-group-btn").forEach((btn) => {
      const on = btn.dataset.adminGroup === group;
      btn.classList.toggle("is-active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    });
    qsa(".admin-tab-btn, .admin-cc-tab").forEach((btn) => {
      const tab = btn.dataset.adminTab;
      const show = !tab || tabs.includes(tab);
      btn.hidden = !show;
    });
  }

  function resolveInitialTab() {
    try {
      const fromUrl = new URLSearchParams(window.location.search).get("tab");
      if (fromUrl && ADMIN_TAB_TO_GROUP[fromUrl]) return fromUrl;
    } catch (_) {}
    const fromSession = readAdminLastTab();
    if (fromSession && ADMIN_TAB_TO_GROUP[fromSession]) return fromSession;
    return "health";
  }

  function switchTab(name) {
    if (!name || !ADMIN_TAB_TO_GROUP[name]) name = "health";
    _activeTab = name;
    persistAdminLastTab(name);
    applyGroupVisibility(ADMIN_TAB_TO_GROUP[name] || "system");
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

  async function switchGroup(group) {
    const tabs = ADMIN_TAB_GROUPS[group] || [];
    if (!tabs.length) return;
    const groupLast = readAdminLastTabForGroup(group);
    const globalLast = readAdminLastTab();
    const name =
      groupLast && tabs.includes(groupLast)
        ? groupLast
        : globalLast && tabs.includes(globalLast)
          ? globalLast
          : tabs[0];
    switchTab(name);
    await loadTab(name);
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
      case "promos":
        result = await loadAdminPromos();
        break;
      case "planets":
        result = await searchAdminPlanets();
        break;
      case "queues":
        result = await loadAdminQueues();
        break;
      case "fleets":
        result = await loadAdminFleets();
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
      case "performance":
        result = await loadAdminPerformance();
        break;
      case "votes":
        result = await loadAdminVotes();
        break;
      case "balance":
        result = await loadAdminBalance();
        loadAdminCombatBots().catch(() => {});
        break;
      case "server":
        result = await loadAdminServer();
        break;
      case "diplomacy":
        result = await loadAdminDiplomacy();
        break;
      case "world_boss":
        result = await loadWorldBossAdmin();
        break;
      case "pirates":
        result = await loadPiratesAdmin();
        break;
      case "inactive_autoplay":
        result = await loadInactiveAutoplayAdmin();
        break;
      case "events":
        result = await loadAdminEvents();
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
    if (typeof GC.syncHudSelectLabelsInRoot === "function") {
      GC.syncHudSelectLabelsInRoot(qs('[data-admin-panel="balance"]'));
    }
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

  /** Balance save: patch resource bar only — no landscape/queue/game-loop side effects. */
  function applyBalanceHudSnapshot(hud, reason) {
    if (!hud || hud.ok === false) return false;
    const planetId = Number(hud.active_planet_id || hud.active_planet?.planet_id || 0);
    if (!planetId) return false;
    if (typeof GC.patchShellHudFromState !== "function") return false;
    GC.patchShellHudFromState(hud, {
      forceResourceBar: true,
      reason: reason || "admin_balance_save",
    });
    if (typeof GC.clearStatusWidgetOffline === "function") GC.clearStatusWidgetOffline();
    return true;
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
      // Prefer HUD refresh — works on /admin (refreshGameState no-ops there).
      if (typeof GC.refreshHudFromGameState === "function") {
        try {
          await GC.refreshHudFromGameState(reason || "admin_change");
        } catch (_) {
          /* non-fatal */
        }
      } else if (typeof GC.refreshGameState === "function") {
        try {
          await GC.refreshGameState(reason || "admin_change");
        } catch (_) {
          /* non-fatal */
        }
      }
    }

    if (typeof GC.releaseShellNavigationBlockers === "function") {
      GC.releaseShellNavigationBlockers(reason || "admin_change");
    } else if (typeof GC.teardownHudSelectPortals === "function") {
      GC.teardownHudSelectPortals();
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
    if (typeof GC.quiesceLiveClientFetches === "function") {
      GC.quiesceLiveClientFetches(reason || "admin_balance_save");
    } else {
      if (typeof GC.stopChatPolling === "function") GC.stopChatPolling();
      if (typeof GC.abortInFlightGameStateFetches === "function") GC.abortInFlightGameStateFetches();
      if (typeof GC.stopPolling === "function") GC.stopPolling();
    }
    await syncAfterAdminChange(reason || "admin_balance_save", {
      settings,
      hud: extras && extras.hud,
      skipGameState: true,
    });
    // GC-INFRA: do NOT restore left-menu accordion state on /admin — that path has no
    // infrastructure route hints and re-applies accordion state against GC-849
    // grid collapse, leaving Infra nav non-interactive. Leaving admin restores
    // via PJAX initPage / _syncNavActive.
    if (typeof GC.releaseShellNavigationBlockers === "function") {
      GC.releaseShellNavigationBlockers(reason || "admin_balance_save");
    } else if (typeof GC.teardownHudSelectPortals === "function") {
      GC.teardownHudSelectPortals();
    }
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
    if (typeof GC.quiesceLiveClientFetches === "function") {
      GC.quiesceLiveClientFetches("admin_balance_save_pre");
    } else if (typeof GC.stopChatPolling === "function") {
      GC.stopChatPolling();
    }
    const res = await adminPost("/api/admin/balance", payload);
    if (res.ok) {
      populateBalanceForm(res.settings || {});
      if (qs("#admin-balance-apply-start")) qs("#admin-balance-apply-start").checked = false;
      notify(t("admin_balance_saved", "Balance-Einstellungen gespeichert."), "success");
      setBalanceStatus(t("admin_balance_saved", "Balance-Einstellungen gespeichert."));
      await afterBalanceMutation(res.settings, "admin_balance_save", { hud: res.hud });
    } else {
      const errMsg =
        res.error === "exchange_arbitrage_risk"
          ? t(
              "error_exchange_arbitrage_risk",
              "Invalid exchange rates: the Crytite buy price must be higher than the Crytite sell return."
            )
          : res.message || res.error || t("admin_action_failed", "Aktion fehlgeschlagen");
      showAlert(errMsg, "error");
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

  async function runAdminRankingRecompute(triggerBtn) {
    const btn = triggerBtn || qs("#admin-btn-ranking-recompute");
    const resultEl = qs("#admin-ranking-recompute-result");
    if (resultEl) resultEl.textContent = t("admin_ranking_recompute_running", "Ranking wird neu berechnet …");
    setBusy(btn, true);
    try {
      const res = await adminPost("/api/admin/ranking/recompute", {});
      if (res.ok) {
        const players = res.players_updated ?? res.players_seen ?? 0;
        const ranks = res.ranks_assigned ?? 0;
        const msg = t("admin_ranking_recompute_success", "Ranking aktualisiert: {players} Spieler, {ranks} Ränge.")
          .replace("{players}", String(players))
          .replace("{ranks}", String(ranks));
        notify(msg, "success");
        if (resultEl) resultEl.textContent = msg;
      } else {
        const errMsg = res.message || res.error || t("admin_ranking_recompute_error", "Ranking konnte nicht aktualisiert werden.");
        showAlert(errMsg, "error");
        if (resultEl) resultEl.textContent = errMsg;
      }
      return res;
    } catch (err) {
      const errMsg = err && err.message ? err.message : t("admin_ranking_recompute_error", "Ranking konnte nicht aktualisiert werden.");
      showAlert(errMsg, "error");
      if (resultEl) resultEl.textContent = errMsg;
      return { ok: false, error: errMsg };
    } finally {
      setBusy(btn, false);
    }
  }

  function fmtCooldown(sec) {
    const s = Math.max(0, Number(sec) || 0);
    if (s <= 0) return t("admin_votes_ready", "Bereit");
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
    return `${m}m`;
  }

  const ADMIN_VOTE_PROVIDER_ORDER = ["topg", "gtop100", "gametoor", "arena_top100"];
  const ADMIN_VOTE_PROVIDER_SHORT = {
    topg: "TopG",
    gtop100: "GT100",
    gametoor: "GToor",
    arena_top100: "Arena",
  };

  function fmtTsShort(ts) {
    if (!ts) return "–";
    try {
      return new Date(Number(ts) * 1000).toLocaleString(undefined, {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch (_) {
      return String(ts);
    }
  }

  function _providerMap(providers) {
    const map = {};
    (Array.isArray(providers) ? providers : []).forEach((pr) => {
      map[String(pr.provider_key || "")] = pr;
    });
    return map;
  }

  function renderAdminVoteProviderCell(pr) {
    if (!pr) {
      return `<td class="admin-votes-pcol"><span class="admin-votes-pchip admin-votes-pchip--empty">–</span></td>`;
    }
    const ready = !!pr.can_vote;
    const statusClass = ready ? "ready" : "wait";
    const label = ready ? "✓" : fmtCooldown(pr.cooldown_remaining_sec);
    const ch =
      pr.last_channel === "reengagement"
        ? t("admin_votes_channel_reengagement", "Historisch synthetisch")
        : pr.last_channel === "player"
          ? t("admin_votes_channel_player", "Extern")
          : "";
    const tip = [
      pr.display_name || pr.provider_key,
      ready ? t("admin_votes_ready", "Bereit") : fmtCooldown(pr.cooldown_remaining_sec),
      pr.last_vote_at
        ? `${t("admin_votes_col_last_vote", "Letzter Vote")}: ${fmtTs(pr.last_vote_at)}`
        : t("vote_center_never", "Noch nie"),
      ch || "—",
    ].join(" · ");
    return (
      `<td class="admin-votes-pcol" title="${esc(tip)}">` +
      `<span class="admin-votes-pchip admin-votes-pchip--${statusClass}">${esc(label)}</span>` +
      (ch ? `<span class="admin-votes-pchip-ch">${esc(ch)}</span>` : "") +
      `</td>`
    );
  }

  function renderAdminVoteStats(data) {
    const host = qs("#admin-votes-stats-output");
    if (!host) return;
    if (!data || !data.ready) {
      host.innerHTML = emptyState(t("admin_votes_unavailable", "Vote-System nicht verfügbar."));
      return;
    }
    const s = data.summary || {};
    const providers = Array.isArray(data.providers) ? data.providers : [];
    const metricsHtml =
      `<div class="admin-metrics-grid admin-votes-metrics-grid">` +
      `<div class="admin-metric-card"><span class="admin-metric-label">${esc(t("admin_votes_metric_24h", "Rewards 24h"))}</span><strong class="admin-metric-value gc-mono">${fmtInt(s.rewards_granted_24h ?? s.votes_24h)}</strong><span class="admin-metric-sub">${esc(t("admin_votes_metric_player", "Extern"))}: ${fmtInt(s.external_votes_24h ?? s.player_votes_24h)} · ${esc(t("admin_votes_metric_reengagement", "Historisch synthetisch"))}: ${fmtInt(s.historical_synthetic_24h ?? s.reengagement_votes_24h)}</span></div>` +
      `<div class="admin-metric-card"><span class="admin-metric-label">${esc(t("admin_votes_metric_7d", "Rewards 7d"))}</span><strong class="admin-metric-value gc-mono">${fmtInt(s.rewards_granted_7d ?? s.votes_7d)}</strong><span class="admin-metric-sub">${esc(t("admin_votes_metric_player", "Extern"))}: ${fmtInt(s.external_votes_7d ?? s.player_votes_7d)} · ${esc(t("admin_votes_metric_reengagement", "Historisch synthetisch"))}: ${fmtInt(s.historical_synthetic_7d ?? s.reengagement_votes_7d)}</span></div>` +
      `<div class="admin-metric-card"><span class="admin-metric-label">${esc(t("admin_votes_metric_pending", "Offene Belohnungen"))}</span><strong class="admin-metric-value gc-mono">${fmtInt(s.pending_rewards)}</strong></div>` +
      `<div class="admin-metric-card"><span class="admin-metric-label">${esc(t("admin_votes_metric_voteable_active", "Vote-bereit (aktiv)"))}</span><strong class="admin-metric-value gc-mono">${fmtInt(s.active_voteable_now)}</strong></div>` +
      `<div class="admin-metric-card"><span class="admin-metric-label">${esc(t("admin_votes_metric_voteable_inactive", "Vote-bereit (inaktiv)"))}</span><strong class="admin-metric-value gc-mono">${fmtInt(s.inactive_voteable_now)}</strong></div>` +
      `</div>`;

    const providerTable = providers.length
      ? `<table class="admin-table admin-table-compact admin-votes-provider-summary"><thead><tr>` +
        `<th>${esc(t("admin_votes_col_provider", "Provider"))}</th>` +
        `<th>${esc(t("admin_votes_col_7d", "7d gesamt"))}</th>` +
        `<th>${esc(t("admin_votes_col_player", "Extern"))}</th>` +
        `<th>${esc(t("admin_votes_col_reengagement", "Historisch"))}</th>` +
        `</tr></thead><tbody>` +
        providers
          .map(
            (p) =>
              `<tr><td>${esc(p.display_name || p.provider_key)}</td>` +
              `<td class="gc-mono">${fmtInt(p.rewards_granted_7d ?? p.votes_7d)}</td>` +
              `<td class="gc-mono">${fmtInt(p.external_votes_7d ?? p.player_votes_7d)}</td>` +
              `<td class="gc-mono">${fmtInt(p.historical_synthetic_7d ?? p.reengagement_votes_7d)}</td></tr>`
          )
          .join("") +
        `</tbody></table>`
      : "";

    host.innerHTML =
      `<div class="admin-votes-dashboard">` +
      `<div class="admin-votes-dashboard-main">${metricsHtml}</div>` +
      (providerTable ? `<div class="admin-votes-dashboard-side">${providerTable}</div>` : "") +
      `</div>`;
  }

  function renderAdminVotePlayers(data) {
    const host = qs("#admin-votes-players-output");
    if (!host) return;
    const rows = Array.isArray(data?.players) ? data.players : [];
    if (!rows.length) {
      host.innerHTML = emptyState(t("admin_votes_no_players", "Keine Spieler gefunden."));
      return;
    }
    const activityLabel = (a) =>
      a === "inactive"
        ? t("admin_votes_filter_inactive", "Inaktiv")
        : t("admin_votes_filter_active", "Aktiv");
    const providerHead = ADMIN_VOTE_PROVIDER_ORDER.map(
      (key) =>
        `<th class="admin-votes-pcol-head" title="${esc(key)}">${esc(ADMIN_VOTE_PROVIDER_SHORT[key] || key)}</th>`
    ).join("");
    host.innerHTML =
      `<div class="admin-votes-players-scroll">` +
      `<table class="admin-table table-std admin-table--entity admin-votes-players-table"><thead><tr>` +
      `<th>${esc(t("admin_votes_col_player_name", "Spieler"))}</th>` +
      `<th>${esc(t("admin_votes_col_activity", "Status"))}</th>` +
      `<th>${esc(t("admin_votes_col_last_seen", "Zuletzt"))}</th>` +
      `<th class="gc-mono">${esc(t("admin_votes_col_votes", "Rewards"))}</th>` +
      `<th class="gc-mono">${esc(t("admin_votes_col_pending", "Offen"))}</th>` +
      providerHead +
      `</tr></thead><tbody>` +
      rows
        .map((p) => {
          const provMap = _providerMap(p.providers);
          const providerCells = ADMIN_VOTE_PROVIDER_ORDER.map((key) =>
            renderAdminVoteProviderCell(provMap[key])
          ).join("");
          const external = p.external_votes ?? p.player_votes;
          const synthetic = p.historical_synthetic_votes ?? p.reengagement_votes;
          return (
            `<tr class="admin-votes-player-row" data-admin-player-id="${Number(p.user_id)}">` +
            `<td class="admin-votes-player-cell">${playerNameLink(p.user_id, p.player_name || p.username)}<span class="admin-small-hint gc-mono">#${Number(p.user_id)}</span></td>` +
            `<td><span class="admin-status-badge ${p.activity === "inactive" ? "admin-status-warn" : "admin-status-ok"}">${esc(activityLabel(p.activity))}</span></td>` +
            `<td class="gc-mono admin-votes-ts">${esc(fmtTsShort(p.last_seen))}</td>` +
            `<td class="gc-mono admin-votes-votes" title="${esc(t("admin_votes_metric_player", "Extern"))}/${esc(t("admin_votes_metric_reengagement", "Historisch synthetisch"))}">${fmtInt(p.rewards_granted ?? p.total_votes)}<span class="admin-votes-split">${fmtInt(external)}/${fmtInt(synthetic)}</span></td>` +
            `<td class="gc-mono">${fmtInt(p.pending_rewards)}</td>` +
            providerCells +
            `</tr>`
          );
        })
        .join("") +
      `</tbody></table></div>` +
      `<p class="admin-small-hint admin-votes-footnote">${esc(t("admin_votes_total_hint", "Gesamt"))}: ${fmtInt(data.total || rows.length)} · ${esc(t("admin_votes_chip_hint", "Chip: Cooldown oder ✓ bereit — Hover für Details"))}</p>`;
  }

  async function loadAdminVotes() {
    const statsHost = qs("#admin-votes-stats-output");
    const playersHost = qs("#admin-votes-players-output");
    if (statsHost) statsHost.innerHTML = loadingHtml();
    if (playersHost) playersHost.innerHTML = loadingHtml();
    const stats = await adminGet("/api/admin/votes/stats");
    if (!stats.ok && stats.error) {
      if (statsHost) statsHost.innerHTML = errorCard(stats);
      return stats;
    }
    renderAdminVoteStats(stats);
    return searchAdminVotesPlayers();
  }

  async function searchAdminVotesPlayers() {
    const q = (qs("#admin-votes-search")?.value || "").trim();
    const activity = qs("#admin-votes-activity")?.value || "all";
    const host = qs("#admin-votes-players-output");
    if (host) host.innerHTML = loadingHtml();
    const data = await adminGet(
      `/api/admin/votes/players?q=${encodeURIComponent(q)}&activity=${encodeURIComponent(activity)}&limit=50`
    );
    if (!data.ok) {
      if (host) host.innerHTML = errorCard(data);
      return data;
    }
    renderAdminVotePlayers(data);
    return data;
  }

  async function runInactiveStorageBoost(triggerBtn) {
    const ok = window.confirm(
      t(
        "admin_inactive_storage_boost_confirm",
        "Alle Planeten inaktiver Spieler: Ferronit-/Crytite-/Brennzellen-Lager mindestens auf Stufe 15 setzen?"
      )
    );
    if (!ok) return null;
    const resultEl = qs("#admin-inactive-storage-result");
    if (resultEl) {
      resultEl.textContent = t("admin_inactive_storage_boost_running", "Lager-Boost für Inaktive …");
    }
    setBusy(triggerBtn, true);
    try {
      const res = await adminPost("/api/admin/inactive/storage-boost", { confirm: true });
      if (res.ok) {
        const msg = t(
          "admin_inactive_storage_boost_success",
          "Lager-Boost: {updated} Planeten · {players} Inaktive · Stufe {level}."
        )
          .replace("{updated}", String(res.planets_updated ?? 0))
          .replace("{players}", String(res.inactive_players ?? 0))
          .replace("{level}", String(res.target_level ?? 15));
        notify(msg, "success");
        if (resultEl) resultEl.textContent = msg;
      } else {
        const errMsg =
          res.message || res.error || t("admin_inactive_storage_boost_error", "Lager-Boost fehlgeschlagen.");
        showAlert(errMsg, "error");
        if (resultEl) resultEl.textContent = errMsg;
      }
      return res;
    } catch (err) {
      const errMsg = err?.message || t("admin_inactive_storage_boost_error", "Lager-Boost fehlgeschlagen.");
      showAlert(errMsg, "error");
      if (resultEl) resultEl.textContent = errMsg;
      return { ok: false, error: errMsg };
    } finally {
      setBusy(triggerBtn, false);
    }
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

  function setCombatBotsStatus(msg) {
    const host = qs("#admin-combat-bots-status");
    if (host) host.textContent = msg || "";
  }

  function renderCombatBotsResults(payload) {
    const host = qs("#admin-combat-bots-results");
    if (!host) return;
    const rows = payload?.results || payload?.status?.recent_results || [];
    if (!rows.length) {
      host.innerHTML = `<p class="admin-small-hint">${esc(t("admin_combat_bots_no_results", "Noch keine Bot-Kämpfe."))}</p>`;
      return;
    }
    const head = `<tr><th>${esc(t("admin_combat_bots_col_scenario", "Szenario"))}</th><th>${esc(t("admin_combat_bots_col_winner", "Sieger"))}</th><th>${esc(t("admin_combat_bots_col_rounds", "Runden"))}</th><th>${esc(t("admin_combat_bots_col_fleet", "Flotte"))}</th><th>${esc(t("admin_combat_bots_col_status", "Status"))}</th></tr>`;
    const body = rows
      .map((r) => {
        const resolved = r.resolved_at ? t("admin_combat_bots_resolved", "beendet") : t("admin_combat_bots_pending", "unterwegs");
        return `<tr>
          <td>${esc(String(r.scenario_key || ""))}</td>
          <td>${esc(String(r.winner || "–"))}</td>
          <td>${esc(String(r.rounds ?? "–"))}</td>
          <td>${esc(String(r.fleet_movement_id ?? "–"))}</td>
          <td>${esc(resolved)}</td>
        </tr>`;
      })
      .join("");
    host.innerHTML = `<table class="admin-table"><thead>${head}</thead><tbody>${body}</tbody></table>`;
  }

  let combatBotsScenarioCatalog = [];

  function populateCombatBotsScenarioSelect(scenarios, filterText) {
    const sel = qs("#admin-combat-bots-scenario");
    if (!sel || !Array.isArray(scenarios) || !scenarios.length) return;
    const current = sel.value;
    const needle = String(filterText || "").trim().toLowerCase();
    const filtered = needle
      ? scenarios.filter((s) => {
          const hay = `${s.key || ""} ${s.label || ""} ${s.notes || ""}`.toLowerCase();
          return hay.includes(needle);
        })
      : scenarios;
    const list = filtered.length ? filtered : scenarios;
    sel.innerHTML = list
      .map(
        (s) =>
          `<option value="${esc(String(s.key))}">${esc(String(s.label || s.key))}</option>`
      )
      .join("");
    if (current && list.some((s) => s.key === current)) sel.value = current;
    else if (list.length) sel.value = list[0].key;
    if (typeof GC.rebuildHudSelect === "function" && sel._gcHudSelect) {
      GC.rebuildHudSelect(sel);
    } else {
      syncAdminHudSelects(sel.closest("#admin-combat-bots-panel") || adminRoot());
    }
  }

  function bindCombatBotsScenarioFilter() {
    const input = qs("#admin-combat-bots-scenario-filter");
    if (!input || input.dataset.gcCombatBotsFilterBound === "1") return;
    input.dataset.gcCombatBotsFilterBound = "1";
    input.addEventListener("input", () => {
      populateCombatBotsScenarioSelect(combatBotsScenarioCatalog, input.value);
    });
  }

  function syncCombatBotsLiveUi(status) {
    const panel = qs("#admin-combat-bots-panel");
    if (!panel) return;
    const live = status?.live_in_game_enabled !== false;
    panel.dataset.combatBotsLive = live ? "1" : "0";
    qsa("[data-admin-action^='combat-bots-']", panel).forEach((btn) => {
      const act = btn.dataset.adminAction || "";
      if (act === "combat-bots-refresh") return;
      btn.disabled = !live;
      btn.setAttribute("aria-disabled", live ? "false" : "true");
    });
    const filter = qs("#admin-combat-bots-scenario-filter", panel);
    const sel = qs("#admin-combat-bots-scenario", panel);
    if (filter) filter.disabled = !live;
    if (sel) sel.disabled = !live;
  }

  async function loadAdminCombatBots() {
    setCombatBotsStatus(t("admin_combat_bots_loading", "Lade Bot-Status…"));
    const data = await adminGet("/api/admin/combat-bots/results?limit=15");
    if (!data.ok) {
      setCombatBotsStatus(data.message || data.error || t("admin_action_failed", "Aktion fehlgeschlagen"));
      return data;
    }
    const status = data.status || {};
    syncCombatBotsLiveUi(status);
    combatBotsScenarioCatalog = status.scenarios || [];
    bindCombatBotsScenarioFilter();
    const filterVal = qs("#admin-combat-bots-scenario-filter")?.value || "";
    populateCombatBotsScenarioSelect(combatBotsScenarioCatalog, filterVal);
    if (status.live_in_game_enabled === false) {
      setCombatBotsStatus(
        t(
          "admin_combat_bots_live_disabled",
          "Live-Bots pausiert — Balance lokal per pytest. Vorbereitet für spätere Bot-Spieler."
        ) +
          (status.local_testing_hint ? ` (${status.local_testing_hint})` : "")
      );
    } else {
      const enabled = status.enabled ? t("admin_combat_bots_on", "aktiv") : t("admin_combat_bots_off", "inaktiv");
      const cd = Number(status.cooldown_seconds || 0);
      const nxt = status.next_scenario_key || "–";
      const cnt = Number(status.scenario_count || 0);
      setCombatBotsStatus(
        `${t("admin_combat_bots_state", "Status")}: ${enabled}` +
          ` — ${cnt} ${t("admin_combat_bots_scenarios", "Szenarien")}` +
          ` — ${t("admin_combat_bots_next", "Nächstes")}: ${nxt}` +
          (cd > 0 ? ` — ${t("admin_combat_bots_cooldown", "Cooldown")}: ${cd}s` : "")
      );
    }
    renderCombatBotsResults(data);
    return data;
  }

  async function ensureCombatBots() {
    const res = await adminPost("/api/admin/combat-bots/ensure", {});
    if (res.ok) {
      notify(t("admin_combat_bots_ensure_ok", "Combat-Bots bereit."), "success");
      await loadAdminCombatBots();
    } else {
      showAlert(
        res.error === "live_bots_disabled"
          ? t(
              "admin_combat_bots_live_disabled",
              "Live-Bots pausiert — Balance lokal per pytest. Vorbereitet für spätere Bot-Spieler."
            )
          : res.message || res.error,
        "error"
      );
    }
    return res;
  }

  async function toggleCombatBots(enabled) {
    const res = await adminPost("/api/admin/combat-bots/toggle", { enabled: !!enabled });
    if (res.ok) {
      notify(
        enabled
          ? t("admin_combat_bots_enabled_msg", "Combat-Bots aktiviert.")
          : t("admin_combat_bots_disabled_msg", "Combat-Bots deaktiviert."),
        "success"
      );
      await loadAdminCombatBots();
    } else {
      showAlert(
        res.error === "live_bots_disabled"
          ? t(
              "admin_combat_bots_live_disabled",
              "Live-Bots pausiert — Balance lokal per pytest. Vorbereitet für spätere Bot-Spieler."
            )
          : res.message || res.error,
        "error"
      );
    }
    return res;
  }

  async function runCombatBotScenario(force) {
    const sel = qs("#admin-combat-bots-scenario");
    const scenarioKey = (sel?.value || "raptor_vs_aegis_equal_cost").trim();
    setCombatBotsStatus(t("admin_combat_bots_running", "Starte Szenario…"));
    const res = await adminPost("/api/admin/combat-bots/run-scenario", {
      scenario_key: scenarioKey,
      force: !!force,
    });
    if (res.ok) {
      const flight = res.flight_seconds ?? "?";
      notify(
        t("admin_combat_bots_run_ok", "Angriff gestartet — echte Flugzeit.") + ` (${flight}s)`,
        "success"
      );
      setCombatBotsStatus(
        `${t("admin_combat_bots_run_ok", "Angriff gestartet — echte Flugzeit.")} fleet=${res.fleet_movement_id ?? "?"} flight=${flight}s`
      );
      await loadAdminCombatBots();
    } else {
      showAlert(
        res.error === "live_bots_disabled"
          ? t(
              "admin_combat_bots_live_disabled",
              "Live-Bots pausiert — Balance lokal per pytest. Vorbereitet für spätere Bot-Spieler."
            )
          : res.message || res.error,
        "error"
      );
      setCombatBotsStatus(
        res.error === "live_bots_disabled"
          ? t(
              "admin_combat_bots_live_disabled",
              "Live-Bots pausiert — Balance lokal per pytest. Vorbereitet für spätere Bot-Spieler."
            )
          : res.message || res.error || ""
      );
    }
    return res;
  }

  async function runNextCombatBotScenario() {
    setCombatBotsStatus(t("admin_combat_bots_running", "Starte Szenario…"));
    const res = await adminPost("/api/admin/combat-bots/run-next-scenario", { force: true });
    if (res.ok) {
      notify(
        `${t("admin_combat_bots_run_ok", "Angriff gestartet — echte Flugzeit.")} [${res.scenario_key || ""}]`,
        "success"
      );
      await loadAdminCombatBots();
    } else {
      showAlert(
        res.error === "live_bots_disabled"
          ? t(
              "admin_combat_bots_live_disabled",
              "Live-Bots pausiert — Balance lokal per pytest. Vorbereitet für spätere Bot-Spieler."
            )
          : res.message || res.error,
        "error"
      );
      setCombatBotsStatus(
        res.error === "live_bots_disabled"
          ? t(
              "admin_combat_bots_live_disabled",
              "Live-Bots pausiert — Balance lokal per pytest. Vorbereitet für spätere Bot-Spieler."
            )
          : res.message || res.error || ""
      );
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
    const motdOn = qs("#motd_enabled");
    if (motdOn) motdOn.checked = !!settings.motd_enabled;
    updateAdminHeaderKpis(settings);
  }

  function collectNewsPayload(options) {
    const opts = options || {};
    return {
      title: (qs("#admin_news_title")?.value || "").trim(),
      body: (qs("#admin_news_body")?.value || "").trim(),
      version_tag: (qs("#admin_news_version")?.value || "").trim(),
      category: (qs("#admin_news_category")?.value || "").trim(),
      badge: (qs("#admin_news_badge")?.value || "").trim(),
      image_url: (qs("#admin_news_image")?.value || "").trim(),
      is_major_release: qs("#admin_news_major")?.checked ? 1 : 0,
      set_banner: opts.setBanner ? 1 : 0,
      is_draft: opts.isDraft ? 1 : 0,
      publish: opts.publish ? 1 : 0,
    };
  }

  function getAdminNewsEditId() {
    const raw = (qs("#admin_news_edit_id")?.value || "").trim();
    const id = Number(raw);
    return Number.isFinite(id) && id > 0 ? id : 0;
  }

  function setAdminNewsEditId(newsId) {
    const field = qs("#admin_news_edit_id");
    if (field) field.value = newsId ? String(newsId) : "";
  }

  function updateAdminNewsFormMode() {
    const editing = getAdminNewsEditId() > 0;
    const titleEl = qs("#admin-news-form-title");
    const btnBanner = qs("#admin_news_btn_banner");
    const btnPublish = qs("#admin_news_btn_publish");
    const btnDraft = qs("#admin_news_btn_draft");
    const btnCancel = qs("#admin_news_btn_cancel");
    const compose = qs("#admin-news-compose");

    if (titleEl) {
      titleEl.textContent = editing
        ? t("admin_news_edit_heading", "Eintrag bearbeiten")
        : t("admin_news_compose_heading", "Neue Meldung veröffentlichen");
    }
    if (btnBanner) {
      btnBanner.textContent = editing
        ? t("admin_news_save_banner", "Speichern & als Banner setzen")
        : t("admin_news_publish", "Veröffentlichen & als Banner setzen");
    }
    if (btnPublish) {
      btnPublish.textContent = editing
        ? t("admin_news_save", "Änderungen speichern")
        : t("admin_news_publish_only", "Veröffentlichen");
    }
    if (btnDraft) btnDraft.classList.toggle("hidden", editing);
    if (btnCancel) btnCancel.classList.toggle("hidden", !editing);
    if (compose) compose.classList.toggle("admin-news-compose--edit", editing);
  }

  function resetAdminNewsForm() {
    setAdminNewsEditId(0);
    ["#admin_news_title", "#admin_news_version", "#admin_news_image", "#admin_news_body"].forEach((sel) => {
      const el = qs(sel);
      if (el) el.value = "";
    });
    const cat = qs("#admin_news_category");
    if (cat) cat.value = "";
    const badge = qs("#admin_news_badge");
    if (badge) badge.value = "";
    const major = qs("#admin_news_major");
    if (major) major.checked = false;
    updateAdminNewsFormMode();
  }

  function fillAdminNewsForm(entry) {
    if (!entry) return;
    setAdminNewsEditId(entry.id);
    const title = qs("#admin_news_title");
    if (title) title.value = entry.title || "";
    const version = qs("#admin_news_version");
    if (version) version.value = entry.version_tag || "";
    const cat = qs("#admin_news_category");
    if (cat) cat.value = entry.category || "";
    const badge = qs("#admin_news_badge");
    if (badge) badge.value = entry.badge || "";
    const image = qs("#admin_news_image");
    if (image) image.value = entry.image_url || "";
    const body = qs("#admin_news_body");
    if (body) body.value = entry.body || "";
    const major = qs("#admin_news_major");
    if (major) major.checked = !!entry.is_major_release;
    updateAdminNewsFormMode();
    qs("#admin-news-compose")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function newsPreviewText(body, maxLines) {
    const lines = String(body || "").split(/\r?\n/).filter((line) => line.trim());
    const slice = lines.slice(0, maxLines || 3);
    const text = slice.join("\n");
    const truncated = lines.length > (maxLines || 3) || String(body || "").length > text.length;
    return { text, truncated };
  }

  function renderAdminNewsList(entries) {
    const host = qs("#admin-news-list");
    const countEl = qs("#admin-news-list-count");
    const rows = Array.isArray(entries) ? entries : [];
    if (countEl) {
      countEl.textContent = rows.length
        ? `(${rows.length})`
        : "";
    }
    if (!host) return;
    if (!rows.length) {
      host.innerHTML = `<p class="admin-small-hint">${esc(t("admin_news_empty", "Noch keine News-Einträge."))}</p>`;
      return;
    }
    host.innerHTML = rows.map((entry) => {
      let statusBadge = `<span class="admin-news-status admin-news-status--archive">${esc(t("admin_news_status_archive", "Archiv"))}</span>`;
      if (entry.is_banner) {
        statusBadge = `<span class="admin-news-status admin-news-status--banner">${esc(t("admin_news_status_banner", "Banner aktiv"))}</span>`;
      } else if (entry.is_draft) {
        statusBadge = `<span class="admin-news-status admin-news-status--draft">${esc(t("admin_news_draft_badge", "Entwurf"))}</span>`;
      }
      const meta = [
        entry.version_tag ? `<span class="admin-news-meta-tag gc-mono">${esc(entry.version_tag)}</span>` : "",
        entry.category ? `<span class="admin-news-meta-tag">${esc(entry.category)}</span>` : "",
      ].filter(Boolean).join("");
      const preview = newsPreviewText(entry.body, 3);
      const previewHtml = esc(preview.text).replace(/\n/g, "<br>");
      const bannerBtn = entry.is_draft || entry.is_banner
        ? ""
        : `<button type="button" class="gc-btn gc-btn-outline gc-btn-sm" data-admin-action="news-set-banner" data-news-id="${Number(entry.id)}">
            ${esc(t("admin_news_set_banner", "Als Banner setzen"))}
          </button>`;
      return `
        <article class="admin-news-card" data-news-id="${Number(entry.id)}">
          <div class="admin-news-card-main">
            <div class="admin-news-card-head">
              <h4 class="admin-news-card-title">${esc(entry.title || "Update")}</h4>
              ${statusBadge}
            </div>
            <div class="admin-news-card-meta">
              <span class="admin-news-card-date gc-mono">${esc(entry.published_label || t("admin_news_no_date", "—"))}</span>
              ${meta}
            </div>
            <p class="admin-news-card-preview">${previewHtml}${preview.truncated ? "…" : ""}</p>
          </div>
          <div class="admin-news-card-actions">
            <button type="button" class="gc-btn gc-btn-outline gc-btn-sm" data-admin-action="news-edit" data-news-id="${Number(entry.id)}">
              ${esc(t("admin_news_edit", "Bearbeiten"))}
            </button>
            ${bannerBtn}
            <button type="button" class="gc-btn gc-btn-danger gc-btn-sm" data-admin-action="news-delete" data-news-id="${Number(entry.id)}">
              ${esc(t("admin_news_delete", "Löschen"))}
            </button>
          </div>
        </article>`;
    }).join("");
  }

  let adminNewsCache = [];

  async function loadAdminNewsRepoAudit() {
    const host = qs("#admin-news-repo-audit");
    if (!host) return;
    const data = await adminGet("/api/admin/universe-news/repository-audit");
    if (!data.ok) {
      adminFail(data, t("admin_action_failed", "Aktion fehlgeschlagen"));
      return;
    }
    host.innerHTML = `
      <strong>${esc(t("admin_news_repo_title", "Repository-Historie"))}</strong>
      · Git: ${data.git_available ? esc(t("admin_news_repo_git_ok", "verfügbar")) : esc(t("admin_news_repo_git_missing", "nicht verfügbar"))}
      · ${esc(t("admin_news_repo_commits", "Commits"))}: ${Number(data.commit_count || 0)}
      · ${esc(t("admin_news_repo_branches", "Branches"))}: ${Number(data.branch_count || 0)}
      · ${esc(t("admin_news_repo_tags", "Tags"))}: ${Number(data.tag_count || 0)}
      · ${esc(t("admin_news_repo_first_commit", "Erster Commit"))}: ${esc(data.first_commit_date || "—")}
      · ${esc(t("admin_news_repo_latest_commit", "Letzter Commit"))}: ${esc(data.latest_commit_date || "—")}
      · ${esc(t("admin_news_repo_current_release", "Aktuelles Release"))}: ${esc(data.current_release || "—")} (${esc(data.current_release_date || "—")})
      · ${esc(t("admin_news_repo_dev_since", "Commits seit Release"))}: ${Number(data.development_commits_since_release || 0)}`;
  }

  async function loadAdminNews() {
    const data = await adminGet("/api/admin/universe-news");
    if (!data.ok) {
      showAlert(data.message || data.error, "error");
      return data;
    }
    adminNewsCache = data.entries || [];
    renderAdminNewsList(adminNewsCache);
    await loadAdminNewsRepoAudit();
    return data;
  }

  async function publishAdminNews(setBanner) {
    const editId = getAdminNewsEditId();
    const payload = collectNewsPayload({ setBanner: !!setBanner, isDraft: false, publish: true });
    if (!payload.body) {
      showAlert(t("admin_news_body_required", "Bitte News-Text eingeben."), "error");
      return { ok: false };
    }
    const res = editId
      ? await adminPatch(`/api/admin/universe-news/${editId}`, payload)
      : await adminPost("/api/admin/universe-news", payload);
    if (res.ok) {
      notify(
        editId
          ? t("admin_news_updated", "News aktualisiert.")
          : t("admin_news_published", "News veröffentlicht."),
        "success"
      );
      resetAdminNewsForm();
      await loadAdminNews();
    } else {
      showAlert(res.message || res.error, "error");
    }
    return res;
  }

  async function saveAdminNewsDraft() {
    const editId = getAdminNewsEditId();
    const payload = collectNewsPayload({ isDraft: true, setBanner: false, publish: false });
    if (!payload.title && !payload.body) {
      showAlert(t("admin_news_body_required", "Bitte Titel oder Text eingeben."), "error");
      return { ok: false };
    }
    const res = editId
      ? await adminPatch(`/api/admin/universe-news/${editId}`, { ...payload, is_draft: 1 })
      : await adminPost("/api/admin/universe-news", payload);
    if (res.ok) {
      notify(t("admin_news_draft_saved", "Entwurf gespeichert."), "success");
      if (!editId) resetAdminNewsForm();
      await loadAdminNews();
    } else {
      showAlert(res.message || res.error, "error");
    }
    return res;
  }

  function startEditAdminNews(newsId) {
    const entry = adminNewsCache.find((row) => Number(row.id) === Number(newsId));
    if (!entry) {
      showAlert(t("admin_news_not_found", "Eintrag nicht gefunden."), "error");
      return;
    }
    fillAdminNewsForm(entry);
  }

  async function importAdminChangelog() {
    const res = await adminPost("/api/admin/universe-news/import-changelog", {});
    if (res.ok) {
      const skipped = Array.isArray(res.skipped_versions) ? res.skipped_versions.length : 0;
      const suffix = skipped ? ` · ${skipped} ${t("admin_news_import_skipped", "Versionen bereits vorhanden")}` : "";
      notify(
        `${t("admin_news_import_ok", "CHANGELOG importiert.")} (+${res.inserted || 0})${suffix}`,
        "success"
      );
      await loadAdminNews();
    } else {
      showAlert(res.message || res.error || t("admin_news_import_failed", "Import fehlgeschlagen."), "error");
    }
    return res;
  }

  async function importAdminGitHistory() {
    const res = await adminPost("/api/admin/universe-news/import-git-history", {});
    if (res.ok) {
      notify(
        `${t("admin_news_import_git_ok", "Git-Historie importiert.")} (+${res.inserted || 0})`,
        "success"
      );
      await loadAdminNews();
    } else {
      const msg = res.error === "git_unavailable"
        ? t("admin_news_git_unavailable", "Git ist auf dem Server nicht verfügbar (Binary oder .git fehlt).")
        : (res.message || res.error);
      showAlert(msg, "error");
    }
    return res;
  }

  async function importAdminFullHistory() {
    const res = await adminPost("/api/admin/universe-news/import-full-history", {});
    if (res.ok) {
      let suffix = "";
      if (res.git_error === "git_unavailable") {
        suffix = ` · ${t("admin_news_git_unavailable_short", "Git-Historie übersprungen")}`;
      }
      notify(
        `${t("admin_news_import_full_ok", "Vollständiger Import abgeschlossen.")} (+${res.inserted || 0})${suffix}`,
        "success"
      );
      await loadAdminNews();
    } else {
      showAlert(res.message || res.error || t("admin_news_import_failed", "Import fehlgeschlagen."), "error");
    }
    return res;
  }

  async function reclassifyAdminNews() {
    const res = await adminPost("/api/admin/universe-news/reclassify-audience", {});
    if (res.ok) {
      notify(t("admin_news_reclassify_ok", "Patchnotes bereinigt."), "success");
      await loadAdminNews();
    } else {
      showAlert(res.message || res.error, "error");
    }
    return res;
  }

  async function publishAdminReleasePack() {
    const version = String(qs("#admin_release_version")?.value || "").trim();
    if (!version) {
      showAlert(t("admin_news_release_version_required", "Bitte Version angeben (z. B. v0.9)."), "error");
      return { ok: false };
    }
    const payload = {
      version_tag: version,
      version_label: String(qs("#admin_release_label")?.value || "").trim(),
      release_date: String(qs("#admin_release_date")?.value || "").trim(),
      badge: String(qs("#admin_release_badge")?.value || "ALPHA").trim(),
      intro: String(qs("#admin_release_intro")?.value || "").trim(),
      added: String(qs("#admin_release_added")?.value || ""),
      changed: String(qs("#admin_release_changed")?.value || ""),
      fixed: String(qs("#admin_release_fixed")?.value || ""),
      set_banner: !!qs("#admin_release_banner")?.checked,
      is_major_release: true,
    };
    const res = await adminPost("/api/admin/universe-news/publish-release", payload);
    if (res.ok) {
      notify(
        `${t("admin_news_release_ok", "Release veröffentlicht.")} ${esc(res.version_tag || version)} (+${res.inserted || 0})`,
        "success"
      );
      ["#admin_release_version", "#admin_release_label", "#admin_release_date", "#admin_release_intro",
        "#admin_release_added", "#admin_release_changed", "#admin_release_fixed"].forEach((sel) => {
        const el = qs(sel);
        if (el) el.value = "";
      });
      const banner = qs("#admin_release_banner");
      if (banner) banner.checked = false;
      await loadAdminNews();
    } else {
      const msg = res.error === "version_exists"
        ? t("admin_news_release_exists", "Diese Version existiert bereits — bitte Einträge bearbeiten.")
        : (res.message || res.error || t("admin_action_failed", "Aktion fehlgeschlagen"));
      showAlert(msg, "error");
    }
    return res;
  }

  async function setAdminNewsBanner(newsId) {
    const res = await adminPost(`/api/admin/universe-news/${Number(newsId)}/banner`, {});
    if (res.ok) {
      notify(t("admin_news_banner_set", "Banner aktualisiert."), "success");
      await loadAdminNews();
    } else {
      showAlert(res.message || res.error, "error");
    }
    return res;
  }

  async function deleteAdminNews(newsId) {
    const id = parseInt(newsId, 10);
    if (!Number.isFinite(id) || id <= 0) {
      showAlert(t("admin_news_delete_invalid", "Ungültige News-ID."), "error");
      return { ok: false };
    }
    const res = await adminPost(`/api/admin/universe-news/${id}/delete`, {});
    if (res.ok) {
      notify(t("admin_news_deleted", "News gelöscht."), "success");
      if (getAdminNewsEditId() === id) resetAdminNewsForm();
      await loadAdminNews();
    } else {
      showAlert(res.message || res.error || t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
    }
    return res;
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
    await loadAdminNews();
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

  function diplomacyGalaxyId() {
    const raw = parseInt(qs("#admin-diplomacy-galaxy")?.value, 10);
    return Number.isFinite(raw) && raw > 0 ? raw : 1;
  }

  function setDiplomacyStatus(msg) {
    const el = qs("#admin-diplomacy-status");
    if (el) el.textContent = msg || "";
  }

  function diplomacyLabel(key, fallback) {
    return t(key, fallback || key);
  }

  function populateDiplomacySelect(selectId, items, selectedKey) {
    const sel = qs(selectId);
    if (!sel) return;
    const placeholder = t("admin_diplomacy_select_placeholder", "— auswählen —");
    const rows = Array.isArray(items) ? items : [];
    sel.innerHTML =
      `<option value="">${esc(placeholder)}</option>` +
      rows
        .map((row) => {
          const key = String(row.key || "");
          const label = diplomacyLabel(row.label_key, key);
          const selected = key === selectedKey ? " selected" : "";
          return `<option value="${esc(key)}"${selected}>${esc(label)} (${esc(key)})</option>`;
        })
        .join("");
    syncAdminHudSelects(sel.parentElement || adminRoot());
  }

  function renderDiplomacyState(data) {
    const out = qs("#admin-diplomacy-output");
    if (!out) return;
    if (!data || !data.ok) {
      out.innerHTML = errorCard(data || { error: "unknown" });
      return;
    }

    const chip = (label, row) => {
      if (!row || !row.key) {
        return `<tr><th>${esc(label)}</th><td>—</td></tr>`;
      }
      const title = diplomacyLabel(row.label_key, row.key);
      const timing = [];
      if (row.started_at) timing.push(`${t("admin_diplomacy_started", "Start")}: ${fmtTs(row.started_at)}`);
      if (row.ends_at) timing.push(`${t("admin_diplomacy_ends", "Ende")}: ${fmtTs(row.ends_at)}`);
      const meta = timing.length ? `<div class="admin-small-hint">${esc(timing.join(" · "))}</div>` : "";
      return `<tr><th>${esc(label)}</th><td><strong>${esc(title)}</strong> <span class="admin-small-hint">(${esc(row.key)})</span>${meta}</td></tr>`;
    };

    out.innerHTML = `
      <div class="admin-card">
        <h3 class="admin-card-title">${esc(t("admin_diplomacy_state_title", "Aktiver Diplomatie-Status"))}</h3>
        <table class="admin-table admin-table-compact">
          <tbody>
            ${chip(t("admin_diplomacy_section_personality", "Galaxy Personality"), data.personality)}
            ${chip(t("admin_diplomacy_section_resolution", "Aktive Resolution"), data.resolution)}
            ${chip(t("admin_diplomacy_section_emergency", "Aktive Emergency"), data.emergency)}
          </tbody>
        </table>
      </div>`;

    const options = data.options || {};
    _diplomacyOptions = options;
    populateDiplomacySelect("#admin-diplomacy-personality-key", options.personalities, data.personality?.key || "");
    populateDiplomacySelect("#admin-diplomacy-resolution-key", options.resolutions, data.resolution?.key || "");
    populateDiplomacySelect("#admin-diplomacy-emergency-key", options.emergencies, data.emergency?.key || "");
  }

  async function loadAdminDiplomacy() {
    setDiplomacyStatus(t("admin_diplomacy_loading", "Lade Diplomatie-Status…"));
    const galaxy = diplomacyGalaxyId();
    const data = await adminGet(`/api/admin/galactic-diplomacy/${galaxy}`);
    if (!data.ok) {
      showAlert(data.message || data.error || t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      renderDiplomacyState(data);
      setDiplomacyStatus("");
      return data;
    }
    renderDiplomacyState(data);
    setDiplomacyStatus(`${t("admin_diplomacy_loaded", "Galaxie geladen.")} G${data.galaxy || galaxy}`);
    return data;
  }

  async function applyAdminDiplomacyLayer(layer, clear) {
    const galaxy = diplomacyGalaxyId();
    const endpoints = {
      personality: "personality",
      resolution: "resolution",
      emergency: "emergency",
    };
    const endpoint = endpoints[layer];
    if (!endpoint) return null;

    const payload = { clear: clear ? 1 : 0 };
    if (!clear) {
      const selectId =
        layer === "personality"
          ? "#admin-diplomacy-personality-key"
          : layer === "resolution"
            ? "#admin-diplomacy-resolution-key"
            : "#admin-diplomacy-emergency-key";
      const key = (qs(selectId)?.value || "").trim();
      if (!key) {
        showAlert(t("admin_diplomacy_key_required", "Bitte zuerst einen Eintrag auswählen."), "error");
        return null;
      }
      if (layer === "personality") payload.personality_key = key;
      if (layer === "resolution") payload.resolution_key = key;
      if (layer === "emergency") payload.emergency_key = key;
    }

    setDiplomacyStatus(t("admin_diplomacy_saving", "Speichere…"));
    const res = await adminPost(`/api/admin/galactic-diplomacy/${galaxy}/${endpoint}`, payload);
    if (!res.ok) {
      showAlert(res.message || res.error || t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      setDiplomacyStatus("");
      return res;
    }
    renderDiplomacyState(res);
    notify(
      clear
        ? t("admin_diplomacy_cleared", "Diplomatie-Ebene gelöscht.")
        : t("admin_diplomacy_saved", "Diplomatie-Ebene gesetzt."),
      "success",
    );
    setDiplomacyStatus(
      clear
        ? t("admin_diplomacy_cleared", "Diplomatie-Ebene gelöscht.")
        : t("admin_diplomacy_saved", "Diplomatie-Ebene gesetzt."),
    );
    return res;
  }

  function setWorldBossStatus(msg) {
    const el = qs("#admin-wb-status");
    if (el) el.textContent = msg || "";
  }

  function populateWorldBossSelect(definitions, selectedKey) {
    const sel = qs("#admin-wb-boss-key");
    if (!sel) return;
    const placeholder = t("admin_wb_select_placeholder", "— Boss wählen —");
    const rows = Array.isArray(definitions) ? definitions : [];
    const prev = selectedKey != null ? String(selectedKey) : String(sel.value || "");
    sel.innerHTML =
      `<option value="">${esc(placeholder)}</option>` +
      rows
        .map((row) => {
          const key = String(row.boss_key || "");
          const label = t(row.name_key || key, key);
          const selected = key && key === prev ? " selected" : "";
          return `<option value="${esc(key)}"${selected}>${esc(label)} (${esc(key)})</option>`;
        })
        .join("");
    syncAdminHudSelects(sel.parentElement || adminRoot());
  }

  function renderWorldBossAdmin(data) {
    const out = qs("#admin-wb-output");
    if (!out) return;
    if (!data || !data.ok) {
      out.innerHTML = errorCard(data || { error: "unknown" });
      return;
    }

    const ev = data.event || null;
    const schedule = data.schedule || {};
    let statusRows = "";
    if (ev && ev.status === "active") {
      const name = t(ev.name_key || ev.boss_key, ev.boss_key || "—");
      const statusLabel = t(`wb_status_${ev.status || "active"}`, ev.status || "active");
      const coords = `${ev.galaxy || "?"}:${ev.system || "?"}:${ev.position || "?"}`;
      statusRows = `
        <tr><th>${esc(t("admin_wb_status_active", "Aktiver Boss"))}</th>
            <td><strong>${esc(name)}</strong> <span class="admin-small-hint">(${esc(statusLabel)})</span></td></tr>
        <tr><th>${esc(t("admin_wb_coords", "Koordinaten"))}</th><td>${esc(coords)}</td></tr>
        <tr><th>${esc(t("admin_wb_hp", "HP"))}</th>
            <td>${esc(String(ev.current_hp ?? "—"))} / ${esc(String(ev.max_hp ?? "—"))}</td></tr>
        <tr><th>${esc(t("admin_wb_ends", "Ende"))}</th><td>${esc(ev.ends_at ? fmtTs(ev.ends_at) : "—")}</td></tr>`;
    } else {
      const eta = schedule.next_eligible_at ? fmtTs(schedule.next_eligible_at) : "—";
      const ready = schedule.spawn_ready
        ? t("admin_wb_spawn_ready", "Spawn bereit (nächster Cron-Tick)")
        : t("admin_wb_idle_eta", "Nächster Spawn frühestens");
      statusRows = `
        <tr><th>${esc(t("admin_wb_status_idle", "Status"))}</th>
            <td>${esc(t("admin_wb_idle", "Kein aktiver Boss"))}</td></tr>
        <tr><th>${esc(ready)}</th><td>${esc(eta)}</td></tr>`;
    }

    out.innerHTML = `
      <div class="admin-card">
        <h3 class="admin-card-title">${esc(t("admin_wb_state_title", "World-Boss-Status"))}</h3>
        <table class="admin-table admin-table-compact"><tbody>${statusRows}</tbody></table>
      </div>`;
    populateWorldBossSelect(data.definitions, ev && ev.boss_key);
  }

  async function loadWorldBossAdmin() {
    setWorldBossStatus(t("admin_wb_loading", "Lade World-Boss-Status…"));
    const data = await adminGet("/api/admin/world-boss");
    if (!data.ok) {
      showAlert(data.message || data.error || t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      renderWorldBossAdmin(data);
      setWorldBossStatus("");
      return data;
    }
    renderWorldBossAdmin(data);
    setWorldBossStatus(t("admin_wb_loaded", "Status geladen."));
    return data;
  }

  async function spawnWorldBossAdmin() {
    const bossKey = (qs("#admin-wb-boss-key")?.value || "").trim();
    if (!bossKey) {
      showAlert(t("admin_wb_boss_required", "Bitte zuerst einen Boss auswählen."), "error");
      return null;
    }
    const gRaw = (qs("#admin-wb-galaxy")?.value || "").trim();
    const sRaw = (qs("#admin-wb-system")?.value || "").trim();
    const pRaw = (qs("#admin-wb-position")?.value || "").trim();
    const payload = {
      boss_key: bossKey,
      force: !!qs("#admin-wb-force")?.checked,
      announce: !!qs("#admin-wb-announce")?.checked,
    };
    if (gRaw !== "") payload.galaxy = parseInt(gRaw, 10);
    if (sRaw !== "") payload.system = parseInt(sRaw, 10);
    if (pRaw !== "") payload.position = parseInt(pRaw, 10);

    setWorldBossStatus(t("admin_wb_spawning", "Spawne Boss…"));
    const spawnOut = qs("#admin-wb-spawn-result");
    if (spawnOut) spawnOut.textContent = "";
    const res = await adminPost("/api/admin/world-boss/spawn", payload);
    if (!res.ok) {
      showAlert(res.message || res.error || t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      setWorldBossStatus("");
      if (spawnOut) spawnOut.textContent = res.message || res.error || "";
      return res;
    }
    notify(t("admin_wb_spawned", "World Boss gespawnt."), "success");
    if (spawnOut) {
      const ev = res.event || {};
      const coords = `${ev.galaxy || "?"}:${ev.system || "?"}:${ev.position || "?"}`;
      spawnOut.textContent = `${t("admin_wb_spawned", "World Boss gespawnt.")} ${coords}`;
    }
    await loadWorldBossAdmin();
    return res;
  }

  function setPiratesStatus(msg) {
    const el = qs("#admin-pirates-status");
    if (el) el.textContent = msg || "";
  }

  function renderPiratesAdmin(data) {
    const out = qs("#admin-pirates-output");
    if (!out) return;
    if (!data || !data.ok) {
      out.innerHTML = `<p class="admin-small-hint">${esc(data?.error || t("admin_action_failed", "Aktion fehlgeschlagen"))}</p>`;
      return;
    }
    const aiOn = !!data.ai_enabled;
    const aiLabel = aiOn
      ? t("admin_pirates_ai_on", "AI: AN")
      : t("admin_pirates_ai_off", "AI: AUS");
    const kpis = data.kpis || {};
    const heatRows = (data.heat_top || [])
      .map(
        (h) =>
          `<tr><td>G${esc(String(h.galaxy_id))}</td><td>${esc(String(h.heat))}</td></tr>`,
      )
      .join("");
    const botRows = (data.bots || [])
      .map((b) => {
        const coords =
          b.exists && b.galaxy != null
            ? `${esc(String(b.galaxy))}:${esc(String(b.system))}:${esc(String(b.position))}`
            : "—";
        return (
          `<tr><td>${esc(b.faction_key || "")}</td><td>${esc(b.display_name || "")}</td>` +
          `<td>${coords}</td>` +
          `<td>${esc(String(b.metal_mine || 0))}/${esc(String(b.research_lab || 0))}/${esc(String(b.orbital_shipyard || 0))}</td>` +
          `<td>${esc(fmtInt(b.score_total || 0))}</td>` +
          `<td>${esc(String(b.ship_count || 0))}</td>` +
          `<td>${esc(String(b.outbound_fleets || 0))}</td>` +
          `<td>${b.exists ? "✓" : "—"}</td></tr>`
        );
      })
      .join("");
    const baseRows = (data.bases || [])
      .map(
        (b) =>
          `<tr><td>#${esc(String(b.id))}</td><td>${esc(b.faction_key || "")}</td>` +
          `<td>${esc(String(b.galaxy))}:${esc(String(b.system))}:${esc(String(b.position))}</td>` +
          `<td>${esc(String(b.strength))}</td><td>${esc(b.status || "")}</td>` +
          `<td>${esc(String(b.current_hp))}/${esc(String(b.max_hp))}</td></tr>`,
      )
      .join("");
    const warRows = (data.pirate_wars || [])
      .map(
        (w) =>
          `<tr><td>G${esc(String(w.galaxy_id))}</td><td>${esc(String(w.heat))}</td><td>${esc(String(w.ends_at || "—"))}</td></tr>`,
      )
      .join("");
    const logRows = (data.log || [])
      .map((row) => {
        const ts = row.ts ? new Date(Number(row.ts) * 1000).toISOString().slice(11, 19) : "";
        return (
          `<tr><td>${esc(ts)}</td><td>${esc(row.severity || "")}</td>` +
          `<td>${esc(row.kind || "")}</td><td>${esc(row.message || "")}</td>` +
          `<td>${esc(row.faction_key || "")}</td></tr>`
        );
      })
      .join("");
    const metrics = renderMetricGrid([
      { label: t("admin_pirates_kpi_bots", "Bots online"), value: esc(String(kpis.bots_online || 0)) },
      { label: t("admin_pirates_live_bases", "Live bases"), value: esc(String(data.live_bases || 0)) },
      { label: t("admin_pirates_kpi_raids", "Raid dispatches (log window)"), value: esc(String(kpis.raid_dispatch_in_log || 0)) },
      { label: t("admin_pirates_kpi_spies", "Spy dispatches (log window)"), value: esc(String(kpis.spy_dispatch_in_log || 0)) },
      { label: t("admin_pirates_kpi_spawns", "Base spawns (log window)"), value: esc(String(kpis.base_spawn_in_log || 0)) },
      { label: t("admin_pirates_kpi_play_loop", "Play-loop (log window)"), value: esc(String(kpis.play_loop_in_log || 0)) },
      { label: t("admin_pirates_kpi_economy_tick", "Economy ticks (log window)"), value: esc(String(kpis.bot_economy_tick_in_log || 0)) },
      { label: t("admin_pirates_kpi_builds_finished", "Builds finished (log window)"), value: esc(String(kpis.builds_finished_in_log || 0)) },
      { label: t("admin_pirates_kpi_wars", "Pirate wars (log window)"), value: esc(String(kpis.pirate_war_in_log || 0)) },
      { label: t("admin_pirates_kpi_infil", "Live infiltrations"), value: esc(String(kpis.live_infiltrations || 0)) },
      { label: t("admin_pirates_kpi_smugglers", "Live smugglers"), value: esc(String(kpis.live_smugglers || 0)) },
    ]);
    out.innerHTML =
      `<div class="admin-card">` +
      `<h3 class="admin-card-title">${esc(t("admin_pirates_section_status", "Status"))} ` +
      `${statusBadge(aiOn ? "ok" : "warn", aiLabel)}</h3>` +
      `</div>` +
      metrics +
      `<div class="admin-section-title"><span class="admin-section-title-text">${esc(t("admin_pirates_bots", "Faction bots"))}</span></div>` +
      renderAdminTable(
        [
          t("admin_pirates_col_faction", "Faction"),
          t("admin_col_name", "Name"),
          t("admin_pirates_col_coords", "Coords"),
          t("admin_pirates_col_buildings", "Mine/Lab/OS"),
          t("admin_pirates_col_score", "Score"),
          t("admin_pirates_col_ships", "Ships"),
          t("admin_pirates_col_fleets", "Fleets"),
          t("admin_pirates_col_ok", "OK"),
        ],
        botRows,
      ) +
      `<div class="admin-section-title"><span class="admin-section-title-text">${esc(t("admin_pirates_bases", "Live bases"))}</span></div>` +
      renderAdminTable(
        [
          t("admin_col_id", "ID"),
          t("admin_pirates_col_faction", "Faction"),
          t("admin_pirates_col_coords", "Coords"),
          t("admin_pirates_col_strength", "Str"),
          t("admin_col_status", "Status"),
          t("admin_pirates_col_hp", "HP"),
        ],
        baseRows,
      ) +
      `<div class="admin-section-title"><span class="admin-section-title-text">${esc(t("admin_pirates_heat_top", "Galaxy heat (top)"))}</span></div>` +
      renderAdminTable(
        [t("admin_pirates_col_galaxy", "G"), t("admin_pirates_col_heat", "Heat")],
        heatRows,
      ) +
      `<div class="admin-section-title"><span class="admin-section-title-text">${esc(t("admin_pirates_wars", "Active pirate_war"))}</span></div>` +
      renderAdminTable(
        [
          t("admin_pirates_col_galaxy", "G"),
          t("admin_pirates_col_heat", "Heat"),
          t("admin_pirates_col_ends", "Ends"),
        ],
        warRows,
      ) +
      `<div class="admin-section-title"><span class="admin-section-title-text">${esc(t("admin_pirates_log", "Action log"))}</span></div>` +
      renderAdminTable(
        [
          t("admin_pirates_col_utc", "UTC"),
          t("admin_pirates_col_severity", "Sev"),
          t("admin_pirates_col_kind", "Kind"),
          t("admin_pirates_col_message", "Message"),
          t("admin_pirates_col_faction", "Faction"),
        ],
        logRows,
      );
  }

  async function loadPiratesAdmin() {
    setPiratesStatus(t("admin_pirates_loading", "Lade Pirate Bot-Log…"));
    const data = await adminGet("/api/admin/pirates");
    if (!data.ok) {
      showAlert(data.message || data.error || t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      renderPiratesAdmin(data);
      setPiratesStatus("");
      return data;
    }
    renderPiratesAdmin(data);
    setPiratesStatus(t("admin_pirates_loaded", "Bot-Log geladen."));
    return data;
  }

  async function setPiratesAiAdmin(enabled) {
    if (
      enabled === false &&
      !adminDestructiveConfirmed(
        "admin_pirates_soft_off_confirm",
        "Pirate AI Soft-Off: disable pirate AI without recalling fleets?",
      )
    ) {
      return null;
    }
    setPiratesStatus(
      enabled
        ? t("admin_pirates_enabling", "Aktiviere Pirate AI…")
        : t("admin_pirates_disabling", "Deaktiviere Pirate AI…"),
    );
    const res = await adminPost("/api/admin/pirates/ai", { enabled: !!enabled });
    if (!res.ok) {
      showAlert(res.message || res.error || t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      setPiratesStatus("");
      return res;
    }
    notify(
      t("admin_pirates_ai_updated", "Pirate AI Kill-Switch aktualisiert."),
      "success",
    );
    await loadPiratesAdmin();
    return res;
  }

  async function hardOffPiratesAiAdmin() {
    if (
      !adminDestructiveConfirmed(
        "admin_pirates_hard_off_confirm",
        "Pirate AI Hard-Off: Soft-Off + Recall aller Pirate-Flotten?",
      )
    ) {
      return null;
    }
    setPiratesStatus(t("admin_pirates_hard_off_running", "Hard-Off läuft…"));
    const res = await adminPost("/api/admin/pirates/ai", { mode: "hard", enabled: false });
    if (!res.ok) {
      showAlert(res.message || res.error || t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      setPiratesStatus("");
      return res;
    }
    notify(
      t("admin_pirates_hard_off_done", "Pirate AI Hard-Off ausgeführt."),
      "success",
    );
    await loadPiratesAdmin();
    return res;
  }

  async function forceSpawnPiratesAdmin() {
    setPiratesStatus(t("admin_pirates_force_spawn_running", "Force-Spawn läuft…"));
    const res = await adminPost("/api/admin/pirates/force-spawn", {});
    if (!res.ok) {
      showAlert(res.message || res.error || t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      setPiratesStatus("");
      return res;
    }
    notify(
      t("admin_pirates_force_spawn_done", "Pirate base force-spawned."),
      "success",
    );
    await loadPiratesAdmin();
    return res;
  }

  async function forceTickPiratesAdmin() {
    setPiratesStatus(t("admin_pirates_force_tick_running", "Force-Tick läuft…"));
    const res = await adminPost("/api/admin/pirates/force-tick", {});
    if (!res.ok) {
      showAlert(res.message || res.error || t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      setPiratesStatus("");
      return res;
    }
    notify(
      t("admin_pirates_force_tick_done", "Pirate-Tick ausgeführt: {n} Play-Steps.").replace(
        "{n}",
        String(res.play_steps || 0),
      ),
      "success",
    );
    await loadPiratesAdmin();
    return res;
  }

  function setInactiveAutoplayStatus(msg) {
    const el = qs("#admin-inactive-autoplay-status");
    if (el) el.textContent = msg || "";
  }

  function renderInactiveAutoplayAdmin(data) {
    const out = qs("#admin-inactive-autoplay-output");
    if (!out) return;
    if (!data || !data.ok) {
      out.innerHTML = `<p class="admin-small-hint">${esc(data?.error || t("admin_action_failed", "Aktion fehlgeschlagen"))}</p>`;
      return;
    }
    const on = !!data.enabled;
    const onLabel = on
      ? t("admin_inactive_autoplay_on", "Autoplay: AN")
      : t("admin_inactive_autoplay_off", "Autoplay: AUS");
    const kpis = data.kpis || {};
    const cfg = data.config || {};
    const last = data.worker_last || {};
    const rosterRows = (data.roster || [])
      .map((r) => {
        const doneBits = [];
        if (r.builds_done) doneBits.push(`${r.builds_done}x ${t("admin_inactive_autoplay_action_build", "Bau")}`);
        if (r.research_done) doneBits.push(`${r.research_done}x ${t("admin_inactive_autoplay_action_research", "Forschung")}`);
        if (r.defense_done) doneBits.push(`${r.defense_done}x ${t("admin_inactive_autoplay_action_defense", "Verteidigung")}`);
        const lastAction = r.last_action
          ? `${esc(r.last_action)}${doneBits.length ? " (" + esc(doneBits.join(", ")) + ")" : ""}`
          : "–";
        const tenureLeft =
          r.tenure_remaining_sec == null
            ? "–"
            : `${Math.round(Number(r.tenure_remaining_sec) / 60)} min`;
        return (
          `<tr><td>${esc(String(r.player_id))}</td><td>${esc(r.username || "–")}</td>` +
          `<td>${esc(fmtTs(r.last_seen))}</td><td>${esc(fmtTs(r.joined_at))}</td>` +
          `<td>${esc(tenureLeft)}</td>` +
          `<td>${esc(fmtTs(r.last_ticked_at))}</td><td>${lastAction}</td></tr>`
        );
      })
      .join("");
    const metrics = renderMetricGrid([
      { label: t("admin_inactive_autoplay_kpi_roster", "Schicht-Größe"), value: esc(String(kpis.roster_size || 0)) },
      { label: t("admin_inactive_autoplay_kpi_shift_cap", "Shift-Cap"), value: esc(String(cfg.shift_cap || kpis.shift_cap || 0)) },
      { label: t("admin_inactive_autoplay_kpi_day_target", "Day-Target (Berlin)"), value: esc(String(cfg.day_target || kpis.day_target || 0)) },
      { label: t("admin_inactive_autoplay_kpi_max_roster", "Ops-Ceiling"), value: esc(String(cfg.max_roster || 0)) },
      { label: t("admin_inactive_autoplay_kpi_online_now", "Gerade \"online\" (Autoplay)"), value: esc(String(kpis.presence_visible_now || 0)) },
      { label: t("admin_inactive_autoplay_kpi_online_cap", "Online = Shift"), value: esc(String(cfg.online_visible_cap || 0)) },
      { label: t("admin_inactive_autoplay_kpi_tenure", "Schicht-Dauer (s)"), value: esc(String(cfg.tenure_sec || kpis.tenure_sec || 0)) },
      { label: t("admin_inactive_autoplay_kpi_woke", "Geweckt (letzter Zyklus)"), value: esc(String(kpis.woke_last_cycle || 0)) },
      { label: t("admin_inactive_autoplay_kpi_evicted", "Evicted (letzter Zyklus)"), value: esc(String(kpis.evicted_last_cycle || 0)) },
      { label: t("admin_inactive_autoplay_kpi_wait", "Wartezeit bis nächstes Wecken (s)"), value: esc(String(kpis.wait_sec || 0)) },
      { label: t("admin_inactive_autoplay_kpi_wait_economy", "Wartezeit bis nächste Economy (s)"), value: esc(String(kpis.wait_economy_sec || 0)) },
      { label: t("admin_inactive_autoplay_kpi_skip_streak", "Skips seit letztem Erfolg"), value: esc(String(kpis.post_maint_skip_streak || 0)) },
      { label: t("admin_inactive_autoplay_kpi_interval", "Weck-Intervall (s)"), value: esc(String(cfg.interval_sec || 0)) },
      { label: t("admin_inactive_autoplay_kpi_economy_interval", "Economy-Intervall (s)"), value: esc(String(cfg.economy_interval_sec || 0)) },
      { label: t("admin_inactive_autoplay_kpi_revisit", "Revisit-Fenster (s)"), value: esc(String(cfg.revisit_sec || 0)) },
      { label: t("admin_inactive_autoplay_kpi_tick", "Roster-Ticks/Cron"), value: esc(String(cfg.tick_per_cron || 0)) },
      { label: t("admin_inactive_autoplay_kpi_chain", "Chain-Limit"), value: esc(String(cfg.chain_limit || 0)) },
    ]);
    out.innerHTML =
      `<div class="admin-card">` +
      `<h3 class="admin-card-title">${esc(t("admin_inactive_autoplay_section_status", "Status"))} ` +
      `${statusBadge(on ? "ok" : "warn", onLabel)}</h3>` +
      `<p class="admin-small-hint">${esc(
        t("admin_inactive_autoplay_last_run", "Letzter Lauf"),
      )}: ${esc(fmtTs(last.at))} (${esc(last.source || "–")})</p>` +
      `</div>` +
      metrics +
      `<div class="admin-section-title"><span class="admin-section-title-text">${esc(
        t("admin_inactive_autoplay_roster", "Day-Shift Roster"),
      )}</span></div>` +
      renderAdminTable(
        [
          t("admin_col_id", "ID"),
          t("admin_col_name", "Name"),
          t("admin_inactive_autoplay_col_last_seen", "Zuletzt gesehen"),
          t("admin_inactive_autoplay_col_joined", "Im Roster seit"),
          t("admin_inactive_autoplay_col_tenure_left", "Tenure rest"),
          t("admin_inactive_autoplay_col_last_ticked", "Zuletzt getickt"),
          t("admin_inactive_autoplay_col_last_action", "Letzte Aktion"),
        ],
        rosterRows,
      );
  }

  async function loadInactiveAutoplayAdmin() {
    setInactiveAutoplayStatus(t("admin_inactive_autoplay_loading", "Lade Inactive Autoplay…"));
    const data = await adminGet("/api/admin/inactive-autoplay");
    if (!data.ok) {
      showAlert(data.message || data.error || t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      setInactiveAutoplayStatus("");
      return data;
    }
    renderInactiveAutoplayAdmin(data);
    setInactiveAutoplayStatus(t("admin_inactive_autoplay_loaded", "Inactive Autoplay geladen."));
    return data;
  }

  async function setInactiveAutoplayAdmin(enabled) {
    setInactiveAutoplayStatus(
      enabled
        ? t("admin_inactive_autoplay_enabling", "Aktiviere Inactive Autoplay…")
        : t("admin_inactive_autoplay_disabling", "Deaktiviere Inactive Autoplay…"),
    );
    const res = await adminPost("/api/admin/inactive-autoplay/toggle", { enabled: !!enabled });
    if (!res.ok) {
      showAlert(res.message || res.error || t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      setInactiveAutoplayStatus("");
      return res;
    }
    notify(
      t("admin_inactive_autoplay_updated", "Inactive Autoplay Kill-Switch aktualisiert."),
      "success",
    );
    await loadInactiveAutoplayAdmin();
    return res;
  }

  async function forceTickInactiveAutoplayAdmin() {
    setInactiveAutoplayStatus(t("admin_inactive_autoplay_force_tick_running", "Force-Tick läuft…"));
    const res = await adminPost("/api/admin/inactive-autoplay/force-tick", {});
    if (!res.ok) {
      showAlert(res.message || res.error || t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      setInactiveAutoplayStatus("");
      return res;
    }
    notify(
      t("admin_inactive_autoplay_force_tick_done", "Roster-Tick ausgeführt: {n} geweckt.").replace(
        "{n}",
        String(res.woke_count || 0),
      ),
      "success",
    );
    await loadInactiveAutoplayAdmin();
    return res;
  }

  let _adminEventsCache = [];
  let _adminEventSlugTouched = false;

  function _pad2(n) {
    return String(n).padStart(2, "0");
  }

  function unixToDatetimeLocal(unixSec) {
    const d = new Date(Number(unixSec) * 1000);
    if (!Number.isFinite(d.getTime())) return "";
    return (
      `${d.getFullYear()}-${_pad2(d.getMonth() + 1)}-${_pad2(d.getDate())}` +
      `T${_pad2(d.getHours())}:${_pad2(d.getMinutes())}`
    );
  }

  function datetimeLocalToUnix(value) {
    const raw = String(value || "").trim();
    if (!raw) return 0;
    const ms = Date.parse(raw);
    if (!Number.isFinite(ms)) return 0;
    return Math.floor(ms / 1000);
  }

  function formatLocalShort(unix) {
    const opts = { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" };
    try {
      return new Date(Number(unix) * 1000).toLocaleString(undefined, opts);
    } catch (_err) {
      return String(unix || "");
    }
  }

  function formatLocalRange(startUnix, endUnix) {
    return `${formatLocalShort(startUnix)}→${formatLocalShort(endUnix)}`;
  }

  function slugifyEventTitle(title) {
    const base = String(title || "")
      .toLowerCase()
      .normalize("NFKD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 40);
    const stamp = new Date()
      .toISOString()
      .slice(0, 10)
      .replace(/-/g, "");
    return (base || "boost") + "-" + stamp;
  }

  function nextSundayAtLocalHour(hour) {
    const d = new Date();
    const day = d.getDay(); // 0=Sun
    let add = (7 - day) % 7;
    if (add === 0) {
      // Already Sunday: if past target hour, jump to next Sunday.
      if (d.getHours() > hour || (d.getHours() === hour && d.getMinutes() > 0)) {
        add = 7;
      }
    }
    const out = new Date(d.getFullYear(), d.getMonth(), d.getDate() + add, hour, 0, 0, 0);
    return out;
  }

  function setEventWindow(startDate, endDate) {
    if (qs("#admin-event-starts")) {
      qs("#admin-event-starts").value = unixToDatetimeLocal(Math.floor(startDate.getTime() / 1000));
    }
    if (qs("#admin-event-ends")) {
      qs("#admin-event-ends").value = unixToDatetimeLocal(Math.floor(endDate.getTime() / 1000));
    }
    updateAdminEventWindowHint();
  }

  function updateAdminEventWindowHint() {
    const hint = qs("#admin-events-window-hint");
    if (!hint) return;
    const start = datetimeLocalToUnix(qs("#admin-event-starts")?.value);
    const end = datetimeLocalToUnix(qs("#admin-event-ends")?.value);
    if (!start || !end || end <= start) {
      hint.textContent = t(
        "admin_events_window_invalid",
        "Bitte Start und Ende wählen (Ende nach Start).",
      );
      return;
    }
    const hours = ((end - start) / 3600).toFixed(1);
    hint.textContent = `${formatLocalRange(start, end)} · ${hours}h · UTC ${start}–${end}`;
  }

  function applyEventEffects(kind) {
    const prod = qs("#admin-event-prod-mult");
    const hold = qs("#admin-event-hold-mult");
    const shop = qs("#admin-event-shop-bps");
    const build = qs("#admin-event-build-mult");
    const research = qs("#admin-event-research-mult");
    if (kind === "combo") {
      if (prod) prod.value = "2";
      if (hold) hold.value = "0.75";
      if (shop) shop.value = "";
      if (build) build.value = "";
      if (research) research.value = "";
    } else if (kind === "prod") {
      if (prod) prod.value = "2";
      if (hold) hold.value = "";
      if (shop) shop.value = "";
      if (build) build.value = "";
      if (research) research.value = "";
    } else if (kind === "hold") {
      if (prod) prod.value = "";
      if (hold) hold.value = "0.75";
      if (shop) shop.value = "";
      if (build) build.value = "";
      if (research) research.value = "";
    } else if (kind === "shop") {
      if (prod) prod.value = "";
      if (hold) hold.value = "";
      if (shop) shop.value = "2000";
      if (build) build.value = "";
      if (research) research.value = "";
    } else if (kind === "build") {
      if (prod) prod.value = "";
      if (hold) hold.value = "";
      if (shop) shop.value = "";
      if (build) build.value = "1.25";
      if (research) research.value = "1.25";
    }
  }

  function applyEventDuration(kind) {
    const now = new Date();
    now.setSeconds(0, 0);
    let start = now;
    let end;
    if (kind === "24h") {
      end = new Date(now.getTime() + 24 * 3600 * 1000);
    } else if (kind === "48h") {
      end = new Date(now.getTime() + 48 * 3600 * 1000);
    } else {
      // Start today 20:00 if still before; otherwise now. End Sunday 20:00.
      const today20 = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 20, 0, 0, 0);
      start = now.getTime() < today20.getTime() ? today20 : now;
      end = nextSundayAtLocalHour(20);
      if (end.getTime() <= start.getTime()) {
        end = new Date(end.getTime() + 7 * 24 * 3600 * 1000);
      }
    }
    setEventWindow(start, end);
  }

  function openEventsCompose() {
    const wrap = qs("#admin-events-compose-wrap");
    if (wrap) wrap.open = true;
    qs("#admin-events-compose")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function formatEtaSeconds(sec) {
    const s = Math.max(0, Math.floor(Number(sec) || 0));
    if (s < 60) return `<1m`;
    if (s < 3600) return `${Math.floor(s / 60)}m`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
    return `${Math.floor(s / 86400)}d ${Math.floor((s % 86400) / 3600)}h`;
  }

  function eventStatusBadge(status) {
    const st = String(status || "");
    const map = {
      active: t("admin_events_status_active", "LIVE"),
      scheduled: t("admin_events_status_scheduled", "GEPLANT"),
      ended: t("admin_events_status_ended", "ENDE"),
      disabled: t("admin_events_status_disabled", "AUS"),
    };
    return map[st] || st;
  }

  function resetAdminEventForm() {
    if (qs("#admin-event-id")) qs("#admin-event-id").value = "";
    _adminEventSlugTouched = false;
    if (qs("#admin-event-title")) qs("#admin-event-title").value = "";
    if (qs("#admin-event-slug")) qs("#admin-event-slug").value = "";
    if (qs("#admin-event-enabled")) qs("#admin-event-enabled").checked = true;
    if (qs("#admin-event-prod-mult")) qs("#admin-event-prod-mult").value = "";
    if (qs("#admin-event-hold-mult")) qs("#admin-event-hold-mult").value = "";
    if (qs("#admin-event-shop-bps")) qs("#admin-event-shop-bps").value = "";
    if (qs("#admin-event-build-mult")) qs("#admin-event-build-mult").value = "";
    if (qs("#admin-event-research-mult")) qs("#admin-event-research-mult").value = "";
    if (qs("#admin-event-starts")) qs("#admin-event-starts").value = "";
    if (qs("#admin-event-ends")) qs("#admin-event-ends").value = "";
    updateAdminEventWindowHint();
  }

  function fillAdminEventForm(entry) {
    if (!entry) return;
    _adminEventSlugTouched = true;
    if (qs("#admin-event-id")) qs("#admin-event-id").value = String(entry.id || "");
    if (qs("#admin-event-title")) qs("#admin-event-title").value = entry.title || "";
    if (qs("#admin-event-slug")) qs("#admin-event-slug").value = entry.slug || "";
    if (qs("#admin-event-starts")) {
      qs("#admin-event-starts").value = unixToDatetimeLocal(entry.starts_at || 0);
    }
    if (qs("#admin-event-ends")) {
      qs("#admin-event-ends").value = unixToDatetimeLocal(entry.ends_at || 0);
    }
    if (qs("#admin-event-enabled")) qs("#admin-event-enabled").checked = !!entry.enabled;
    let prod = "";
    let hold = "";
    let shop = "";
    let build = "";
    let research = "";
    (entry.effects || []).forEach((eff) => {
      if (eff.kind === "production_mult") prod = String(eff.mult);
      if (eff.kind === "expedition_hold_mult") hold = String(eff.mult);
      if (eff.kind === "shop_discount_bps") shop = String(eff.bps);
      if (eff.kind === "build_time_speed") build = String(eff.mult);
      if (eff.kind === "research_time_speed") research = String(eff.mult);
    });
    if (qs("#admin-event-prod-mult")) qs("#admin-event-prod-mult").value = prod;
    if (qs("#admin-event-hold-mult")) qs("#admin-event-hold-mult").value = hold;
    if (qs("#admin-event-shop-bps")) qs("#admin-event-shop-bps").value = shop;
    if (qs("#admin-event-build-mult")) qs("#admin-event-build-mult").value = build;
    if (qs("#admin-event-research-mult")) qs("#admin-event-research-mult").value = research;
    updateAdminEventWindowHint();
    openEventsCompose();
  }

  function collectAdminEventPayload() {
    const effects = [];
    const prodRaw = (qs("#admin-event-prod-mult")?.value || "").trim();
    const holdRaw = (qs("#admin-event-hold-mult")?.value || "").trim();
    const shopRaw = (qs("#admin-event-shop-bps")?.value || "").trim();
    const buildRaw = (qs("#admin-event-build-mult")?.value || "").trim();
    const researchRaw = (qs("#admin-event-research-mult")?.value || "").trim();
    if (prodRaw !== "") {
      effects.push({ kind: "production_mult", mult: Number(prodRaw) });
    }
    if (holdRaw !== "") {
      effects.push({ kind: "expedition_hold_mult", mult: Number(holdRaw) });
    }
    if (shopRaw !== "") {
      effects.push({ kind: "shop_discount_bps", bps: Number(shopRaw) });
    }
    if (buildRaw !== "") {
      effects.push({ kind: "build_time_speed", mult: Number(buildRaw) });
    }
    if (researchRaw !== "") {
      effects.push({ kind: "research_time_speed", mult: Number(researchRaw) });
    }
    let slug = (qs("#admin-event-slug")?.value || "").trim();
    const title = (qs("#admin-event-title")?.value || "").trim();
    if (!slug) slug = slugifyEventTitle(title || "boost");
    return {
      title,
      slug,
      starts_at: datetimeLocalToUnix(qs("#admin-event-starts")?.value),
      ends_at: datetimeLocalToUnix(qs("#admin-event-ends")?.value),
      enabled: !!qs("#admin-event-enabled")?.checked,
      effects,
    };
  }

  function formatPresetEffectSummary(effects) {
    return (effects || [])
      .map((e) => {
        if (e.kind === "production_mult") {
          const pct = Math.round((Number(e.mult) - 1) * 100);
          return pct >= 0 ? `Prod +${pct}%` : `Prod ${pct}%`;
        }
        if (e.kind === "expedition_hold_mult") {
          const pct = Math.round((1 - Number(e.mult)) * 100);
          return `Hold −${pct}%`;
        }
        if (e.kind === "shop_discount_bps") {
          return `Shop −${Math.round(Number(e.bps) / 100)}%`;
        }
        if (e.kind === "build_time_speed") {
          const pct = Math.round((Number(e.mult) - 1) * 100);
          return `Build +${pct}%`;
        }
        if (e.kind === "research_time_speed") {
          const pct = Math.round((Number(e.mult) - 1) * 100);
          return `Research +${pct}%`;
        }
        if (e.kind === "asteroid_spawn_mult") return `Asteroid ×${e.mult}`;
        if (e.kind === "world_boss_spawn_mult") return `Boss Hunt ×${e.mult}`;
        if (e.kind === "inactive_farm_mult") return `Inactive Farms ×${e.mult}`;
        return e.kind;
      })
      .join(" · ");
  }

  function renderAdminEventPresets(presets) {
    const host = qs("#admin-events-preset-gallery");
    if (!host) return;
    const list = Array.isArray(presets) ? presets : [];
    if (!list.length) {
      host.innerHTML = `<p class="admin-small-hint">${esc(
        t("admin_events_presets_empty", "Keine Presets geladen."),
      )}</p>`;
      return;
    }
    host.innerHTML = list
      .map((p) => {
        const bits = [];
        if (p.has_effects) bits.push(formatPresetEffectSummary(p.effects) || "");
        if (p.has_world_boss) bits.push(t("admin_events_preset_wb", "World Boss"));
        const dur = p.duration
          ? String(p.duration).replace(/_/g, " ")
          : t("admin_events_preset_now", "sofort");
        return (
          `<div class="admin-events-preset-tile" data-preset-id="${esc(p.id)}">` +
          `<div class="admin-events-preset-title" title="${esc(p.title || p.id)}">${esc(p.title || p.id)}</div>` +
          `<div class="admin-events-preset-effects" title="${esc((bits.join(" · ") || "—") + " · " + dur)}">${esc(bits.join(" · ") || "—")} · ${esc(dur)}</div>` +
          `<div class="admin-events-row-actions">` +
          `<button type="button" class="gc-btn gc-btn-primary gc-btn-xs" data-admin-action="events-preset-apply" data-preset-id="${esc(p.id)}">` +
          `${esc(t("admin_events_preset_apply", "Start"))}</button>` +
          `<button type="button" class="gc-btn gc-btn-outline gc-btn-xs" data-admin-action="events-preset-prefill" data-preset-id="${esc(p.id)}">` +
          `${esc(t("admin_events_preset_prefill_short", "Form"))}</button>` +
          `</div></div>`
        );
      })
      .join("");
  }

  async function applyAdminEventPreset(presetId, forceWorldBoss) {
    const status = qs("#admin-events-preset-status");
    if (status) {
      status.textContent = t("admin_events_preset_applying", "Preset wird angewendet…");
    }
    const payload = {
      tz_offset_minutes: -new Date().getTimezoneOffset(),
      force_world_boss: !!forceWorldBoss,
    };
    const res = await adminPost(
      `/api/admin/events/presets/${encodeURIComponent(presetId)}/apply`,
      payload,
    );
    if (!res.ok) {
      showAlert(res.message || res.error || t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      if (status) status.textContent = res.message || res.error || "";
      return res;
    }
    const actions = res.actions || [];
    const failedWb = actions.find((a) => a.type === "spawn_world_boss" && !a.ok);
    if (failedWb) {
      const err = failedWb.error || "spawn_failed";
      if (err === "boss_key_already_active" || err === "concurrent_cap") {
        const retry = window.confirm(
          t(
            "admin_events_preset_wb_force",
            "World Boss konnte nicht gespawnt werden ({err}). Mit force erneut versuchen?",
          ).replace("{err}", err),
        );
        if (retry) {
          return applyAdminEventPreset(presetId, true);
        }
      }
      notify(
        t("admin_events_preset_partial", "Event angelegt, World Boss fehlgeschlagen:") +
          " " +
          err,
        "warn",
      );
    } else {
      notify(t("admin_events_preset_ok", "Preset angewendet."), "success");
    }
    if (status) {
      const eid = res.event && res.event.id ? `#${res.event.id}` : "";
      status.textContent = `${t("admin_events_preset_ok", "Preset angewendet.")} ${eid}`.trim();
    }
    await loadAdminEvents();
    return res;
  }

  function prefillAdminEventPreset(presetId, presets) {
    const list = Array.isArray(presets) ? presets : _adminEventPresetsCache || [];
    const preset = list.find((p) => p.id === presetId);
    if (!preset) return;
    if (!preset.has_effects) {
      notify(
        t("admin_events_preset_no_effects", "Dieses Preset hat nur Actions (z. B. World Boss) — bitte Anwenden nutzen."),
        "info",
      );
      return;
    }
    if (qs("#admin-event-id")) qs("#admin-event-id").value = "";
    _adminEventSlugTouched = false;
    if (qs("#admin-event-title")) qs("#admin-event-title").value = preset.title || preset.id;
    if (qs("#admin-event-slug")) {
      qs("#admin-event-slug").value = slugifyEventTitle(preset.slug_prefix || preset.id);
    }
    if (qs("#admin-event-enabled")) qs("#admin-event-enabled").checked = true;
    if (qs("#admin-event-prod-mult")) qs("#admin-event-prod-mult").value = "";
    if (qs("#admin-event-hold-mult")) qs("#admin-event-hold-mult").value = "";
    if (qs("#admin-event-shop-bps")) qs("#admin-event-shop-bps").value = "";
    if (qs("#admin-event-build-mult")) qs("#admin-event-build-mult").value = "";
    if (qs("#admin-event-research-mult")) qs("#admin-event-research-mult").value = "";
    (preset.effects || []).forEach((eff) => {
      if (eff.kind === "production_mult" && qs("#admin-event-prod-mult")) {
        qs("#admin-event-prod-mult").value = String(eff.mult);
      }
      if (eff.kind === "expedition_hold_mult" && qs("#admin-event-hold-mult")) {
        qs("#admin-event-hold-mult").value = String(eff.mult);
      }
      if (eff.kind === "shop_discount_bps" && qs("#admin-event-shop-bps")) {
        qs("#admin-event-shop-bps").value = String(eff.bps);
      }
      if (eff.kind === "build_time_speed" && qs("#admin-event-build-mult")) {
        qs("#admin-event-build-mult").value = String(eff.mult);
      }
      if (eff.kind === "research_time_speed" && qs("#admin-event-research-mult")) {
        qs("#admin-event-research-mult").value = String(eff.mult);
      }
    });
    const dur = String(preset.duration || "24h");
    if (dur === "until_sunday_2000") applyEventDuration("sunday");
    else if (dur === "48h") applyEventDuration("48h");
    else applyEventDuration("24h");
    openEventsCompose();
  }

  let _adminEventPresetsCache = [];
  let _adminEventSchedulesCache = [];

  function weekdayLabel(day) {
    const labels = [
      t("admin_events_weekday_mon", "Mo"),
      t("admin_events_weekday_tue", "Di"),
      t("admin_events_weekday_wed", "Mi"),
      t("admin_events_weekday_thu", "Do"),
      t("admin_events_weekday_fri", "Fr"),
      t("admin_events_weekday_sat", "Sa"),
      t("admin_events_weekday_sun", "So"),
    ];
    return labels[Number(day)] || String(day);
  }

  function renderAdminEventSchedules(schedules) {
    const host = qs("#admin-events-schedule-list");
    if (!host) return;
    const list = Array.isArray(schedules) ? schedules : [];
    _adminEventSchedulesCache = list;
    if (!list.length) {
      host.innerHTML = `<p class="admin-small-hint">${esc(
        t("admin_events_schedules_empty", "Keine Schedule-Rules (Migration 144?)."),
      )}</p>`;
      return;
    }
    const rows = list
      .map((s) => {
        const days = (s.weekdays || []).map(weekdayLabel).join("");
        const en = !!s.enabled;
        const nw = s.next_window || null;
        let stateClass = "is-off";
        let stateLabel = t("admin_events_schedule_off", "AUS");
        let whenLine = "—";
        if (en && nw) {
          if (nw.already_materialized && nw.in_progress) {
            stateClass = "is-live";
            stateLabel = t("admin_events_schedule_slot_live", "LIVE");
            whenLine = `→${formatLocalShort(nw.ends_at)}`;
          } else if (nw.already_materialized) {
            stateClass = "is-ready";
            stateLabel = t("admin_events_schedule_ready", "OK");
            whenLine = formatLocalRange(nw.starts_at, nw.ends_at);
          } else if (nw.in_progress) {
            stateClass = "is-due";
            stateLabel = t("admin_events_schedule_due", "DUE");
            whenLine = formatLocalRange(nw.starts_at, nw.ends_at);
          } else {
            stateClass = "is-queued";
            stateLabel = t("admin_events_schedule_queued", "NÄCHST");
            whenLine = `in ${formatEtaSeconds(nw.seconds_until_start)} · ${formatLocalShort(nw.starts_at)}`;
          }
        } else if (en) {
          stateClass = "is-queued";
          stateLabel = t("admin_events_schedule_on", "AN");
        }
        return (
          `<tr class="${stateClass}" data-schedule-id="${Number(s.id)}">` +
          `<td><span class="admin-events-pill">${esc(stateLabel)}</span></td>` +
          `<td title="${esc(s.name || s.preset_id)}">${esc(s.name || s.preset_id)}</td>` +
          `<td title="${esc(whenLine)}">${esc(whenLine)}</td>` +
          `<td class="gc-mono">${esc(days)} ${esc(s.local_start_hhmm || "")}</td>` +
          `<td><div class="admin-events-row-actions">` +
          `<button type="button" class="gc-btn gc-btn-outline gc-btn-xs" data-admin-action="events-schedule-toggle" data-schedule-id="${Number(s.id)}" data-enabled="${en ? "0" : "1"}">` +
          `${esc(en ? t("admin_events_schedule_disable", "Pause") : t("admin_events_schedule_enable", "An"))}</button>` +
          `<button type="button" class="gc-btn gc-btn-primary gc-btn-xs" data-admin-action="events-schedule-materialize" data-schedule-id="${Number(s.id)}">` +
          `${esc(t("admin_events_schedule_materialize", "Anlegen"))}</button>` +
          `</div></td></tr>`
        );
      })
      .join("");
    host.innerHTML =
      `<table>` +
      `<colgroup><col class="col-st"><col class="col-name"><col class="col-when"><col class="col-rule"><col class="col-act"></colgroup>` +
      `<thead><tr>` +
      `<th>${esc(t("admin_events_col_status", "Status"))}</th>` +
      `<th>${esc(t("admin_events_col_name", "Rule"))}</th>` +
      `<th>${esc(t("admin_events_col_when", "Nächster Slot"))}</th>` +
      `<th>${esc(t("admin_events_col_rule", "Zeit"))}</th>` +
      `<th></th>` +
      `</tr></thead><tbody>${rows}</tbody></table>`;
  }

  async function toggleAdminEventSchedule(scheduleId, enabled) {
    const status = qs("#admin-events-schedule-status");
    const res = await adminPatch(`/api/admin/events/schedules/${Number(scheduleId)}`, {
      enabled: !!enabled,
    });
    if (!res.ok) {
      showAlert(res.message || res.error || t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      if (status) status.textContent = res.message || res.error || "";
      return res;
    }
    notify(t("admin_events_schedule_saved", "Schedule aktualisiert."), "success");
    await loadAdminEvents();
    return res;
  }

  async function materializeAdminEventSchedule(scheduleId) {
    const status = qs("#admin-events-schedule-status");
    if (status) {
      status.textContent = t("admin_events_schedule_running", "Materialisiere…");
    }
    const res = await adminPost(
      `/api/admin/events/schedules/${Number(scheduleId)}/materialize`,
      { force: true },
    );
    if (!res.ok) {
      showAlert(res.message || res.error || t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      if (status) status.textContent = res.message || res.error || "";
      return res;
    }
    if (res.skipped) {
      notify(t("admin_events_schedule_skipped", "Bereits materialisiert für diesen Slot."), "info");
    } else {
      notify(t("admin_events_schedule_ok", "Schedule materialisiert."), "success");
    }
    if (status) {
      const eid = res.event && res.event.id ? `#${res.event.id}` : "";
      status.textContent = `${t("admin_events_schedule_ok", "Schedule materialisiert.")} ${eid}`.trim();
    }
    await loadAdminEvents();
    return res;
  }

  function bindAdminEventFormHelpers() {
    const titleEl = qs("#admin-event-title");
    const slugEl = qs("#admin-event-slug");
    if (titleEl && !titleEl.dataset.eventsBound) {
      titleEl.dataset.eventsBound = "1";
      titleEl.addEventListener("input", () => {
        if (_adminEventSlugTouched || !slugEl) return;
        slugEl.value = slugifyEventTitle(titleEl.value);
      });
    }
    if (slugEl && !slugEl.dataset.eventsBound) {
      slugEl.dataset.eventsBound = "1";
      slugEl.addEventListener("input", () => {
        _adminEventSlugTouched = true;
      });
    }
    ["#admin-event-starts", "#admin-event-ends"].forEach((sel) => {
      const el = qs(sel);
      if (el && !el.dataset.eventsBound) {
        el.dataset.eventsBound = "1";
        el.addEventListener("change", updateAdminEventWindowHint);
        el.addEventListener("input", updateAdminEventWindowHint);
      }
    });
  }

  function renderAdminEvents(data) {
    bindAdminEventFormHelpers();
    const activeHost = qs("#admin-events-active");
    const liveCards = qs("#admin-events-live-cards");
    const listHost = qs("#admin-events-list");
    const active = data.active || {};
    _adminEventPresetsCache = Array.isArray(data.presets) ? data.presets : [];
    renderAdminEventPresets(_adminEventPresetsCache);
    renderAdminEventSchedules(Array.isArray(data.schedules) ? data.schedules : []);

    const shopBps = Number(active.shop_discount_bps || 0);
    const factorRows = [
      {
        label: t("admin_events_kpi_prod", "Prod"),
        value: `×${Number(active.production_mult || 1).toFixed(2)}`,
        hot: Number(active.production_mult || 1) > 1.001,
      },
      {
        label: t("admin_events_kpi_hold", "Hold"),
        value: `×${Number(active.expedition_hold_mult || 1).toFixed(2)}`,
        hot: Math.abs(Number(active.expedition_hold_mult || 1) - 1) > 0.001,
      },
      {
        label: t("admin_events_kpi_shop", "Shop"),
        value: shopBps > 0 ? `−${Math.round(shopBps / 100)}%` : "—",
        hot: shopBps > 0,
      },
      {
        label: t("admin_events_kpi_build", "Build"),
        value: `×${Number(active.build_time_speed || 1).toFixed(2)}`,
        hot: Number(active.build_time_speed || 1) > 1.001,
      },
      {
        label: t("admin_events_kpi_research", "Research"),
        value: `×${Number(active.research_time_speed || 1).toFixed(2)}`,
        hot: Number(active.research_time_speed || 1) > 1.001,
      },
      {
        label: t("admin_events_kpi_asteroid", "Asteroid"),
        value: `×${Number(active.asteroid_spawn_mult || 1).toFixed(2)}`,
        hot: Number(active.asteroid_spawn_mult || 1) > 1.001,
      },
      {
        label: t("admin_events_kpi_boss", "Boss"),
        value: `×${Number(active.world_boss_spawn_mult || 1).toFixed(2)}`,
        hot: Number(active.world_boss_spawn_mult || 1) > 1.001,
      },
      {
        label: t("admin_events_kpi_farm", "Farm"),
        value: `×${Number(active.inactive_farm_mult || 1).toFixed(2)}`,
        hot: Number(active.inactive_farm_mult || 1) > 1.001,
      },
    ].filter((m) => m.hot);

    if (activeHost) {
      if (!factorRows.length) {
        activeHost.innerHTML = `<span class="admin-events-quiet">${esc(
          t("admin_events_live_none", "Keine Extra-Boni — Basiswerte."),
        )}</span>`;
      } else {
        activeHost.innerHTML = factorRows
          .map(
            (m) =>
              `<span class="admin-events-chip is-hot"><b>${esc(m.label)}</b> ${esc(m.value)}</span>`,
          )
          .join("");
      }
    }

    _adminEventsCache = Array.isArray(data.events) ? data.events : [];
    const liveEvents = Array.isArray(active.events) ? active.events : [];
    if (liveCards) {
      if (!liveEvents.length) {
        liveCards.innerHTML = "";
      } else {
        liveCards.innerHTML = liveEvents
          .map((ev) => {
            const effects = formatPresetEffectSummary(ev.effects);
            const eid = Number(ev.id);
            return (
              `<div class="admin-events-live-row" data-event-id="${eid}">` +
              `<strong title="${esc(ev.title || ev.slug)}">${esc(ev.title || ev.slug)}</strong>` +
              `<span title="${esc(effects || "")}">${esc(effects || "—")}</span>` +
              `<span class="admin-small-hint" title="${esc(formatLocalRange(ev.starts_at, ev.ends_at))}">${esc(formatLocalRange(ev.starts_at, ev.ends_at))}</span>` +
              `<div class="admin-events-row-actions">` +
              `<button type="button" class="gc-btn gc-btn-outline gc-btn-xs" data-admin-action="events-edit" data-event-id="${eid}">${esc(
                t("admin_events_edit_short", "Edit"),
              )}</button>` +
              `<button type="button" class="gc-btn gc-btn-danger gc-btn-xs" data-admin-action="events-delete" data-event-id="${eid}">${esc(
                t("admin_events_delete_short", "Del"),
              )}</button>` +
              `</div></div>`
            );
          })
          .join("");
      }
    }

    const countEl = qs("#admin-events-list-count");
    const scheduled = _adminEventsCache.filter((e) => e.status === "scheduled");
    const closedEv = _adminEventsCache.filter((e) => e.status === "ended" || e.status === "disabled");
    if (countEl) {
      const parts = [];
      if (scheduled.length) parts.push(`${scheduled.length} ${t("admin_events_status_scheduled", "GEPLANT")}`);
      if (closedEv.length) parts.push(`${closedEv.length} ${t("admin_events_list_closed", "alt")}`);
      countEl.textContent = parts.length ? parts.join(" · ") : t("admin_events_list_none_extra", "keine");
    }
    if (!listHost) return;
    if (!scheduled.length && !closedEv.length) {
      listHost.innerHTML = `<p class="admin-small-hint">${esc(
        t("admin_events_list_empty_extra", "Keine geplanten oder alten Events."),
      )}</p>`;
      return;
    }

    function rowHtml(ev) {
      const effects = formatPresetEffectSummary(ev.effects);
      const st = String(ev.status || "");
      return (
        `<div class="admin-events-item status-${esc(st)}" data-event-id="${Number(ev.id)}">` +
        `<span class="admin-events-pill status-${esc(st)}">${esc(eventStatusBadge(st))}</span>` +
        `<div class="admin-events-item-main">` +
        `<div class="admin-events-item-title">${esc(ev.title || ev.slug)}</div>` +
        `<div class="admin-events-item-meta">${esc(effects || "—")} · ${esc(formatLocalRange(ev.starts_at, ev.ends_at))}</div>` +
        `</div>` +
        `<div class="admin-events-row-actions">` +
        `<button type="button" class="gc-btn gc-btn-outline gc-btn-xs" data-admin-action="events-edit" data-event-id="${Number(ev.id)}">${esc(
          t("admin_events_edit_short", "Edit"),
        )}</button>` +
        `<button type="button" class="gc-btn gc-btn-danger gc-btn-xs" data-admin-action="events-delete" data-event-id="${Number(ev.id)}">${esc(
          t("admin_events_delete_short", "Del"),
        )}</button>` +
        `</div></div>`
      );
    }

    let html = scheduled.map(rowHtml).join("");
    if (closedEv.length) {
      html +=
        `<details class="admin-events-old">` +
        `<summary>${esc(t("admin_events_list_show_old", "Alte / beendete anzeigen"))} (${closedEv.length})</summary>` +
        closedEv.map(rowHtml).join("") +
        `</details>`;
    }
    listHost.innerHTML = html;
  }

  async function loadAdminEvents() {
    const data = await adminGet("/api/admin/events");
    if (!data.ok) {
      showAlert(data.message || data.error || t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      return data;
    }
    renderAdminEvents(data);
    return data;
  }

  async function saveAdminEvent() {
    const payload = collectAdminEventPayload();
    if (!payload.starts_at || !payload.ends_at || payload.ends_at <= payload.starts_at) {
      showAlert(
        t("admin_events_window_invalid", "Bitte Start und Ende wählen (Ende nach Start)."),
        "error",
      );
      return null;
    }
    if (!payload.effects.length) {
      showAlert(
        t("admin_events_effects_required", "Mindestens einen Effekt setzen (Prod und/oder Hold)."),
        "error",
      );
      return null;
    }
    const idRaw = (qs("#admin-event-id")?.value || "").trim();
    let res;
    if (idRaw) {
      res = await adminPatch(`/api/admin/events/${Number(idRaw)}`, payload);
    } else {
      res = await adminPost("/api/admin/events", payload);
    }
    if (!res.ok) {
      showAlert(res.message || res.error || t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      return res;
    }
    notify(t("admin_events_saved", "Event gespeichert."), "success");
    resetAdminEventForm();
    await loadAdminEvents();
    return res;
  }

  async function editAdminEvent(eventId) {
    const entry = _adminEventsCache.find((e) => Number(e.id) === Number(eventId));
    if (!entry) {
      showAlert(t("admin_events_not_found", "Event nicht gefunden."), "error");
      return;
    }
    fillAdminEventForm(entry);
  }

  async function deleteAdminEvent(eventId) {
    if (
      !window.confirm(
        t("admin_events_delete_confirm", "Event wirklich löschen?"),
      )
    ) {
      return null;
    }
    const res = await adminDelete(`/api/admin/events/${Number(eventId)}`);
    if (!res.ok) {
      showAlert(res.message || res.error || t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      return res;
    }
    notify(t("admin_events_deleted", "Event gelöscht."), "success");
    await loadAdminEvents();
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

  function collectUniverseResetOptions() {
    const opts = {};
    document.querySelectorAll("[data-universe-reset-domain]").forEach((el) => {
      const key = el.getAttribute("data-universe-reset-domain");
      if (key) opts[key] = !!el.checked;
    });
    return opts;
  }

  function syncUniverseResetSelectAll() {
    const master = qs("#universe_reset_select_all");
    const boxes = [...document.querySelectorAll("[data-universe-reset-domain]")];
    if (!master || !boxes.length) return;
    const allOn = boxes.every((el) => el.checked);
    const anyOn = boxes.some((el) => el.checked);
    master.checked = allOn;
    master.indeterminate = !allOn && anyOn;
  }

  function initUniverseResetDomainCheckboxes() {
    const master = qs("#universe_reset_select_all");
    const boxes = [...document.querySelectorAll("[data-universe-reset-domain]")];
    if (!boxes.length) return;
    boxes.forEach((el) => {
      el.addEventListener("change", syncUniverseResetSelectAll);
    });
    if (master) {
      master.addEventListener("change", () => {
        const on = !!master.checked;
        boxes.forEach((el) => {
          el.checked = on;
        });
        master.indeterminate = false;
      });
    }
    syncUniverseResetSelectAll();
  }

  async function resetAdminUniverseKeepInventory() {
    const reset_options = collectUniverseResetOptions();
    if (!Object.values(reset_options).some(Boolean)) {
      showAlert(
        t("admin_universe_reset_domains_required", "Wähle mindestens einen Bereich zum Zurücksetzen."),
        "error",
      );
      return null;
    }
    if (
      !adminDestructiveConfirmed(
        "admin_universe_reset_confirm_dialog",
        "Universum wirklich zurücksetzen? Inventar bleibt erhalten. Diese Aktion kann nicht rückgängig gemacht werden.",
      )
    ) {
      return null;
    }
    const res = await adminPost("/api/admin/universe-reset", { confirm: true, reset_options });
    if (res.ok) {
      const n = res.players_reinitialized ?? 0;
      const backup = res.backup_path ? ` Backup: ${res.backup_path}` : "";
      const msg = t(
        "msg_admin_universe_reset",
        "Season-Reset abgeschlossen. %(count)s Spieler neu initialisiert.%(backup)s",
      )
        .replace("%(count)s", String(n))
        .replace("%(backup)s", backup);
      notify(msg, "success");
      setServerStatus(msg);
      await syncAfterAdminChange("admin_universe_reset", { reloadTab: true });
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
    if (
      !adminDestructiveConfirmed(
        "admin_migrations_confirm_dialog",
        "Ausstehende Migrationen jetzt ausführen? Datenbank wird geändert.",
      )
    ) {
      return { ok: false, error: "cancelled" };
    }
    const data = await adminPost("/api/admin/migrations/run", { confirm: true });
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
      "item",
      "booster",
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

  async function loadAdminPromos() {
    const host = qs("#admin-promos-panel");
    if (!host) return { ok: false };
    host.innerHTML = loadingHtml();
    const data = await adminGet("/api/admin/promos/state");
    if (!data.ok) {
      host.innerHTML = errorCard(data);
      return data;
    }
    const creators = data.creators || [];
    const campaigns = data.campaigns || [];
    const rows = creators
      .map((c) => {
        const perf = c.performance || {};
        const bal = perf.balance || c.balance || {};
        const code = perf.code || ((c.codes || []).find((p) => p.active) || {}).code || "—";
        const statusLabel =
          (perf.status || (c.active ? "active" : "inactive")) === "active"
            ? t("admin_promos_state_active", "active")
            : t("admin_promos_state_inactive", "inactive");
        const toggleCodes = (c.codes || [])
          .map((p) => {
            const on = !!p.active;
            const toggleLabel = on
              ? t("admin_promos_disable", "Disable")
              : t("admin_promos_enable", "Enable");
            return (
              `<button type="button" class="gc-btn gc-btn-xs gc-btn-outline" data-admin-promo-toggle="${p.id}" data-active="${on ? 0 : 1}">` +
              `${esc(toggleLabel)}</button>`
            );
          })
          .join(" ");
        return (
          `<tr data-creator-id="${c.id}">` +
          `<td>${esc(c.display_name)}</td>` +
          `<td><strong>${esc(code)}</strong></td>` +
          `<td>${Number(perf.registrations || 0)}</td>` +
          `<td>${Number(perf.active_7d || 0)}</td>` +
          `<td>${Number(perf.active_30d || 0)}</td>` +
          `<td>${Number(perf.donations || 0)}</td>` +
          `<td>${(Number(perf.revenue_cents || 0) / 100).toFixed(2)} €</td>` +
          `<td>${(Number(bal.available || 0) / 100).toFixed(2)} €</td>` +
          `<td>${esc(statusLabel)} ${toggleCodes} <a class="gc-btn gc-btn-xs gc-btn-outline" href="/api/admin/promos/${c.id}/ledger.csv">${esc(t("admin_promos_csv", "CSV"))}</a></td>` +
          `</tr>`
        );
      })
      .join("");
    const campaignRows = campaigns
      .map((p) => {
        const on = !!p.active;
        const toggleLabel = on
          ? t("admin_promos_disable", "Disable")
          : t("admin_promos_enable", "Enable");
        const maxR = p.max_redemptions == null ? "∞" : String(p.max_redemptions);
        return (
          `<tr>` +
          `<td><strong>${esc(p.code)}</strong></td>` +
          `<td>${(Number(p.discount_bps || 0) / 100).toFixed(0)}%</td>` +
          `<td>${Number(p.redemptions || 0)} / ${esc(maxR)}</td>` +
          `<td>${esc(p.notes || "—")}</td>` +
          `<td>` +
          `<button type="button" class="gc-btn gc-btn-xs gc-btn-outline" data-admin-promo-toggle="${p.id}" data-active="${on ? 0 : 1}">${esc(toggleLabel)}</button>` +
          `</td>` +
          `</tr>`
        );
      })
      .join("");
    host.innerHTML =
      `<div class="admin-tool-panel">` +
      `<h4 class="admin-tool-panel__title">${esc(t("admin_promos_create", "Creator anlegen"))}</h4>` +
      `<div class="admin-form-grid">` +
      `<label>${esc(t("admin_promos_player_id", "Player ID"))}<input type="number" id="admin-promo-player-id" class="gc-input"></label>` +
      `<label>${esc(t("admin_promos_name", "Name"))}<input type="text" id="admin-promo-name" class="gc-input"></label>` +
      `<label>${esc(t("admin_promos_code", "Code"))}<input type="text" id="admin-promo-code" class="gc-input"></label>` +
      `<label>${esc(t("admin_promos_paypal", "PayPal"))}<input type="text" id="admin-promo-paypal" class="gc-input"></label>` +
      `<button type="button" class="gc-btn gc-btn-primary" id="admin-promo-create">${esc(t("admin_promos_create_btn", "Anlegen"))}</button>` +
      `</div></div>` +
      `<div class="admin-tool-panel" style="margin-top:0.75rem">` +
      `<h4 class="admin-tool-panel__title">${esc(t("admin_promos_campaign_create", "Event-/Discount-Code"))}</h4>` +
      `<p class="admin-small-hint">${esc(t("admin_promos_campaign_hint", "Nur Shop-Rabatt — ideal für Verlosungen & Events. Keine Creator-Kommission."))}</p>` +
      `<div class="admin-form-grid">` +
      `<label>${esc(t("admin_promos_code", "Code"))}<input type="text" id="admin-campaign-code" class="gc-input"></label>` +
      `<label>${esc(t("admin_promos_discount_pct", "Rabatt %"))}<input type="number" id="admin-campaign-discount" class="gc-input" value="10" min="1" max="90"></label>` +
      `<label>${esc(t("admin_promos_max_uses", "Max Uses"))}<input type="number" id="admin-campaign-max" class="gc-input" placeholder="∞"></label>` +
      `<label>${esc(t("admin_promos_notes", "Notiz"))}<input type="text" id="admin-campaign-notes" class="gc-input" placeholder="Event Giveaway"></label>` +
      `<button type="button" class="gc-btn gc-btn-primary" id="admin-campaign-create">${esc(t("admin_promos_campaign_create_btn", "Code anlegen"))}</button>` +
      `</div></div>` +
      `<div class="admin-section-title" style="margin-top:1rem"><span class="admin-section-title-text">${esc(t("admin_promos_campaigns_title", "Campaign Codes"))}</span></div>` +
      `<div class="admin-table-wrap"><table class="admin-table admin-table-compact"><thead><tr>` +
      `<th>${esc(t("admin_promos_col_code", "Code"))}</th>` +
      `<th>${esc(t("admin_promos_discount_pct", "Rabatt %"))}</th>` +
      `<th>${esc(t("admin_promos_col_uses", "Uses"))}</th>` +
      `<th>${esc(t("admin_promos_notes", "Notiz"))}</th>` +
      `<th>${esc(t("admin_promos_col_status", "Status"))}</th>` +
      `</tr></thead><tbody>${campaignRows || `<tr><td colspan="5">${esc(t("admin_promos_campaigns_empty", "Keine Campaign-Codes"))}</td></tr>`}</tbody></table></div>` +
      `<div class="admin-section-title" style="margin-top:1rem"><span class="admin-section-title-text">${esc(t("admin_promos_creators_title", "Creators"))}</span></div>` +
      `<div class="admin-table-wrap"><table class="admin-table admin-table-compact"><thead><tr>` +
      `<th>${esc(t("admin_promos_col_creator", "Creator"))}</th>` +
      `<th>${esc(t("admin_promos_col_code", "Code"))}</th>` +
      `<th>${esc(t("admin_promos_col_regs", "Registrations"))}</th>` +
      `<th>${esc(t("admin_promos_col_active_7d", "Active (7d)"))}</th>` +
      `<th>${esc(t("admin_promos_col_active_30d", "Active (30d)"))}</th>` +
      `<th>${esc(t("admin_promos_col_donations", "Donations"))}</th>` +
      `<th>${esc(t("admin_promos_col_revenue", "Revenue"))}</th>` +
      `<th>${esc(t("admin_promos_col_balance", "Balance €"))}</th>` +
      `<th>${esc(t("admin_promos_col_status", "Status"))}</th>` +
      `</tr></thead><tbody>${rows || `<tr><td colspan="9">${esc(t("admin_promos_empty", "Keine Creators"))}</td></tr>`}</tbody></table></div>`;

    const createBtn = qs("#admin-promo-create", host);
    if (createBtn) {
      createBtn.onclick = async () => {
        const body = {
          player_id: Number(qs("#admin-promo-player-id", host)?.value || 0),
          display_name: qs("#admin-promo-name", host)?.value || "",
          code: qs("#admin-promo-code", host)?.value || "",
          paypal_email: qs("#admin-promo-paypal", host)?.value || "",
        };
        const res = await adminPost("/api/admin/promos/creators", body);
        if (!res.ok) {
          showAlert(res.message || res.error, "error");
          return;
        }
        showAlert(t("admin_promos_created", "Creator angelegt."), "success");
        await loadAdminPromos();
      };
    }
    const campaignBtn = qs("#admin-campaign-create", host);
    if (campaignBtn) {
      campaignBtn.onclick = async () => {
        const discountPct = Number(qs("#admin-campaign-discount", host)?.value || 10);
        const maxRaw = qs("#admin-campaign-max", host)?.value;
        const body = {
          kind: "campaign",
          code: qs("#admin-campaign-code", host)?.value || "",
          discount_bps: Math.round(discountPct * 100),
          max_redemptions: maxRaw === "" || maxRaw == null ? null : Number(maxRaw),
          notes: qs("#admin-campaign-notes", host)?.value || "",
        };
        const res = await adminPost("/api/admin/promos/codes", body);
        if (!res.ok) {
          showAlert(res.message || res.error, "error");
          return;
        }
        showAlert(t("admin_promos_campaign_created", "Campaign-Code angelegt."), "success");
        await loadAdminPromos();
      };
    }
    host.querySelectorAll("[data-admin-promo-toggle]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const res = await adminPost("/api/admin/promos/codes/active", {
          promo_id: Number(btn.getAttribute("data-admin-promo-toggle") || 0),
          active: Number(btn.getAttribute("data-active") || 0) === 1,
        });
        if (!res.ok) {
          showAlert(res.message || res.error, "error");
          return;
        }
        await loadAdminPromos();
      });
    });
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

  async function loadAdminOnlinePlayers() {
    const out = qs("#admin-online-output");
    const countEl = qs("[data-admin-online-count]");
    if (out) out.innerHTML = loadingHtml();
    const data = await adminGet("/api/admin/players?online=1");
    if (!data.ok) {
      showAlert(data.message, "error");
      if (out) out.innerHTML = errorCard(data);
      return data;
    }
    const players = Array.isArray(data.players) ? data.players : [];
    if (countEl) countEl.textContent = String(players.length);
    if (!out) return data;
    if (!players.length) {
      out.innerHTML = `<p class="admin-empty">${esc(t("admin_online_players_empty", "Niemand online"))}</p>`;
      return data;
    }
    const nowSec = Math.floor(Date.now() / 1000);
    const rows = players.map((p) => {
      const last = Number(p.last_seen) || 0;
      const ago = last > 0 ? Math.max(0, nowSec - last) : null;
      const agoLabel =
        ago == null
          ? "—"
          : ago < 60
            ? t("admin_online_players_ago_sec", "vor %ss").replace("%s", String(ago))
            : t("admin_online_players_ago_min", "vor %s min").replace(
                "%s",
                String(Math.floor(ago / 60))
              );
      const display = p.player_name || p.username || String(p.id);
      return `<tr class="admin-entity-row" data-admin-player-id="${p.id}" title="${esc(t("admin_btn_details", "Details"))}">
        <td class="col-id">${p.id}</td>
        <td class="col-name">${playerNameLink(p.id, display)}</td>
        <td class="col-flag">${p.is_admin ? "✓" : "–"}</td>
        <td class="col-date" title="${esc(fmtTs(p.last_seen))}">${esc(agoLabel)}</td>
      </tr>`;
    });
    out.innerHTML = renderTable(
      [
        t("admin_col_id", "ID"),
        t("admin_col_username", "Username"),
        t("admin_col_admin", "Admin"),
        t("admin_col_last_seen", "Zuletzt"),
      ],
      rows,
      { inline: true }
    );
    return data;
  }

  async function renderPlayerDetail(data) {
    const el = qs("#admin-player-detail");
    if (!el || !data.ok) return;
    const p = data.player || {};
    const hw = data.homeworld || {};
    const score = data.score || {};
    const planets = Array.isArray(data.planets) ? data.planets : [];
    const research = data.research || {};
    const researchKeys = Array.isArray(data.research_keys) ? data.research_keys : Object.keys(research);
    const planetRows = planets
      .map(
        (pl) =>
          `<tr class="admin-entity-row" data-admin-open-planet="${pl.id}" title="${esc(t("admin_btn_details", "Details"))}">` +
          `<td class="col-id">${pl.id}</td>` +
          `<td class="col-name">${esc(pl.name || "")}</td>` +
          `<td class="col-flag">${pl.is_homeworld ? "HW" : "–"}</td>` +
          `</tr>`
      )
      .join("");
    const researchGrid = researchKeys
      .map((key) => {
        const lvl = Number(research[key] || 0);
        return (
          `<label class="admin-level-cell">` +
          `<span class="admin-level-key">${esc(key)}</span>` +
          `<input type="number" min="0" max="100" class="admin-input admin-input-sm admin-research-level" data-tech-key="${esc(key)}" value="${lvl}">` +
          `</label>`
        );
      })
      .join("");
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
      <div class="admin-danger-zone">
        <p class="admin-small-hint">${t("admin_player_delete_hint", "Account unwiderruflich löschen. Spielernamen zur Bestätigung eingeben.")}</p>
        <input type="text" class="admin-input admin-input-sm" id="admin-player-delete-username" placeholder="${t("admin_player_delete_username", "Spielername")}" autocomplete="off">
        <button type="button" class="gc-btn gc-btn-danger gc-btn-sm" data-admin-action="player-delete" data-player-id="${p.id}" data-player-name="${esc(p.username || "")}">${t("admin_btn_delete_player", "Account löschen")}</button>
      </div>
      <div class="admin-toolbar admin-toolbar--tight">
        <input type="number" min="0" class="admin-input admin-input-sm" id="admin-player-metal" placeholder="${t("metal", "Ferronit")}">
        <input type="number" min="0" class="admin-input admin-input-sm" id="admin-player-crystal" placeholder="${t("crystal", "Crytite")}">
        <input type="number" min="0" class="admin-input admin-input-sm" id="admin-player-fuel" placeholder="${t("fuel_cells", "Brennzellen")}">
        <button type="button" class="gc-btn gc-btn-primary gc-btn-sm" data-admin-action="player-resources-add" data-player-id="${p.id}">${t("admin_btn_apply", "Addieren")}</button>
        <button type="button" class="gc-btn gc-btn-outline gc-btn-sm" data-admin-action="player-resources-set" data-player-id="${p.id}">${t("admin_btn_set_resources", "Setzen")}</button>
      </div>
      <div class="admin-section-title"><span class="admin-section-title-text">${t("admin_player_planets", "Planeten")}</span></div>
      ${
        planetRows
          ? `<div class="admin-table-wrap"><table class="admin-table table-std admin-table--entity"><thead><tr>
              <th>${esc(t("admin_col_id", "ID"))}</th>
              <th>${esc(t("admin_col_name", "Name"))}</th>
              <th>HW</th>
            </tr></thead><tbody>${planetRows}</tbody></table></div>`
          : `<p class="admin-small-hint">${esc(t("admin_player_no_planets", "Keine Planeten."))}</p>`
      }
      <details class="admin-buildings-detail open" open>
        <summary>${t("admin_research", "Forschung")}</summary>
        <div class="admin-level-grid">${researchGrid || `<p class="admin-small-hint">–</p>`}</div>
        <div class="admin-toolbar">
          <button type="button" class="gc-btn gc-btn-primary gc-btn-sm" data-admin-action="player-research-save" data-player-id="${p.id}">${t("admin_btn_save_research", "Forschung speichern")}</button>
        </div>
      </details>`;
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
    const keys = Array.isArray(data.building_keys) && data.building_keys.length
      ? data.building_keys
      : Object.keys(b);
    const caps = data.storage_caps || {};
    const ships = data.ships || {};
    const defense = data.defense || {};
    const shipKeys = Array.isArray(data.ship_keys) && data.ship_keys.length
      ? data.ship_keys
      : Object.keys(ships);
    const defenseKeys = Array.isArray(data.defense_keys) && data.defense_keys.length
      ? data.defense_keys
      : Object.keys(defense);
    const buildingGrid = keys
      .map((key) => {
        const lvl = Number(b[key] || 0);
        return (
          `<label class="admin-level-cell">` +
          `<span class="admin-level-key">${esc(key)}</span>` +
          `<input type="number" min="0" max="100" class="admin-input admin-input-sm admin-building-level" data-building-key="${esc(key)}" value="${lvl}">` +
          `</label>`
        );
      })
      .join("");
    const shipGrid = shipKeys
      .map((key) => {
        const qty = Number(ships[key] || 0);
        return (
          `<label class="admin-level-cell">` +
          `<span class="admin-level-key">${esc(key)}</span>` +
          `<input type="number" min="0" class="admin-input admin-input-sm admin-ship-qty" data-ship-key="${esc(key)}" value="${qty}">` +
          `</label>`
        );
      })
      .join("");
    const defenseGrid = defenseKeys
      .map((key) => {
        const qty = Number(defense[key] || 0);
        return (
          `<label class="admin-level-cell">` +
          `<span class="admin-level-key">${esc(key)}</span>` +
          `<input type="number" min="0" class="admin-input admin-input-sm admin-defense-qty" data-defense-key="${esc(key)}" value="${qty}">` +
          `</label>`
        );
      })
      .join("");
    el.innerHTML = `
      <h3 class="admin-subtitle">#${pl.id} ${esc(pl.name || "")}</h3>
      <p>${t("metal", "Ferronit")}: ${fmtInt(pl.metal)} · ${t("crystal", "Crytite")}: ${fmtInt(pl.crystal)} · ${t("fuel_cells", "Brennzellen")}: ${fmtInt(pl.fuel_cells)}</p>
      <p class="admin-small-hint">${t("admin_storage_caps", "Lager-Caps")}: ${t("metal", "Ferronit")} ${fmtInt(caps.metal)} · ${t("crystal", "Crytite")} ${fmtInt(caps.crystal)} · ${t("fuel_cells", "Brennzellen")} ${fmtInt(caps.fuel_cells)}</p>
      <div class="admin-toolbar admin-toolbar--tight">
        <input type="number" min="0" class="admin-input admin-input-sm" id="admin-planet-metal" placeholder="${t("metal", "Ferronit")}">
        <input type="number" min="0" class="admin-input admin-input-sm" id="admin-planet-crystal" placeholder="${t("crystal", "Crytite")}">
        <input type="number" min="0" class="admin-input admin-input-sm" id="admin-planet-fuel" placeholder="${t("fuel_cells", "Brennzellen")}">
        <button type="button" class="gc-btn gc-btn-primary gc-btn-sm" data-admin-action="planet-resources-set" data-planet-id="${pl.id}">${t("admin_btn_set_resources", "Setzen")}</button>
      </div>
      <details class="admin-buildings-detail" open>
        <summary>${t("admin_buildings", "Gebäude")}</summary>
        <div class="admin-level-grid" id="admin-planet-buildings-grid">${buildingGrid}</div>
        <div class="admin-toolbar">
          <button type="button" class="gc-btn gc-btn-primary gc-btn-sm" data-admin-action="planet-buildings-save" data-planet-id="${pl.id}">${t("admin_btn_save_buildings", "Gebäude speichern")}</button>
        </div>
      </details>
      <details class="admin-buildings-detail">
        <summary>${t("admin_ships", "Schiffe")}</summary>
        <div class="admin-level-grid">${shipGrid}</div>
        <div class="admin-toolbar">
          <button type="button" class="gc-btn gc-btn-outline gc-btn-sm" data-admin-action="planet-ships-save" data-planet-id="${pl.id}">${t("admin_btn_save_ships", "Schiffe setzen")}</button>
        </div>
      </details>
      <details class="admin-buildings-detail">
        <summary>${t("admin_defense", "Verteidigung")}</summary>
        <div class="admin-level-grid">${defenseGrid}</div>
        <div class="admin-toolbar">
          <button type="button" class="gc-btn gc-btn-outline gc-btn-sm" data-admin-action="planet-defense-save" data-planet-id="${pl.id}">${t("admin_btn_save_defense", "Verteidigung setzen")}</button>
        </div>
      </details>
      <div class="admin-danger-zone">
        <p class="admin-small-hint">${t("admin_planet_reset_hint", "Planet auf Ausgangszustand zurücksetzen.")}</p>
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

  function formatFleetRemaining(sec) {
    const s = Math.max(0, parseInt(sec, 10) || 0);
    if (s <= 0) return t("admin_fleet_due_now", "Due now");
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m ${s % 60}s`;
  }

  function formatLockUntil(ts) {
    const n = parseInt(ts, 10);
    if (!Number.isFinite(n) || n <= 0) return "—";
    try {
      return new Date(n * 1000).toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
    } catch (_) {
      return String(n);
    }
  }

  function datetimeLocalToUnix(value) {
    if (!value) return null;
    const ms = Date.parse(value);
    if (!Number.isFinite(ms)) return null;
    return Math.floor(ms / 1000);
  }

  function unixToDatetimeLocal(ts) {
    const n = parseInt(ts, 10);
    if (!Number.isFinite(n) || n <= 0) return "";
    const d = new Date(n * 1000);
    const pad = (x) => String(x).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  const FLEET_MISSION_ORDER = [
    "transport", "collect", "recycle", "deploy", "spy", "attack", "colonize", "hold", "expedition",
  ];

  function renderFleetMissionLocksTable(locks) {
    const reasonOptions = [
      ["reset_protection", t("admin_fleet_lock_reason_reset", "Reset-Schutz")],
      ["maintenance", t("admin_fleet_lock_reason_maintenance", "Wartung")],
      ["exploit_fix", t("admin_fleet_lock_reason_exploit", "Exploit-Fix")],
      ["event", t("admin_fleet_lock_reason_event", "Event")],
      ["manual", t("admin_fleet_lock_reason_manual", "Manuell")],
    ];
    const rows = FLEET_MISSION_ORDER.map((mission) => {
      const lock = (locks && locks[mission]) || {};
      const active = !!lock.locked;
      const until = lock.locked_until;
      const status = active
        ? (until
          ? t("admin_fleet_lock_status_until", "Gesperrt bis %(until)s").replace("%(until)s", formatLockUntil(until))
          : t("admin_fleet_lock_status_locked", "Gesperrt"))
        : t("admin_fleet_lock_status_active", "Aktiv");
      const reasonSel = reasonOptions.map(([val, label]) =>
        `<option value="${esc(val)}"${lock.reason === val ? " selected" : ""}>${esc(label)}</option>`
      ).join("");
      const missionLabel = t(`fleet_mission_${mission}`, mission);
      return `<tr data-fleet-lock-row="${esc(mission)}">` +
        `<td>${esc(missionLabel)} <span class="admin-small-hint gc-mono">(${esc(mission)})</span></td>` +
        `<td class="admin-fleet-lock-status">${esc(status)}</td>` +
        `<td><input type="datetime-local" class="admin-input admin-input-sm" data-fleet-lock-until value="${esc(unixToDatetimeLocal(until))}"></td>` +
        `<td><select class="admin-input admin-select admin-input-sm" data-gc-hud-select data-fleet-lock-reason>${reasonSel}</select></td>` +
        `<td class="admin-table-actions">` +
        `<button type="button" class="gc-btn gc-btn-${active ? "outline" : "danger"} gc-btn-xs" data-admin-action="fleet-mission-lock-toggle" data-mission="${esc(mission)}" data-locked="${active ? "0" : "1"}">${esc(active ? t("admin_fleet_lock_unlock", "Entsperren") : t("admin_fleet_lock_lock", "Sperren"))}</button>` +
        `</td></tr>`;
    });
    return renderTable(
      [
        t("admin_col_mission", "Mission"),
        t("admin_col_status", "Status"),
        t("admin_fleet_lock_until_col", "Sperren bis"),
        t("admin_fleet_lock_reason_col", "Grund"),
        "",
      ],
      rows
    );
  }

  async function loadFleetMissionLocks() {
    const out = qs("#admin-fleet-mission-locks");
    if (out) out.innerHTML = loadingHtml();
    const data = await adminGet("/api/admin/fleet-mission-locks");
    if (!data.ok) {
      if (out) out.innerHTML = errorCard(data);
      return data;
    }
    if (out) {
      out.innerHTML = `<div class="admin-card">${renderFleetMissionLocksTable(data.locks || {})}</div>`;
      if (typeof GC.initHudSelects === "function") GC.initHudSelects(out);
    }
    return data;
  }

  async function setFleetMissionLockFromRow(mission, locked) {
    const row = qs(`[data-fleet-lock-row="${mission}"]`);
    const untilRaw = row?.querySelector("[data-fleet-lock-until]")?.value || "";
    const reason = row?.querySelector("[data-fleet-lock-reason]")?.value || "manual";
    const lockedUntil = datetimeLocalToUnix(untilRaw);
    const payload = { mission, locked: !!locked, reason };
    if (locked && lockedUntil) payload.locked_until = lockedUntil;
    const data = await adminPost("/api/admin/fleet-mission-locks", payload);
    if (data.ok) {
      notify(t("admin_fleet_lock_saved", "Missionssperre gespeichert."), "success");
      await loadFleetMissionLocks();
    } else {
      showAlert(data.message || t("admin_fleet_lock_error", "Sperre konnte nicht gespeichert werden."), "error");
    }
    return data;
  }

  async function resetFleetAttackProtection72h() {
    const data = await adminPost("/api/admin/fleet-mission-locks/reset-attack-protection", { duration_hours: 72 });
    if (data.ok) {
      notify(t("admin_attack_protection_72h_ok", "Angriffssperre für 72 Stunden gesetzt."), "success");
      await loadFleetMissionLocks();
    } else {
      showAlert(data.message || t("admin_fleet_lock_error", "Sperre konnte nicht gespeichert werden."), "error");
    }
    return data;
  }

  async function loadAdminFleets() {
    await loadFleetMissionLocks();
    const out = qs("#admin-fleets-output");
    const pid = qs("#admin-fleet-player-id")?.value;
    const status = qs("#admin-fleet-status")?.value || "all";
    const params = new URLSearchParams({ status });
    if (pid) params.set("player_id", pid);
    if (out) out.innerHTML = loadingHtml();
    const data = await adminGet(`/api/admin/fleets?${params}`);
    if (!data.ok) {
      showAlert(data.message, "error");
      if (out) out.innerHTML = errorCard(data);
      return data;
    }
    const rows = data.movements || [];
    const advanceBtn = (id, complete) =>
      `<button type="button" class="gc-btn gc-btn-${complete ? "primary" : "outline"} gc-btn-xs" data-admin-action="fleet-advance" data-fleet-id="${id}" data-fleet-complete="${complete ? "1" : "0"}">${esc(
        complete
          ? t("admin_btn_fleet_complete", "Abschließen")
          : t("admin_btn_fleet_advance", "Nächste Phase")
      )}</button>`;
    if (out) {
      out.innerHTML =
        `<div class="admin-card">` +
        `<h3 class="admin-subtitle">${esc(t("admin_fleets_active_title", "Aktive Flotten"))} (${rows.length})</h3>` +
        (rows.length
          ? renderTable(
              [
                "ID",
                t("admin_col_player_name", "Player"),
                t("admin_col_mission", "Mission"),
                t("admin_col_status", "Status"),
                t("admin_col_target", "Ziel"),
                t("admin_col_eta", "ETA"),
                "",
              ],
              rows.map(
                (mv) =>
                  `<tr>` +
                  `<td>${mv.id}</td>` +
                  `<td>${playerNameLink(mv.player_id, mv.player_name)}</td>` +
                  `<td>${esc(mv.mission_type || "")}</td>` +
                  `<td>${esc(mv.status || "")}</td>` +
                  `<td class="gc-mono">${esc(mv.target_coords || "—")}</td>` +
                  `<td class="gc-mono">${esc(formatFleetRemaining(mv.remaining_seconds))}</td>` +
                  `<td class="admin-table-actions">${advanceBtn(mv.id, false)} ${advanceBtn(mv.id, true)}</td>` +
                  `</tr>`
              )
            )
          : `<p class="admin-small-hint">${esc(t("admin_fleets_empty", "Keine aktiven Flottenbewegungen."))}</p>`) +
        `</div>`;
    }
    return data;
  }

  async function advanceAdminFleet(fleetId, complete) {
    const data = await adminPost(`/api/admin/fleet/${fleetId}/advance`, { complete: !!complete });
    if (data.ok) {
      const tpl = t(
        "admin_fleet_advance_ok",
        "%(before)s → %(after)s (%(steps)s Schritt(e))"
      );
      notify(
        tpl
          .replace("%(before)s", String(data.status_before || ""))
          .replace("%(after)s", String(data.status_after || ""))
          .replace("%(steps)s", String(data.steps || 0)),
        "success"
      );
      await loadAdminFleets();
      await syncAfterAdminChange("admin_fleet_advance");
    } else showAlert(data.message || data.error, "error");
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
          <p class="admin-small-hint">${t("admin_queue_clear_hint", "Alle Warteschlangen-Einträge im gewählten Bereich löschen.")}</p>
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
    if (
      !adminDestructiveConfirmed(
        "admin_queue_clear_confirm_dialog",
        "Warteschlangen wirklich leeren?",
      )
    ) {
      return { ok: false, error: "cancelled" };
    }
    const scope = qs("#admin-queue-clear-scope")?.value || "planet";
    const body = { confirm: true, scope, queue_type: "both" };
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
      const rw = r.ranking_worker || {};
      const maint = r.maintenance || {};
      const hb = maint.bag_heartbeat || {};
      const rankAt = rw.last_run_at
        ? new Date(Number(rw.last_run_at) * 1000).toLocaleString()
        : t("admin_tick_never", "—");
      const rankOk =
        rw.ok === true
          ? t("admin_tick_ok", "OK")
          : rw.ok === false
            ? t("admin_tick_error", "Fehler")
            : t("admin_tick_unknown", "—");
      const nextRank =
        rw.next_run_in_sec != null
          ? `${Math.max(0, Number(rw.next_run_in_sec) || 0)} s`
          : "—";
      const maintMode = maint.sidecar_enabled
        ? t("admin_maint_mode_sidecar", "Sidecar")
        : maint.embedded_cron_enabled
          ? t("admin_maint_mode_embedded", "Embedded")
          : t("admin_maint_mode_off", "AUS");
      const hbAge =
        hb.age_sec != null ? `${Math.max(0, Number(hb.age_sec) || 0)} s` : t("admin_tick_never", "—");
      const hbStale = hb.stale === true;
      const maintAlert = hbStale
        ? `<div class="admin-alert admin-alert-error"><strong>${esc(
            t("admin_maint_bag_stale_title", "Maintenance-Owner stale")
          )}</strong> ${esc(
            t(
              "admin_maint_bag_stale_hint",
              "Kein Bag-Heartbeat — Sidecar/Embedded prüft Logs ([maintenance-worker] started). Ranking-Auto kann ausfallen."
            )
          )}</div>`
        : "";
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
        <div class="admin-section-title">
          <span class="admin-section-title-text">${esc(t("admin_ranking_worker_title", "Ranking-Worker (Dirty-Batch ~10 min)"))}</span>
        </div>
        <p class="admin-small-hint">${esc(
          t(
            "admin_ranking_worker_hint",
            "Auto aktualisiert nur dirty markierte Spieler; Admin-Button = Full-Reconcile aller Scores. Ränge werden nach dem Dirty-Batch neu gesetzt."
          )
        )}</p>
        <div class="admin-kpi-grid">
          ${[
            [t("admin_ranking_worker_last", "Letzter Ranking-Lauf"), rankAt],
            [t("admin_tick_status", "Status"), rankOk],
            [t("admin_tick_source", "Quelle"), rw.last_run_source || "—"],
            [t("admin_tick_duration", "Dauer"), rw.duration_ms != null ? `${rw.duration_ms} ms` : "—"],
            [t("admin_ranking_worker_players", "Dirty-Spieler aktualisiert"), rw.players_updated != null ? rw.players_updated : 0],
            [t("admin_ranking_worker_ranks", "Ränge neu gesetzt"), rw.ranks_assigned != null ? rw.ranks_assigned : 0],
            [t("admin_ranking_worker_dirty", "Dirty pending"), rw.dirty_pending != null ? rw.dirty_pending : 0],
            [t("admin_ranking_worker_next", "Nächster Ranking-Lauf in"), nextRank],
            [t("admin_maint_mode", "Maintenance"), maintMode],
            [t("admin_maint_bag_age", "Bag-Heartbeat Alter"), hbAge],
            [t("admin_maint_bag_source", "Bag-Quelle"), hb.source || "—"],
          ]
            .map(
              ([k, v]) => `<div class="admin-kpi-card admin-card"><div class="admin-metric-label">${esc(k)}</div><div class="admin-metric-value">${esc(v)}</div></div>`
            )
            .join("")}
        </div>
        ${maintAlert}
        ${
          (qt.errors || []).length
            ? `<div class="admin-alert admin-alert-error"><strong>${esc(t("admin_tick_errors", "Fehler"))}</strong><pre class="admin-pre">${esc((qt.errors || []).join("\n"))}</pre></div>`
            : ""
        }`;
    }
    return data;
  }

  let _perfRefreshTimer = null;

  function stopPerfAutoRefresh() {
    if (_perfRefreshTimer) {
      clearInterval(_perfRefreshTimer);
      _perfRefreshTimer = null;
    }
  }

  function startPerfAutoRefresh() {
    stopPerfAutoRefresh();
    _perfRefreshTimer = setInterval(() => {
      if (_activeTab !== "performance") {
        stopPerfAutoRefresh();
        return;
      }
      loadAdminPerformance({ quiet: true }).catch(() => {});
    }, 12000);
  }

  async function loadAdminPerformance(opts) {
    const quiet = !!(opts && opts.quiet);
    const out = qs("#admin-performance-output");
    if (out && !quiet) out.innerHTML = loadingHtml();
    const data = await adminGet("/api/admin/performance");
    if (!data.ok) {
      if (!quiet) showAlert(data.message, "error");
      if (out) out.innerHTML = errorCard(data);
      return data;
    }
    const status = String(data.status || "normal").toUpperCase();
    const proc = data.process || {};
    const req1m = (data.requests && data.requests["1m"]) || {};
    const routes = data.routes || [];
    const components = data.components || [];
    const slowQueries = data.slow_queries || [];
    const diagnosis = data.diagnosis || {};
    const history = data.history_60m || [];
    const statusLevel =
      status === "CRITICAL" ? "error" : status === "PRESSURE" || status === "WARM" ? "warn" : "ok";

    const routeRows = routes
      .slice(0, 12)
      .map(
        (r) =>
          `<tr><td>${esc(r.route)}</td><td>${esc(r.request_count)}</td><td>${esc(r.p50_ms)}</td><td>${esc(r.p95_ms)}</td><td>${esc(r.p99_ms)}</td><td>${esc(r.max_ms)}</td></tr>`
      )
      .join("");
    const compRows = components
      .slice(0, 10)
      .map(
        (c) =>
          `<tr><td>${esc(c.component)}</td><td>${esc(c.avg_ms)}</td><td>${esc(Math.round((c.share || 0) * 100))}%</td><td>${esc(c.samples)}</td></tr>`
      )
      .join("");
    const sqRows = slowQueries
      .slice(0, 10)
      .map(
        (q) =>
          `<tr><td><code>${esc(q.signature)}</code></td><td>${esc(q.count)}</td><td>${esc(q.p95_ms)}</td><td>${esc(q.max_ms)}</td></tr>`
      )
      .join("");
    const histMax = Math.max(1, ...history.map((h) => Number(h.p95_ms) || 0));
    const histBars = history
      .slice(-30)
      .map((h) => {
        const hgt = Math.max(2, Math.round(((Number(h.p95_ms) || 0) / histMax) * 48));
        return `<span class="admin-perf-bar" title="${esc(h.p95_ms)}ms / ${esc(h.request_count)} req" style="height:${hgt}px"></span>`;
      })
      .join("");

    if (out) {
      out.innerHTML = `
        <div class="admin-metrics-grid">
          <div class="admin-metric-card admin-card">
            <div class="admin-metric-label">${esc(t("admin_perf_status", "STATUS"))}</div>
            <div class="admin-metric-value">${statusBadge(statusLevel, status)}</div>
          </div>
          <div class="admin-metric-card admin-card">
            <div class="admin-metric-label">${esc(t("admin_perf_cpu", "CPU"))}</div>
            <div class="admin-metric-value">${esc(proc.cpu_percent != null ? proc.cpu_percent + "%" : "n/a")}</div>
          </div>
          <div class="admin-metric-card admin-card">
            <div class="admin-metric-label">${esc(t("admin_perf_memory", "MEMORY"))}</div>
            <div class="admin-metric-value">${esc(proc.rss_mb != null ? proc.rss_mb + " MB" : "n/a")}</div>
          </div>
          <div class="admin-metric-card admin-card">
            <div class="admin-metric-label">${esc(t("admin_perf_rps", "RPS"))}</div>
            <div class="admin-metric-value">${esc(req1m.requests_per_second != null ? req1m.requests_per_second : 0)}</div>
          </div>
          <div class="admin-metric-card admin-card">
            <div class="admin-metric-label">${esc(t("admin_perf_active", "ACTIVE REQ"))}</div>
            <div class="admin-metric-value">${esc(data.active_requests != null ? data.active_requests : 0)}</div>
          </div>
          <div class="admin-metric-card admin-card">
            <div class="admin-metric-label">${esc(t("admin_perf_p50", "p50"))}</div>
            <div class="admin-metric-value">${esc(req1m.p50_ms != null ? req1m.p50_ms + "ms" : "—")}</div>
          </div>
          <div class="admin-metric-card admin-card">
            <div class="admin-metric-label">${esc(t("admin_perf_p95", "p95"))}</div>
            <div class="admin-metric-value">${esc(req1m.p95_ms != null ? req1m.p95_ms + "ms" : "—")}</div>
          </div>
          <div class="admin-metric-card admin-card">
            <div class="admin-metric-label">${esc(t("admin_perf_p99", "p99"))}</div>
            <div class="admin-metric-value">${esc(req1m.p99_ms != null ? req1m.p99_ms + "ms" : "—")}</div>
          </div>
        </div>

        <section class="admin-section admin-card">
          <h3 class="admin-subtitle">${esc(t("admin_perf_diagnosis", "Diagnose"))}</h3>
          <p><strong>${esc(t("admin_perf_cause", "Wahrscheinlichste Ursache"))}:</strong> ${esc(diagnosis.cause || "—")}</p>
          <p class="admin-small-hint">${esc(diagnosis.recommendation || "")}</p>
        </section>

        <section class="admin-section admin-card">
          <h3 class="admin-subtitle">${esc(t("admin_perf_hot_routes", "HOT ROUTES"))}</h3>
          <div class="admin-table-wrap"><table class="admin-table"><thead><tr>
            <th>${esc(t("admin_perf_col_route", "Route"))}</th><th>n</th><th>p50</th><th>p95</th><th>p99</th><th>max</th>
          </tr></thead><tbody>${routeRows || `<tr><td colspan="6">${esc(t("admin_perf_empty", "Noch keine Samples."))}</td></tr>`}</tbody></table></div>
        </section>

        <section class="admin-section admin-card">
          <h3 class="admin-subtitle">${esc(t("admin_perf_hot_components", "HOT COMPONENTS"))}</h3>
          <div class="admin-table-wrap"><table class="admin-table"><thead><tr>
            <th>${esc(t("admin_perf_col_component", "Component"))}</th><th>avg</th><th>%</th><th>n</th>
          </tr></thead><tbody>${compRows || `<tr><td colspan="4">${esc(t("admin_perf_empty", "Noch keine Samples."))}</td></tr>`}</tbody></table></div>
        </section>

        <section class="admin-section admin-card">
          <h3 class="admin-subtitle">${esc(t("admin_perf_slow_queries", "SLOW QUERIES"))}</h3>
          <div class="admin-table-wrap"><table class="admin-table"><thead><tr>
            <th>${esc(t("admin_perf_col_signature", "Signature"))}</th><th>n</th><th>p95</th><th>max</th>
          </tr></thead><tbody>${sqRows || `<tr><td colspan="4">${esc(t("admin_perf_empty", "Keine Slow Queries."))}</td></tr>`}</tbody></table></div>
        </section>

        <section class="admin-section admin-card">
          <h3 class="admin-subtitle">${esc(t("admin_perf_history", "Verlauf (p95, letzte 30 Min)"))}</h3>
          <div class="admin-perf-history">${histBars || `<p class="admin-small-hint">${esc(t("admin_perf_empty", "Noch keine Samples."))}</p>`}</div>
        </section>`;
    }
    startPerfAutoRefresh();
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

  function renderAdminMessageRows(messages) {
    return messages.map(
      (m) => `<tr class="admin-support-ticket-row${_selectedAdminMessageId === m.id ? " is-active" : ""}"
              data-admin-message-id="${m.id}">
            <td class="col-id">${m.id}</td>
            <td class="col-name">${playerNameLink(m.recipient_player_id, m.recipient_name || `#${m.recipient_player_id}`)}</td>
            <td class="col-subject">${esc(m.subject)}</td>
            <td class="col-cat">${esc(t(`messages.category.${m.category}`, m.category))}</td>
            <td class="col-date">${esc(fmtTs(m.created_at))}</td>
          </tr>`
    );
  }

  function renderAdminMessagesTable(messages) {
    const columns = [
      { label: "ID", className: "col-id" },
      { label: t("admin_messages_col_recipient", "Empfaenger"), className: "col-name" },
      { label: t("admin_messages_col_subject", "Betreff"), className: "col-subject" },
      { label: t("messages.category.system", "Kat."), className: "col-cat" },
      { label: t("admin_messages_col_date", "Datum"), className: "col-date" },
    ];
    const preview = messages.slice(0, ADMIN_MESSAGES_PREVIEW);
    const extra = messages.slice(ADMIN_MESSAGES_PREVIEW);
    let html = renderTable(columns, renderAdminMessageRows(preview), { inline: true });

    if (extra.length) {
      const collapseLabel = _adminMessagesExpanded
        ? t("admin_messages_show_less", "Weniger anzeigen")
        : t("admin_messages_show_all", "Alle Nachrichten anzeigen");
      html += `
        <div class="admin-messages-collapse">
          <button type="button"
                  class="gc-btn gc-btn-outline gc-btn-sm admin-messages-collapse-btn"
                  data-admin-action="messages-toggle-all"
                  aria-expanded="${_adminMessagesExpanded ? "true" : "false"}">
            ${esc(collapseLabel)} (${extra.length})
          </button>
          <div class="admin-messages-collapse-body"${_adminMessagesExpanded ? "" : " hidden"}>
            ${renderTable(columns, renderAdminMessageRows(extra), { inline: true })}
          </div>
        </div>`;
    }
    return html;
  }

  async function loadAdminMessages() {
    const listOut = qs("#admin-messages-list");
    if (!listOut) return null;
    listOut.innerHTML = loadingHtml();
    _adminMessagesExpanded = false;

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

    listOut.innerHTML = renderAdminMessagesTable(messages);

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

  async function adminMessagesBroadcast() {
    const subject = (qs("#admin-messages-broadcast-subject")?.value || "").trim();
    const body = (qs("#admin-messages-broadcast-body")?.value || "").trim();
    const confirmed = qs("#admin-messages-broadcast-confirm")?.checked === true;
    if (!subject || !body) {
      showAlert(t("messages.error_validation", "Eingabe ungueltig."), "error");
      return null;
    }
    if (!confirmed) {
      showAlert(t("admin_messages_broadcast_confirm_required", "Bestaetigung per Haekchen erforderlich."), "error");
      return null;
    }
    const res = await adminPost("/api/admin/messages/broadcast", {
      subject,
      body,
      confirm: true,
    });
    if (res.ok) {
      const count = res.delivered_count ?? res.data?.delivered_count ?? "?";
      notify(
        t("admin_messages_broadcast_ok", "System-Broadcast gesendet (%(count)s Spieler).").replace("%(count)s", String(count)),
        "success"
      );
      if (qs("#admin-messages-broadcast-subject")) qs("#admin-messages-broadcast-subject").value = "";
      if (qs("#admin-messages-broadcast-body")) qs("#admin-messages-broadcast-body").value = "";
      const confirmEl = qs("#admin-messages-broadcast-confirm");
      if (confirmEl) confirmEl.checked = false;
      await loadAdminMessages();
    } else {
      showAlert(res.message || res.error || t("admin_action_failed", "Fehler"), "error");
    }
    return res;
  }

  function toggleAdminMessagesCollapse() {
    _adminMessagesExpanded = !_adminMessagesExpanded;
    const listOut = qs("#admin-messages-list");
    if (!listOut) return;
    const body = listOut.querySelector(".admin-messages-collapse-body");
    const btn = listOut.querySelector("[data-admin-action='messages-toggle-all']");
    if (body) body.hidden = !_adminMessagesExpanded;
    if (btn) {
      btn.setAttribute("aria-expanded", _adminMessagesExpanded ? "true" : "false");
      const extraCount = btn.textContent.match(/\((\d+)\)/)?.[1] || "";
      const label = _adminMessagesExpanded
        ? t("admin_messages_show_less", "Weniger anzeigen")
        : t("admin_messages_show_all", "Alle Nachrichten anzeigen");
      btn.textContent = extraCount ? `${label} (${extraCount})` : label;
    }
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
    if (act === "refresh-online") return loadAdminOnlinePlayers();
    if (act === "search-planets") return searchAdminPlanets();
    if (act === "load-queues") return loadAdminQueues();
    if (act === "load-fleets") return loadAdminFleets();
    if (act === "fleet-locks-refresh") return loadFleetMissionLocks();
    if (act === "fleet-attack-protection-72h") return resetFleetAttackProtection72h();
    if (act === "fleet-mission-lock-toggle") {
      const mission = btn.dataset.mission;
      const locked = btn.dataset.locked === "1";
      if (!mission) return null;
      return setFleetMissionLockFromRow(mission, locked);
    }
    if (act === "finish-due") return finishDueQueues();
    if (act === "load-audit") return loadAuditLog();
    if (act === "chat-search") return searchAdminChatMessages();
    if (act === "support-refresh") return loadAdminSupport();
    if (act === "messages-refresh") return loadAdminMessages();
    if (act === "messages-send") return adminMessagesSend();
    if (act === "messages-broadcast") return adminMessagesBroadcast();
    if (act === "messages-toggle-all") return toggleAdminMessagesCollapse();
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
    if (act === "refresh-performance") return loadAdminPerformance();
    if (act === "balance-save") return saveAdminBalance();
    if (act === "balance-preset-b") return applyBalancePresetB();
    if (act === "ranking-recompute") return runAdminRankingRecompute(btn);
    if (act === "votes-refresh") return loadAdminVotes();
    if (act === "votes-search") return searchAdminVotesPlayers();
    if (act === "inactive-storage-boost") return runInactiveStorageBoost(btn);
    if (act === "combat-hof-backfill") return backfillCombatHof();
    if (act === "combat-bots-ensure") return ensureCombatBots();
    if (act === "combat-bots-toggle") return toggleCombatBots(btn.dataset.combatBotsEnabled === "1");
    if (act === "combat-bots-run") return runCombatBotScenario(true);
    if (act === "combat-bots-run-next") return runNextCombatBotScenario();
    if (act === "combat-bots-refresh") return loadAdminCombatBots();
    if (act === "server-save") return saveAdminServer();
    if (act === "news-publish") return publishAdminNews(true);
    if (act === "news-publish-only") return publishAdminNews(false);
    if (act === "news-save-draft") return saveAdminNewsDraft();
    if (act === "news-import-changelog") return importAdminChangelog();
    if (act === "news-import-git") return importAdminGitHistory();
    if (act === "news-import-full") return importAdminFullHistory();
    if (act === "news-reclassify") return reclassifyAdminNews();
    if (act === "news-publish-release") return publishAdminReleasePack();
    if (act === "news-edit") return startEditAdminNews(btn.dataset.newsId);
    if (act === "news-cancel-edit") return resetAdminNewsForm();
    if (act === "news-set-banner") return setAdminNewsBanner(btn.dataset.newsId);
    if (act === "news-delete") return deleteAdminNews(btn.dataset.newsId);
    if (act === "server-resources") return applyAdminResources();
    if (act === "diplomacy-load") return loadAdminDiplomacy();
    if (act === "diplomacy-set-personality") return applyAdminDiplomacyLayer("personality", false);
    if (act === "diplomacy-clear-personality") return applyAdminDiplomacyLayer("personality", true);
    if (act === "diplomacy-set-resolution") return applyAdminDiplomacyLayer("resolution", false);
    if (act === "diplomacy-clear-resolution") return applyAdminDiplomacyLayer("resolution", true);
    if (act === "diplomacy-set-emergency") return applyAdminDiplomacyLayer("emergency", false);
    if (act === "diplomacy-clear-emergency") return applyAdminDiplomacyLayer("emergency", true);
    if (act === "world-boss-refresh") return loadWorldBossAdmin();
    if (act === "world-boss-spawn") return spawnWorldBossAdmin();
    if (act === "pirates-refresh") return loadPiratesAdmin();
    if (act === "pirates-ai-on") return setPiratesAiAdmin(true);
    if (act === "pirates-ai-off") return setPiratesAiAdmin(false);
    if (act === "pirates-ai-hard-off") return hardOffPiratesAiAdmin();
    if (act === "pirates-force-spawn") return forceSpawnPiratesAdmin();
    if (act === "pirates-force-tick") return forceTickPiratesAdmin();
    if (act === "inactive-autoplay-refresh") return loadInactiveAutoplayAdmin();
    if (act === "inactive-autoplay-on") return setInactiveAutoplayAdmin(true);
    if (act === "inactive-autoplay-off") return setInactiveAutoplayAdmin(false);
    if (act === "inactive-autoplay-force-tick") return forceTickInactiveAutoplayAdmin();
    if (act === "events-refresh") return loadAdminEvents();
    if (act === "events-preset-apply") {
      const pid = String(btn.getAttribute("data-preset-id") || "").trim();
      if (pid) return applyAdminEventPreset(pid, false);
      return null;
    }
    if (act === "events-preset-prefill") {
      const pid = String(btn.getAttribute("data-preset-id") || "").trim();
      if (pid) prefillAdminEventPreset(pid);
      return null;
    }
    if (act === "events-schedule-toggle") {
      const sid = parseInt(btn.getAttribute("data-schedule-id") || "", 10);
      const en = btn.getAttribute("data-enabled") === "1";
      if (Number.isFinite(sid)) return toggleAdminEventSchedule(sid, en);
      return null;
    }
    if (act === "events-schedule-materialize") {
      const sid = parseInt(btn.getAttribute("data-schedule-id") || "", 10);
      if (Number.isFinite(sid)) return materializeAdminEventSchedule(sid);
      return null;
    }
    if (act === "events-new") {
      resetAdminEventForm();
      applyEventEffects("combo");
      applyEventDuration("48h");
      if (qs("#admin-event-title")) {
        qs("#admin-event-title").value = t(
          "admin_events_weekend_title",
          "Res-Prod / Expo Event",
        );
      }
      if (qs("#admin-event-slug") && qs("#admin-event-title")) {
        qs("#admin-event-slug").value = slugifyEventTitle(qs("#admin-event-title").value);
      }
      openEventsCompose();
      return null;
    }
    if (act === "events-reset") {
      resetAdminEventForm();
      return null;
    }
    if (act === "events-effect-combo") {
      applyEventEffects("combo");
      return null;
    }
    if (act === "events-effect-prod") {
      applyEventEffects("prod");
      return null;
    }
    if (act === "events-effect-hold") {
      applyEventEffects("hold");
      return null;
    }
    if (act === "events-effect-shop") {
      applyEventEffects("shop");
      return null;
    }
    if (act === "events-effect-build") {
      applyEventEffects("build");
      return null;
    }
    if (act === "events-dur-24h") {
      applyEventDuration("24h");
      return null;
    }
    if (act === "events-dur-48h") {
      applyEventDuration("48h");
      return null;
    }
    if (act === "events-dur-sunday") {
      applyEventDuration("sunday");
      return null;
    }
    if (act === "events-save") return saveAdminEvent();
    if (act === "events-edit") return editAdminEvent(btn.dataset.eventId);
    if (act === "events-delete") return deleteAdminEvent(btn.dataset.eventId);
    if (act === "server-universe-reset") return resetAdminUniverseKeepInventory();
    if (act === "run-queue-tick") return runQueueTick(btn);
    if (act === "queue-cancel") return cancelQueueJob(btn.dataset.queueType, btn.dataset.jobId);
    if (act === "fleet-advance") {
      const fleetId = parseInt(btn.dataset.fleetId, 10);
      if (!Number.isFinite(fleetId)) return null;
      return advanceAdminFleet(fleetId, btn.dataset.fleetComplete === "1");
    }
    if (act === "queue-clear") return clearQueues();

    if (act === "player-set-admin") {
      const body = { is_admin: btn.dataset.isAdmin === "1" ? 1 : 0 };
      if (body.is_admin === 0) {
        if (
          !adminDestructiveConfirmed(
            "admin_confirm_remove_admin_dialog",
            "Admin-Rechte wirklich entziehen?",
          )
        ) {
          return null;
        }
        body.confirm = true;
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
      if (
        !adminDestructiveConfirmed(
          "admin_confirm_ban_dialog",
          "Spieler wirklich bannen?",
        )
      ) {
        return null;
      }
      const res = await adminPost(`/api/admin/player/${btn.dataset.playerId}/ban`, {
        confirm: true,
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
      if (
        !adminDestructiveConfirmed(
          "admin_confirm_ban_dialog",
          "Spieler wirklich bannen?",
        )
      ) {
        return null;
      }
      const hoursRaw = qs("#admin-ban-hours")?.value;
      const hours = hoursRaw === "" || hoursRaw == null ? 24 : parseInt(hoursRaw, 10);
      const res = await adminPost(`/api/admin/player/${playerId}/ban`, {
        confirm: true,
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
    if (act === "player-delete") {
      const expectedUsername = (qs("#admin-player-delete-username")?.value || "").trim();
      if (!expectedUsername) {
        showAlert(t("admin_player_delete_username_required", "Spielername zur Bestätigung eingeben."), "error");
        return null;
      }
      if (
        !window.confirm(
          t(
            "admin_player_delete_final_confirm",
            "Account wirklich unwiderruflich löschen? Alle Planeten, Flotten und Daten gehen verloren."
          )
        )
      ) {
        return null;
      }
      const res = await adminPost(`/api/admin/player/${btn.dataset.playerId}/delete`, {
        confirm: true,
        expected_username: expectedUsername,
      });
      if (res.ok) {
        notify(t("admin_player_deleted", "Account gelöscht."), "success");
        _selectedPlayerId = null;
        const detail = qs("#admin-player-detail");
        if (detail) {
          detail.innerHTML = `<p class="admin-small-hint">${esc(t("admin_player_deleted_hint", "Spieler wurde entfernt."))}</p>`;
        }
        await searchAdminPlayers();
        await syncAfterAdminChange("admin_player_delete");
      } else adminFail(res, t("admin_player_delete_failed", "Account konnte nicht gelöscht werden."));
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
      } else adminFail(res);
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
        renderPlanetDetail(res);
        await searchAdminPlanets();
        await syncAfterAdminChange("admin_planet_resources");
      } else showAlert(res.message, "error");
      return res;
    }
    if (act === "planet-buildings-save") {
      const buildings = {};
      qsa(".admin-building-level").forEach((input) => {
        const key = input.getAttribute("data-building-key");
        if (!key) return;
        buildings[key] = parseInt(input.value, 10) || 0;
      });
      const planetId = btn.dataset.planetId;
      let res = await adminPost(`/api/admin/planet/${planetId}/buildings`, { buildings });
      // Legacy fallback: singular /building when bulk route is unavailable (stale process).
      if (!res.ok && Number(res.httpStatus) === 404) {
        for (const [building_type, level] of Object.entries(buildings)) {
          res = await adminPost(`/api/admin/planet/${planetId}/building`, {
            building_type,
            level,
          });
          if (!res.ok) break;
        }
      }
      if (res.ok) {
        notify(t("admin_action_success", "OK"), "success");
        renderPlanetDetail(res);
        await syncAfterAdminChange("admin_planet_buildings");
      } else showAlert(res.message || res.error, "error");
      return res;
    }
    if (act === "planet-ships-save") {
      const ships = {};
      qsa(".admin-ship-qty").forEach((input) => {
        const key = input.getAttribute("data-ship-key");
        if (!key) return;
        ships[key] = parseInt(input.value, 10) || 0;
      });
      const res = await adminPost(`/api/admin/planet/${btn.dataset.planetId}/ships`, {
        ships,
        replace: true,
      });
      if (res.ok) {
        notify(t("admin_action_success", "OK"), "success");
        await loadAdminPlanet(btn.dataset.planetId);
        await syncAfterAdminChange("admin_planet_ships");
      } else showAlert(res.message || res.error, "error");
      return res;
    }
    if (act === "planet-defense-save") {
      const defense = {};
      qsa(".admin-defense-qty").forEach((input) => {
        const key = input.getAttribute("data-defense-key");
        if (!key) return;
        defense[key] = parseInt(input.value, 10) || 0;
      });
      const res = await adminPost(`/api/admin/planet/${btn.dataset.planetId}/defense`, {
        defense,
        mode: "set",
      });
      if (res.ok) {
        notify(t("admin_action_success", "OK"), "success");
        renderPlanetDetail(res);
        await syncAfterAdminChange("admin_planet_defense");
      } else showAlert(res.message || res.error, "error");
      return res;
    }
    if (act === "player-research-save") {
      const research = {};
      qsa(".admin-research-level").forEach((input) => {
        const key = input.getAttribute("data-tech-key");
        if (!key) return;
        research[key] = parseInt(input.value, 10) || 0;
      });
      const res = await adminPost(`/api/admin/player/${btn.dataset.playerId}/research`, { research });
      if (res.ok) {
        notify(t("admin_action_success", "OK"), "success");
        await renderPlayerDetail(res);
        await syncAfterAdminChange("admin_player_research");
      } else showAlert(res.message || res.error, "error");
      return res;
    }
    if (act === "planet-reset") {
      if (
        !adminDestructiveConfirmed(
          "admin_planet_reset_confirm_dialog",
          "Planet wirklich zurücksetzen?",
        )
      ) {
        return null;
      }
      const res = await adminPost(`/api/admin/planet/${btn.dataset.planetId}/reset`, {
        confirm: true,
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

      const groupBtn = e.target.closest(".admin-group-btn");
      if (groupBtn && groupBtn.dataset.adminGroup) {
        await switchGroup(groupBtn.dataset.adminGroup);
        return;
      }

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

      const openPlanetRow = e.target.closest("tr[data-admin-open-planet]");
      if (openPlanetRow) {
        const planetId = openPlanetRow.getAttribute("data-admin-open-planet");
        switchTab("planets");
        await loadTab("planets");
        await loadAdminPlanet(planetId);
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
      if (e.target.id === "admin-votes-search") {
        e.preventDefault();
        await searchAdminVotesPlayers();
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
    initUniverseResetDomainCheckboxes();

    if (!_adminPanelBootstrapped) {
      _adminPanelBootstrapped = true;
      showAlert("");
      const initial = resolveInitialTab();
      const healthOut = qs("#admin-health-output");
      if (healthOut && initial === "health") healthOut.innerHTML = loadingHtml();
      switchTab(initial);
      loadAdminRuntime().then(() => loadTab(initial));
      loadAdminOnlinePlayers();
    }

    syncAdminHudSelects(adminRoot());
    console.debug("[GC] admin panel initialized");
  }

  GC.teardownAdminPanel = function teardownAdminPanel() {
    adminLeaveShellCleanup();
  };

  GC.modules = GC.modules || {};
  GC.modules.admin = initAdminPanel;
  GC.initAdminPanel = initAdminPanel;
  GC.adminConfirmDanger = adminConfirmDanger;
  GC.loadAdminHealth = loadAdminHealth;
  GC.loadAdminMigrations = loadAdminMigrations;
  GC.searchAdminPlayers = searchAdminPlayers;
  GC.loadAdminOnlinePlayers = loadAdminOnlinePlayers;
  GC.loadAdminPlayer = loadAdminPlayer;
  GC.searchAdminPlanets = searchAdminPlanets;
  GC.loadAdminQueues = loadAdminQueues;
  GC.loadAdminFleets = loadAdminFleets;
  GC.cancelQueueJob = cancelQueueJob;
  GC.loadAuditLog = loadAuditLog;

  if (typeof GC.registerCleanup === "function") {
    GC.registerCleanup(function adminPanelCleanup() {
      adminLeaveShellCleanup();
    }, { persistent: true });
  }

  bindAdminPanelOnce();
})();
