# GC-PG-NUMERIC-READINESS-001 — PostgreSQL / Big-Number Readiness Audit

**Status:** ACTIVE AUDIT / binding migration inventory  
**Code baseline:** `cb89cb53c2f59002dd5c6a990c826389ba96d396`  
**Date:** 2026-09-04  
**Production authority:** PostgreSQL (SQLite remains local/dev compatibility only)

---

## 1. Why this audit exists

Genesis Colonies intentionally has no hard endgame level cap. Historic SQLite schema choices therefore cannot be treated as permanent numeric contracts.

The Ferronit Mine L387 → L388 production bug exposed the first concrete overflow:

- L388 Ferronit upgrade metal cost exceeds signed 64-bit BIGINT.
- Migration 163 introduced lossless decimal TEXT snapshots for `build_queue`.
- The same numeric assumptions still exist in other systems.

The old GC-622 conclusion ("INT32 is not the problem; REAL becomes critical around 9e15") was correct for the SQLite-era scale, but it is no longer sufficient after the PostgreSQL cutover and live values above the JavaScript/IEEE-754 safe integer range.

This audit separates four different limits:

| Class | Limit | Failure mode |
|---|---:|---|
| PostgreSQL `INTEGER` / int4 | ±2,147,483,647 | hard DB overflow |
| PostgreSQL `BIGINT` / int8 | ±9,223,372,036,854,775,807 | hard DB overflow |
| IEEE-754 DOUBLE / JS Number exact integer range | ±9,007,199,254,740,991 | silent integer precision loss |
| Python `int` / PostgreSQL `NUMERIC` / decimal TEXT | effectively arbitrary for GC scale | preferred for unbounded exact gameplay values |

---

## 2. Critical PostgreSQL rewrite fact

`game/sql_pg_rewrite.py` does **not** convert every SQLite `INTEGER` to PostgreSQL BIGINT.

It currently rewrites:

- `INTEGER PRIMARY KEY AUTOINCREMENT` → `BIGSERIAL PRIMARY KEY`
- `dna_seed INTEGER` → `BIGINT`
- `REAL` → `DOUBLE PRECISION`

Ordinary gameplay `INTEGER` columns become PostgreSQL **int4** unless explicitly widened by `game/schema_bootstrap.py::_POSTGRES_I64_COLUMNS`.

That manual list is useful but incomplete.

---

## 3. Current status legend

| Status | Meaning |
|---|---|
| READY | exact for the intended unbounded domain |
| LIMITED | safe for current practical values but has a finite BIGINT ceiling |
| RISK | schema/runtime can lose precision or hit int4 before expected GC scale |
| NOT READY | known concrete path can already exceed its type |
| DOC STALE | documentation contradicts current production/code truth |

---

# 4. Numeric readiness matrix

## 4.1 Core resources — P0

| Domain | Current persistence | PG result | Status | Target |
|---|---|---|---|---|
| `planets.metal` | REAL | DOUBLE PRECISION | **NOT READY** | NUMERIC / exact decimal policy |
| `planets.crystal` | REAL | DOUBLE PRECISION | **NOT READY** | NUMERIC / exact decimal policy |
| `planets.fuel_cells` | REAL | DOUBLE PRECISION | **NOT READY** | NUMERIC / exact decimal policy |
| `exchange_log.give_amount` | REAL | DOUBLE PRECISION | **NOT READY** | NUMERIC |
| `exchange_log.receive_amount` | REAL | DOUBLE PRECISION | **NOT READY** | NUMERIC |
| `players.exchange_daily_used` | REAL | DOUBLE PRECISION | **RISK** | NUMERIC / integer policy |
| `planets.fuel_exchange_daily_used` | REAL | DOUBLE PRECISION | **RISK** | NUMERIC / integer policy |
| `debris_fields.metal/crystal` | REAL | DOUBLE PRECISION | **NOT READY** | NUMERIC |
| `asteroid_fields.metal/crystal/fuel_cells` | REAL | DOUBLE PRECISION | **NOT READY** | NUMERIC |
| `asteroid_field_claims.metal/crystal/fuel_cells` | REAL | DOUBLE PRECISION | **NOT READY** | NUMERIC |

Reason: live resource values already exceed `Number.MAX_SAFE_INTEGER` / exact DOUBLE integer range. Precision loss is therefore not hypothetical.

### Runtime consequence

Several runtime paths still intentionally cross through `float()` because the resource columns are DOUBLE. The Ferronit L388 compatibility helper also binds costs above i64 as float for the resource debit while storing the paid queue snapshot exactly. This prevents a hard bind overflow but **does not make the resource debit integer-exact**.

---

## 4.2 Build / research / shipyard / defense / troop queues — P0/P1

### Build queue

| Field | Current | Status |
|---|---|---|
| `build_queue.cost_metal_exact` | decimal TEXT | **READY** |
| `build_queue.cost_crystal_exact` | decimal TEXT | **READY** |
| legacy `cost_metal/cost_crystal` | BIGINT after widening | LIMITED / rolling compatibility |

Migration 163 is the correct model for an exact paid-cost snapshot.

### Research queue

| Field | Current PG intent | Status | Problem |
|---|---|---|---|
| `research_queue.cost_metal` | BIGINT via widening list | **LIMITED** | no exact arbitrary snapshot |
| `research_queue.cost_crystal` | BIGINT via widening list | **LIMITED** | no exact arbitrary snapshot |

Unbounded research costs will eventually reproduce the L388 build-queue class of bug.

### Shipyard queue

| Field | Current PG intent | Status | Problem |
|---|---|---|---|
| `amount` | BIGINT via widening list | LIMITED | finite amount ceiling |
| `cost_metal` | BIGINT via widening list | **LIMITED / HIGH RISK** | huge batch total can exceed i64 |
| `cost_crystal` | BIGINT via widening list | **LIMITED / HIGH RISK** | huge batch total can exceed i64 |
| `cost_fuel_cells` | DOUBLE PRECISION | **NOT READY** | precision loss above 2^53 |
| exact cost snapshot | absent | **NOT READY** | no arbitrary-precision refund snapshot |

This is directly relevant to multi-billion ship orders: the unit count can fit BIGINT while the multiplied total cost can exceed BIGINT.

### Defense queue

Historical schema uses ordinary SQLite INTEGER for:

- `defense_queue.amount`
- `cost_metal`
- `cost_crystal`

and REAL for `cost_fuel_cells`.

None of the defense queue amount/cost columns are currently in `_POSTGRES_I64_COLUMNS`.

**PostgreSQL outcome:** int4 for amount/metal/crystal, DOUBLE for fuel.

**Status: NOT READY (P0).**

### Troops

| Field | Current | Status |
|---|---|---|
| `planet_troops.amount` | ordinary INTEGER → PG int4 | **NOT READY** |
| `troop_queue.amount` | ordinary INTEGER → PG int4 | **NOT READY** |
| `troop_queue.cost_metal/crystal` | BIGINT via widening | LIMITED |

No hard game cap guarantees that troop stock/order sizes stay below 2.147 billion.

---

## 4.3 Ship / defense stock — P1 no-max hardening

| Field | Current PG | Status |
|---|---|---|
| `planet_ships.amount` | BIGINT via widening | LIMITED |
| `planet_defense.amount` | BIGINT via widening | LIMITED |

These are safe for billions and for the reported 9,999,999,999 ship quantity, but BIGINT is not an unlimited Genesis contract. Treat these as P1 migration candidates to NUMERIC if the no-max rule applies literally to unit stock forever.

---

## 4.4 Auction House — P0

Migration 047 defines:

- `auction_house_listings.start_price INTEGER`
- `auction_house_listings.current_bid INTEGER`
- `auction_house_bids.amount INTEGER`

There is no later BIGINT/NUMERIC migration and these columns are absent from `_POSTGRES_I64_COLUMNS`.

**PostgreSQL result: int4.**

This means resource-denominated auctions are not safe above ~2.147 billion even though player balances are already many orders of magnitude larger.

**Status: NOT READY (P0).**

**Target:** NUMERIC exact amounts, because auction comparisons/order-by arithmetic should stay numeric in SQL.

---

## 4.5 Alliance economy — P0/P1

Migration 088 uses ordinary INTEGER for:

- `alliances.pool_metal`
- `alliances.pool_crystal`
- `alliances.pool_fuel_cells`
- `alliance_donations.amount`
- `alliance_projects.cost_metal`
- `alliance_projects.cost_crystal`
- `alliance_projects.cost_fuel_cells`
- `alliance_xp`, `xp_granted`

No matching widening entries exist today.

**PostgreSQL result: int4.**

Resource pools/donations/project costs are therefore **NOT READY** for current GC economic scale. XP is lower priority unless progression scaling can exceed int4.

---

## 4.6 World Boss / pirate boss numerics — P1

Migration 100/124 uses ordinary INTEGER for:

- world boss definition/event `max_hp`
- event `current_hp`
- contribution `damage`

Migration 107 uses ordinary INTEGER for pirate boss `max_hp/current_hp/damage`.

No BIGINT/NUMERIC widening was found for these HP/damage fields.

Current seeded values are small, but this is incompatible with long-term scaling and large player combat values.

**Status: RISK / P1**, promote to P0 before the next boss-health scaling pass.

Target: NUMERIC exact integer semantics for HP/damage, not DOUBLE.

---

## 4.7 Scores — mostly READY

Migration 154 deliberately rebuilt `player_scores.score_*` as decimal TEXT.

- Python `int` is authoritative for score arithmetic.
- ranking serialization has explicit JS-safe bigint handling.
- alliance war raw score fields in migration 155 are also TEXT.

**Persistence status: READY.**

Caveat: not every non-ranking endpoint has a generic big-int JSON transformer. Any score copied into unrelated payloads must still be checked at the API boundary.

---

## 4.8 Hall of Fame / directives / case battle values — P1

Migration scan found ordinary INTEGER in:

- combat Hall of Fame destroyed/loss score fields (migration 062)
- Imperial Directive target/progress values (migration 080)
- Case Battle `total_battle_value`, `reward_amount`, `reward_value` (migration 130)
- several XP/progress/reward counters

These are not all present in the current widening list.

Classification:

- score/value fields derived from the unbounded economy: **RISK / P1**
- fixed gameplay counters/XP with bounded design: INT4 may remain valid, but the bound must be explicit in docs/tests.

Do not blanket-convert every INTEGER column. Coordinates, levels, enum-like counters, flags, ranks and short timers are legitimate int4 candidates.

---

## 4.9 Expedition / pirate score aggregates — LIMITED

Current widening list already upgrades:

- `expedition_daily_value.expo_value_total`
- `expedition_daily_recorded.expo_value`
- `pirate_intel.resources_score`
- `pirate_intel.fleet_score`
- `pirate_intel.defense_score`
- `chronicle_entries.score_value`
- `directive_progress.delta`

to BIGINT.

This fixed the SQLite-i64 → PG-int4 parity problem, but these remain **LIMITED** under a literal no-max contract.

---

## 4.10 Planet Evolution special economy — P1/P2

Migration 016 stores as REAL / DOUBLE:

- `planet_special_resources.amount`
- `cap`
- `production_per_hour`
- `consumption_per_hour`
- `planet_trade_routes.amount_per_hour`
- `planet_import_demands.required_per_hour`
- several definition base-cap/output/rate fields

Rates may legitimately be fractional, so this domain must **not** be blindly converted to integer.

Recommended target:

- balances/caps: NUMERIC with explicit scale policy
- rates: NUMERIC with bounded fractional scale
- ratios/chances/efficiencies: DOUBLE is acceptable when they are intentionally non-exact coefficients

---

# 5. Fleet JSON and API transport

`fleet_movements.ships_json` and `resources_json` are TEXT. Python's JSON parser preserves integer tokens as Python `int`, so DB storage itself is not limited by BIGINT.

However:

- normal JSON responses emit Python ints as JavaScript numbers unless explicitly converted to strings;
- repository search found the generic `_json_safe_bigints` protection only in the ranking path;
- `GC.parseIntNumber` ultimately uses JavaScript `Number` / `parseInt`, so it is **not an arbitrary-precision data type**.

Therefore:

| Layer | Status |
|---|---|
| TEXT JSON persistence | READY for integer token length |
| Python server arithmetic | READY if no float conversion |
| generic API transport >2^53 | **NOT READY / PARTIAL** |
| browser exact arithmetic >2^53 | **NOT READY** |
| pure string formatting without arithmetic | can be READY if implemented string-first |

A global API contract is needed: gameplay integers above JS safe range must be decimal strings, and frontend code must avoid converting them back to Number when exact arithmetic is required.

---

# 6. Bootstrap / widening lifecycle

`migrate.py::ensure_db_exists()` calls `ensure_postgres_i64_columns()` **before** numbered migrations.

On a fresh Postgres database, tables created by later migrations do not exist during that first widening pass.

`game/models.py::init_db()` also runs the widening helper during application bootstrap, so the normal web boot can repair listed columns after migrations. This prevents calling the migration-runner ordering a guaranteed production failure, but it is still fragile:

- `migrate.py` alone does not produce the final widened schema on first bootstrap.
- offline/staging tools that inspect immediately after `python migrate.py` can observe int4 columns that the app would widen later.
- columns absent from the static list are never repaired.

**Status: RISK / P1 bootstrap hygiene.**

Recommended: run schema-final numeric hardening after all numbered migrations as part of the migration owner, then test first-boot schema in one pass.

---

# 7. Code-level precision hazards found

The audit found active patterns that must be removed during the numeric migration:

- resource persistence and reads using `float(...)`
- `int(float(resource))` in some gameplay/report paths
- shipyard queue fuel snapshot converting through float
- Exchange daily usage stored/read as float
- generic Flask JSON payloads with JS-unsafe integers
- frontend `parseIntNumber` as Number-based fallback
- resource ticker/display interpolation operating on Number

Not every `float()` is a bug. Timestamps, ratios, chances, efficiencies, seconds and non-authoritative UI interpolation can remain float. The migration must target **exact economic quantities**, not mathematical coefficients.

---

# 8. Existing systems already done correctly

Keep these patterns:

1. **Score persistence:** decimal TEXT + Python int.
2. **Ranking JSON:** convert JS-unsafe ints to decimal strings.
3. **Build queue paid cost:** exact decimal TEXT snapshot, legacy i64 only for rolling compatibility.
4. **Postgres explicit widening:** useful for domains that are intentionally i64-bound.
5. **Fleet JSON storage:** TEXT is acceptable when exact ints stay ints and API transport is hardened.

---

# 9. Documentation drift discovered

## DOC STALE — must be reconciled

### `GC-622_INTEGER_OVERFLOW_AUDIT.md`

Still describes the risk as a future issue around 9e15. Live GC values and L388 costs have already crossed that boundary.

### `GC-622B_RESOURCE_INTEGER_MIGRATION.md`

Target says REAL → INTEGER. That is no longer a valid cross-backend target:

- PostgreSQL INTEGER is int4.
- BIGINT is still finite and already insufficient for some upgrade costs.
- target must be a domain policy based on NUMERIC / decimal TEXT, not generic INTEGER.

### SQLite-production references

Some older docs still state that production remains SQLite while newer canonical performance/cutover docs state PostgreSQL is production-authoritative after 2026-08-31.

Docs reconciliation must mark historical SQLite statements as archived history, not current architecture.

---

# 10. Recommended migration sequence

## P0-A — exact primary resources

1. Decide canonical PostgreSQL resource type and fractional policy.
   - Recommended direction: `NUMERIC` with an explicit scale, not BIGINT.
2. Migrate:
   - planets metal/crystal/fuel_cells
   - Exchange amounts/daily usage
   - debris
   - asteroid resource pools/claims
3. Remove authoritative `float()` conversions.
4. Add >2^53 and >2^63 round-trip tests.
5. Add string-safe API transport.

### Important data note

Existing DOUBLE values have already lost some low-order precision. A NUMERIC migration can preserve the **current stored value**, but cannot reconstruct units lost historically. Migration must define a one-time normalization/rounding rule.

## P0-B — int4 gameplay money

Migrate to NUMERIC:

- auction prices/bids
- alliance pools/donations/project costs
- defense queue amount/costs
- troop stock/queue amount

## P0-C — all paid queue snapshots

Apply the build-queue exact-snapshot pattern to:

- research queue
- shipyard queue (all three resources)
- defense queue
- troop queue if/when fuel or larger costs are introduced

## P1 — no-max unit/value hardening

Evaluate NUMERIC for:

- planet_ships.amount
- planet_defense.amount
- expedition/pirate aggregate value fields
- Hall of Fame score values
- directives targets/progress
- case battle values
- World Boss HP/damage

## P1 — bootstrap schema-final pass

Move/duplicate numeric hardening after numbered migrations and add a fresh-Postgres first-run invariant test.

## P1 — browser bigint contract

Create one shared serializer/consumer contract for all gameplay integers, not ranking-only logic.

---

# 11. Runtime verification requirement

This document is a **code/migration audit**. Production schema can differ because of historical migration order and previous manual deploys.

A read-only `scripts/pg_numeric_readiness_audit.py` accompanies this audit and queries `information_schema.columns` on the actual PostgreSQL database.

The production acceptance report must record only schema metadata/types — never player values or secrets.

---

# 11.1 Audit hardening after merged baseline

The first merged runtime auditor deliberately started as a focused schema-policy check. Post-merge review exposed several ways it could report a false green. These are now part of the binding audit contract:

- PostgreSQL constrained `NUMERIC(p,s)` must be classified using `numeric_precision` / `numeric_scale`, not only `data_type`.
- `NUMERIC(..., 0)` is **not** valid for a fractional `decimal_rate` contract.
- `--strict` must fail `LIMITED` for `exact_unbounded` and `exact_snapshot`; BIGINT remains acceptable only where the policy explicitly asks for an `at_least_i64` floor.
- Pirate boss HP/damage from migration 107 is part of the runtime policy inventory.
- Combat Hall of Fame attacker/defender loss values are audited alongside total destroyed value.
- Imperial Directive target/progress/delta fields and Case Battle aggregate/reward values are audited at runtime, not merely mentioned in this document.

This keeps the runtime report aligned with the migration inventory: a known risk documented here must not be invisible to `--strict`.

---

# 12. Definition of PostgreSQL numeric-ready

Genesis Colonies is only "numeric PostgreSQL ready" when:

- no unbounded gameplay quantity relies on PG int4;
- exact economic quantities do not rely on DOUBLE;
- paid queue snapshots cannot overflow BIGINT;
- values above 2^53 survive DB → Python → JSON → browser without silent precision loss;
- fresh Postgres bootstrap reaches the final schema in one migration run + normal startup contract;
- canonical docs no longer describe SQLite limits as the current production architecture;
- tests cover at least:
  - >2^31
  - >2^53
  - >2^63
  - exact debit/refund round-trip
  - fleet/unit amount round-trip
  - auction bid round-trip
  - resource API round-trip.

---

## Rule 19 / architecture

This audit introduces no second economy, cache or gameplay authority. Code remains authoritative in the existing owners. The follow-up migration must change canonical columns in place (or one controlled migration cutover), not maintain permanent parallel resource ledgers.
