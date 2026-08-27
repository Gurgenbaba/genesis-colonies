from pathlib import Path
import re

path = Path("static/js/galaxy-quick-action.js")
src = path.read_text(encoding="utf-8")

needle = '      mapActionError: typeof GC.mapActionError === "function" ? GC.mapActionError.bind(GC) : null,\n'
repl = needle + '      fleetReasonText: typeof GC.fleetReasonText === "function" ? GC.fleetReasonText.bind(GC) : null,\n'
if "fleetReasonText:" not in src:
    assert needle in src
    src = src.replace(needle, repl, 1)

needle = '    _attackPresetsLoading: false,\n'
if "_attackPresetsLoadFailed" not in src:
    assert needle in src
    src = src.replace(needle, needle + '    _attackPresetsLoadFailed: false,\n', 1)

src = src.replace('      if (!fetchGameAction) return 0;\n', '      if (!fetchGameAction) return null;\n', 1)
old = '''      } catch (_) {
        /* fall through */
      }
      return 0;
    },

    /**
     * One-click recycle send'''
new = '''      } catch (_) {
        return null;
      }
      return null;
    },

    /**
     * One-click recycle send'''
if old in src:
    src = src.replace(old, new, 1)

old = '''      const available = await this.resolveAvailableReclaimersAsync(root);
      const sendCount = Math.min(available, need);

      if (!originPlanetId) {'''
new = '''      const available = await this.resolveAvailableReclaimersAsync(root);
      if (available === null) {
        showNotify(t("fleet_error_server_error", t("fleet_error_generic", "Fleet action failed.")), "error");
        return null;
      }
      const sendCount = Math.min(available, need);

      if (!originPlanetId) {'''
if old in src:
    src = src.replace(old, new, 1)

old = '''      const available = await this.resolveAvailableReclaimersAsync(root);
      const sendCount = Math.min(available, needed);

      if (!originPlanetId) {'''
new = '''      const available = await this.resolveAvailableReclaimersAsync(root);
      if (available === null) {
        showNotify(t("fleet_error_server_error", t("fleet_error_generic", "Fleet action failed.")), "error");
        return;
      }
      const sendCount = Math.min(available, needed);

      if (!originPlanetId) {'''
if old in src:
    src = src.replace(old, new, 1)

if "fleetPayload(res)" not in src:
    pattern = re.compile(r'''    notifyFleetError\(reason, res, reasonMap\) \{.*?\n    \},\n\n    async runGuarded''', re.S)
    replacement = '''    fleetPayload(res) {
      if (res?.data && typeof res.data === "object") return res.data;
      if (res?.payload && typeof res.payload === "object") return res.payload;
      return res || {};
    },

    fleetReason(res, fallback = "generic") {
      const payload = this.fleetPayload(res);
      return String(
        res?.error ||
        res?.reason ||
        payload?.error ||
        payload?.reason ||
        fallback
      );
    },

    notifyFleetError(reason, res, reasonMap) {
      const { t, showNotify, mapActionError, fleetReasonText } = deps();
      const key = String(reason || "generic");
      const payload = this.fleetPayload(res);
      let msg = "";

      if (reasonMap && Object.prototype.hasOwnProperty.call(reasonMap, key)) {
        const entry = reasonMap[key];
        msg = typeof entry === "function" ? entry(res) : entry;
      }

      if (!msg) {
        const fleetKey = `fleet_error_${key}`;
        const translated = t(fleetKey, "");
        if (translated && translated !== fleetKey) msg = translated;
      }

      if (!msg && fleetReasonText) {
        msg = fleetReasonText(key, payload);
      }

      if (!msg && mapActionError) {
        const mapped = mapActionError(key, payload);
        const genericAction = t("msg_generic_error", "");
        if (mapped && mapped !== genericAction) msg = mapped;
      }

      if (!msg) msg = t("fleet_error_generic", "Fleet action failed.");
      showNotify(msg, "error");
    },

    async runGuarded'''
    src, count = pattern.subn(replacement, src, count=1)
    assert count == 1, count

old = '''      const exec = async () => {
        const res = await fetchGameAction("/api/fleet/send", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            ...(domPlanetId ? { "X-GC-Dom-Planet-Id": String(domPlanetId) } : {}),
          },
          body: JSON.stringify(payload),
        });
        if (res?.ok) {
          applyActionState(res, applyReason);
          if (typeof onSuccess === "function") onSuccess(res);
        } else if (typeof onError === "function") {
          onError(res?.error || res?.reason || "generic", res);
        }
        return res;
      };'''
new = '''      const exec = async () => {
        let res;
        try {
          res = await fetchGameAction("/api/fleet/send", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Requested-With": "XMLHttpRequest",
              ...(domPlanetId ? { "X-GC-Dom-Planet-Id": String(domPlanetId) } : {}),
            },
            body: JSON.stringify(payload),
          });
        } catch (_err) {
          if (typeof onError === "function") {
            onError("server_error", { ok: false, error: "server_error" });
          }
          return null;
        }
        if (res?.ok) {
          applyActionState(res, applyReason);
          if (typeof onSuccess === "function") onSuccess(res);
        } else if (typeof onError === "function") {
          onError(this.fleetReason(res), res);
        }
        return res;
      };'''
if old in src:
    src = src.replace(old, new, 1)

old = '      const emptyText = t("galaxy_quick_attack_empty", "No raid template available.");\n'
new = '''      const emptyText = this._attackPresetsLoadFailed
        ? t("fleet_error_server_error", t("fleet_error_generic", "Fleet action failed."))
        : t("galaxy_quick_attack_empty", "No raid template available.");
'''
if old in src:
    src = src.replace(old, new, 1)

old = '''        const body = await res.json().catch(() => ({}));
        const presets = body?.ok && body?.data?.presets ? body.data.presets : [];
        this._attackPresetsCache = Array.isArray(presets) ? presets : [];
        return this._attackPresetsCache;
      } catch (_err) {
        this._attackPresetsCache = [];
        return [];
      } finally {'''
new = '''        const body = await res.json().catch(() => ({}));
        if (!res.ok || !body?.ok) {
          this._attackPresetsLoadFailed = true;
          this._attackPresetsCache = null;
          return [];
        }
        const presets = body?.data?.presets || [];
        this._attackPresetsLoadFailed = false;
        this._attackPresetsCache = Array.isArray(presets) ? presets : [];
        return this._attackPresetsCache;
      } catch (_err) {
        this._attackPresetsLoadFailed = true;
        this._attackPresetsCache = null;
        return [];
      } finally {'''
if old in src:
    src = src.replace(old, new, 1)

old = '''      await this.runGuarded(btn, async () => {
        const res = await fetchGameAction("/api/planet/relocation/start", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
          },
          body: JSON.stringify({
            galaxy: targetGalaxy,
            system: targetSystem,
            position: targetPosition,
            request_id: this.makeRequestId("galaxy-reloc"),
          }),
        });
        if (res?.ok) {'''
new = '''      await this.runGuarded(btn, async () => {
        let res;
        try {
          res = await fetchGameAction("/api/planet/relocation/start", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Requested-With": "XMLHttpRequest",
            },
            body: JSON.stringify({
              galaxy: targetGalaxy,
              system: targetSystem,
              position: targetPosition,
              request_id: this.makeRequestId("galaxy-reloc"),
            }),
          });
        } catch (_err) {
          showNotify(t("fleet_error_server_error", t("planet_relocation_failed", "Relocation failed.")), "error");
          return;
        }
        if (res?.ok) {'''
if old in src:
    src = src.replace(old, new, 1)

path.write_text(src, encoding="utf-8")
