# GC-PERF-PG-SCHEMA-001 — PostgreSQL Schema & Migration Parity

> Status: ✅ **Abnahme grün** (Staging migrate×2 + bootstrap + live pytest)  
> Epic: EPIC-19 Performance Core · [GC_PERF_CORE.md](GC_PERF_CORE.md)  
> **Kein Production-Cutover in diesem Ticket.**

---

## Problem

`GC_DB_BACKEND=postgres` und Connection-Pool existieren, aber die 95 SQLite-Migrationen starten keine leere PostgreSQL-Datenbank zuverlässig. Ohne Schema-Port ist Live-Betrieb unsicher.

---

## Betroffene Dateien

- `migrate.py`
- `game/sql_pg_rewrite.py` (neu)
- `game/db_pg.py` (Migration-Connection)
- `tests/test_gc_perf_pg_schema_001.py` (neu)
- `docs/GC_PERF_CORE.md` / dieses Doc

**Nicht bearbeiten:** Production-Env, SQLite-Livedaten, Datenimporter (→ MIGRATE-001), `main.js`-Split.

---

## Anforderungen

1. SQLite-Migrations-SQL in Postgres-taugliches SQL übersetzen (häufige Idiome).
2. `migrate.py` unterstützt `GC_DB_BACKEND=postgres` + `DATABASE_URL`.
3. **Core-Bootstrap** (`game/schema_bootstrap.py`): leere PG bekommt `users`/`players`/`planets`/… vor Migration `006+` (entspricht SQLite-`init_db`).
4. Leere Postgres-DB vollständig bootstrappen (alle Migrationen).
5. Zweiter `python migrate.py`-Lauf ist idempotent (keine Fehler).
6. SQLite-Pfad unverändert (Dev-Default).
7. Ohne `DATABASE_URL` klarer Fehler — kein stiller Fallback auf SQLite.
8. **`init_db()` auf Postgres** seeden nur (Admin/Settings) — kein SQLite-`AUTOINCREMENT`-DDL; Schema bleibt bei migrate + bootstrap.
9. Runtime-Adapter (`db_pg`) rewritten SQLite-Idiome (`INSERT OR IGNORE`, `AUTOINCREMENT`, PRAGMA-Skip) + `lastval()` für `lastrowid`.
10. `ensure_*`-Schema-Helper nutzen `table_columns` statt `PRAGMA table_info`.
11. **`planets.dna_seed` → BIGINT** auf Postgres (`ensure_postgres_i64_columns` + Rewriter), weil Seeds den vollen signed-64-bit-Bereich nutzen (SQLite-`INTEGER` ist bereits i64).

### Zu behandelnde Idiome

```text
PRAGMA → skip
AUTOINCREMENT / INTEGER PRIMARY KEY AUTOINCREMENT
INSERT OR IGNORE / INSERT OR REPLACE
BEGIN IMMEDIATE → BEGIN
datetime('now') / strftime(...)
REAL → DOUBLE PRECISION (wo nötig)
? bleibt über db_pg-Rewrite zur Laufzeit; Migrationen nutzen meist Literale
```

---

## Akzeptanzkriterien

- [x] `GC_DB_BACKEND=postgres DATABASE_URL=… python migrate.py` erzeugt Schema
- [x] Zweiter Lauf: „Alle Migrationen sind bereits angewendet“ / keine Fehler
- [x] Unit-Tests für Rewriter (ohne Live-Postgres)
- [x] Optional: `GC_TEST_POSTGRES_URL=… pytest tests/test_gc_perf_pg_schema_001.py -v` inkl. Live-Migrate
- [ ] SQLite `python migrate.py` Regression grün (lokal nach Env-Reset)
- [x] Keine Production-Variablen geändert
- [x] `bootstrap_application` auf Staging-Postgres OK
- [x] `scripts/pg_schema_accept.py` → `acceptance probe: OK`

## Live-Abnahme (leere Staging-Postgres)

**Nicht** Production-`DATABASE_URL` verwenden. Lokal nur Public-URL der wegwerfbaren Staging-DB.

```powershell
$env:GC_DB_BACKEND="postgres"
$env:GC_TEST_POSTGRES_URL="<DATABASE_PUBLIC_URL>"
$env:DATABASE_URL=$env:GC_TEST_POSTGRES_URL
$env:APP_ENV="development"
$env:GC_SKIP_MIGRATION_CHECK="1"

python -c "import os; print('backend=', os.getenv('GC_DB_BACKEND')); print('url_set=', bool(os.getenv('DATABASE_URL')))"
python scripts/pg_schema_accept.py
```

Das Skript führt aus: migrate → migrate (Idempotenz) → Inventar → Bootstrap → Live-pytest. Passwörter werden nicht geloggt.

Danach SQLite-Regression (Env zurücksetzen):

```powershell
Remove-Item Env:GC_DB_BACKEND -ErrorAction SilentlyContinue
Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
Remove-Item Env:GC_TEST_POSTGRES_URL -ErrorAction SilentlyContinue
python -m pytest tests/test_gc_perf_core_001.py tests/test_gc_perf_db_002.py tests/test_gc_perf_pg_schema_001.py tests/test_persistence.py -q
```

---

## Referenz-Docs

- [ ] [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md)
- [ ] [GC_PERF_CORE.md](GC_PERF_CORE.md)
- [ ] [GC_PERF_DB_001_POSTGRES_AUDIT.md](GC_PERF_DB_001_POSTGRES_AUDIT.md)

---

## Nächstes Ticket nach Abnahme

**GC-PERF-PG-PARITY-001** — Backend-Parität auf leerer PG-DB — [Spec](GC_PERF_PG_PARITY_001.md) (Block A gestartet).
