# GC-PG-HIGHSPEED-001 — PostgreSQL Hotpath Highspeed (Umbrella)

> Status: 📋 Master-Doc · First implement slice: **001A Galaxy Bulk** (not started)  
> Epic: EPIC-19 Performance Core · Related: [GC_PERF_CORE.md](GC_PERF_CORE.md) · [PERFORMANCE.md](PERFORMANCE.md) · Cutover: [database/GC-DB-POSTGRES-002-CUTOVER.md](database/GC-DB-POSTGRES-002-CUTOVER.md)  
> Incident context: live PG cutover 2026-08-31 · hotfixes #131 / #132 / #133 on `main`

---

## Goal

Genesis Colonies on PostgreSQL must perform **at least as well as** the previous optimized SQLite production path while preserving **all** gameplay and admin functionality.

- PostgreSQL remains **authoritative**. No SQLite fallback. No dual live backends.
- **No disabling features** as a permanent performance solution (incident soft-off only, time-boxed).
- Optimization principle: remove unnecessary **roundtrips**, **writes**, **connection churn**, and **lock contention**. Do **not** weaken transactional correctness for real mutations.

> PostgreSQL removed the global SQLite writer bottleneck. Event-driven / lazy state removes the remaining unnecessary work.

---

## Non-goals / hard rules

| Do | Do not |
|----|--------|
| Keep atomic short TXs for spend / queue / fleet send / shop / WB damage | Raise `GC_PG_LOCK_TIMEOUT` to hide contention |
| Bulk SELECT + Python maps | Per-planet N+1 query storms |
| Soft-skip / out-of-band presence & metrics | Block gameplay HTTP on `last_seen` / `runtime_state` telemetry |
| Cache admin telemetry snapshots | Idle Admin Performance = thousands of SQL / 15s |
| Measure pool sizes | Blind `GC_PG_POOL_MAX` inflation |

**Locks stay** where gameplay needs them. **Unneeded locks and writes leave** hotpaths.

---

## Baseline (post-cutover evidence)

Observed after live PG + #131–#133 (Admin Perf / spikes; rough):

| Hotpath | Observed (rough) | Notes |
|---------|------------------|-------|
| Galaxy GET | ~500 SQL, **100+ DB opens**, multi-second | Dominant network RTT tax |
| `/api/game-state` | ~1.5–3s+ diet; spikes with writes | Chatty + optional writes |
| Presence `players.last_seen` | Lock wait → hang (pre-#133) | #133: 250ms local + soft-skip |
| Initiation visit | `InFailedSqlTransaction` cascades | #131/#133: rollback + SAVEPOINT |
| Admin Performance idle | ~3300 SQL / ~15s | Self-load; do not “delete the panel” |
| World Boss maint stage | ~1.4s `manage_tx=1` | Monolith TX |
| Ranking dirty | 1 dirty → rewrite **128** ranks ~1.6s | Set-based rewrite needed |
| Bootstrap | ~20s pool thread stop noise | One-shot seed without `close_pool()` |

#133 (`f2d47d0`): presence soft-skip, initiation SAVEPOINT, `table_exists` / `galaxy_max` caches — **incident relief**, not Highspeed complete.

---

## Acceptance gates (umbrella)

| Hotpath | Acceptance |
|---------|------------|
| Galaxy | SQL **&lt;100** (stretch **&lt;50**); DB opens **≈1** request connection; **p95 &lt;1s** |
| `/api/game-state` | later **p50 &lt;250ms**, **p95 &lt;750ms** |
| Pure game-state poll | **0** DB writes |
| Presence | **0** user-visible lock wait on HTTP |
| Admin Perf idle | **near-zero** background DB load (cached snapshot) |
| Maintenance vs HTTP | **no multi-second** row-lock stalls on player requests |
| Features | **100% preserved** (WB, ranking, admin, fleets, events, …) |

---

## Slice roadmap

```text
001A Galaxy Bulk          ← FIRST implement slice
  ├─→ 001F SQLite Legacy Throttle Audit (docs only; may run parallel with 001B)
  ↓
001B game-state zero-write
  ↓
001C Presence / hot-row removal (prefer player_presence table)
  ↓
001D Admin Performance snapshot
  ↓
001E Worker non-blocking ownership (pg_try_advisory_lock / short TX)
```

Deploy + measure after **each code slice**. No big-bang. **001F does not flip defaults**; it inventories SQLite-era throttles and feeds later micro-tickets.

### 001F — SQLite Legacy Throttle Audit

Companion: **[GC_PG_HIGHSPEED_001F.md](GC_PG_HIGHSPEED_001F.md)**.

001A–E remove hotpath roundtrips/writes/lock contention. 001F answers the separate question: **which conservative limits exist because Genesis was protecting SQLite's single-writer path, and which remain valid under PostgreSQL?**

Classification is fixed to **KEEP / PG-RETUNE / REMOVE / REPLACE**. Every future REMOVE/RETUNE needs its own measured micro-ticket; 001F itself is docs/inventory only. It starts after 001A and may run in parallel with 001B.

### Deferred (separate tickets)

| Ticket | Scope |
|--------|--------|
| **GC-PERF-WRITE-MIN-001** | Resource materialize-on-mutation; rate-change boundaries; drop periodic poll persist |
| **GC-PG-HIGHSPEED-002** | `EXPLAIN ANALYZE` top queries; real missing indexes; Buildings/Research N+1; measured pool tuning |
| **GC-PG-HIGHSPEED-001F1** | PG-aware Autoplay defaults; remove pure writer-yield on PG only after Soft-On measurement |
| **GC-PG-HIGHSPEED-001F2** | Verify backend-only mutex/busy-timeout behavior; Flask/Gunicorn/pool defaults after 001E |
| Bootstrap `close_pool()` | One-shot entrypoint seed — deploy restart hygiene (can ship as tiny 001A-adjacent or 001E prep) |
| Ranking set-based rewrite | Prefer under **001E** or dedicated micro-ticket after 001A |
| World Boss short TX | Prefer under **001E** (monolith → per-attack commits) |
| LiveOps `no_window` ≠ `error` | Logging hygiene (P2) |

### OUT OF SCOPE for **HIGHSPEED-001A**

- Resource materialize-on-mutation redesign  
- Production rate-boundary architecture  
- Broad index redesign  
- Generic prepared-statement work  
- Pool tuning by guesswork  
- Feature removal  
- World Boss / Ranking / Admin / Presence table migration (later slices)
- SQLite-era throttle/default changes (inventory only in **001F**, runtime changes later)

---

## Target architecture (polls vs mutations)

**Read-mostly (should not mutate just because the player looks):**

```text
GET /api/game-state          → 001B (zero-write poll)
GET /galaxy composition      → 001A list_system writes=0
  (page shell materialize via _load_player_view_with_resources → WRITE-MIN / later)
GET /buildings · /research · /fleet · /ranking · …
```

**Write on real state change (short TX, one connection):**

```text
queue start · spend · fleet send · shop · WB attack · message send
event materialize · due fleet settle · rate-boundary materialize
```

Client may animate between authoritative snapshots; **server reconstructs truth** from timestamps + rates (Ferdi / lazy projection). Client never authors economy math.

---

## GC-PG-HIGHSPEED-001A — Galaxy Bulk (first code slice)

### Status

📋 Spec only — **no Galaxy code in this doc PR**.

### Why first

Live evidence: Galaxy **~500 SQL + 100+ opens** is the clearest PostgreSQL network-RTT failure mode. Fixing it unlocks perceptible page speed without touching mutation semantics.

### Owner

| Role | Module |
|------|--------|
| Primary | `game/galaxy.py` (`list_system`, nav, slot composition) — CORE_ARCHITECTURE §17 |
| Route only if needed | `app.py` `galaxy_view` wiring (pass/reuse request `conn`) |
| Conn helper only if needed | `game/db.py` (no second galaxy engine) |
| Tests | `tests/test_gc_pg_highspeed_001a.py` |
| Doc | this file |

**Max 3–5 product files + tests + this doc.** No architecture shuffle for filenames. No parallel galaxy module.

### Today (anti-pattern)

```text
System load
  → per planet: owner / alliance / activity / protection / …
  → many orphan db() checkouts
  → ~500 statements, 100+ opens
```

### Target

```text
ONE request connection
  → bulk: system planets
  → bulk: players
  → bulk: alliances
  → bulk: protection / activity / other required metadata
  → Python maps by id
  → serialize (same response shape)
```

Prefer **several clear bulk queries** over one unmaintainable mega-JOIN. **Zero writes** on the **`list_system` composition path** (see gate scope below).

### Write-free `list_system` path (required for 001A)

**Gate scope:** `writes=0` applies to **`list_system` / Galaxy slot composition** (debris + enrichers), **not** the full HTML `/galaxy` page shell.

Today the page route (`galaxy_view` → `_load_player_view_with_resources`) can still write via `refresh_player_live_state` / `update_planet_resources`, and empty-universe bootstrap via `ensure_asteroids_present`. Those shell/materialize writes stay **out of 001A** (→ **WRITE-MIN-001** / later Highspeed slices). Do not expand 001A to make the whole page route write-free.

Today `get_debris_for_system()` calls `expire_due_debris_fields(...)` on the **read** path and can physically `DELETE` expired debris during Galaxy composition. That conflicts with **semantics frozen** + **acquisition-only change** + `list_system` `writes=0`.

**001A rule:**

```text
Visible debris semantics unchanged
  → expired fields are filtered out of the response (not shown)
  → NO physical DELETE / expire mutation on list_system / get_debris_for_system

Physical cleanup
  → only the existing maintenance debris stage
     (fleet_worker post-maint → expire_due_debris_fields)
```

Players must still **not see** expired debris on Galaxy. Persistence cleanup stays on the worker — Galaxy does not become a second expire owner.

### Semantics frozen

Galaxy must still show the same facts as today (no gameplay change):

- Planets / commanders / coordinates  
- Activity / inactivity presentation  
- Alliance  
- Protection / attackability gates already in response  
- Expedition / POI / pirate / debris fields as currently **visible** (expired hidden; no read-path DELETE)  
- Fleet / spy / action affordances already in response  
- Existing i18n / UI payload keys  

Only **data acquisition** is batched (plus the debris read/expire split above so `list_system` is write-free).

### Test gates (001A)

Structural (CI-stable), not flaky wall-clock. Measure around **`list_system(...)`** (or an equivalent composition entry that excludes page-shell materialize):

```text
Galaxy response parity: PASS
Postgres path: PASS (when GC_TEST_POSTGRES_URL / dual path available)

SQL statements:     required < 100   (stretch < 50)
DB connection opens: required <= 3   (target 1)
Writes on list_system path: 0
  including: no expire_due_debris_fields / DELETE from get_debris_for_system
  NOT required (001A): zero writes from _load_player_view_with_resources /
                       refresh_player_live_state / ensure_asteroids_present
Repeated per-planet owner/alliance/score/protection/pirate-profile queries: 0

No: LockNotAvailable · InFailedSqlTransaction · deadlock · pool exhaustion
```

Fixtures / cases:

- empty system  
- 1 planet  
- multiple players  
- same alliance / different alliances  
- inactive player  
- protected player  
- denser populated system  
- system with **expired** debris row still in DB → composition hides it, row remains until maint expire  

Example assertions:

```python
assert sql_count < 100
assert connection_count <= 3
assert write_count == 0  # list_system / composition only
```

### Implementation notes (for the agent that codes 001A)

1. Start from `list_system` + callers; pass `conn` everywhere; kill orphan `db()` / `get_galaxy_max()` without conn on this path.  
2. Prefetch maps once per request; slot loop becomes pure CPU.  
3. Primary N+1 hotspots to collapse: per-slot pirate AI profile, noob protection, planet score, and other slot enrichers — these dominate the ~500 queries.  
4. `get_debris_for_system`: stop calling `expire_due_debris_fields` on composition; filter `expires_at <= now` (or equivalent) in the SELECT / Python. Maint worker remains sole physical expire owner.  
5. Do **not** pull page-shell resource materialize / asteroid bootstrap into 001A to chase a full-route `writes=0`.  
6. Reuse existing owners (`alliance.are_players_allied` → batch variant **in alliance owner** if needed — no duplicate alliance truth).  
7. Keep Regel 19: extend owner, delete replaced per-slot query helpers if unused.  
8. Measure with existing request perf (`sql_count` / `db_connection_open_count`) — do not invent a second metrics stack.

### Done when

- [ ] Gates above green on SQLite CI path; PG when URL set  
- [ ] `list_system` write_count == 0 (debris expire only on maint)  
- [ ] Production Admin spike: Galaxy SQL &lt;100, opens ≈1–3, p95 trending &lt;1s  
- [ ] No feature / response regression called out in Galaxy contract tests  

---

## Ops (post-cutover, until Highspeed lands)

| Knob | Guidance |
|------|----------|
| `GC_INACTIVE_AUTOPLAY_ENABLED=0` | Incident soft-off only — re-enable after 001E / write-min |
| `GC_PG_LOCK_TIMEOUT=2s` | Fail fast; do **not** raise to 30–60s |
| `GC_PG_POOL_MAX` | Measure; prefer ~8–12 web + small worker pool later (002) |
| Admin Performance tab | Prefer closed under pressure until 001D |
| `ANALYZE;` | Run once after bulk import / cutover on Postgres |

---

## Related shipped hotfixes

| PR | What |
|----|------|
| #131 | TX rollback after initiation failure; `runtime_state` SAVEPOINT; case-battles ORDER BY |
| #132 | Diet nav directives `read_only` (smoke unblock) |
| #133 | Presence 250ms soft-skip; initiation SAVEPOINT; schema/`galaxy_max` caches |

---

## Next action

1. Review/merge this master doc.  
2. Implement **only** `GC-PG-HIGHSPEED-001A` (Galaxy Bulk) against the gates above.  
3. Deploy + measure 001A. Then open **001B** and the docs-only **001F** audit lane; runtime throttle unlocks remain separate micro-PRs.
