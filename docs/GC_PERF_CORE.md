# EPIC Performance Core — Maximum Speed Stack

> Status: ✅ **Core Foundation abgeschlossen** (nicht Production-Cutover)  
> Related: [ROADMAP.md](ROADMAP.md) Phase 7 · [EPICS.md](EPICS.md) EPIC-12 / EPIC-19 · [ARCHITECTURE.md](ARCHITECTURE.md) · [GC_PERF_DB_001_POSTGRES_AUDIT.md](GC_PERF_DB_001_POSTGRES_AUDIT.md)

## Entscheidung

- **Kein PHP-Neubau.** Stack bleibt Python + Flask.
- **Kein Production-Cutover auf Postgres**, solange Schema-Port, Parität und Datenimport nicht grün sind.
- SQLite bleibt Default und Live-Wahrheit bis Staging + Cutover-Checkliste.
- Keine Parallel-Systeme (GC-000 Regel 15/17/19).

## Status-Einordnung

| Bereich | Status |
|---------|--------|
| Messbarkeit | ✅ |
| PostgreSQL-Treiber und Pool | ✅ vorbereitet |
| Worker-Infrastruktur | ✅ vorbereitet |
| Diet-State / Poll-Delta | ✅ Client `?since=` + default-on (**GC-PERF-LIVE-001**); server early-exit (**GC-PERF-STATE-004**) |
| Lazy-Persistierung / Cache / Lasttest-Tool | ✅ Basis |
| PostgreSQL-Schema (alle Tabellen/Migrationen) | ✅ **GC-PERF-PG-SCHEMA-001** |
| Backend-Parität auf leerer PG-DB | 🔄 A/B/C/D ✅ · E–F → **GC-PERF-PG-PARITY-001** |
| SQLite→Postgres Datenimport | ❌ → GC-PERF-PG-MIGRATE-001 |
| Railway Staging + Smoke + Baseline | ❌ |
| Production-Cutover | ❌ |
| Vollständiger `main.js`-Split | 🔄 Scaffold → GC-PERF-JS-002 |
| EffectResolver-Cache | ✅ request-scoped (**GC-PERF-EFFECT-CACHE-001**) |
| Diet early-exit vor Payload-Build | ✅ **GC-PERF-STATE-004** |

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

## Ticket-Serie B — Postgres Cutover (offen)

Reihenfolge verbindlich:

```text
Schema-Port
→ Postgres-Parität
→ Datenimporter
→ Railway-Staging
→ Lasttest
→ Backup + Wartungsfenster
→ Production-Cutover
→ Beobachtung
→ main.js wirklich extrahieren (GC-PERF-JS-002)
```

| Ticket | Inhalt | Status |
|--------|--------|--------|
| **[GC-PERF-PG-SCHEMA-001](GC_PERF_PG_SCHEMA_001.md)** | PostgreSQL-Schema & Migration Parity | ✅ |
| **[GC-PERF-PG-PARITY-001](GC_PERF_PG_PARITY_001.md)** | Backend-Parität auf leerer PG-DB (kritische Systeme) | ✅ A/B/C/D · 📋 E–F |
| **GC-PERF-PG-MIGRATE-001** | SQLite→Postgres Importer + Invarianten | 📋 |
| **GC-PERF-PG-STAGING-001** | Railway Staging + Worker + Smoke | 📋 |
| **GC-PERF-PG-BASELINE-001** | SQLite vs PG Staging Metriken | 📋 |
| **GC-PERF-PG-CUTOVER-001** | Wartungsfenster, Import, Rollback-Plan | 📋 |
| **GC-PERF-JS-002** | Echter `main.js`-Split (Symbole löschen) | 📋 |
| **GC-PERF-EFFECT-CACHE-001** | EffectResolver request-scoped Cache | ✅ |
| **GC-PERF-LIVE-001** | Client diet `?since=` + Busy-Poll Fleet/Defense | ✅ |
| **GC-PERF-STATE-004** | Early exit vor diet payload build | ✅ |

## Explizit nicht tun (jetzt)

- Production `GC_DB_BACKEND=postgres` umschalten
- SQLite-Volume/Datei löschen
- Produktiven Multi-Worker ohne Schema-Parität
- Blind-SQL-Dump als „Migration“

## Owner

| System | Owner |
|--------|-------|
| DB Backend / Pool | `game/db.py`, `game/db_pg.py` |
| Migration Runner | `migrate.py` + `game/sql_pg_rewrite.py` |
| Game Worker | `game/tick_runner.py`, `scripts/run_game_worker.py` |
