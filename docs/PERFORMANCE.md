# Performance Intelligence (GC-PERF-AUTO)

> Owner: `game/perf_intel.py` (aggregation / pressure / diagnosis)  
> Request spans: `game/live_state.py` (`RequestPerfState`, `perf_span`)  
> DB timing: `game/db.py`  
> Admin: `GET /api/admin/performance` + Admin Control Center tab **performance**  
> Related: [GC_PERF_CORE.md](GC_PERF_CORE.md) · [STATE_AJAX.md](STATE_AJAX.md) · [ARCHITECTURE.md](ARCHITECTURE.md)

## Prinzip

**Erst messen, dann ändern.** Keine zweite Queue-/Fleet-/Game-State-Engine. Railway-Metriken sind optional; die App muss sich selbst erklären.

## Wave 1 (shipped)

| Ticket | Inhalt |
|--------|--------|
| GC-PERF-AUTO-001 | `/api/game-state` call-tree audit (this doc) |
| GC-PERF-AUTO-002 | Always-on recorder, `perf_span`, DB query timing, process metrics |
| GC-PERF-AUTO-003 | Ringbuffer, percentiles, hotspots, pressure + hysteresis, rule diagnosis |
| GC-PERF-AUTO-004 | Admin API + SERVER PERFORMANCE tab |
| GC-PERF-AUTO-005 | Stable poll jitter on `GC.polling` |

## Follow-ups (not Wave 1)

### GC-PERF-AUTO-006 — Load Guard (Phase F)

Defer only non-gameplay work when pressure/critical:

- Stretch ranking recompute intervals
- Skip optional cosmetic / admin panel warmups
- Soften noncritical maintenance bag steps

**Never skip:** resource authority, due queue finish, fleet/combat results, player mutations.

Single source: `perf_intel.get_pressure_state()`.

### GC-PERF-AUTO-007A — Payload / page child spans + spike snapshots (shipped)

Breaks opaque `state_build` (`payload_ms`) into children via `perf_span`:

| Span | Section |
|------|---------|
| `payload.nav_badges` | Nav badge HUD |
| `payload.fleets_hud` | Active fleets / alerts |
| `payload.score` | Score + rank |
| `payload.active_planet` | Visuals + identity |
| `payload.panel` | Buildings/overview panel |
| `payload.notifications` | Unread / toast |
| `payload.liveops` | Server events + live_events |
| `page_context.overview` / `.shipyard` / `.fleet` | SSR page builders |

`payload_ms` is a **parent envelope** (like `handler_ms`) — hotspots/diagnosis prefer children.

**Spike ring:** last ~48 slow requests (`≥ max(GC_PERF_SLOW_MS, 500)` — debug `=0` does **not** flood spikes) as `spikes[]` on admin API + **LETZTE SPIKES** UI (route + top costs + SQL). No always-on full tracing.

### GC-PERF-SQL-HOT-002 — Frequency signatures for N+1

Slow individual statements are not enough to diagnose N+1: 200 queries at 2–4ms each can dominate a request without entering `slow_queries`.

- Sampled requests keep a bounded (max 64 distinct) normalized SQL-signature map: count, cumulative DB time, max statement time. Bind/literal values are removed by `normalize_sql_signature`.
- PostgreSQL timing is attached at the sqlite-compatible `PgCursor` so both `conn.execute` and `cur.execute` are measured exactly once.
- Slow-request spike rows expose the top repeated signatures (max 5 in payload, top 3 rendered) directly under Top Costs.
- This is diagnostic-only process memory; no gameplay state, persistence, or cache authority is introduced.

### GC-PERF-AUTO-007B — Evidence-driven cut (partial)

- Removed double-count: `_load_page_live_context` no longer records `page_context_ms` for live-refresh wall time (was twin of `live_context_ms`).
- True `page_context.*` only on Overview/Shipyard/Fleet builders.
- **Live-safe:** `build_overview_status` / overview rows only when `include_panel` (diet + action_slim used to build then strip).
- `live_context_ms` + `payload_fleets_hud_ms` are **parent envelopes** (like `payload_ms`) — diagnosis prefers children.
- Child spans: `live.hud_reads`, `fleets.dirty_tick` / `.alerts` / `.radar` / `.active` / `.slots`.
- `payload.panel` children: `panel.overview_rows` / `.overview_status` / `.buildings_rows` / `.buildings_delta`.
- **Live cut (evidence):** diet / probe / non-research pages use `get_research_status(include_techs=False)` — queue HUD only; full catalog stays on `/research`, techtree, scoped research `include_panel`.
- Idle poll + persist-only paths call `mark_request_live_refreshed()` so HUD `skip_finish=True` actually skips finish.
- Meta/reward actions (login rewards, battle pass, vote, politics, referrals) use `_hud_only_game_state` — no full `payload.panel`.
- Further cuts only after spike samples show the next child hotspot (N≥20).

### GC-PERF-COMMON-001 — Read-only shell/action hotpaths

Prod evidence: `admin_panel` 4.87s / 1017 SQL and `api_inventory_open_container` 4.09s / 691 SQL; both spent most time in DB-backed live refresh, queue finish and resource sync after no additional gameplay finish was required.

- Control Center shell projects committed player resources/energy read-only; opening `/admin` never owns queue finishing.
- Inventory / Case-Battle post-mutation responses rebuild their global HUD through the canonical read-mostly `game_state` path after the mutation transaction has committed; inventory + battle state are then freshly read.
- `_read_player_live_state_no_writes` reuses the already loaded research + EffectResolver modifier snapshot for storage caps instead of rebuilding the full DB-backed effect stack.
- No gameplay formulas, queue authority or mutation ordering changed.

### GC-PERF-PANEL-SCOPE-001 + GC-WAKE-001 — Idle wake hang

Spike evidence: `api_game_state` p95 ~2s with `panel.buildings_rows` + `hud.research` on every `include_panel=1` (also concurrent TK apply).

- Client wake (`wakeClientAfterHidden`): abort hung diet polls on `tab_visible` / bfcache `pageshow`; clear stuck PJAX; reset `?since=` after long hide; no optimistic `_authLoopAborted` clear.
- Canonical panel fetch sends `panel_page` (+ `panel_tab` on buildings).
- Server builds `buildings_panel` / overview panel slices only for the scoped page; research catalog only for `research`/`techtree` (or unscoped legacy `include_panel`).

### GC-PERF-PANEL-CONN-001 — Buildings panel request conn

Spike evidence: `panel.buildings_rows` ~0.8–1.1s and `sql_count` ~3800 on `include_panel=1&panel_page=buildings` (orphan `db()` opens + PRAGMA×4 per open).

- `get_buildings_panel_rows` / `get_buildings_panel_delta` take request `conn` (+ optional shared `research_levels`).
- Pass-through: `get_research_levels`, `BuildingsPanelContext.for_planet`, `resolve_stage_layout`, `get_game_settings` / queue limit.
- Perf meta: `db_connection_open_count` (Admin spikes show `SQL / opens`).
- No global EffectResolver cache in this ticket — measure first; Research-Time / Panel-Scope-002 follow separately.

### GC-PERF-RESEARCH-TIME-001 — Shared resolver for research catalog times

Spike evidence: `hud.research` ~500–700ms on research `include_panel` (catalog called `get_research_time` per tech → orphan `get_research_levels` / EffectResolver rebuild each time).

- `get_research_time(..., levels=, conn=, resolver=)` — prefer shared resolver; no levels refetch when `resolver=` set.
- `get_research_status` builds **one** EffectResolver for queue start fallback + tech catalog + MAX-queue preview.
- Same pass-through in `summarize_max_queueable_research_jobs`, queue reschedule, technical data table, auto_empire.
- Semantics unchanged (still `EffectResolver.get_research_time_seconds`); Panel-Scope-002 / TK remain separate.

### GC-PERF-PANEL-SCOPE-002 — No unscoped heavy catalogs

Prod evidence: `api_auction_house_bid` ~1.8–2.1s with `panel.buildings_rows≈850` + `overview_rows` because `include_panel=True` without `panel_page` built **all** heavy catalogs.

- Unscoped `include_panel=1` → HUD / lightweight only (no buildings/overview/research/defense/shipyard/exchange/auction catalogs).
- `panel_page` matrix: buildings | research/techtree | defense | shipyard | trader_hub | auction_house | overview.
- Legacy actions map via `_FINISH_SOURCE_PANEL_PAGE` (e.g. auction bid → `auction_house`).
- Perf meta: `panels_built`, `panel_page`, `panel_total_ms` (Admin spikes show `panels=… @page`).
- Out of scope: `finish_fleet` / writer-lock (separate ticket).

### GC-PERF-HUD-READS-001 — HUD read children + shared research levels

Spike evidence: `live.hud_reads` ~80–110ms on slow polls (envelope).

- Child spans: `hud.build_queue` / `hud.research` / `hud.prod` — `live.hud_reads` is parent (diagnosis prefers children).
- One `get_research_levels` shared into `get_research_status(levels=…)` + `get_building_production_per_hour(research=…, conn=…)`.
- Drop duplicate `get_research_modifiers` on the user_id EffectResolver production path.
- Live rates/queues unchanged — same server payloads, fewer duplicate reads.

**Reading spikes:** `db_begin_immediate` as top diagnosis is often **lock wait** (one writer), not BEGIN cost itself — e.g. `api_chat_messages` waiting while `admin_panel` holds a write TX. Prefer spike rows over the aggregate %. `hud.research` ≫100ms on `research_view` is the full tech catalog (include_techs), not diet.

### GC-INFRA-ADMIN-001 — Admin must not rebind leftnav accordion

Admin keeps the game shell sidebar. HUD sync used to call `restoreLeftmenuState(/admin)` and break Infrastruktur expand/nested clicks (GC-849). Skip sidebar restore + role sync while on `/admin`; stop perf auto-refresh on leave.

**Follow-up GC-INFRA-ADMIN-002:** Orphan `body > .gc-hud-select-menu` (default CSS `top:0;left:0`) blocked left/right nav clicks. Park off-screen + `pointer-events:none` until positioned; teardown removes all body menus; accordion closest falls back to `.gc-sidebar`.

### GC-PERF-DEFENSE-SSR-006 — Mode-specific Defense SSR + shared catalog snapshot

Code audit evidence: `/defense` rendered two mutually exclusive heavy surfaces in one request. The Structures path built the complete Defense catalog + locked requirement cards, then also built Troops + Secret Vault state. The Troops tab paid the inverse cost. The Defense catalog additionally reloaded Buildings/Research through `defense_unlocked` / `max_build_amount_for_planet` for individual rows despite already having those snapshots.

- `defense_view` resolves `tab=structures|troops` before heavy page-context construction.
- Structures SSR builds only Defense catalog/queue/locked cards.
- Troops SSR builds only Barracks troops + Secret Vault state.
- Template emits only the active heavy top-level panel.
- Cross-tab clicks fall back to the existing PJAX href when the sibling panel is intentionally absent; no second navigation/state owner.
- Buildable + locked Defense catalogs share one request-local Buildings, Research and Defense-stock snapshot.
- `defense_unlocked` / `max_build_amount_for_planet` keep historical DB fallbacks for standalone callers, but catalog loops pass the shared snapshots.
- New `page_context.defense` child span makes post-deploy p95/SQL evidence visible in the existing Performance Intelligence stack.

Regression: `tests/test_gc_perf_defense_ssr_006.py` + existing Defense single-request-connection test + Sentinel.

### GC-PERF-DIRECTIVES-008 — Directives claim + page-state hotpath

Railway showed `POST /api/imperial-directives/claim` around ~3 s. The route performed three distinct post-click costs:

- mutate/commit the reward,
- build a full `include_panel=True` game-state,
- open another connection and rebuild Imperial Directives state.

The Directives UI already consumes these separately: `state` only feeds `applyActionState()`; `imperial_directives` feeds the page cards.

Fix:

- Claim and Claim-All use `_hud_only_game_state()`; no full panel/catalog build.
- HUD/live-state refresh runs first; authoritative Directives page-state is then rebuilt on the still-open mutation connection so queue-finish progress cannot be overwritten by stale cards.
- `get_imperial_directives_state()` bulk-loads all referenced definitions once instead of one SQL lookup per directive.
- Existing directive validation/generation shares the same bulk definition snapshot for stale checks and category seeding.
- Bulk lookup deliberately retains disabled/weight-0 definitions so already-issued historical directives serialize correctly.

Regression: `tests/test_gc_perf_directives_008.py` + API claim contract + Smoke + Sentinel.

### GC-PERF-NAV-007 — Core navigation + mutation payload hotpath

Production evidence after the Fleet deadline deploy still showed common HTML pages around ~1–2 s and HUD mutation clicks in the multi-second range. Audit found work that was independent of the requested page/action:

- PJAX renders kept the existing shell DOM but `inject_globals()` still rebuilt the full Codex template/client catalog and three persisted user-option reads.
- Codex full render evaluated the complete unlock catalog separately for panel/client/tip surfaces.
- `_payload_from_live_context()` opened fresh score/rank connections although it already owned a request connection.
- lightweight polls and `action_slim` mutation states built universe-wide `player_stats` and then discarded them.
- `action_slim` also built Planet Teaser + Codex and discarded both in `apply_action_state_diet()`.
- mutation state serialized full Battle Pass reward tracks even though claim routes return their updated Battle Pass payload separately.

Fix:

- Codex route-visit ownership moves to the existing page live-state connection, preserving unlock semantics on full + PJAX navigation.
- PJAX skips full Codex and user-option shell rebuilds.
- Full shell options share one DB connection.
- Full Codex computes one unlock snapshot and reuses it across panel, commander tip and client article config.
- score/rank/player-stats reuse the request connection.
- diet/action states do not construct `player_stats`; action state does not construct Planet Teaser or Codex.
- `action_slim` requests Battle Pass without full reward tracks; dedicated Battle Pass mutation payload remains authoritative for the Premium UI.

Regression: `tests/test_gc_perf_core_navigation_007.py` + normal Smoke + Sentinel.

### GC-PERF-PJAX-SHELL-023 — Drop redundant shell DB checkouts on soft navigation

Code audit after the Timekeeper chain found two unconditional context-processor reads that still ran on every PJAX page response even though the browser keeps the existing shell:

- `get_current_user()` opened a fresh connection after `require_login` had already resolved the same player into `g.player`.
- `get_game_settings()` opened another connection although PJAX only consumes `#main-content`; the persistent shell already owns the settings-dependent shell UI.

Fix:

- PJAX template context reuses the authenticated guard snapshot from `g.player`.
- PJAX skips the global `GAME_SETTINGS` reload; domain page builders continue to read settings through their request-owned connection when needed.
- Full-page/auth/landing rendering keeps the historical context behavior.
- Regression makes both global helpers fatal during a PJAX `/buildings` render, proving the soft-navigation context processor cannot regress to those extra pool checkouts.

This is deliberately a connection-pressure cut, not a gameplay cache: no server authority, queue/resource timing, or page-domain state changes.

### GC-PERF-PJAX-VISIT-025 — Repeat route visits stay read-only

The common page live-context still treated every qualifying navigation as a write even after both durable visit records already existed:

- Command Initiation repeated an idempotent `INSERT OR IGNORE` into `player_initiation_progress` for the same `ini_page_seen:*` event.
- The orchestrator marked Initiation as commit-worthy whenever the hook returned without an exception, even when no row/progress changed.
- Codex already performed a read-before-insert, but the orchestrator still marked every route visit as commit-worthy.

Fix:

- `mark_page_seen()` probes the durable event first and only inserts on the first visit.
- Initiation page-visit results expose `recorded` alongside real progress changes.
- Codex route visits return whether an unlock row was actually inserted.
- `_load_page_live_context()` commits visit work only when Initiation/Codex actually changed durable state.
- First-visit unlock/progression semantics remain unchanged; repeated PJAX visits become read-only unless genuine Initiation progress advances.

Regression includes a duplicate-visit INSERT guard and a real repeated PJAX request that must complete without a page-live commit.

### GC-PERF-AUTH-NAV-026 — Reuse auth guard across safe navigation bursts

After the PJAX shell and page connection cuts, protected HTML navigation could still open a separate PostgreSQL connection in `require_login`: the validated player guard row expired after only 2 seconds, shorter than a normal human click interval.

Fix:

- Safe non-API GET/HEAD navigation reuses the validated player guard row for up to 15 seconds.
- API and mutation-facing guard freshness remains 2 seconds.
- Pool-timeout stale fallback remains capped at 30 seconds and safe-navigation only.
- The 15-second navigation window matches the already existing negative ban cache, so this does not extend the effective no-ban cache horizon beyond the current security model.

Regression ages a cached player by five seconds and requires HTML navigation to perform zero player reload checkout; API stale-cache behavior remains strict.

### GC-PERF-NAV-CONN-027 — Read-page routes reuse the live-context connection

Post-Timekeeper audit found several older HTML/PJAX routes still doing `live context -> close -> page-state on a second connection` even though their page builders are read-only.

Fix:

- Combat Simulator, Vote Center, Galactic Politics and Inventory now create one request connection before live-context refresh and pass it through page-state composition.
- Inventory reuses the already resolved live-context planet for its page-level planet identity instead of performing another explicit context-planet read.
- Mutation-bearing surfaces (Auction, Story, Initiation, Referrals qualification, Creator, Planet Evolution) are intentionally excluded and remain separate follow-ups.

Regression structurally requires exactly one route-owned `db()` checkout, `conn=conn` + `close_conn=False` on live context, and the same connection on each page builder.

### GC-PERF-PG-NAV-030 — Real PostgreSQL navigation structural sentinel

SQLite Browser Sentinel cannot expose PostgreSQL round-trip / pool regressions. A dedicated PG16 CI gate now exercises the authenticated core PJAX surfaces twice: first pass warms one-time Codex/Initiation/bootstrap state; second pass records the existing navigation perf headers.

Measured per route:

- `X-GC-Nav-Server-Ms`
- `X-GC-Nav-Sql-Count`
- `X-GC-Nav-Sql-Write-Count`
- `X-GC-Nav-Db-Connections`
- `X-GC-Nav-Db-Query-Ms`

Hard structural budget on the repeated pass: `writes == 0` and `db_connections <= 1`. Wall-clock and SQL counts are printed as diagnostic evidence; route-specific SQL budgets are set only after the first real PG run instead of inventing thresholds.

Core matrix: Overview, Buildings, Research, Shipyard, Defense, Fleet, Galaxy, Empire, Combat Simulator, Inventory, Vote Center and Galactic Politics.

### GC-PERF-PG-WEB-031 — PostgreSQL web concurrency removes single-worker head-of-line blocking

Production still started Gunicorn with a hardcoded `GUNICORN_WORKERS=1` fallback even after the database cutover. That left one gthread process as the global HTTP choke point: one slow request could occupy enough of the process to make unrelated menu navigation feel frozen.

GC-PERF-PG-NAV-030 provides the key counter-evidence against intrinsic page slowness. On real PostgreSQL 16, the repeated PJAX matrix currently measures:

- 12 core routes;
- exactly **1 DB connection per route**;
- **0 writes** on every repeated navigation;
- server time about **113–154 ms**;
- DB query time about **64–88 ms**;
- 168–249 SQL statements depending on page.

So the ordinary PJAX handler is no longer a 5–10 second path in isolation. Production stalls are therefore treated as concurrency / network / contention problems first, not an excuse to add a parallel state engine.

Fix:

- `scripts/docker-entrypoint.sh` loads `.env` through `init_config()` before resolving worker count.
- Worker count comes from the single owner `game.config.get_gunicorn_workers()`.
- SQLite remains one worker by default.
- PostgreSQL defaults to two gthread workers.
- PostgreSQL **Production floors a persisted legacy `GUNICORN_WORKERS=1` to 2**; higher explicit values remain allowed.
- Existing lazy per-process PG pools, maintenance sidecar and queue-worker ownership remain unchanged.
- Railway production must use the private `DATABASE_URL`, never `DATABASE_PUBLIC_URL`, for service-to-database traffic.

Regression covers SQLite default, PostgreSQL default, Production legacy-floor behavior, development override behavior and entrypoint env-loading order.

### GC-PERF-EXPO-RACE-006 — Holding race + mass-launch refresh storm

Post-deploy Railway evidence after GC-PERF-FLEET-DEADLINE-005 exposed two follow-ups:

- Online deadline pass and global Fleet worker could enter the same expedition `holding` resolution concurrently. The final status claim was atomic but happened **after** daily ledger/loot/report side effects. PostgreSQL therefore observed a duplicate `expedition_daily_recorded.movement_id`.
- Mass-expedition success called `applyActionState(..., "fleet_mass_expo_success")` (which already schedules Fleet reconciliation) **and** directly awaited `refreshFleetState()`. Large launches therefore created redundant `/api/fleet/state` requests.

Fix:

- Expedition holding takes a PostgreSQL row lock on the movement before any side effect; the loser waits, observes the new status, and exits.
- `record_expedition_daily_value()` claims its ledger row with `INSERT ... ON CONFLICT(movement_id) DO NOTHING`; only the successful insert advances the daily aggregate.
- Mass-expedition success uses one deferred coalesced Fleet-state reconciliation, matching normal Fleet send.
- Mutation action diet compacts `active_fleets` / `fleet_alerts` to their HUD slices before serialization.

### GC-PERF-FLEET-DEADLINE-005 — No more fleet rows stuck at 0s

Production symptom: mass expeditions could show `RÜCKFLUG 0s` for tens of seconds; expedition reports could also appear late after `HALTEND` elapsed.

Root cause: the poll correctly detected a due movement through `player_fleet_is_dirty()`, but then deferred processing whenever the global Fleet-Worker heartbeat was considered fresh. The worker/maintenance cadence is 60 s and heartbeat freshness can span two intervals, so "worker ran recently" did not mean "worker has seen the deadline that expired after that run".

- No new polling engine or per-fleet timer.
- Existing active Game-State poll remains the trigger.
- Indexed due probe stays read-only and cheap while nothing is due.
- A real due deadline invokes `process_player_due_fleets_now()` regardless of heartbeat freshness.
- The pass owns a separate connection and uses existing per-movement short transactions.
- Online budget defaults: PostgreSQL 256 movements / 900 ms; SQLite 64 / 400 ms, env-overridable.
- Priority for the online pass: returning → holding → outbound, so slot/loot returns and expedition outcome/messages cannot starve behind new arrivals.
- Existing conditional status claims keep races with the global worker idempotent.
- `fleet_tick_ms` continues to measure the actual deadline finish cost.

Regression: `tests/test_gc_perf_fleet_deadline_005.py`, `tests/test_gc_prod_sqlite_stall_001a.py`, `tests/test_gc_nav_fleet_readonly_001.py`.

### GC-PERF-FLEET-HUD-001 — Drawer without mission resolve

Spike evidence: `fleets.active` 70–120ms on slow `/api/game-state` while drawer only needs labels/timers.

- `build_active_fleets_payload` → `list_active_movements(..., enrich_world_target=False)`.
- Light path: JOIN target planet name + `resources.world_key` presentation — **no** per-row `resolve_fleet_target` (debris/pirate/boss scans).
- Full enrich remains default for Fleet page / Overview / Command Map (`list_active_movements` default).
- Live UI unchanged: count, timers, expand list, recall/cancel flags still from movement rows.

### GC-PERF-FEEL-001 — Shell background weight

- `static/img/background.webp` recompressed (~272KB → ~84KB @ 1400w); CSS still WebP primary via `image-set`.

### GC-PERF-AUTO-007 — Evidence-driven optimizations (continued)

Only after live/staging samples prove a hotspot (diet finish, nav badges, N+1 SQL, …).

---

## `/api/game-state` call tree (audit)

```text
GET /api/game-state
├─ before_request
│  ├─ start_request_perf (+ perf_intel concurrent++)
│  └─ _fleet_tick_before_authenticated_request
│     └─ SKIPPED for endpoint api_game_state
├─ api_game_state()
│  ├─ [?since + diet + GC_STATE_DELTA]
│  │  └─ try_diet_poll_early_unchanged → maybe {unchanged:true} (no finish)
│  ├─ _build_game_state_payload
│  │  ├─ diet: finish_source=game_state
│  │  │  └─ _load_page_live_context → read_player_live_state_for_poll
│  │  │     ├─ player_fleet_is_dirty → [?due] process_player_due_fleets_now (bounded short-TX)
│  │  │     ├─ finish_player_due_work  (queue-only conditional safety-net)
│  │  │     └─ update_planet_resources(skip_queue_finish=True)  (write only after real finish)
│  │  ├─ panel: finish_source=game_state_panel
│  │  │  └─ refresh_player_live_state → always finish + resource sync
│  │  └─ _payload_from_live_context
│  │     ├─ HUD: resources, queues slim, fleets, score, nav_badges, live_events, …
│  │     ├─ diet: apply_lightweight_game_state_diet (strip catalogs)
│  │     └─ attach_canonical_server_time
│  └─ [?since] build_delta_game_state → maybe {unchanged:true}
└─ after_request / teardown → finish_request_perf → perf_intel.record_request
```

### Diet vs panel

| | Diet poll | Panel / full |
|---|---|---|
| Query | `GET /api/game-state` (+ `?since=`) | `?include_panel=1` |
| Live path | `read_player_live_state_for_poll` | `refresh_player_live_state` |
| Queue finish | Conditional | Always |
| Resource write | Throttled (`GC_RESOURCE_PERSIST_SEC`) | Always |
| Payload | HUD then strip heavy keys | Full catalogs |

### What runs on diet (typical)

- Queue finish only when due / dirty / pending interval
- Per-player fleet deadline pass only when the indexed dirty probe finds an actually due phase (not a global worker tick)
- Nav badges / live_events / score reads (not ranking recompute)
- Ranking / global fleet / maintenance bag: **maintenance sidecar / cron**, not diet

### Diet strip (`apply_lightweight_game_state_diet`)

Drops (among others): `player_stats`, `building_queue`, `research_queue`, `buildings`, `codex`, `imperial_directives` body, `planet_relocation`, heavy fleet rows. Keeps HUD resources, slim queues, fleets, score, nav badges.

**Battle Pass on diet:** `include_tracks=False` (no `levels` catalog) — claimable_count/ops stay for nav badge + toast. Full tracks on `include_panel` / action payloads / premium SSR.

---

## Metrics model

- **In-memory only** (Wave 1): ringbuffer + minute buckets (60m history)
- No DB writes per request
- Bounded memory; thread-safe short locks
- Process CPU/RSS via optional `psutil`, else stdlib fallbacks (never crash)

### Performance state (not game-state)

`NORMAL → WARM → PRESSURE → CRITICAL` with hysteresis; `RECOVERY` when leaving pressure/critical while metrics improve.

### Slow request classes

| Total | Class |
|-------|-------|
| > 500 ms | slow |
| > 1000 ms | very_slow |
| > 2500 ms | critical |

Log line: `[GC PERF] CRITICAL REQUEST` (+ top component costs).

Legacy detailed line `[GC REQUEST PERF]` remains env-gated (`GC_REQUEST_PERF_DEBUG` / `GC_PERF_DEBUG`).

### Config

| Env | Default | Role |
|-----|---------|------|
| `GC_PERF_INTEL` | `1` | Always-on aggregator |
| `GC_PERF_INTEL_SAMPLE` | `1.0` | Detail span/SQL sample rate |
| `GC_PERF_SLOW_MS` / `GC_REQUEST_PERF_SLOW_MS` | `500` | Slow threshold |
| `GC_PERF_SLOW_QUERY_MS` | `100` | Slow query threshold |
| `GC_REQUEST_PERF_DEBUG` | `0` | Verbose `[GC REQUEST PERF]` logs |

---

## Admin

- Tab: System → **performance**
- API: `GET /api/admin/performance` (`@require_admin_api`)
- Poll interval ~12s (dashboard must stay light)
- Sections: status · diagnose · **spikes** · hot routes · hot components · slow queries · history

## Poll jitter (GC-PERF-AUTO-005)

Singleton `GC.polling` applies a **stable per-tab** jitter of ±12.5% around active/idle/hidden intervals. No second poll engine; `/api/game-state` remains SSoT.
