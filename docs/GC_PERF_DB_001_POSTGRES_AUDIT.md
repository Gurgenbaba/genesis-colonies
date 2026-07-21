# GC-PERF-DB-001 — PostgreSQL-Kompatibilitätsaudit

> Epic: [GC_PERF_CORE.md](GC_PERF_CORE.md)  
> Status: ✅ Audit complete — Implementierung in **GC-PERF-DB-002**  
> Datum: 2026-07-21

## Ziel

Inventar aller SQLite-spezifischen Patterns, die einer PostgreSQL-Migration im Weg stehen. **Kein Schema-Rewrite in diesem Ticket.**

## Zusammenfassung

| Kategorie | Schwere | Hot-Path? | Priorität für DB-002 |
|-----------|---------|-----------|----------------------|
| `game/db.py` Schema-Helpers (`sqlite_master`, `PRAGMA`) | Hoch | Ja (viele Call-Sites) | P0 — portable Helpers |
| Connection/`BEGIN IMMEDIATE`/Writer-Mutex | Hoch | Ja | P0 — Postgres BEGIN + row locks |
| `?` Placeholders (psycopg braucht `%s`) | Hoch | Ja | P0 — Adapter in `db()` |
| Migrationen: `AUTOINCREMENT`, `INSERT OR IGNORE/REPLACE` | Hoch | Bootstrap | P1 — dual-path / rewriter |
| Runtime `PRAGMA table_info` außerhalb `db.py` | Mittel | Teilweise | P1 — auf `table_columns()` umstellen |
| `sqlite_master` außerhalb `db.py` | Mittel | Selten | P1 — auf `table_exists()` |
| SQLite-Funktionen in SQL (`IFNULL`, `strftime`, …) | Mittel | Gemischt | P2 — Query-Audit Hot-Paths |
| `migrate.py` rein SQLite | Hoch | Deploy | P1 — Postgres migrate path |

## 1. Owner-Layer (`game/db.py`)

Bereits vorbereitet:

- `GC_DB_BACKEND` / `get_db_backend()`
- `begin_write_transaction()` Branch `BEGIN` für postgres
- `lock_planet_for_update()` / `lock_player_for_update()` (`FOR UPDATE`)
- `describe_db_connection()`, `DATABASE_URL` detection

Noch SQLite-only:

| Symbol | Pattern |
|--------|---------|
| `db()` | `sqlite3.connect` + `PRAGMA …` |
| `table_exists` / `index_exists` | `sqlite_master` |
| `table_columns` | `PRAGMA table_info` |
| Writer mutex | Prozess-lokal (bei Postgres unnötig / schädlich für Multi-Worker) |

**Empfehlung DB-002:** Helpers backend-aware; Mutex nur bei `sqlite`.

## 2. Runtime `sqlite_master` / `PRAGMA` (außerhalb db.py)

Call-Sites die auf portable Helpers umgestellt werden sollten:

| Modul | Pattern |
|-------|---------|
| `game/admin.py`, `game/admin_universe_reset.py` | `sqlite_master` table list |
| `game/galactic_diplomacy/*`, `game/galactic_directives/definitions.py` | `sqlite_master` + `PRAGMA table_info` |
| `game/activity_xp.py`, `game/expedition_events.py` | `sqlite_master` existence |
| `game/shipyard_queue.py`, `game/defense.py`, `game/alliance.py` | `PRAGMA table_info` |
| `game/vote_rewards.py`, `game/options.py`, `game/account_email.py` | `PRAGMA table_info` |
| `game/referrals.py`, `game/planet_evolution/*` | `PRAGMA table_info(planets/users)` |
| `migrate.py` | `PRAGMA journal_mode/foreign_keys/busy_timeout` |

## 3. Migrationen (`migrations/*.sql`)

Häufige SQLite-Idiome (Counts aus Repo-Scan):

- `AUTOINCREMENT` / `INTEGER PRIMARY KEY` — Postgres: `SERIAL` / `GENERATED … AS IDENTITY`
- `INSERT OR IGNORE` / `INSERT OR REPLACE` — Postgres: `ON CONFLICT`
- `CREATE TABLE IF NOT EXISTS` — meist portabel
- Seed-Migrations mit SQLite-spezifischen Defaults

**Strategie DB-002 (gewählt):** Runtime-Adapter zuerst (App läuft gegen Postgres mit portiertem Schema). Migration-Runner bekommt Postgres-Zweig; bestehende `.sql` bleiben SQLite-Quelle für Dev; Produktions-Postgres nutzt übersetzte/gespiegelte Schema-Bootstrap-Phase (kein Big-Bang Rewrite aller 90+ Files in einem Ticket).

## 4. SQL-Dialekt in Game-Logik

Zusätzlich zu Schema-Helpers prüfen Hot-Paths in DB-002:

- `IFNULL` → `COALESCE` (oft schon `COALESCE`)
- `GROUP_CONCAT` → `string_agg`
- Boolean als `0/1` INTEGER vs Postgres `BOOLEAN`
- Timestamps als REAL/epoch vs `TIMESTAMPTZ` — GC speichert meist epoch floats → weiter `DOUBLE PRECISION`

## 5. Deploy-Constraints

| Umgebung | Heute | Nach DB-002 |
|----------|-------|-------------|
| Local Dev | SQLite default | SQLite default |
| Railway (aktuell) | SQLite Volume, 1 Writer | Optional Postgres Service |
| Multi-Worker Gunicorn | Blockiert durch SQLite | Erfordert `GC_DB_BACKEND=postgres` |

`docs/ARCHITECTURE.md` / README warnen bereits: Postgres-Service nicht linken, bis Backend shipped.

## 6. Test-Plan für DB-002

- Unit: placeholder rewrite, `table_exists`/`table_columns` postgres branch (mock oder skip ohne `DATABASE_URL`)
- Integration (optional CI job): `GC_DB_BACKEND=postgres` + Testcontainer
- Regression: gesamte Suite weiter gegen SQLite

## 7. Nicht-Ziele dieses Audits

- Kein Connection-Pool hier
- Keine Worker-Trennung (→ GC-PERF-WORKER-001)
- Kein Redis

## Ergebnis

Audit abgeschlossen. **Nächster Schritt:** GC-PERF-DB-002 implementiert `db()` + portable Schema-Helpers + Pool; Call-Sites schrittweise auf `table_exists`/`table_columns`/`column_exists` umstellen (Dead-Code-frei, Regel 19).

---

## 8. Nach SCHEMA-001 — verbleibende Runtime-Queries (nicht Migrations-DDL)

Stand nach GC-PERF-DB-002 / SCHEMA-001-Rewriter. Diese Stellen blockieren **nicht** zwingend den leeren Schema-Bootstrap, müssen aber vor/mit **GC-PERF-PG-PARITY-001** portiert oder hinter `table_exists`/`table_columns` gelegt werden:

| Bereich | Pattern | Owner-Hinweis |
|---------|---------|---------------|
| `game/messages.py` | `json_extract(metadata_json, …)` | Postgres: `metadata_json::jsonb ->>` / `jsonb_path` |
| `game/ranking.py` | `strftime('%s','now')` in SQL | `EXTRACT(EPOCH FROM NOW())` oder Python `time.time()` |
| `game/codex.py` | `datetime('now')` in INSERT | `NOW()` / epoch |
| `game/timekeeper.py` | `INSERT OR IGNORE` Runtime | `ON CONFLICT DO NOTHING` |
| Viele Module | direkte `PRAGMA table_info` / `sqlite_master` | auf `game.db.table_columns` / `table_exists` umstellen |
| `game/options.py`, `models.py` | Runtime-`CREATE TABLE … AUTOINCREMENT` | nur SQLite-Bootstrap; Postgres nutzt Migrationen |

**PRAGMA-Policy (SCHEMA-001):** Nur SQLite-Steueranweisungen (`journal_mode`, `foreign_keys`, `busy_timeout`, …) werden beim Migrate übersprungen — PostgreSQL erzwingt FKs nativ. Schema-relevante DDL darf nicht still verschwinden.

Live-Abnahme leere Staging-DB: `python scripts/pg_schema_accept.py` (siehe [GC_PERF_PG_SCHEMA_001.md](GC_PERF_PG_SCHEMA_001.md)).
