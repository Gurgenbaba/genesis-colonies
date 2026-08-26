/* GC-FLT-UX-02 — partial-success launch for selected saved Fleet presets. */
(() => {
  "use strict";

  const GC = window.GC || (window.GC = {});
  if (GC.FleetBulkLaunchBound) return;
  GC.FleetBulkLaunchBound = true;

  const t = (key, fallback) =>
    typeof GC.t === "function" ? GC.t(key, fallback) : (fallback || key);
  const reasonText = (reason, context) => {
    if (typeof GC.fleetReasonText === "function") {
      return GC.fleetReasonText(reason, context || {});
    }
    return t(`fleet_error_${String(reason || "generic")}`, t("fleet_error_generic", "Fleet action failed."));
  };
  const makeRequestId = () => {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }
    return `fleet-bulk-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
  };
  const page = () => document.getElementById("fleet-page");
  const selectedIds = (root) =>
    Array.from(root?.querySelectorAll("[data-fleet-bulk-preset]:checked") || [])
      .map((input) => parseInt(input.value || "0", 10))
      .filter((id) => id > 0);

  const syncButton = (root) => {
    if (!root) return;
    const btn = root.querySelector("[data-fleet-bulk-launch]");
    if (!btn || btn.getAttribute("aria-busy") === "true") return;
    btn.disabled = selectedIds(root).length === 0;
    const all = root.querySelector("[data-fleet-bulk-select-all]");
    const items = Array.from(root.querySelectorAll("[data-fleet-bulk-preset]"));
    if (all && items.length) {
      const checked = items.filter((item) => item.checked).length;
      all.checked = checked === items.length;
      all.indeterminate = checked > 0 && checked < items.length;
    }
  };

  const clearNode = (node) => {
    while (node?.firstChild) node.removeChild(node.firstChild);
  };

  const renderResult = (root, payload) => {
    const host = root?.querySelector("[data-fleet-bulk-result]");
    if (!host) return "";
    clearNode(host);
    host.hidden = false;
    const started = Math.max(0, Number(payload?.started_count || 0));
    const skipped = Math.max(0, Number(payload?.skipped_count || 0));
    const template = t("fleet_bulk_launch_summary", "{started} started · {skipped} skipped");
    const summary = template
      .replace("{started}", String(started))
      .replace("{skipped}", String(skipped));
    const summaryEl = document.createElement("strong");
    summaryEl.className = "fleet-bulk-launch-summary";
    summaryEl.textContent = summary;
    host.appendChild(summaryEl);

    const skippedRows = Array.isArray(payload?.skipped) ? payload.skipped : [];
    if (skippedRows.length) {
      const title = document.createElement("span");
      title.className = "fleet-bulk-launch-skipped-title";
      title.textContent = t("fleet_bulk_launch_skipped_title", "Skipped");
      host.appendChild(title);
      const list = document.createElement("ul");
      list.className = "fleet-bulk-launch-skipped-list";
      skippedRows.forEach((row) => {
        const item = document.createElement("li");
        const name = String(row?.name || `#${Number(row?.preset_id || 0)}`);
        const nameEl = document.createElement("strong");
        nameEl.className = "fleet-bulk-launch-skip-name";
        nameEl.textContent = name;
        const reasonEl = document.createElement("span");
        reasonEl.className = "fleet-bulk-launch-skip-reason";
        reasonEl.textContent = reasonText(row?.reason, row?.context || {});
        item.appendChild(nameEl);
        item.appendChild(document.createTextNode(" "));
        item.appendChild(reasonEl);
        list.appendChild(item);
      });
      host.appendChild(list);
    }
    return summary;
  };

  const setBusy = (btn, busy) => {
    if (!btn) return;
    btn.setAttribute("aria-busy", busy ? "true" : "false");
    btn.disabled = Boolean(busy);
  };

  const launch = async (root, btn) => {
    const presetIds = selectedIds(root);
    const resultHost = root.querySelector("[data-fleet-bulk-result]");
    if (!presetIds.length) {
      if (resultHost) {
        clearNode(resultHost);
        resultHost.hidden = false;
        resultHost.textContent = t("fleet_bulk_launch_none_selected", "Select at least one fleet preset.");
      }
      return;
    }
    const originPlanetId = parseInt(root.dataset.planetId || "0", 10) || 0;
    if (!originPlanetId) {
      if (resultHost) {
        clearNode(resultHost);
        resultHost.hidden = false;
        resultHost.textContent = reasonText("origin_not_found");
      }
      return;
    }

    setBusy(btn, true);
    try {
      if (typeof GC.fetchGameAction !== "function") throw new Error("fleet_bulk_fetch_unavailable");
      const res = await GC.fetchGameAction("/api/fleet/bulk-launch-presets", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest",
          "X-GC-Dom-Planet-Id": String(originPlanetId),
        },
        body: JSON.stringify({
          origin_planet_id: originPlanetId,
          preset_ids: presetIds,
          request_id: makeRequestId(),
        }),
      });
      if (!res?.ok) {
        const payload = (res?.data && typeof res.data === "object") ? res.data : {};
        const msg = reasonText(res?.error || res?.reason || "generic", payload);
        if (resultHost) {
          clearNode(resultHost);
          resultHost.hidden = false;
          resultHost.textContent = msg;
        }
        if (typeof GC.showNotify === "function") GC.showNotify(msg, "error");
        return;
      }

      if (typeof GC.applyActionState === "function") {
        GC.applyActionState(res, "fleet_bulk_launch");
      }
      const payload = (res.data && typeof res.data === "object") ? res.data : {};
      const summary = renderResult(root, payload);
      if (typeof GC.showNotify === "function") {
        GC.showNotify(summary || t("fleet_bulk_launch_success", "Fleet bulk launch complete."), Number(payload.started_count || 0) > 0 ? "success" : "info");
      }
      root.querySelectorAll("[data-fleet-bulk-preset]").forEach((input) => { input.checked = false; });
      const selectAll = root.querySelector("[data-fleet-bulk-select-all]");
      if (selectAll) {
        selectAll.checked = false;
        selectAll.indeterminate = false;
      }
      if (typeof GC.refreshGameState === "function") {
        Promise.resolve(GC.refreshGameState()).catch(() => {});
      }
    } catch (_) {
      const msg = reasonText("generic");
      if (resultHost) {
        clearNode(resultHost);
        resultHost.hidden = false;
        resultHost.textContent = msg;
      }
      if (typeof GC.showNotify === "function") GC.showNotify(msg, "error");
    } finally {
      setBusy(btn, false);
      syncButton(root);
    }
  };

  document.addEventListener("change", (event) => {
    const root = page();
    if (!root) return;
    const all = event.target.closest?.("[data-fleet-bulk-select-all]");
    if (all && root.contains(all)) {
      root.querySelectorAll("[data-fleet-bulk-preset]").forEach((input) => {
        input.checked = Boolean(all.checked);
      });
      syncButton(root);
      return;
    }
    const preset = event.target.closest?.("[data-fleet-bulk-preset]");
    if (preset && root.contains(preset)) syncButton(root);
  });

  document.addEventListener("click", (event) => {
    const btn = event.target.closest?.("[data-fleet-bulk-launch]");
    const root = page();
    if (!btn || !root || !root.contains(btn)) return;
    event.preventDefault();
    launch(root, btn);
  });

  syncButton(page());
})();
