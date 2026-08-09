# AJAX / PJAX Contract

Verbindlicher Client-Server-Vertrag für Navigation und Aktionen. Siehe [STATE_AJAX.md](STATE_AJAX.md), [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md).

---

## Shell & PJAX

| Element | Verhalten |
|---------|-----------|
| `templates/base.html` | Bleibt im DOM (Nav, Resource Bar, Planet Switcher) |
| `#main-content` | Wird bei Navigation ersetzt |
| Link-Klasse | `.gc-nav-link` / `data-gc-nav` / `data-pjax` / Header (`.gc-topbar a`) ohne `data-no-pjax` |

### Navigation flow

```text
Klick Nav-Link
  → GC.cleanupPage({ preserveGameLoop? })
  → fetch(url, { headers: { "X-PJAX": "true" } })
  → #main-content aus HTML extrahieren und ersetzen
  → GC.initPage({ pjax, skipGameState?, skipPolling? })
  → refreshGameState("page_init") nur wenn nicht SSR-/Light-PJAX-Skip
```

Light-PJAX und SSR-Skip (Owner: `static/main.js`, Details in [STATE_AJAX.md](STATE_AJAX.md)):

| Fall | Verhalten |
|------|-----------|
| `pageHasSsrLiveBoot()` / `shouldSkipInitGameStateAfterSsr` | Kein sofortiger Full-`/api/game-state` nach frischem SSR (GC-742) |
| Ingame-Shell / Buildings-Tab Light-PJAX | `skipGameState` (+ ggf. `preserveGameLoop` / `skipPolling`) |
| Hung diet-poll before PJAX | Always `abortInFlightGameStateFetches()` + `GC.stopPolling()` even on light-nav — polls must not run during HTML render (local SQLite starvation / PJAX timeout) |
| Rapid nav coalesce | Latest destination wins; **do not** abort+restart in-flight HTML PJAX (`_pjaxPendingNav`) — abort pileups freeze local SQLite/Werkzeug |
| PJAX HTML timeout | 25s (> SQLite `busy_timeout` 20s) → **toast + release blockers + restart polling**, **no** `location.assign` (hard-load cascades CloseWaits locally) |
| Local SQLite Flask | Dev default `GC_FLASK_THREADED=0` ([`app.py`](../app.py)) — serialize requests; override with `GC_FLASK_THREADED=1` |
| Soft-Nav tickers (**GC-PERF-PJAX-TICKER-001**) | Progress-Ticker pausiert während Apply (`cleanupPage` → `initPage`); Resource-Ticker bleibt; `requestFinishRefresh` / queue-timer-zero no-op solange `GC.pjaxInFlight` |
| PJAX fetch failure | Hard-load fallback (`location.assign`) so the shell does not stay toast-only |
| Shell-HUD nach Login | `#gc-hud-boot-state` → `bootstrapHudFromDom()` vor Fleet-Drawer (GC-INSTANT-UX-001A) |
| Production `/h` Rates SSR | `HEADER_PROD_PER_HOUR` / `prod_per_hour` in `#resource-bar` — Climb ohne Diet-Poll (**GC-INSTANT-HUD-RATES-001**) |
| Busy-Flags aus SSR | `bootstrapBusyFlagsFromDom()` nach Queue-Bootstrap; First Diet-Poll = volle Cadence (**GC-INSTANT-POLL-BOOT-001**) |
| Timer-Zero Finish | Optimistic Level aus `data-target-level`, dann Canonical `include_panel=1` + `panel_page` (**GC-INSTANT-QUEUE-FINISH-001**, **GC-PERF-PANEL-SCOPE-001**) |
| Tab / bfcache wake | `wakeClientAfterHidden` — abort in-flight game-state, release shell blockers, clear stuck PJAX; exclusive `tab_visible` refresh (**GC-WAKE-001**) |
| Identity First Paint | `#gc-identity-critical` im `<head>` (**GC-INSTANT-IDENTITY-FOUC-001**) |
| Fleet-Seite mit `#fleet-page-state` `ready: true` | `initFleet` skippt sofortiges `refreshFleetState` (GC-INSTANT-UX-001C) |
| PJAX server context | Score/Rank, `HEADER_PLANETS`, Landscape hinter `_is_lightweight_layout_request()` — Shell bleibt im DOM (**GC-PERF-PJAX-CTX-SHELL-001**) |

Diet-Poll bleibt Hintergrund-Wahrheit; HUD/Finish-UX hängt nicht mehr am ersten Poll. Kein zweites Polling-System.

### Pflicht-APIs (`static/main.js`)

| API | Zweck |
|-----|--------|
| `GC.navigateTo(url, opts)` | PJAX-Navigation |
| `GC.reloadCurrentPage(opts)` | Gleiche Route neu laden (Planetwechsel, Scope-Mismatch) |
| `GC.fetchGameAction(url, options)` | POST/GET mit Credentials, JSON |
| `GC.refreshGameState(reason)` | `GET /api/game-state` |
| `applyActionState(json, reason)` | `json.state` anwenden + Polling neu starten |
| `GC.bootstrapHudFromDom()` | Slim HUD (fleets/unread) aus SSR hydratisieren |
| `GC.setActionBusy(el, busy)` | Pending-UX (`is-busy` / `gc-bld-head-action-btn--busy`) |

---

## Verbotene Navigation

In Spiel-Modulen (`static/main.js`, Seiten-Templates, `static/js/messages.js`):

```js
window.location.reload();
location.reload();
window.location.href = target;  // als Navigation
location.href = target;
```

### Dokumentierte Ausnahmen

| Ort | Grund |
|-----|--------|
| Login / Logout | Auth-Redirect (Flask) |
| `GC.reloadCurrentPage` Fallback | Nur wenn `GC.navigateTo` fehlt (Fatal / No-JS) |
| `static/admin.js` | Admin Control Center (separate Shell, kein PJAX) |
| Datei-Download, `target="_blank"`, externe URLs | Browser-Standard |
| `messages.js` / `main.js` `else`-Zweig | Fallback wenn `GC.navigateTo` nicht geladen |

Neue Ausnahmen nur mit Eintrag in `tests/test_core_architecture_enforcement.py` (`ALLOWLIST`).

---

## AJAX Action Contract

### Response shape (Spieler-APIs)

```json
{
  "ok": true,
  "reason": "ok",
  "state": { }
}
```

`state` = vollständiger oder panel-relevanter game-state payload (wie nach `POST` Build/Research).

**Shipyard (GC-512D):** `POST /api/shipyard/build` und `/api/shipyard/queue/cancel` liefern `{ ok, state }` via `fleet_ok()` + `body["state"]` (optional zusätzlich `data`). Client: **state-first** — `applyActionState(res)` wenn `res.state`; `applyShipyardState(page, res.data)` nur wenn `res.data` (Stocks/Labels). Siehe [STATE_AJAX.md](STATE_AJAX.md).

### Client

```js
const res = await GC.fetchGameAction("/api/…", { method: "POST", body: … });
if (res.ok) applyActionState(res, "reason_string");
```

| Verboten | Pflicht |
|----------|---------|
| `location.reload()` nach erfolgreicher Action | `applyActionState(res, …)` |
| UI raten und Ressourcen lokal abziehen | State vom Server patchen |
| Pro Countdown-Zeile / Nachricht eigenen Full-Reload | Ein State-Patch pro Zyklus (`scheduleFleetStateRefresh`, gebündelte Toasts) |

Idempotenz: Header `X-Request-Id` oder JSON `request_id`.

### Notification batching (GC-FLEET-NOTIFICATION-BATCH-001)

- Server behält Einzel-Nachrichten in `player_messages`.
- Client bündelt Toast/Sound pro Kategorie innerhalb eines kurzen Fensters (`MESSAGE_NOTIFY_BATCH_MS`).
- Incoming-Attack-Alarme bleiben separat (`fleet_alerts` / `_maybePlayIncomingAttackNotify`).
- Unread-Badge nutzt die echte Anzahl; Toasts deduplizieren über Message-IDs.

---

## Planet switch

```text
POST /api/planets/active  { planet_id }
  → applyActionState(res, "planet_switch")
  → GC.reloadCurrentPage({ force: true })   // scoped pages
```

Details: [PLANET_SCOPE.md](PLANET_SCOPE.md).

---

## Lifecycle & Cleanup

Bei Modul-Init:

```js
GC.registerCleanup(() => { /* clearInterval, abort, removeListener */ });
```

Vor PJAX-Swap: `GC.cleanupPage()` — stoppt Polling-Abort, rAF, registrierte Cleanups.

Chat: `GC.resumeChatPolling()` nach PJAX (eigenes Intervall, kein game-state).

---

## Legacy routes

`GET /upgrade/<type>`, `GET /research_start/<key>` — No-JS-Fallback. Mit JS: Klick-Intercept → POST APIs.

---

## Tests

```bash
python -m pytest tests/test_core_architecture_enforcement.py tests/test_game_state_live.py tests/test_planet_registry.py -v
```
