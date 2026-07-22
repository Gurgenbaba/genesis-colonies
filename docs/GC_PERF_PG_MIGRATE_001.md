# GC-PERF-PG-MIGRATE-001 — SQLite→Postgres Datenimporter + Invarianten

> Status: 🔄 **Script + Spec (minimum)** — kein Production-Cutover  
> Epic: EPIC-19 Performance Core · [GC_PERF_CORE.md](GC_PERF_CORE.md)  
> Vorbedingungen: ✅ [GC-PERF-PG-SCHEMA-001](GC_PERF_PG_SCHEMA_001.md) · ✅ [GC-PERF-PG-PARITY-001](GC_PERF_PG_PARITY_001.md) (A–F SQLite; PG Staging wenn URL gesetzt)  
> **Kein Railway-Staging-Cutover · kein produktiver Backend-Switch · SQLite bleibt Default.**

---

## Purpose

Einen **geordneten, row-basierten** SQLite→PostgreSQL-Datenimporter liefern, der:

1. bestehende PG-Schema-Parität voraussetzt (Schema bereits via migrate auf dem Ziel),
2. Tabellen in FK-sicherer Reihenfolge kopiert (kein Blind-SQL-Dump),
3. Identity-/Serial-Sequenzen nach dem Import zurücksetzt,
4. Dry-Run und Row-Count-Reports für Abnahme bereitstellt,
5. klar fehlschlägt, wenn Postgres nicht konfiguriert ist.

Dieses Ticket ist **nicht** der Live-Cutover. Livedaten-Import auf Staging/Prod bleibt bei **GC-PERF-PG-STAGING-001** / **GC-PERF-PG-CUTOVER-001**.

---

## Prerequisites

| Check | Ticket / Hinweis |
|-------|------------------|
| PG-Schema bootstrapt idempotent | SCHEMA-001 grün |
| Kritische Systeme verhalten sich auf leerer PG-DB | PARITY-001 A–F (SQLite immer; PG opt-in) |
| Ziel-DB ist bereits migriert | `python migrate.py` mit `GC_DB_BACKEND=postgres` |
| Quelle ist eine konsistente SQLite-Datei | Default `game/game.db` oder `GC_DB_PATH` |

Ohne Schema auf dem Ziel: Importer **nicht** verwenden (CREATE TABLE gehört nicht hierher).

---

## Table copy order / FK considerations

Owner: `scripts/pg_import_sqlite.py` → `compute_import_table_order()`.

1. Alle User-Tabellen aus der SQLite-Quelle lesen (`sqlite_master`, ohne `sqlite_%`).
2. Skip-Liste (nicht kopieren): `migration_history` (Ziel hat bereits SCHEMA-Migrationen), interne SQLite-Hilfstabellen.
3. FK-Kanten aus `PRAGMA foreign_key_list` → Kind→Eltern.
4. Topologische Sortierung (Eltern vor Kindern). Bekannte Roots (`users`, `players`, Definition-Kataloge, …) erhalten Priorität bei Gleichstand.
5. Tabellen ohne FK-Kante: nach Roots, alphabetisch.
6. Zyklus-Erkennung: klarer Fehler (kein stilles Dump-Bypass). Beim echten Write zusätzlich `session_replication_role = replica` als Sicherheitsnetz (FK-Checks temporär gelockert), danach zurück auf `origin`.

**Invarianten nach Import (manuell / Follow-up-Checks):**

- `users.id == players.id` für alle Spielerzeilen
- Row-Counts Quelle ≈ Ziel (pro Tabelle; Skip-Liste ausgenommen)
- Keine orphan FKs nach Re-Enable der Checks
- Sequenz-`last_value` ≥ `MAX(id)` je Serial-Spalte

---

## Sequence / identity reset

Nach dem Kopieren aller Tabellen:

```sql
SELECT setval(
  pg_get_serial_sequence(quote_ident(table), quote_ident(column)),
  GREATEST(COALESCE((SELECT MAX(id_col) FROM table), 1), 1),
  true
);
```

Owner-Funktion: `reset_postgres_sequences()`. Deckt serial/identity-Spalten über `pg_get_serial_sequence` für importierte Tabellen. Ohne Reset würden neue INSERTs mit bestehenden IDs kollidieren.

---

## Dry-run mode

```text
python scripts/pg_import_sqlite.py --dry-run
python scripts/pg_import_sqlite.py --dry-run --sqlite path/to/game.db
```

Dry-Run:

- braucht **kein** Postgres / keine `DATABASE_URL`,
- listet Import-Reihenfolge,
- zählt SQLite-Zeilen pro Tabelle,
- schreibt keinen Ziel-Write,
- Exit 0 bei erfolgreicher Analyse.

Echter Import:

```text
$env:GC_DB_BACKEND="postgres"
$env:DATABASE_URL="<staging public URL>"
python scripts/pg_import_sqlite.py --sqlite game/game.db
# optional vor dem Copy leeren:
python scripts/pg_import_sqlite.py --wipe --sqlite game/game.db
```

Fehlt `GC_DB_BACKEND=postgres` oder eine Postgres-`DATABASE_URL` / `GC_TEST_POSTGRES_URL`: **klarer Exit mit Fehlermeldung** (kein stiller SQLite-Fallback).

---

## Deliverables

| Artefakt | Rolle |
|----------|-------|
| `docs/GC_PERF_PG_MIGRATE_001.md` | Spec (dieses Doc) |
| `scripts/pg_import_sqlite.py` | Importer (ordered copy, sequences, dry-run, row report) |
| `tests/test_gc_perf_pg_migrate_001.py` | Modul/Order/Dry-Run; PG-Pfad nur mit `GC_TEST_POSTGRES_URL` |

---

## Explizit out-of-scope

- Railway Staging Provisioning / Smoke (**STAGING-001**)
- Production-Wartungsfenster, DNS/Env-Switch, Rollback-Drill (**CUTOVER-001**)
- Default-Backend auf Postgres umstellen
- SQLite-Datei oder Volume löschen
- Blind `pg_dump` / `.sql`-File Replay als „Migration“
- Worker gegen Postgres in Production

---

## Abnahmekriterien (Minimum dieses Tickets)

- [x] Spec-Doc vorhanden und in `GC_PERF_CORE.md` verlinkt
- [x] Importer-Skript: Dry-Run + Ordered Copy + Sequence Reset + Row-Count-Report
- [x] Kein Blind-SQL-Dump
- [x] Klarer Fehler ohne Postgres-URL
- [x] Tests ohne `GC_TEST_POSTGRES_URL` grün (Helpers / Dry-Run)
- [ ] Live-Import gegen Staging-PG (Follow-up mit echter URL; nicht Cutover)
- [ ] Post-Import Invarianten-Suite auf Staging (Follow-up)

---

## Referenz-Docs

- [GC_PERF_CORE.md](GC_PERF_CORE.md)
- [GC_PERF_PG_SCHEMA_001.md](GC_PERF_PG_SCHEMA_001.md)
- [GC_PERF_PG_PARITY_001.md](GC_PERF_PG_PARITY_001.md)
- [GC_PERF_DB_001_POSTGRES_AUDIT.md](GC_PERF_DB_001_POSTGRES_AUDIT.md)
- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md)
