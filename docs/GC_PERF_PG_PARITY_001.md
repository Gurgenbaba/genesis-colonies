# GC-PERF-PG-PARITY-001 — Backend-Parität auf leerer PostgreSQL-DB

> Status: ✅ Block A–F (SQLite grün; PG wenn `GC_TEST_POSTGRES_URL`)  
> Epic: EPIC-19 Performance Core · [GC_PERF_CORE.md](GC_PERF_CORE.md)  
> Vorbedingung: ✅ [GC-PERF-PG-SCHEMA-001](GC_PERF_PG_SCHEMA_001.md)  
> **Kein Livedaten-Import · kein Production-Cutover · kein produktiver Worker gegen Postgres.**  
> **Lokal Default bleibt SQLite (`game/game.db`). Kein lokales Docker-Postgres.**  
> **Postgres-Parität nur in eigener Shell mit `GC_TEST_POSTGRES_URL` (Railway Staging).**

---

## Problem

Schema-Port ist grün, aber Verhaltensparität (Auth, Queues, Fleet, …) zwischen SQLite und PostgreSQL ist noch nicht bewiesen. Typische Risiken: `lastrowid`, Integrity-Errors, Booleans, NULL-Sort, `INSERT OR REPLACE`-Semantik, Sequenzen, Transaktionszustand.

---

## Scope-Blöcke

| Block | Domäne | Status |
|-------|--------|--------|
| **A** | Auth + Bootstrap + Homeworld | ✅ SQLite + PG |
| **B** | Economy + Planet Scope | ✅ SQLite + PG |
| **C** | Unit Queues (Build/Research/Shipyard/Defense) | ✅ SQLite + PG |
| **D** | Fleet + Combat | ✅ |
| **E** | Evolution + Meta | ✅ |
| **F** | Race + Restart / Tick-Idempotenz | ✅ |

---

## Betroffene Dateien (Block A)

- `tests/pg_fixtures.py` (Owner: isolierte PG-Testdb)
- `tests/test_gc_perf_pg_parity_001.py`
- `game/db.py` — `is_integrity_error` (dual-backend)
- `game/models.py` — Auth/Homeworld Integrity-Handling
- `docs/GC_PERF_CORE.md` / dieses Doc

**Nicht bearbeiten:** Production-Env, SQLite-Livedaten, Importer (→ MIGRATE-001), Worker-Prod-Cutover.

---

## Test-Fixture-Regeln

- Owner: `tests/pg_fixtures.py`
- **Default (schnell):** bestehende Staging-URL wiederverwenden (SCHEMA-001 bereits migriert), zwischen Tests `TRUNCATE` — **kein paralleler Lauf** gegen dieselbe DB
- **Opt-in Isolation (langsam über Public-Proxy):** `GC_TEST_POSTGRES_ISOLATE=1` → `CREATE DATABASE gc_parity_<id>` + Full-Migrate
- Pool nach Env-Wechsel schließen (`close_pool`)
- Ohne `GC_TEST_POSTGRES_URL`: PG-Tests skippen; SQLite-Paritätspfad bleibt grün

```powershell
# Eigene Shell — pytest -s zeigt [pg_fixtures]-Fortschritt live
# Kein python app.py parallel gegen dieselbe DATABASE_URL (sonst Lock-Wait)
$env:GC_DB_BACKEND="postgres"
$env:GC_TEST_POSTGRES_URL="<staging public URL>"
$env:DATABASE_URL=$env:GC_TEST_POSTGRES_URL
python -m pytest tests/test_gc_perf_pg_parity_001.py -v -s
```

---

## Abnahmekriterien (Gesamt)

- [ ] Registrierung und Login auf PG grün
- [ ] Default-Spieler + Homeworld korrekt
- [ ] aktive Kolonie korrekt
- [x] Gebäude-/Research-Queues grün
- [x] Shipyard-/Defense-Queues grün
- [x] Refund und Reschedule identisch
- [x] Fleet send/arrival/return grün
- [x] Combat/Loot/Debris grün
- [x] Expedition grün
- [x] Planet Evolution grün
- [x] Poll-State und Actions grün
- [x] parallele Enqueues ohne Duplicate/Overflow
- [x] Worker-Tick idempotent
- [x] Neustart verliert keinen Zustand
- [x] keine SQLite-spezifischen Runtime-Queries im getesteten Pfad
- [x] SQLite-Suite-Pfad für Block A weiterhin grün

### Block A

- [x] Isolierte PG-Fixture (`CREATE DATABASE` / Drop) — opt-in via `GC_TEST_POSTGRES_ISOLATE=1`
- [x] Default-Reuse-Fixture für bereits migrierte Staging-DB (kein Hang am Full-Migrate)
- [x] Default-Admin + Homeworld nach `init_db`
- [x] `create_user` → Player + Homeworld + Score-Row
- [x] `users.id == players.id`
- [x] `active_planet_id` auf eigenen Homeworld gesetzt (Owner: `ensure_player_and_homeworld`)
- [x] Default-Gebäude = 0, Start-Ressourcen = `DEFAULT_GAME_SETTINGS`
- [x] `game_settings` Keys/Werte = SQLite-Defaults
- [x] `init_db` erneut → keine Duplikate (Users/Planets/Settings)
- [x] Duplicate-Username → klarer Fehler (PG UniqueViolation)
- [x] Passwort-Hash Verify Roundtrip
- [x] `dna_seed` speicherbar (BIGINT)
- [x] SQLite-Parity-Test grün (`test_parity_a_auth_bootstrap_sqlite`)
- [x] PG-Parity-Test grün (`test_parity_a_auth_bootstrap_postgres`)

### Block B

- [x] SQLite: Ressourcen-Tick + Context-Planet + `active_planet_id` (`test_parity_b_economy_scope_sqlite`)
- [x] PG: derselbe Test (`test_parity_b_economy_scope_postgres`) — Scalar-`MAX`→`GREATEST` im Dialekt-Owner
- [ ] aktive Kolonie wechseln (HTTP)
- [ ] Poll ohne Writes bei Unverändert

### Block C

- [x] Buildings: enqueue + finish_due + level-up
- [x] Buildings: cancel pending → full refund + empty queue
- [x] Account research: enqueue + cancel pending refund
- [x] Shipyard: dual enqueue, cancel head → reschedule remaining, finish → ships
- [x] Defense: enqueue + cancel
- [x] Parallel build enqueue (2 jobs)
- [x] SQLite (`test_parity_c_queues_sqlite`)
- [x] PG Staging (`test_parity_c_queues_postgres`) — nested `COMMIT` in GDP personality ensure + `sqlite_master` schema probes fixed
- [ ] Planet Research / Ascension (optional follow-up in C or E)

### Block D

- [x] Transport send → arrival credit → return ships
- [x] Double-tick idempotent (arrivals / holding)
- [x] Attack → combat report messages (attacker + defender)
- [x] Loot loaded on return + credited at home
- [x] Debris spawned at target coords
- [x] Expedition hold → returning loot idempotent
- [x] Portable `json_extract` for fleet report idempotency (`messages.py`)
- [x] `expedition_daily_value` readiness via `table_exists` (no `sqlite_master`)
- [x] SQLite (`test_parity_d_fleet_combat_sqlite`)
- [ ] PG Staging (`test_parity_d_fleet_combat_postgres`) — run when `GC_TEST_POSTGRES_URL` set

### Block E

- [x] Evolution schema ready + DNA seed bounds
- [x] Planet research enqueue + finish → level
- [x] Specialization pick (`forge_world`)
- [x] Score/meta planet list still resolves
- [x] SQLite (`test_parity_e_evolution_sqlite`)
- [ ] PG Staging (`test_parity_e_evolution_postgres`) — run when `GC_TEST_POSTGRES_URL` set

### Block F

- [x] Concurrent build enqueues without queue corruption
- [x] Fleet tick double-call idempotent after pool restart
- [x] Due movement still processes after `close_pg_pool` / reconnect
- [x] SQLite (`test_parity_f_race_restart_sqlite`)
- [ ] PG Staging (`test_parity_f_race_restart_postgres`) — run when `GC_TEST_POSTGRES_URL` set

---

## Paritäts-Matrix

| Domäne     | SQLite | PostgreSQL | Abweichung |
| ---------- | -----: | ---------: | ---------- |
| Auth (A)   |   grün |       grün | — |
| Economy (B)|   grün |       grün | Scalar `MAX`→`GREATEST` |
| Buildings  |   grün |       grün | nested COMMIT / SAVEPOINT |
| Research   |   grün |       grün | — |
| Shipyard   |   grün |       grün | — |
| Defense    |   grün |       grün | — |
| Fleet      |   grün |       📋* | Block D — SQLite ✅; PG via staging URL |
| Combat     |   grün |       📋* | Block D — SQLite ✅; PG via staging URL |
| Evolution  |   grün |       📋* | Block E — SQLite ✅; PG via staging URL |
| Race tests |   grün |       📋* | Block F — SQLite ✅; PG via staging URL |

Nach vollständiger Matrix → **GC-PERF-PG-MIGRATE-001**.

---

## Referenz-Docs

- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md)
- [GC_PERF_CORE.md](GC_PERF_CORE.md)
- [GC_PERF_PG_SCHEMA_001.md](GC_PERF_PG_SCHEMA_001.md)
- [GC_PERF_DB_001_POSTGRES_AUDIT.md](GC_PERF_DB_001_POSTGRES_AUDIT.md)
