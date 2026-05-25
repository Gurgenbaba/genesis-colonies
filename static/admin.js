/**
 * Genesis Colonies – Admin Control Center (AJAX, PJAX-safe)
 */
(function () {
  "use strict";

  const GC = window.GC || (window.GC = {});
  const LOCALE = window.GC_LOCALE || {};

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
    const x = Number(n) || 0;
    return x.toLocaleString("de-DE");
  }

  function fmtTs(ts) {
    if (!ts) return "–";
    try {
      return new Date(Number(ts) * 1000).toLocaleString();
    } catch (_) {
      return String(ts);
    }
  }

  function notify(msg, kind) {
    if (typeof GC.showNotify === "function") {
      GC.showNotify(msg, kind || "info");
      return;
    }
    console.log("[admin]", kind, msg);
  }

  async function adminFetch(url, options) {
    const opts = {
      credentials: "same-origin",
      cache: "no-store",
      headers: { Accept: "application/json" },
      ...options,
    };
    if (opts.body && typeof opts.body === "object" && !(opts.body instanceof FormData)) {
      opts.headers = { "Content-Type": "application/json", ...opts.headers };
      opts.body = JSON.stringify(opts.body);
    }
    if (typeof GC.fetchJSON === "function" && (!opts.method || opts.method === "GET")) {
      try {
        return await GC.fetchJSON(url, opts);
      } catch (err) {
        return { ok: false, error: err.message || "fetch_failed" };
      }
    }
    const res = await fetch(url, opts);
    let data = {};
    try {
      data = await res.json();
    } catch (_) {}
    if (!res.ok && data.ok !== true) {
      data.ok = false;
      data.error = data.error || `HTTP ${res.status}`;
    }
    return data;
  }

  async function adminPost(url, body) {
    if (typeof GC.fetchJSON === "function") {
      try {
        return await GC.fetchJSON(url, {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify(body || {}),
        });
      } catch (err) {
        return { ok: false, error: err.message || "post_failed" };
      }
    }
    return adminFetch(url, { method: "POST", body: body || {} });
  }

  function setBusy(btn, busy) {
    if (!btn) return;
    btn.disabled = !!busy;
    btn.dataset.busy = busy ? "1" : "0";
  }

  function statusBadge(ok) {
  const cls = ok ? "admin-cc-badge-ok" : "admin-cc-badge-fail";
    return `<span class="admin-cc-badge ${cls}">${ok ? "OK" : "FAIL"}</span>`;
  }

  function renderKeyValues(obj) {
    if (!obj || typeof obj !== "object") return `<pre>${String(obj)}</pre>`;
    return `<dl class="admin-cc-kv">${Object.entries(obj)
      .map(([k, v]) => {
        let val = v;
        if (v && typeof v === "object") val = JSON.stringify(v);
        return `<dt>${k}</dt><dd>${val}</dd>`;
      })
      .join("")}</dl>`;
  }

  function switchTab(name) {
    qsa(".admin-cc-tab").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.adminTab === name);
    });
    qsa(".admin-cc-panel").forEach((panel) => {
      const active = panel.dataset.panel === name;
      panel.classList.toggle("is-active", active);
      panel.hidden = !active;
    });
  }

  async function loadAdminHealth() {
    const out = qs("#admin-health-output");
    if (out) out.innerHTML = `<p class="admin-cc-loading">${t("admin_loading", "Lade…")}</p>`;
    const data = await adminFetch("/api/admin/health");
    if (!data.ok) {
      notify(t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      if (out) out.textContent = data.error || "error";
      return data;
    }
    const h = data.health || {};
    const checks = h.checks || {};
    if (out) {
      out.innerHTML = `
        
        <div class="admin-cc-health-grid">
          <div class="admin-metric-card">
            <div class="admin-metric-label">${t("admin_health_status", "Status")}</div>
            <div class="admin-metric-value">${statusBadge(h.status === "ok")} ${h.status || "?"}</div>
          </div>
          <div class="admin-metric-card">
            <div class="admin-metric-label">${t("admin_health_version", "Version")}</div>
            <div class="admin-metric-value">${h.version || "–"}</div>
          </div>
          <div class="admin-metric-card">
            
            <div class="admin-metric-label">${t("admin_health_checked", "Geprüft")}</div>
            <div class="admin-metric-value">${fmtTs(h.checked_at)}</div>
          </div>
        </div>
        ${renderKeyValues(checks)}
      `;
    }
    return data;
  }

  async function loadAdminMigrations() {
    const out = qs("#admin-migrations-output");
    if (out) out.innerHTML = `<p class="admin-cc-loading">${t("admin_loading", "Lade…")}</p>`;
    const data = await adminFetch("/api/admin/migrations");
    if (!data.ok) {
      notify(t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      return data;
    }
    const m = data.migrations || {};
    const runZone = qs("#admin-migrations-run-zone");
    if (runZone) runZone.hidden = !!(m.pending && m.pending.length === 0);
    if (out) {
      out.innerHTML = `
        <p><strong>${t("admin_migrations_db_path", "DB-Pfad")}:</strong> <code>${m.db_path || ""}</code></p>
        <p><strong>${t("admin_migrations_backend", "Backend")}:</strong> ${m.backend || "sqlite"} ·
        ${statusBadge(!!m.current)} ${m.current ? t("admin_migrations_current", "aktuell") : t("admin_migrations_pending_label", "ausstehend")}</p>
        <h3>${t("admin_migrations_applied", "Angewendet")}</h3>
        <ul class="admin-cc-list">${(m.applied || []).map((x) => `<li>${x}</li>`).join("") || `<li>–</li>`}</ul>
        <h3>${t("admin_migrations_pending", "Ausstehend")}</h3>
        <ul class="admin-cc-list admin-cc-list-warn">${(m.pending || []).map((x) => `<li>${x}</li>`).join("") || `<li>${t("admin_none", "Keine")}</li>`}</ul>
      `;
    }
    return data;
  }

  async function runAdminMigrations() {
    const confirmEl = qs("#admin-migrations-confirm");
    const body = { confirm_text: confirmEl ? confirmEl.value : "" };
    const data = await adminPost("/api/admin/migrations/run", body);
    if (data.ok) notify(t("admin_action_success", "Erfolgreich"), "success");
    else notify(data.message || t("admin_confirm_required", "Bestätigung erforderlich"), "error");
    await loadAdminMigrations();
    return data;
  }

  async function searchAdminPlayers() {
    const q = (qs("#admin-players-search")?.value || "").trim();
    const list = qs("#admin-players-list");
    if (list) list.innerHTML = `<p class="admin-cc-loading">${t("admin_loading", "Lade…")}</p>`;
    const data = await adminFetch(`/api/admin/players?q=${encodeURIComponent(q)}`);
    if (!data.ok) {
      notify(t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      return data;
    }
    const rows = data.players || [];
    if (list) {
      list.innerHTML = `
        <table class="ban-table table-std admin-cc-table">
          <thead><tr>
            <th>ID</th><th>${t("admin_col_username", "Username")}</th><th>${t("admin_col_admin", "Admin")}</th>
            <th>${t("admin_col_last_seen", "Zuletzt")}</th><th></th>
          </tr></thead>
          <tbody>
            ${rows.map((p) => `
              <tr>
                <td>${p.id}</td>
                <td>${p.username || ""}</td>
                <td>${p.is_admin ? "✓" : "–"}</td>
                <td>${fmtTs(p.last_seen)}</td>
                <td><button type="button" class="gc-btn gc-btn-outline gc-btn-xs" data-admin-player-id="${p.id}">${t("admin_btn_details", "Details")}</button></td>
              </tr>`).join("")}
          </tbody>
        </table>`;
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
      <div class="admin-cc-detail-card">
        <h3>#${p.id} ${p.username || ""} ${p.is_admin ? `<span class="admin-cc-badge admin-cc-badge-ok">Admin</span>` : ""}</h3>
        <p>${t("admin_col_last_seen", "Zuletzt")}: ${fmtTs(p.last_seen)} · Score: ${fmtInt(score.total)} (#${score.rank || "?"})</p>
        <p>Homeworld: ${hw.name || "–"} · ${t("metal", "Ferronit")}: ${fmtInt(hw.metal)} · ${t("crystal", "Crytite")}: ${fmtInt(hw.crystal)}</p>
        <div class="admin-cc-actions">
          <button type="button" class="gc-btn gc-btn-outline gc-btn-sm" data-admin-action="player-set-admin" data-player-id="${p.id}" data-is-admin="${p.is_admin ? 0 : 1}">${p.is_admin ? t("admin_btn_remove_admin", "Admin entfernen") : t("admin_btn_grant_admin", "Admin setzen")}</button>
          <button type="button" class="gc-btn gc-btn-outline gc-btn-sm" data-admin-action="player-repair-hw" data-player-id="${p.id}">${t("admin_btn_repair_homeworld", "Homeworld reparieren")}</button>
          <button type="button" class="gc-btn gc-btn-danger gc-btn-sm" data-admin-action="player-ban" data-player-id="${p.id}">${t("admin_btn_ban", "Bannen")}</button>
          <button type="button" class="gc-btn gc-btn-outline gc-btn-sm" data-admin-action="player-unban" data-player-id="${p.id}">${t("admin_btn_unban", "Entbannen")}</button>
        </div>
        <div class="admin-cc-inline-form">
          <label>${t("admin_resources_add", "Ressourcen addieren")}</label>
          <input type="number" min="0" class="admin-input admin-input-sm" id="admin-player-metal" placeholder="${t("metal", "Ferronit")}">
          <input type="number" min="0" class="admin-input admin-input-sm" id="admin-player-crystal" placeholder="${t("crystal", "Crytite")}">
          <button type="button" class="gc-btn gc-btn-primary gc-btn-sm" data-admin-action="player-resources" data-player-id="${p.id}">${t("admin_btn_apply", "Anwenden")}</button>
        </div>
      </div>`;
  }

  async function loadAdminPlayer(id) {
    const data = await adminFetch(`/api/admin/player/${id}`);
    if (!data.ok) notify(t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
    else renderPlayerDetail(data);
    return data;
  }

  async function searchAdminPlanets() {
    const q = (qs("#admin-planets-search")?.value || "").trim();
    const list = qs("#admin-planets-list");
    if (list) list.innerHTML = `<p class="admin-cc-loading">${t("admin_loading", "Lade…")}</p>`;
    const data = await adminFetch(`/api/admin/planets?q=${encodeURIComponent(q)}`);
    if (!data.ok) {
      notify(t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      return data;
    }
    const rows = data.planets || [];
    if (list) {
      list.innerHTML = `
        <table class="ban-table table-std admin-cc-table">
          <thead><tr><th>ID</th><th>${t("admin_col_name", "Name")}</th><th>${t("admin_col_owner", "Owner")}</th><th>HW</th><th></th></tr></thead>
          <tbody>${rows.map((pl) => `
            <tr>
              <td>${pl.id}</td><td>${pl.name || ""}</td><td>${pl.owner_username || pl.player_id || ""}</td>
              <td>${pl.is_homeworld ? "✓" : "–"}</td>
              <td><button type="button" class="gc-btn gc-btn-outline gc-btn-xs" data-admin-planet-id="${pl.id}">${t("admin_btn_details", "Details")}</button></td>
            </tr>`).join("")}
          </tbody>
        </table>`;
    }
    return data;
  }

  function renderPlanetDetail(data) {
    const el = qs("#admin-planet-detail");
    if (!el || !data.ok) return;
    const pl = data.planet || {};
    const b = data.buildings || {};
    el.innerHTML = `
      <div class="admin-cc-detail-card">
        <h3>#${pl.id} ${pl.name || ""}</h3>
        <p>${t("metal", "Ferronit")}: ${fmtInt(pl.metal)} · ${t("crystal", "Crytite")}: ${fmtInt(pl.crystal)}</p>
        <details><summary>${t("admin_buildings", "Gebäude")}</summary><pre>${JSON.stringify(b, null, 2)}</pre></details>
        
        <div class="admin-cc-inline-form">
          <input type="number" min="0" class="admin-input admin-input-sm" id="admin-planet-metal" placeholder="${t("metal", "Ferronit")}">
          <input type="number" min="0" class="admin-input admin-input-sm" id="admin-planet-crystal" placeholder="${t("crystal", "Crytite")}">
          <button type="button" class="gc-btn gc-btn-primary gc-btn-sm" data-admin-action="planet-resources-set" data-planet-id="${pl.id}">${t("admin_btn_set_resources", "Setzen")}</button>
          <input type="text" class="admin-input admin-input-sm" id="admin-planet-reset-confirm" placeholder="RESET PLANET">
          <button type="button" class="gc-btn gc-btn-danger gc-btn-sm" data-admin-action="planet-reset" data-planet-id="${pl.id}">${t("admin_btn_reset_planet", "Planet reset")}</button>
        </div>
      </div>`;
  }

  async function loadAdminPlanet(id) {
    const data = await adminFetch(`/api/admin/planet/${id}`);
    if (!data.ok) notify(t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
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
    if (out) out.innerHTML = `<p class="admin-cc-loading">${t("admin_loading", "Lade…")}</p>`;
    const data = await adminFetch(`/api/admin/queues?${params}`);
    if (!data.ok) {
      notify(t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      return data;
    }
    const bq = data.build_queue || [];
    const rq = data.research_queue || [];
    const rowBtn = (type, id) =>
      `<button type="button" class="gc-btn gc-btn-danger gc-btn-xs" data-admin-action="queue-cancel" data-queue-type="${type}" data-job-id="${id}">${t("admin_btn_cancel", "Abbrechen")}</button>`;
    if (out) {
      out.innerHTML = `
        <h3>${t("admin_build_queue", "Bau-Queue")}</h3>
        <table class="ban-table table-std admin-cc-table"><thead><tr><th>ID</th><th>Planet</th><th>Typ</th><th>Status</th><th></th></tr></thead>
        <tbody>${bq.map((j) => `<tr><td>${j.id}</td><td>${j.planet_id}</td><td>${j.building_type}</td><td>${j.status}</td><td>${rowBtn("build", j.id)}</td></tr>`).join("") || `<tr><td colspan="5">–</td></tr>`}</tbody></table>
        <h3>${t("admin_research_queue", "Forschungs-Queue")}</h3>
        <table class="ban-table table-std admin-cc-table"><thead><tr><th>ID</th><th>User</th><th>Tech</th><th>Status</th><th></th></tr></thead>
        <tbody>${rq.map((j) => `<tr><td>${j.id}</td><td>${j.user_id}</td><td>${j.tech_key}</td><td>${j.status}</td><td>${rowBtn("research", j.id)}</td></tr>`).join("") || `<tr><td colspan="5">–</td></tr>`}</tbody></table>`;
    }
    return data;
  }

  async function cancelQueueJob(type, id) {
    const data = await adminPost(`/api/admin/queue/${type}/${id}/cancel`, {});
    if (data.ok) notify(t("admin_action_success", "Erfolgreich"), "success");
    else notify(t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
    await loadAdminQueues();
    return data;
  }

  async function finishDueQueues() {
    const data = await adminPost("/api/admin/queues/finish-due", {});
    if (data.ok) notify(t("admin_action_success", "Erfolgreich"), "success");
    else notify(t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
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
    if (out) out.innerHTML = `<p class="admin-cc-loading">${t("admin_loading", "Lade…")}</p>`;
    const data = await adminFetch(`/api/admin/audit-log?${params}`);
    if (!data.ok) {
      notify(t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      return data;
    }
    const rows = data.entries || [];
    if (out) {
      out.innerHTML = `
        <table class="ban-table table-std admin-cc-table">
          <thead><tr><th>ID</th><th>${t("admin_col_time", "Zeit")}</th><th>Admin</th><th>Action</th><th>Target</th></tr></thead>
          <tbody>${rows.map((e) => `
            <tr>
              <td>${e.id}</td><td>${fmtTs(e.created_at)}</td><td>${e.admin_username || e.admin_id}</td>
              <td>${e.action}</td><td>${e.target_type || ""} ${e.target_id || ""}</td>
            </tr>`).join("") || `<tr><td colspan="5">–</td></tr>`}
          </tbody>
        </table>`;
    }
    return data;
  }

  async function loadAdminRuntime() {
    const out = qs("#admin-runtime-output");
    if (out) out.innerHTML = `<p class="admin-cc-loading">${t("admin_loading", "Lade…")}</p>`;
    const data = await adminFetch("/api/admin/runtime");
    if (!data.ok) {
      notify(t("admin_action_failed", "Aktion fehlgeschlagen"), "error");
      return data;
    }
    if (out) out.innerHTML = renderKeyValues(data.runtime || {});
    return data;
  }

  function bindAdminPanel(root) {
    if (!root || root.dataset.adminBound === "1") return;
    root.dataset.adminBound = "1";

    root.addEventListener("click", async (e) => {
      const tab = e.target.closest(".admin-cc-tab");
      if (tab) {
        switchTab(tab.dataset.adminTab);
        return;
      }

      const btn = e.target.closest("[data-admin-action]");
      if (btn) {
        e.preventDefault();
        if (btn.dataset.busy === "1") return;
        setBusy(btn, true);
        try {
          const act = btn.dataset.adminAction;
          if (act === "refresh-health") await loadAdminHealth();
          else if (act === "refresh-migrations") await loadAdminMigrations();
          else if (act === "run-migrations") await runAdminMigrations();
          else if (act === "search-players") await searchAdminPlayers();
          else if (act === "search-planets") await searchAdminPlanets();
          else if (act === "load-queues") await loadAdminQueues();
          else if (act === "finish-due") await finishDueQueues();
          else if (act === "load-audit") await loadAuditLog();
          else if (act === "refresh-runtime") await loadAdminRuntime();
          else if (act === "queue-cancel") await cancelQueueJob(btn.dataset.queueType, btn.dataset.jobId);
          else if (act === "player-set-admin") {
            const body = { is_admin: btn.dataset.isAdmin === "1" ? 1 : 0 };
            if (body.is_admin === 0) {
              const c = prompt(t("admin_confirm_remove_admin", "Tippe REMOVE ADMIN"));
              if (c !== "REMOVE ADMIN") return;
              body.confirm_text = c;
            }
            const res = await adminPost(`/api/admin/player/${btn.dataset.playerId}/set-admin`, body);
            if (res.ok) notify(t("admin_action_success", "Erfolgreich"), "success");
            else notify(res.message || t("admin_action_failed", "Fehler"), "error");
            await loadAdminPlayer(btn.dataset.playerId);
            await searchAdminPlayers();
          } else if (act === "player-ban") {
            const c = prompt(t("admin_confirm_ban", "Tippe BAN PLAYER"));
            if (c !== "BAN PLAYER") return;
            const res = await adminPost(`/api/admin/player/${btn.dataset.playerId}/ban`, { confirm_text: c, reason: "admin panel", hours: 24 });
            if (res.ok) notify(t("admin_action_success", "Erfolgreich"), "success");
            await loadAdminPlayer(btn.dataset.playerId);
          } else if (act === "player-unban") {
            await adminPost(`/api/admin/player/${btn.dataset.playerId}/unban`, {});
            notify(t("admin_action_success", "Erfolgreich"), "success");
            await loadAdminPlayer(btn.dataset.playerId);
          } else if (act === "player-repair-hw") {
            await adminPost(`/api/admin/player/${btn.dataset.playerId}/repair-homeworld`, {});
            notify(t("admin_action_success", "Erfolgreich"), "success");
            await loadAdminPlayer(btn.dataset.playerId);
          } else if (act === "player-resources") {
            await adminPost(`/api/admin/player/${btn.dataset.playerId}/resources`, {
              mode: "add",
              metal: qs("#admin-player-metal")?.value || 0,
              crystal: qs("#admin-player-crystal")?.value || 0,
            });
            notify(t("admin_action_success", "Erfolgreich"), "success");
            await loadAdminPlayer(btn.dataset.playerId);
          } else if (act === "planet-resources-set") {
            await adminPost(`/api/admin/planet/${btn.dataset.planetId}/resources`, {
              mode: "set",
              metal: qs("#admin-planet-metal")?.value || 0,
              crystal: qs("#admin-planet-crystal")?.value || 0,
            });
            notify(t("admin_action_success", "Erfolgreich"), "success");
            await loadAdminPlanet(btn.dataset.planetId);
          } else if (act === "planet-reset") {
            const c = qs("#admin-planet-reset-confirm")?.value || "";
            const res = await adminPost(`/api/admin/planet/${btn.dataset.planetId}/reset`, { confirm_text: c });
            if (res.ok) notify(t("admin_action_success", "Erfolgreich"), "success");
            else notify(res.message || t("admin_confirm_required", "Bestätigung nötig"), "error");
            await loadAdminPlanet(btn.dataset.planetId);
          }
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
      if (plBtn) {
        await loadAdminPlanet(plBtn.dataset.adminPlanetId);
      }
    });
  }

  function initAdminPanel() {
    const root = qs("#admin-control-center");
    if (!root) return;
    bindAdminPanel(root);
    loadAdminHealth();
    loadAdminMigrations();
  }

  GC.modules = GC.modules || {};
  GC.modules.admin = initAdminPanel;
  GC.loadAdminHealth = loadAdminHealth;
  GC.loadAdminMigrations = loadAdminMigrations;
  GC.searchAdminPlayers = searchAdminPlayers;
  GC.loadAdminPlayer = loadAdminPlayer;
  GC.searchAdminPlanets = searchAdminPlanets;
  GC.loadAdminQueues = loadAdminQueues;
  GC.cancelQueueJob = cancelQueueJob;
  GC.loadAuditLog = loadAuditLog;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      if (qs("#admin-control-center")) initAdminPanel();
    });
  } else if (qs("#admin-control-center")) {
    initAdminPanel();
  }
})();
