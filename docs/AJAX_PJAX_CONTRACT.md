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
  → GC.cleanupPage()
  → fetch(url, { headers: { "X-PJAX": "true" } })
  → #main-content aus HTML extrahieren und ersetzen
  → GC.initPage({ force: true })
  → GC.refreshGameState("page_init")
```

### Pflicht-APIs (`static/main.js`)

| API | Zweck |
|-----|--------|
| `GC.navigateTo(url, opts)` | PJAX-Navigation |
| `GC.reloadCurrentPage(opts)` | Gleiche Route neu laden (Planetwechsel, Scope-Mismatch) |
| `GC.fetchGameAction(url, options)` | POST/GET mit Credentials, JSON |
| `GC.refreshGameState(reason)` | `GET /api/game-state` |
| `applyActionState(json, reason)` | `json.state` anwenden + Polling neu starten |

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

### Client

```js
const res = await GC.fetchGameAction("/api/…", { method: "POST", body: … });
if (res.ok) applyActionState(res, "reason_string");
```

| Verboten | Pflicht |
|----------|---------|
| `location.reload()` nach erfolgreicher Action | `applyActionState(res, …)` |
| UI raten und Ressourcen lokal abziehen | State vom Server patchen |

Idempotenz: Header `X-Request-Id` oder JSON `request_id`.

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
python -m pytest tests/test_core_architecture_enforcement.py tests/test_game_state_live.py tests/test_header_planet_switcher.py -v
```
