# AJAX / PJAX Contract

Verbindlicher Client-Server-Vertrag für Navigation und Aktionen. Siehe [STATE_AJAX.md](STATE_AJAX.md), [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md).

---

## Shell & PJAX

| Element | Verhalten |
|---------|-----------|
| `templates/base.html` | Bleibt im DOM (Nav, Resource Bar, Planet Switcher) |
| `#main-content` | Wird bei Navigation ersetzt |
| Link-Klasse | `.gc-nav-link` ohne `data-no-pjax` |

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
| Hung diet-poll before PJAX | Always `abortInFlightGameStateFetches()` even on light-nav — avoids SQLite worker starvation after long idle |
| Soft-Nav tickers (**GC-PERF-PJAX-TICKER-001**) | Progress-Ticker pausiert während Apply (`cleanupPage` → `initPage`); Resource-Ticker bleibt; `requestFinishRefresh` / queue-timer-zero no-op solange `GC.pjaxInFlight` |
| PJAX fetch failure | Hard-load fallback (`location.assign`) so the shell does not stay toast-only |
| Shell-HUD nach Login | `#gc-hud-boot-state` → `bootstrapHudFromDom()` vor Fleet-Drawer (GC-INSTANT-UX-001A) |
| Fleet-Seite mit `#fleet-page-state` `ready: true` | `initFleet` skippt sofortiges `refreshFleetState` (GC-INSTANT-UX-001C) |
| PJAX server context | Score/Rank, `HEADER_PLANETS`, Landscape hinter `_is_lightweight_layout_request()` — Shell bleibt im DOM (**GC-PERF-PJAX-CTX-SHELL-001**) |

Diet-Poll / deferred first poll liefert weiterhin Live-Updates; kein zweites Polling-System.

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
