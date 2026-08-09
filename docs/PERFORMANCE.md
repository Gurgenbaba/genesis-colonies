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
│  │  │     ├─ finish_player_due_work  (conditional: due/dirty/throttled)
│  │  │     │  └─ finish_due_work → … → process_fleet_tick (per-player)
│  │  │     └─ update_planet_resources(skip_queue_finish=True)  (throttled persist)
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
- Per-player fleet tick inside finish (not global worker tick)
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
