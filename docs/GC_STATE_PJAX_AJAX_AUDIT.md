# GC-CLEAN-001 — Project-wide State / AJAX / PJAX Reality Audit

**Status:** Audit complete (read-only). No Big-Bang refactor in this ticket.  
**Date:** 2026-07-14  
**Owner:** GC-000 canonical architecture (`docs/CORE_ARCHITECTURE.md`, `docs/STATE_AJAX.md`, `docs/AJAX_PJAX_CONTRACT.md`)

---

## 1. Executive Summary

Genesis Colonies is **functionally far along**, but the client/server boundary has grown through many incremental AI tickets. The **canonical model exists and mostly works** — one `/api/game-state`, `GC.lastState`, `applyGameStateData()`, `applyActionState()`, PJAX shell — but **parallel paths, stale patches, and legacy envelopes** create drift, extra network work, and “works after reload” UX.

### Symptom mapping (reported 2026-07-14)

| Symptom | Likely audit cause | Priority |
|---------|-------------------|----------|
| **Spiel fühlt sich langsamer an** | PJAX light-nav only partial; full nav still stops/restarts poll; galaxy prefetch storm on idle; duplicate HUD refresh paths; SSR still renders full `base.html` on every PJAX; recent preload/LCP churn on tab switches | P1 |
| **Planet Evolution Boost / Timekeeper nicht sofort sichtbar** | `patchQueuePanelsImmediate()` + `_syncTimekeeperButtonsFromState()` **exclude PE**; PE uses `/api/planets/{id}/state` + `reloadCurrentPage()` instead of `applyActionState()` | **P0** |
| **Galaxie PJAX 500 (prod, fixed `5fca1cc`)** | PJAX stub `player_view={id}` broke `base.html` (`player.metal`) — lesson: **SSR always renders shell** | P0 (fixed) |

### Findings count (approximate)

| Category | kanonisch | erlaubt | legacy | dupliziert | gefährlich |
|----------|-----------|---------|--------|------------|------------|
| State sources | 12 | 4 | 6 | 8 | 10 |
| Poll/timer owners | 4 | 2 | 4 | 4 | 5 |
| Fetch helpers | 2 | 1 | 0 | 3 | 16+ raw bypasses |
| API envelopes | 1 target | 5 domain-specific | 3 aliases | 6 families | ~15 gameplay gaps |
| Page modules | 25 | 2 (messages/admin) | 0 | 3 init paths | 5 lifecycle gaps |
| Queue renderers | 3 live patterns | 0 | 1 retired stack | 6 SSR/JS pairs | 2 PE patchers |
| Dead-code candidates | — | — | 12+ | — | — |

---

## 2. Current State Architecture

### 2.1 Canonical path (target — already partially live)

```text
GET /api/game-state
        ↓
GC.refreshGameState(reason)
        ↓
applyGameStateData(data, reason)  |  applyHudOnlyGameState (poll/tab)
        ↓
GC.lastState  (via patchHudLastState / commitGameStateCache)
        ↓
HUD + page module patches
```

**Owners:** `app.py:api_game_state` → `_build_game_state_payload`; `static/main.js:refreshGameState`, `applyGameStateData`, `applyHudOnlyGameState`.

### 2.2 Mutation path (target)

```text
User action
    ↓
GC.fetchGameAction(url, opts)
    ↓
POST /api/*
    ↓
{ ok, state }  (+ optional domain fields)
    ↓
applyActionState(res, reason)
    ↓
patchQueuePanelsImmediate(state)  →  applyGameStateData(state, reason)
    ↓
DOM patch (HUD + scoped panels)
```

**Owner:** `static/main.js:applyActionState` (~49 call sites).

### 2.3 State source inventory

| Source | File / function | State kind | Consumer | Class |
|--------|-----------------|------------|----------|-------|
| `/api/game-state` | `app.py:api_game_state` | Full/panel game state | Poll, actions, HUD | **kanonisch** |
| `GC.lastState` | `static/main.js:commitGameStateCache`, `patchHudLastState` | Client cache (~28 HUD keys) | All live UI | **kanonisch** |
| SSR resource bar | `templates/base.html`, `bootstrapResourceLiveFromDom` | Metal/crystal/fuel snapshot | Resource ticker | **kanonisch** (boot only) |
| SSR boosters JSON | `#gc-header-boosters-state` | `active_boosters` | `bootstrapHeaderBoostersFromDom` | **kanonisch** (boot) |
| `hydratePageFromLastState` | `static/main.js` | Reuse `GC.lastState` on PJAX | `initPage` when allowed | **kanonisch** |
| `/api/notifications/summary` | `app.py`, `applyNotificationSummary` | Unread/attack slice | HUD badges | **erlaubt** (perf split) |
| `/api/planets/{id}/state` | `app.py`, `refreshPlanetEvolutionState` | PE queues/cards | PE page only | **dupliziert** (parallel to game-state) |
| `_boostHudState` | `static/main.js:patchShellHudBoosters` | Booster chip cache | Header boosters | **dupliziert** / **gefährlich** (stale fallback) |
| `_resourceLive` / `_resourceDisplay` | `static/main.js` | Display projection | Resource bar tick | **erlaubt** (display-only) |
| `_inventoryLastState` | `static/main.js` | Page-local inventory | Inventory cards | **dupliziert** |
| Queue render signatures | `_lastQueueSignature`, `_lastPePlanetTechQueueSignature`, … | Skip re-render | Card/mini-queue | **erlaubt** |
| `fleetPage._fleetRt` | `static/main.js` | Fleet preview cache | Fleet form | **erlaubt** (page-local) |
| `localStorage` | galaxy prefs, sidebar, fleet drawer, chat UI | **UI prefs only** | Shell UX | **erlaubt** |
| `/api/status` | `app.py` | Alias of game-state | Tests/legacy | **legacy** |
| Poll finish throttle | `game/queue_poll.py:POLL_FINISH_INTERVAL_SEC` (~25s) | Server-side finish cadence | Poll path | **erlaubt** (documented) |

**Rule:** UI state (accordion, drawer height) may stay local. **Mechanic state must not.**

---

## 3. Current AJAX Architecture

### 3.1 Fetch wrapper matrix

| Helper | Definition | Call sites (static/) | Request | Idempotency | Error/auth | State handling |
|--------|------------|---------------------|---------|-------------|------------|----------------|
| `GC.fetchGameAction` | `main.js:1877` | **~58** | JSON POST | Per-route `request_id` | Redirect `/login` on auth | Caller → `applyActionState` |
| `GC.fetchJSON` | `main.js:1917` | **~20** | GET JSON | — | Abort on `cleanupPage` | Caller applies |
| Raw `fetch()` | scattered | **~25** | mixed | mixed | inconsistent | **bypass** |

### 3.2 Raw `fetch()` bypasses (migration targets)

| File | Routes / purpose | Risk |
|------|------------------|------|
| `static/main.js` | PJAX HTML (`navigateTo`, galaxy prefetch), `/api/game-state` HUD refresh (L12934), inventory POST, alliance profile/logo, locale, support tickets, player-card, whats-new | **P1** — parallel to canonical helpers |
| `static/js/messages.js` | Inbox load (intentional: no abort on PJAX) | **erlaubt** |
| `static/js/chat.js` | Chat poll/send | **erlaubt** (separate domain) |
| `static/js/galaxy-quick-action.js` | Fleet presets GET | **P2** |
| `static/admin.js` | Admin API | **erlaubt** (separate shell) |

### 3.3 Duplicate fetch patterns

- **Dual game-state fetch:** `GC.fetchJSON("/api/game-state")` (poll) vs raw `fetch("/api/game-state")` (HUD refresh `main.js:12934`).
- **Duplicate queue cancel UI:** global HUD handlers (L5159–5238) and buildings/research page handlers (L30998–31160) — same `/api/buildings/cancel`, `/api/research/cancel`.
- **PE `postAction`:** `fetchGameAction` → fallback `fetchJSON` (`main.js:23644–23656`).

---

## 4. Current PJAX / Lifecycle Architecture

### 4.1 Canonical navigation

```text
GC.navigateTo(url, opts)
  → (optional) isIngameShellPjaxNavigation / isBuildingsTabOnlyNavigation
  → abort prior PJAX / preserveGameLoop
  → fetch HTML (X-PJAX: true)
  → applyPjaxPayload
      → GC.cleanupPage({ preserveGameLoop })
      → #main-content swap
      → GC.initPage({ pjax, skipGameState?, skipPolling? })
```

**Owners:** `static/main.js:GC.navigateTo`, `applyPjaxPayload`, `GC.cleanupPage`, `GC.initPage`.

### 4.2 Light PJAX tiers (2026-07 perf work)

| Tier | Trigger | opts | Effect |
|------|---------|------|--------|
| **Buildings tab** | `isBuildingsTabOnlyNavigation` | `skipGameState`, `skipPolling`, `preserveGameLoop`, `skipLcpPreload` | Best — no poll restart |
| **Ingame shell** | `isIngameShellPjaxNavigation` | `skipGameState`, `preserveGameLoop` | Skips `/api/game-state` on nav; poll continues |
| **Planet switch** | `reloadCurrentPage` after `/api/planets/active` | `skipGameState`, `skipPolling`, `skipHydrate` | HUD-only patch + SSR fragment |
| **Full nav** | Sidebar first visit, `force: true`, admin leave | default | **stopPolling + refreshGameState** — still slow |

**Gap:** Many routes (Overview ↔ Fleet ↔ Galaxy ↔ Shipyard) still use **full cleanup** → `polling stopped` → immediate `refreshGameState` visible in prod logs.

### 4.3 Navigation exceptions

| Mechanism | Sites | Class |
|-----------|-------|-------|
| `GC.navigateTo` | ~58 | **kanonisch** |
| `GC.reloadCurrentPage` | ~30 | **kanonisch** (wraps navigateTo) |
| `location.reload()` | `main.js:2581, 2611, 31649` | **erlaubt** (fullDocument, fallback, locale) |
| `location.href =` | login redirect, messages fallback, options fallback, radar/galaxy navigateTo-missing | **erlaubt** |
| `window.location.assign` | auth routes in `navigateTo`, PJAX fail, shop checkout, logout | **erlaubt** |

**Enforcement:** `tests/test_core_architecture_enforcement.py` + `tests/test_gc592f_pjax_regression.py` allowlists synced to current line numbers (2026-08 Soft-Reload migration Wave 0).

### 4.4 Page module registry (`GC.modules`)

25+ modules in `main.js` — overview, inventory, auction_house, vote_center, referrals, alliance, imperial_directives, galactic_politics, trader_hub, fleet, logistics, shipyard, defense, buildings, research, **planet_evolution**, empire, galaxy, ranking, hall_of_fame, chronicles, records, techtree, combat_simulator, options, login_rewards, premium, shop, creator, world_boss, skilltree, …

**External:** `messages.js` → `GC.modules.messages`; `admin.js` → `GC.modules.admin`.

| Route | Module | Init | Cleanup | SSR hydrate | Live patch | PJAX-safe | Multi-bind risk |
|-------|--------|------|---------|-------------|------------|-----------|-----------------|
| `/buildings` | buildings | `GC.modules.buildings` | `registerCleanup` | mini-queue + hero SSR | `renderBuildQueue`, `patchCardQueuesFromOwnerMap` | Yes (light tab) | Low |
| `/research` | research | same pattern | yes | yes | yes | Yes | Low |
| `/shipyard` | shipyard | same | yes | mini-queue SSR; cards JS-only | `patchShipyardCardQueues` | Yes | Medium |
| `/defense` | defense | same | yes | same | same | Yes | Medium |
| `/planet_evolution` | planet_evolution | `bindPlanetEvolutionOnce` | yes | PE card SSR | `applyActionState` + queue patch; soft PJAX only for policy/event structural SSR | **Yes** (GC-CLEAN-002) | Medium |
| `/fleet` | fleet | module init | yes | partial | fleet state fetch | Yes | Medium |
| `/galaxy` | galaxy | module init | yes | full SSR system | minimal JS patch; soft on debris/relocate | Partial | Medium |
| `/messages` | messages (special) | `runMessagesPageModule` | `registerPageCleanup` | inbox SSR | messages.js local | Partial | Medium |
| `/login-rewards` | login_rewards | yes | yes | calendar SSR | `patchLoginRewardsDom` (incl. days) | Yes | Low |
| `/premium` | premium | yes | yes | tracks/ops SSR | `patchBattlePassDom`; soft only on daily period rollover | Yes | Low |
| `/shop` | shop | yes | yes | catalog SSR | `_markShopSkuOwned` / free-shop render | Yes | Low |

**Lifecycle owner:** `GC.registerCleanup` (~60 registrations), cleared in `GC.cleanupPage`.

---

### 4.5 Soft-PJAX inventory (migrate / keep / defer)

Updated 2026-08 Soft-Reload migration. Soft = `GC.reloadCurrentPage` (HTML swap), not `location.reload`.

| Domain | Classification | Notes |
|--------|----------------|-------|
| Login Rewards claim | **migrated** | `patchLoginRewardsDom` updates day cards |
| Battle Pass claim / claim-op | **migrated** | `patchBattlePassDom`; soft only `bp_daily_period_rollover` |
| Shop fulfill (shop page) | **migrated** | `_markShopSkuOwned` |
| Shop fulfill (premium embed) | **keep soft** | Premium unlock needs track SSR |
| Creator terms ack | **keep soft** | Dashboard behind `terms_required` SSR |
| PE research choose / spec pick / upgrade | **migrated** (DOM patch + soft false) | Policy/event still soft |
| PE policy / event resolve | **keep soft** | Structural SSR panels |
| World Boss claim | **migrated** | Replace claim panel in-place |
| World Boss defeated / catch success | **keep soft** | Claim strip / companion SSR |
| Skilltree unlock / SP claim | **migrated** | `patchMapFromState` |
| Skilltree class pick/swap (no skill map yet) | **keep soft** | Class-grid ↔ map SSR |
| Auction new lots | **keep soft** | Lot cards not in DOM |
| Galaxy QA relocate / debris live | **defer** | Slot SSR |
| Planet switch / scope mismatch | **keep** | Canonical scope contract |
| Locale / auth / admin / payment | **hard load** | Documented exceptions |
| Legacy `/upgrade`, `/research_start` | **defer** | JS-intercepted; No-JS redirect fallback |
| Admin PJAX | **defer** | ROADMAP intentional |

---

## 5. API Envelope Matrix

**Target contract (gameplay mutations):**

```json
{ "ok": true, "state": { ... } }
```

### 5.1 Envelope families

| Family | Helper | Shape | Has top-level `state`? | Domains |
|--------|--------|-------|------------------------|---------|
| Canonical | `_action_json_response` | `{ok, reason, state}` | Yes | buildings, research, exchange, timekeeper, PE API |
| Fleet | `fleet_ok` / `fleet_err` | `{ok, data/message, state?}` | Usually | fleet, shipyard build |
| Defense | `_defense_json_response` | `{ok, state, queue, defenses}` | Yes | defense |
| Alliance | `_alliance_action_json` | `{ok, state, alliance}` | Yes | alliance |
| Inventory | `_inventory_action_*` | `{ok, reason, state, inventory}` | Yes | inventory |
| Options | `_options_api_response` | `{ok, error, data}` | **No** | options, planet rename/delete |
| Chat | `_chat_json` | `{ok, error, data}` | **No** | chat |
| Messages | `_messages_json` | `{ok, error, data}` | **No** | messages |
| Support | `_support_json` | `{ok, error, data}` | **No** | support |

### 5.2 Gameplay routes — compliance snapshot

| Route group | Server `state`? | Client wrapper | Client applies `state`? | Gap |
|-------------|-----------------|----------------|-------------------------|-----|
| `/api/buildings/*`, `/api/research/*` | Yes | `fetchGameAction` | `applyActionState` | — |
| `/api/shipyard/*`, `/api/defense/*` | Yes | `fetchGameAction` | `applyActionState` | — |
| `/api/fleet/*`, logistics | Yes | `fetchGameAction` | `applyActionState` | — |
| `/api/timekeeper/apply` | Yes | `fetchGameAction` | `applyActionState` | **PE domain not patched in UI** |
| `/api/planets/{id}/research|spec|policy|events/*` | Yes | `postAction` | **`reloadCurrentPage`** | **P0 contract violation** |
| `/api/planets/active` | Yes | `fetchGameAction` | `applyActionState` (hudOnly) | — |
| `/api/options/planet-name`, `/api/planet/delete` | No / partial | `fetchGameAction` | manual refresh | P1 |
| `/api/inventory/use` | Yes | raw `fetch` | `applyActionState` | P1 wrapper bypass |
| `/api/vote/visit` | No | `fetchGameAction` | DOM-only | P2 |

---

## 6. Polling Matrix

| Loop | Owner | Interval | Endpoint | Start | Cleanup | Parallel OK? |
|------|-------|----------|----------|-------|---------|--------------|
| Game-state poll | `GC.startPolling` → `gameStatePollTick` | 3s active / 5s idle / 15s hidden | `/api/game-state` | `initPage` afterInit | `GC.stopPolling`, `cleanupPage` | **Must be singleton** |
| Notification poll | `GC.startNotificationPoll` | 1s / 5s hidden | `/api/notifications/summary` | deferred boot | cleanup | **erlaubt** (separate) |
| Progress ticker | `GC.startProgressTicker` | adaptive 50–1000ms timeout chain | — (DOM timers) | initPage | cleanup | **erlaubt** |
| Resource ticker | `startResourceTicker` | setInterval | — (DOM projection) | initPage | cleanup | **erlaubt** (display) |
| Chat poll | `static/js/chat.js` | setTimeout chain | `/api/chat/*` | `scheduleDeferredChatBoot` | registerCleanup | **erlaubt** (separate domain) |

### Legacy / dead polling artifacts

| Item | Location | Status |
|------|----------|--------|
| `GC.shipyardPollMs` / poll interval stubs | removed | Canonical `/api/game-state` + progress ticker only |
| `GC.stopStatusPoller` | alias of `stopPolling` | **legacy** |

### Polling risks

- **Poll = hudOnly** (`isHudOnlyGameStateReason`): normal poll does not patch buildings/research/PE panels → relies on timer-zero → `forceCanonicalGameStateRefresh`.
- **Poll finish throttle** ~25s (`game/queue_poll.py`) → jobs can look stuck if client timer refresh fails.
- **Nav churn:** non-light PJAX calls `stopPolling()` then immediate restart + `refreshGameState` — user-visible slowness.

---

## 7. Renderer Duplications

### 7.1 Live patterns

| UI component | SSR | JS renderer / patcher | Duplication |
|--------------|-----|----------------------|-------------|
| Mini-queue strip | `partials/page_mini_queue_strip.html` | `GC.renderMiniQueueStrip` | Full parallel (intentional) |
| Hero queue (build/research) | `render_hero_queue` in page templates | `renderHeroQueueOverlay` | Parallel; macro **duplicated** in buildings + research |
| Card queue (ship/defense) | **none** | `GC.renderCardQueueBlock` | JS-only |
| Card queue (PE) | `pe_card_queue_block` | `renderPePlanetTechQueue` + `applyPeResearchCardQueueJobs` | **Dual patchers on same list** |
| Resource bar | `base.html` SSR | `tickLiveResourceBar` | SSR + poll (canonical) |
| HUD boosters | `#gc-header-boosters-state` | `patchShellHudBoosters` | SSR + `_boostHudState` cache |

### 7.2 Retired stack (orphaned)

- `partials/page_queue_compact.html` + `_updatePageQueueCompact*` in `main.js` — **no template hosts**.
- `partials/build_queue.html`, `research_queue.html`, `shipyard_queue.html` — macros **unused in pages**.
- `render_research_card_queue` in `research.html` — **defined, never called**.

### 7.3 Hydrate paths (naming legacy)

` _bootstrapPageQueueCompactLiveFromDom` / `_hydratePageQueueCompactsFromState` → target **mini-queue** hosts (`#build-mini-queue`, etc.), not retired compact headers.

---

## 8. Dead-Code Candidates

Each candidate requires **call-site grep before deletion** (Regel 19).

| Candidate | Definition | Call-site evidence | Ticket |
|-----------|------------|-------------------|--------|
| `_updatePageQueueCompact` + `_*QueueCompact` wrappers | `main.js:~8654–8703` | Only internal; no template IDs | GC-CLEAN-007 |
| `page_queue_compact.html` | `templates/partials/` | No page imports | GC-CLEAN-007 |
| `build_queue.html`, `research_queue.html`, `shipyard_queue.html` partials | templates | Tests only | GC-CLEAN-007 |
| `render_research_card_queue` macro | `research.html` | 0 invocations | GC-CLEAN-008 |
| `reorderCardQueueBlocks` | `main.js` | Test assertion only | GC-CLEAN-007 |
| `updateBuildQueueLive` | `main.js` | Definition only | GC-CLEAN-007 |
| `GC.clearBuildingCardQueue` | alias | 0 call sites | GC-CLEAN-007 |
| `attach_card_jobs_by_owner` | `game/queue_card.py` | Definition only | GC-CLEAN-007 |
| `_updateMiniQueueSlots` | `main.js` | Empty stub | GC-CLEAN-007 |
| `GC.shipyardPollMs`, `_shipyardPollIntervalId` | removed | — | GC-TK-SKIP-QUEUE-001 |
| `/api/status` alias | `app.py` | Tests/legacy | GC-CLEAN-006 |
| Compact queue CSS | `style.css` ~9260+ | No HTML IDs | GC-CLEAN-008 |
| Stale tick selectors `.build-job-active` etc. | `updateAllProgressBars` | No current SSR | GC-CLEAN-007 |

---

## 9. Critical Risks (P0–P1)

### P0 — fix before next feature wave

1. **PE not in immediate action patch path** — `patchQueuePanelsImmediate` (L3619–3687) handles buildings/research/shipyard/defense only; `_syncTimekeeperButtonsFromState` (L7856–7893) same. **Timekeeper/boost on PE page stays stale until reload or separate PE fetch.**
2. **PE actions use `reloadCurrentPage` instead of `applyActionState`** — e.g. research start (`main.js:24145–24153`), spec pick (`24176`), policy/events pattern. Server returns `{ok, state}`; client ignores canonical patch.
3. **Galaxy PJAX 500 class of bugs** — any optimization that skips `_load_player_view_with_resources()` breaks `base.html` SSR. **Rule: PJAX still renders full template tree.**

### P1 — performance + trust

4. **Partial light-PJAX** — only buildings tabs + generic ingame when `pageHasSsrLiveBoot()`. Fleet/Galaxy/Overview switches still full poll restart (user logs confirm).
5. **Galaxy idle prefetch storm** — `initGalaxyPrefetchHints` + fleet-page coord links fire many PJAX prefetches; failures (500/502) add load (`main.js:24699`, `24757`).
6. **`_boostHudState` stale fallback** — when action `state` omits `active_boosters`, chips may not update until poll.
7. **Architecture enforcement tests stale** — `test_core_architecture_enforcement.py` allowlist lines don't match `main.js` reload/href sites.
8. **~16 raw `fetch()` mutation/read bypasses** in `main.js` — inconsistent abort/auth/state handling.

### P2 — cleanup

9. Duplicate queue-cancel handlers.  
10. Six API envelope families for gameplay-adjacent domains.  
11. Retired queue compact stack + CSS.  
12. `render_hero_queue` duplicated across buildings/research templates.

---

## 10. Target Architecture (unchanged — GC-000)

Do **not** reinvent. Consolidate **to** this:

### Global state

```text
/api/game-state → GC.lastState → applyGameStateData()
```

### Mutations

```text
GC.fetchGameAction() → POST → { ok, state } → applyActionState()
```

### Navigation

```text
cleanupPage() → PJAX → #main-content → initPage() → one page module
```

### Page modules

```text
init / optional patchFromState / cleanup via registerCleanup
```

**No page-owned game-state polling.**

### Rendering

- SSR = initial truth for visible DOM.
- Live patches must preserve **same DOM contract** (classes, `data-*`, timer attrs from `card_queue_macros.html`).
- One canonical patcher per component — no third parallel renderer.

---

## 11. Migration Order (safe waves)

```text
Wave 0 (hotfix)     PE immediate patch + applyActionState (user-visible boost bug)
Wave 1              Fetch/action helper audit + inventory/locale raw fetch migration
Wave 2              Polling singleton hardening + kill dead poll IDs + reduce nav poll churn
Wave 3              PJAX lifecycle: extend light-nav coverage + fix enforcement tests
Wave 4              Queue renderer consolidation (retired compact stack removal)
Wave 5              API envelope normalization (options/chat stay separate)
Wave 6              Dead code wave 1 (grep-proven)
Wave 7              CSS/template duplication cleanup
```

**Rule:** migrate call-sites → tests green → grep old symbols → delete legacy in **same ticket**.

---

## 12. Ticket Split

### GC-CLEAN-002 — PE action state + timekeeper patch (P0 hotfix)

**Status:** ✅ (2026-07-22) — `finalizePeMutationSuccess` + soft content PJAX for structural PE; research start stays patch-only.  
**Follow-up 2026-08:** research choose / spec pick / upgrade → DOM patch + `softContent: false`; policy/event remain soft.  
**Scope:** `static/main.js` only (+ tests).  
**Do:**
- Extend `patchQueuePanelsImmediate` + `_syncTimekeeperButtonsFromState` for `planet_evolution` / `planet_research` when `.planet-evolution-page` active.
- PE `postAction` success → `applyActionState(res, reason)` instead of `reloadCurrentPage` where `{ok, state}` present.
- Reset `_lastPePlanetTechQueueSignature` in `resetQueueRenderSignaturesForImmediatePatch`.
- On `timekeeper_apply` + PE domain: call `refreshPlanetEvolutionState(activePlanetId)` or inline PE queue patch from `state`.

**Tests:** extend `test_gc835_frontend_state_contract.py`, PE timekeeper contract.  
**Risk:** Low if scoped to PE page only.

---

### GC-CLEAN-003 — Game-state polling singleton audit/fix

**Scope:** `static/main.js`, `game/queue_poll.py`.  
**Do:** Dead `GC.shipyardPollMs` / interval stubs removed (GC-TK-SKIP-QUEUE-001); document notification poll as allowed exception; ensure `cleanupPage({ preserveGameLoop })` never double-starts poll; fix `polling already active` log spam.

**Tests:** extend `test_static_live_updates.py` poll contracts.

---

### GC-CLEAN-004 — PJAX lifecycle + light navigation completion

**Scope:** `static/main.js`, `tests/test_core_architecture_enforcement.py`.  
**Do:** Extend light-nav to remaining high-traffic routes without breaking force-reload paths; update allowlist line numbers; add contract for `preserveGameLoop` + `skipGameState` on ingame nav.

**Tests:** `test_main_js_gc742`, `test_gc592f_pjax_regression`, enforcement tests.

---

### GC-CLEAN-005 — Queue renderer consolidation

**Scope:** `static/main.js`, `templates/partials/`, `static/style.css`.  
**Do:** Remove retired compact stack; extract shared `render_hero_queue` partial; reconcile PE dual list patchers; remove stale `.build-job-active` tick branches.

**Tests:** `test_queue_card_global_ux.py`, domain queue tests — update, don't weaken.

---

### GC-CLEAN-006 — API envelope normalization (gameplay)

**Scope:** `app.py` thin routes, `game/*` handlers.  
**Do:** Options planet rename/delete → include top-level `state`; document chat/messages/support as intentional non-game-state domains.

**Tests:** route contract tests per endpoint touched.

---

### GC-CLEAN-007 — Dead code wave 1

**Scope:** items in §8 with grep proof.  
**Do:** Delete only after call-site migration in same PR.

---

### GC-CLEAN-008 — CSS/template duplication cleanup

**Scope:** compact CSS, unused partials, hero macro dedup.  
**Do:** After GC-CLEAN-005.

---

### GC-CLEAN-009 — Fetch bypass migration

**Scope:** raw `fetch` in `main.js` for gameplay paths (inventory, HUD game-state refresh).  
**Do:** Migrate to `fetchGameAction` / `fetchJSON` with documented exceptions list in test allowlist.

---

### GC-CLEAN-010 — Performance regression baseline

**Scope:** docs + optional `docs/GC-856` extension.  
**Do:** Measure TTFB + client nav timeline (Overview→Fleet→Galaxy→Buildings tab) before/after waves 2–4; cap galaxy prefetch concurrency on idle.

---

## Tests — existing + planned

### Existing architecture contracts (keep green)

| Test file | Guards |
|-----------|--------|
| `tests/test_core_architecture_enforcement.py` | reload/href allowlist (**needs line update**) |
| `tests/test_static_live_updates.py` | game-state skip, PJAX, poll, action state |
| `tests/test_gc592f_pjax_regression.py` | PJAX markers |
| `tests/test_gc835_frontend_state_contract.py` | `patchCardQueuesFromOwnerMap`, PE patches |
| `tests/test_queue_card_global_ux.py` | queue DOM/CSS contracts |
| `tests/test_buildings_card_queue.py` | light buildings PJAX |

### Planned static tests (GC-CLEAN-006+)

- No new module-owned `/api/game-state` poller outside allowlist.
- No `location.reload()` outside documented allowlist (synced lines).
- Gameplay POST routes in allowlist must return `state` key (grep `app.py` + contract list).
- Each `GC.modules.*` entry has `registerCleanup` or documented exception.
- No new call sites to retired helpers (`_updatePageQueueCompact`, etc.) after deletion.

---

## Appendix A — Duplicate systems summary

| Domain | Parallel paths |
|--------|------------------|
| Game state | `/api/game-state` vs `/api/planets/{id}/state` (PE) vs SSR `_load_page_live_context` |
| HUD refresh | `applyHudOnlyGameState` vs `refreshHudFromGameState` vs `GC.applyHudFromGameState` |
| Booster display | SSR JSON vs `GC.lastState.active_boosters` vs `_boostHudState` |
| Unread badges | game-state poll vs `/api/notifications/summary` |
| PE mutation UX | `applyActionState` (canonical) + soft PJAX only for policy/event structural SSR |
| Queue UI | mini-queue SSR/JS + hero overlay + card block + retired compact |
| Fetch | `fetchGameAction` vs `fetchJSON` vs raw `fetch` |

---

## Appendix B — What NOT to do

- Rewrite `main.js` as SPA/framework.
- Change all API envelopes in one commit.
- Delete code without grep-proven zero call sites.
- Add a second universal queue renderer beside `GC.renderCardQueueBlock` / `GC.renderMiniQueueStrip`.
- Skip SSR shell requirements on PJAX “optimization.”

---

## Completion checklist (GC-CLEAN-001)

- [x] Full repository inventory (state, poll, nav, fetch, API, PJAX, renderers, dead code)
- [x] Concrete file/function references (not generic advice)
- [x] Prioritized P0–P3 list
- [x] Target architecture aligned with GC-000
- [x] Executable follow-up tickets GC-CLEAN-002 … GC-CLEAN-010
- [x] No risky Big-Bang implementation in this ticket

**Next recommended action:** Soft-Reload Wave complete for meta claims (login/BP/shop/WB claim/PE choose+spec). Remaining: Galaxy slot-live, Admin PJAX, legacy `/upgrade` — only with explicit Go (see §4.5 defer).
