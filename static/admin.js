/**
 * Genesis Colonies – Admin Control Center (Premium Operations UI)
 */
(function () {
  "use strict";

  const GC = window.GC || (window.GC = {});
  const LOCALE = window.GC_LOCALE || {};
  let _activeTab = "health";
  let _isProduction = false;

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
    let res;
    try {
      res = await fetch(url, opts);
    } catch (err) {
      return { ok: false, error: "network_error", message: err.message, httpStatus: 0 };
    }
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
    switch (name) {
      case "health":
        return loadAdminHealth();
      case "migrations":
        return loadAdminMigrations();
      case "players":
        return searchAdminPlayers();
      case "planets":
        return searchAdminPlanets();
      case "queues":
        return loadAdminQueues();
      case "audit":
        return loadAuditLog();
      case "runtime":
        return loadAdminRuntime();
      default:
        return null;
    }
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
            <h3>${t("admin_health_db", "Datenbank")}</h3>
            ${statusBadge(db.ok ? "ok" : "error", db.ok ? "OK" : "FAIL")}
            <p class="admin-small-hint">${esc(db.path || "")}</p>
          </div>
          <div class="admin-card">
            <h3>${t("admin_migrations_title", "Migrationen")}</h3>
            ${statusBadge(mig.ok ? "ok" : "warn", mig.current ? "OK" : "PENDING")}
            <p class="admin-small-hint">${(mig.pending || []).length} pending</p>
          </div>
          <div class="admin-card">
            <h3>${t("admin_health_writable", "Writable")}</h3>
            ${statusBadge(wr.ok ? "ok" : "error", wr.ok ? "OK" : "FAIL")}
          </div>
          <div class="admin-card">
            <h3>${t("admin_health_config", "Config")}</h3>
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
            <h3>${t("admin_migrations_applied", "Angewendet")} (${(m.applied || []).length})</h3>
            <ul class="admin-list">${(m.applied || []).map((x) => `<li>${esc(x)}</li>`).join("") || `<li>${t("admin_none", "Keine")}</li>`}</ul>
          </div>
          <div class="admin-card">
            <h3>${t("admin_migrations_pending", "Ausstehend")} (${(m.pending || []).length})</h3>
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

  function renderTable(headers, rows) {
    if (!rows.length) return emptyState(t("admin_empty", "Keine Einträge"));
    return `<div class="admin-table-wrap"><table class="admin-table ban-table table-std">
      <thead><tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead>
      <tbody>${rows.join("")}</tbody></table></div>`;
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
      (p) => `<tr>
        <td>${p.id}</td><td>${esc(p.username)}</td><td>${p.is_admin ? "✓" : "–"}</td>
        <td>${esc(fmtTs(p.last_seen))}</td>
        <td><button type="button" class="gc-btn gc-btn-outline gc-btn-xs" data-admin-player-id="${p.id}">${t("admin_btn_details", "Details")}</button></td>
      </tr>`
    );
    if (list) {
      list.innerHTML = renderTable(
        ["ID", t("admin_col_username", "Username"), t("admin_col_admin", "Admin"), t("admin_col_last_seen", "Zuletzt"), ""],
        rows
      );
    }
    return data;
  }

  function renderPlayerDetail(data) {
    const el = qs("#admin-player-detail");
    if (!el || !data.ok) return;
    const p = data.player || {};
    const hw = data.homeworld || {};
    const score = data.score || {};
    el.innerHTML = `
      <h3>#${p.id} ${esc(p.username)} ${p.is_admin ? statusBadge("ok", "Admin") : ""}</h3>
      <p>${t("admin_col_last_seen", "Zuletzt")}: ${esc(fmtTs(p.last_seen))} · Score: ${fmtInt(score.total)} (#${score.rank || "?"})</p>
      <p>Homeworld: ${esc(hw.name || "–")} · ${t("metal", "Ferronit")}: ${fmtInt(hw.metal)} · ${t("crystal", "Crytite")}: ${fmtInt(hw.crystal)}</p>
      <div class="admin-action-row">
        <button type="button" class="gc-btn gc-btn-outline gc-btn-sm" data-admin-action="player-set-admin" data-player-id="${p.id}" data-is-admin="${p.is_admin ? 0 : 1}">${p.is_admin ? t("admin_btn_remove_admin", "Admin entfernen") : t("admin_btn_grant_admin", "Admin setzen")}</button>
        <button type="button" class="gc-btn gc-btn-outline gc-btn-sm" data-admin-action="player-repair-hw" data-player-id="${p.id}">${t("admin_btn_repair_homeworld", "Homeworld reparieren")}</button>
        <button type="button" class="gc-btn gc-btn-danger gc-btn-sm" data-admin-action="player-ban" data-player-id="${p.id}">${t("admin_btn_ban", "Bannen")}</button>
        <button type="button" class="gc-btn gc-btn-outline gc-btn-sm" data-admin-action="player-unban" data-player-id="${p.id}">${t("admin_btn_unban", "Entbannen")}</button>
      </div>
      <div class="admin-action-row">
        <input type="number" min="0" class="admin-input admin-input-sm" id="admin-player-metal" placeholder="${t("metal", "Ferronit")}">
        <input type="number" min="0" class="admin-input admin-input-sm" id="admin-player-crystal" placeholder="${t("crystal", "Crytite")}">
        <button type="button" class="gc-btn gc-btn-primary gc-btn-sm" data-admin-action="player-resources-add" data-player-id="${p.id}">${t("admin_btn_apply", "Addieren")}</button>
        <button type="button" class="gc-btn gc-btn-outline gc-btn-sm" data-admin-action="player-resources-set" data-player-id="${p.id}">${t("admin_btn_set_resources", "Setzen")}</button>
      </div>`;
  }

  async function loadAdminPlayer(id) {
    const data = await adminGet(`/api/admin/player/${id}`);
    if (!data.ok) showAlert(data.message, "error");
    else renderPlayerDetail(data);
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
      (pl) => `<tr>
        <td>${pl.id}</td><td>${esc(pl.name)}</td><td>${esc(pl.owner_username || pl.player_id || "")}</td>
        <td>${pl.is_homeworld ? "✓" : "–"}</td>
        <td><button type="button" class="gc-btn gc-btn-outline gc-btn-xs" data-admin-planet-id="${pl.id}">${t("admin_btn_details", "Details")}</button></td>
      </tr>`
    );
    if (list) {
      list.innerHTML = renderTable(
        ["ID", t("admin_col_name", "Name"), t("admin_col_owner", "Owner"), "HW", ""],
        rows
      );
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
      <h3>#${pl.id} ${esc(pl.name || "")}</h3>
      <p>${t("metal", "Ferronit")}: ${fmtInt(pl.metal)} · ${t("crystal", "Crytite")}: ${fmtInt(pl.crystal)}</p>
      <details class="admin-buildings-detail"><summary>${t("admin_buildings", "Gebäude")}</summary><pre>${esc(JSON.stringify(b, null, 2))}</pre></details>
      <div class="admin-action-row">
        <input type="number" min="0" class="admin-input admin-input-sm" id="admin-planet-metal" placeholder="${t("metal", "Ferronit")}">
        <input type="number" min="0" class="admin-input admin-input-sm" id="admin-planet-crystal" placeholder="${t("crystal", "Crytite")}">
        <button type="button" class="gc-btn gc-btn-primary gc-btn-sm" data-admin-action="planet-resources-set" data-planet-id="${pl.id}">${t("admin_btn_set_resources", "Setzen")}</button>
      </div>
      <div class="admin-action-row">
        <select class="admin-input admin-input-sm" id="admin-planet-building-type">${buildingOpts}</select>
        <input type="number" min="0" max="100" class="admin-input admin-input-sm" id="admin-planet-building-level" placeholder="Level">
        <button type="button" class="gc-btn gc-btn-outline gc-btn-sm" data-admin-action="planet-building-set" data-planet-id="${pl.id}">${t("admin_btn_set_building", "Gebäude setzen")}</button>
      </div>
      
      <div class="admin-danger-zone">
        <p class="admin-small-hint">${t("admin_planet_reset_hint", "Tippe RESET PLANET zur Bestätigung")}</p>
        <input type="text" class="admin-input" id="admin-planet-reset-confirm" placeholder="RESET PLANET" autocomplete="off">
        <button type="button" class="gc-btn gc-btn-danger gc-btn-sm" data-admin-action="planet-reset" data-planet-id="${pl.id}">${t("admin_btn_reset_planet", "Planet reset")}</button>
      </div>`;
  }

  async function loadAdminPlanet(id) {
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
    if (out) {
      out.innerHTML = `
        <div class="admin-card">
          <h3>${t("admin_build_queue", "Bau-Queue")} (${bq.length})</h3>
          ${renderTable(
            ["ID", "Planet", "Typ", "Status", ""],
            bq.map(
              (j) =>
                `<tr><td>${j.id}</td><td>${j.planet_id}</td><td>${esc(j.building_type)}</td><td>${esc(j.status)}</td><td>${cancelBtn("build", j.id)}</td></tr>`
            )
          )}
        </div>
        <div class="admin-card">
          <h3>${t("admin_research_queue", "Forschungs-Queue")} (${rq.length})</h3>
          ${renderTable(
            ["ID", "User", "Tech", "Status", ""],
            rq.map(
              (j) =>
                `<tr><td>${j.id}</td><td>${j.user_id}</td><td>${esc(j.tech_key)}</td><td>${esc(j.status)}</td><td>${cancelBtn("research", j.id)}</td></tr>`
            )
          )}
        </div>
        <div class="admin-danger-zone">
          <p class="admin-small-hint">${t("admin_queue_clear_hint", "Tippe CLEAR QUEUE")}</p>
          <input type="text" class="admin-input" id="admin-queue-clear-confirm" placeholder="CLEAR QUEUE" autocomplete="off">
          <select class="admin-input admin-input-sm" id="admin-queue-clear-scope">
            <option value="planet">${t("admin_filter_planet_id", "Planet")}</option>
            <option value="player">${t("admin_filter_player_id", "Player")}</option>
          </select>
          <button type="button" class="gc-btn gc-btn-danger gc-btn-sm" data-admin-action="queue-clear">${t("admin_btn_clear_queue", "Queue leeren")}</button>
        </div>`;
    }
    return data;
  }

  async function cancelQueueJob(type, id) {
    const data = await adminPost(`/api/admin/queue/${type}/${id}/cancel`, {});
    if (data.ok) notify(t("admin_action_success", "Erfolgreich"), "success");
    else showAlert(data.message, "error");
    await loadAdminQueues();
    return data;
  }

  async function finishDueQueues() {
    const data = await adminPost("/api/admin/queues/finish-due", {});
    if (data.ok) notify(t("admin_action_success", "Erfolgreich"), "success");
    else showAlert(data.message, "error");
    await loadAdminQueues();
    return data;
  }

  async function clearQueues() {
    const confirmText = qs("#admin-queue-clear-confirm")?.value || "";
    const scope = qs("#admin-queue-clear-scope")?.value || "planet";
    const body = { confirm_text: confirmText, scope, queue_type: "both" };
    if (scope === "planet") body.planet_id = qs("#admin-queue-planet-id")?.value;
    else body.player_id = qs("#admin-queue-player-id")?.value;
    const data = await adminPost("/api/admin/queues/clear", body);
    if (data.ok) notify(t("admin_action_success", "Erfolgreich"), "success");
    else showAlert(data.message, "error");
    await loadAdminQueues();
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
    _isProduction = !!r.production;
    if (out) {
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
        </div>`;
    }
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
    if (act === "refresh-runtime") return loadAdminRuntime();
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
      if (res.ok) notify(t("admin_action_success", "OK"), "success");
      else showAlert(res.message, "error");
      await loadAdminPlayer(btn.dataset.playerId);
      await searchAdminPlayers();
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
      if (res.ok) notify(t("admin_action_success", "OK"), "success");
      else showAlert(res.message, "error");
      await loadAdminPlayer(btn.dataset.playerId);
      return res;
    }
    if (act === "player-unban") {
      const res = await adminPost(`/api/admin/player/${btn.dataset.playerId}/unban`, {});
      notify(t("admin_action_success", "OK"), "success");
      await loadAdminPlayer(btn.dataset.playerId);
      return res;
    }
    if (act === "player-repair-hw") {
      await adminPost(`/api/admin/player/${btn.dataset.playerId}/repair-homeworld`, {});
      notify(t("admin_action_success", "OK"), "success");
      return loadAdminPlayer(btn.dataset.playerId);
    }
    if (act === "player-resources-add" || act === "player-resources-set") {
      const mode = act.endsWith("set") ? "set" : "add";
      await adminPost(`/api/admin/player/${btn.dataset.playerId}/resources`, {
        mode,
        metal: qs("#admin-player-metal")?.value || 0,
        crystal: qs("#admin-player-crystal")?.value || 0,
      });
      notify(t("admin_action_success", "OK"), "success");
      return loadAdminPlayer(btn.dataset.playerId);
    }
    if (act === "planet-resources-set") {
      await adminPost(`/api/admin/planet/${btn.dataset.planetId}/resources`, {
        mode: "set",
        metal: qs("#admin-planet-metal")?.value || 0,
        crystal: qs("#admin-planet-crystal")?.value || 0,
      });
      notify(t("admin_action_success", "OK"), "success");
      return loadAdminPlanet(btn.dataset.planetId);
    }
    if (act === "planet-building-set") {
      await adminPost(`/api/admin/planet/${btn.dataset.planetId}/building`, {
        building_type: qs("#admin-planet-building-type")?.value,
        level: qs("#admin-planet-building-level")?.value || 0,
      });
      notify(t("admin_action_success", "OK"), "success");
      return loadAdminPlanet(btn.dataset.planetId);
    }
    if (act === "planet-reset") {
      const res = await adminPost(`/api/admin/planet/${btn.dataset.planetId}/reset`, {
        confirm_text: qs("#admin-planet-reset-confirm")?.value || "",
      });
      if (res.ok) notify(t("admin_action_success", "OK"), "success");
      else showAlert(res.message, "error");
      return loadAdminPlanet(btn.dataset.planetId);
    }
    return null;
  }

  function bindAdminPanel(root) {
    root.addEventListener("click", async (e) => {
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

      const pBtn = e.target.closest("[data-admin-player-id]");
      if (pBtn) {
        await loadAdminPlayer(pBtn.dataset.adminPlayerId);
        return;
      }
      const plBtn = e.target.closest("[data-admin-planet-id]");
      if (plBtn) await loadAdminPlanet(plBtn.dataset.adminPlanetId);
    });

    root.addEventListener("keydown", async (e) => {
      if (e.key !== "Enter") return;
      if (e.target.id === "admin-players-search") {
        e.preventDefault();
        await searchAdminPlayers();
      }
      if (e.target.id === "admin-planets-search") {
        e.preventDefault();
        await searchAdminPlanets();
      }
    });
  }

  function initAdminPanel() {
    const root = qs("#admin-control-center");
    if (!root) return;

    if (!root._gcAdminReady) {
      bindAdminPanel(root);
      root._gcAdminReady = true;
    }

    const healthOut = qs("#admin-health-output");
    if (healthOut) healthOut.innerHTML = loadingHtml();

    switchTab("health");
    loadAdminRuntime().then(() => loadTab("health"));
    console.debug("[GC] admin panel initialized");
  }

  GC.teardownAdminPanel = function teardownAdminPanel() {
    _activeTab = "health";
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
      const root = qs("#admin-control-center");
      if (root) root._gcAdminReady = false;
      _activeTab = "health";
    });
  }

  document.addEventListener("DOMContentLoaded", function adminBootFallback() {
    if (!qs("#admin-control-center")) return;
    if (GC.currentPage === "admin") return;
    if (typeof GC.initAdminPanel === "function") GC.initAdminPanel();
  });
})();
