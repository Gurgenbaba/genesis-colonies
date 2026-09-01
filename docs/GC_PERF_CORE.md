# EPIC Performance Core — Maximum Speed Stack

> Status: ✅ **Core Foundation + Production Postgres cutover** (2026-08-31) · Next: [GC_PG_HIGHSPEED_001.md](GC_PG_HIGHSPEED_001.md)  
> Related: [ROADMAP.md](ROADMAP.md) Phase 7 · [EPICS.md](EPICS.md) EPIC-12 / EPIC-19 · [ARCHITECTURE.md](ARCHITECTURE.md) · [GC_PERF_DB_001_POSTGRES_AUDIT.md](GC_PERF_DB_001_POSTGRES_AUDIT.md)

## Entscheidung

- **Kein PHP-Neubau.** Stack bleibt Python + Flask.
- **PostgreSQL is production-authoritative** after live cutover (2026-08-31). Runbook: [GC-DB-POSTGRES-002-CUTOVER.md](database/GC-DB-POSTGRES-002-CUTOVER.md).
- SQLite remains the local/dev default and a kept volume backup — not the live source of truth.
- Keine Parallel-Systeme (GC-000 Regel 15/17/19).
- Hotpath work continues under **[GC-PG-HIGHSPEED-001](GC_PG_HIGHSPEED_001.md)** (001A Galaxy Bulk first) — fewer roundtrips/writes/locks, not longer timeouts or feature kills.
- After 001A, **[GC-PG-HIGHSPEED-001F](GC_PG_HIGHSPEED_001F.md)** inventories SQLite-era throttles before any PG-aware default unlocks; 001F is docs-only and may run parallel to 001B.

## Status-Einordnung

| Bereich | Status |
|---------|--------|
| Messbarkeit | ✅ |
| PostgreSQL-Treiber und Pool | ✅ live |
| Worker-Infrastruktur | ✅ live |
| Diet-State / Poll-Delta | ✅ Client `?since=` + default-on (**GC-PERF-LIVE-001**); server early-exit (**GC-PERF-STATE-004**) |
| Lazy-Persistierung / Cache / Lasttest-Tool | ✅ Basis |
| PostgreSQL-Schema (alle Tabellen/Migrationen) | ✅ **GC-PERF-PG-SCHEMA-001** |
| Backend-Parität auf leerer PG-DB | ✅ **GC-PERF-PG-PARITY-001** (SQLite + PG Staging; live cutover 2026-08-31) |
| SQLite→Postgres Datenimport | ✅ **GC-PERF-PG-MIGRATE-001** + live cutover |
| Railway Staging + Smoke + Baseline | ✅ cutover smoke; continue via Highspeed gates |
| Production-Cutover | ✅ 2026-08-31 — next: Highspeed-001 |
| Vollständiger `main.js`-Split | 🔄 Scaffold → GC-PERF-JS-002 |
| EffectResolver-Cache | ✅ request-scoped (**GC-PERF-EFFECT-CACHE-001**) |
| Diet early-exit vor Payload-Build | ✅ **GC-PERF-STATE-004** + probe-skip **STATE-005** |
| Threat Net poll cost (probe/notif fingerprint) | ✅ **GC-PERF-RADAR-001** |
| Poll stop/start thrash (hidden+busy) | ✅ **GC-PERF-POLL-THRASH-001** |
| Chat idle poll (panel closed) | ✅ **GC-PERF-CHAT-IDLE-001** |
| PJAX shell globals skip (score/planets) | ✅ **GC-PERF-PJAX-CTX-SHELL-001** |
| Galaxy prefetch gate (concurrency + pause) | ✅ **GC-PERF-GALAXY-PREFETCH-GATE-001** |
| PE PJAX HTML slim + baseline bytes | ✅ **GC-PERF-PJAX-BYTES-HEAVY-001** |

## Zielarchitektur

```text
Browser → CDN/Proxy → Gunicorn Multi-Worker → Flask
                         ├── PostgreSQL (autoritativ)
                         ├── Redis (flüchtig)
                         └── Game-Worker (eine Primary-Instanz)
```

## Messbudgets

Siehe `game.config.get_perf_budgets()` / [ARCHITECTURE.md](ARCHITECTURE.md). Baseline: `python scripts/perf_baseline.py`.

## Ticket-Serie A — Foundation (abgeschlossen)

| Ticket | Status |
|--------|--------|
| GC-PERF-CORE-001 … LOAD-001 | ✅ (JS-001 = Scaffold) |

## Ticket-Serie PERF-AUTO — Automatic Performance Intelligence

| Ticket | Inhalt | Status |
|--------|--------|--------|
| **GC-PERF-AUTO-001…005** | Audit, instrumentation, rolling metrics, admin dashboard, poll jitter | ✅ Wave 1 — [PERFORMANCE.md](PERFORMANCE.md) |
| GC-PERF-AUTO-006 | Load Guard (defer non-gameplay only) | 📋 after evidence |
| **GC-PERF-AUTO-007A** | Payload/page child spans + spike snapshots | ✅ — [PERFORMANCE.md](PERFORMANCE.md) |
| GC-PERF-AUTO-007B | Evidence-driven cuts (page_context double-count fixed) | 🔄 partial — more after live spikes |
| GC-PERF-FEEL-001 | Shell background WebP weight | ✅ |

## Ticket-Serie B — Postgres Cutover

Live cutover 2026-08-31: Postgres authoritative in production. Runbook: [GC-DB-POSTGRES-002-CUTOVER.md](database/GC-DB-POSTGRES-002-CUTOVER.md).

**Next:** PostgreSQL hotpath highspeed — [GC_PG_HIGHSPEED_001.md](GC_PG_HIGHSPEED_001.md) (first code slice **001A Galaxy Bulk**). After 001A, [001F](GC_PG_HIGHSPEED_001F.md) audits SQLite-era throttles while 001B can continue in parallel.

| Ticket | Inhalt | Status |
|--------|--------|--------|
| **[GC-PERF-PG-SCHEMA-001](GC_PERF_PG_SCHEMA_001.md)** | PostgreSQL-Schema & Migration Parity | ✅ |
| **[GC-PERF-PG-PARITY-001](GC_PERF_PG_PARITY_001.md)** | Backend-Parität (kritische Systeme) | ✅ live Postgres |
| **[GC-PERF-PG-MIGRATE-001](GC_PERF_PG_MIGRATE_001.md)** / cutover import | SQLite→Postgres Importer + Live Cutover | ✅ live |
| **[GC-PG-HIGHSPEED-001](GC_PG_HIGHSPEED_001.md)** | PG hotpath highspeed umbrella (001A Galaxy first) | 📋 |
| **[GC-PG-HIGHSPEED-001F](GC_PG_HIGHSPEED_001F.md)** | SQLite-era throttle inventory; KEEP / PG-RETUNE / REMOVE / REPLACE; no default flips | 📋 after 001A, docs-only |
| **GC-PERF-WRITE-MIN-001** | Materialize-on-mutation / rate boundaries | 📋 after 001A–C |
| **GC-PERF-JS-002** | Echter `main.js`-Split (Symbole löschen) | ✅ shipyard + defense page binders; page-scoped script load |
| **GC-PERF-OVERVIEW-TTFB-001** | `g.gc_fleet_hud` / `g.gc_world_boss_*` stash for inject_globals | ✅ |
| **GC-PERF-EFFECT-CACHE-001** | EffectResolver request-scoped Cache | ✅ |
| **GC-PERF-LIVE-001** | Client diet `?since=` + Busy-Poll Fleet/Defense | ✅ |
| **GC-PERF-STATE-004** | Early exit vor diet payload build | ✅ |
| **GC-PERF-STATE-005** | Process-local probe skip when since+unread match (TTL 3s; mutations clear FP) | ✅ |
| **GC-PERF-RADAR-001** | Threat Net: fingerprint on probe/notification; batched bubbles; scoped SQL; diet alert slice; client signature/ticker split | ✅ |
| **GC-PERF-POLL-THRASH-001** | No stop/start on unchanged hidden polls | ✅ |
| **GC-PERF-CHAT-IDLE-001** | Chat message poll slows when panel closed | ✅ |
| **GC-PERF-PJAX-CTX-SHELL-001** | Skip score/rank/HEADER_PLANETS on PJAX | ✅ |
| **GC-PERF-GALAXY-PREFETCH-GATE-001** | Galaxy prefetch concurrency=1 + pause | ✅ |
| **GC-PERF-PJAX-BYTES-HEAVY-001** | PE SSR slim (locked info + history) + baseline | ✅ |
| **GC-INSTANT-QUEUE-FINISH-001** | Optimistic level at timer-zero; idle/landscape no-snap | ✅ |
| **GC-INSTANT-HUD-RATES-001** | SSR production `/h` into resource bar | ✅ |
| **GC-INSTANT-POLL-BOOT-001** | Busy from SSR; first diet = full cadence | ✅ |
| **GC-INSTANT-IDENTITY-FOUC-001** | Critical identity CSS in `<head>` | ✅ |
| **[GC-PERF-FLEET-SEND-001](GC_PERF_FLEET_SEND_001.md)** | Instant fleet send/recall (slim state, no finish on RTT, deferred client refresh) | ✅ |
| **[GC-PERF-PROD-001](GC_PERF_PROD_001.md)** | Production latency floor: `/healthz`, Soft-Off A/B, request wall | ✅ prove + ops |
| **GC-PERF-PROD-002** | Maintenance bag in sidecar process (`run_maintenance_worker.py`); gunicorn free of Soft-On GIL | ✅ |

## Explizit nicht tun (jetzt)

- SQLite-Volume/Datei löschen (Backup / rollback hygiene)
- Blind-SQL-Dump als „Migration“ / naive sqlite→psql dump
- Lock timeouts hochdrehen statt Writes/Contention zu senken
- Features permanent abschalten als Performance-Fix (Autoplay=0 = incident soft-off only)
- Parallel Galaxy-/Presence-/Admin-Systeme neben den Ownern
- SQLite-era throttle knobs blind auf Maximalwerte setzen; 001F classifies first, later micro-tickets measure changes

## Owner

| System | Owner |
|--------|-------|
| DB Backend / Pool | `game/db.py`, `game/db_pg.py` |
| Migration Runner | `migrate.py` + `game/sql_pg_rewrite.py` |
| Game Worker | `game/tick_runner.py`, `scripts/run_game_worker.py` |
