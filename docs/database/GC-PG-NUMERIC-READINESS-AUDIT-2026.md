# GC-PG-NUMERIC-READINESS-AUDIT-2026

Status: **binding audit baseline**  
Audit date: **2026-09-04**  
Audited production code base: `main@cb89cb53c2f59002dd5c6a990c826389ba96d396`  
Scope: PostgreSQL numeric safety, arbitrary precision, SQLite legacy compatibility, API/JSON precision and browser gameplay inputs.

> **Core conclusion:** “PostgreSQL-ready” does not mean “BIGINT everywhere”.
> Genesis Colonies deliberately has unbounded / extremely large economy values. A numeric domain is only ready when it is either:
>
> 1. explicitly and regression-tested **bounded below its storage/transport limit**, or
> 2. **exact end-to-end** across DB → Python → JSON → JavaScript input/display.
>
> `INTEGER`, `BIGINT`, `REAL/DOUBLE PRECISION` and JavaScript `Number` each fail at different thresholds.

## 1. Numeric boundaries

| Boundary | Exact / valid integer range | Genesis consequence |
|---|---:|---|
| PostgreSQL `INTEGER/int4` | ±2,147,483,647 | unsafe for many quantities/scores immediately |
| JavaScript safe integer | ±9,007,199,254,740,991 | JSON numbers / gameplay `Number` lose integer precision above ~9e15 |
| PostgreSQL `BIGINT/int8` | ±9,223,372,036,854,775,807 | too small for current high-level economy costs |
| SQLite `INTEGER` | signed i64 | same hard integer ceiling as BIGINT |
| SQLite `REAL` / PostgreSQL `DOUBLE PRECISION` | ~53-bit integer precision | stores large magnitudes, but no longer exact above ~9e15 |
| Python `int` | arbitrary precision | preferred server authority for integer gameplay values |
| PostgreSQL `NUMERIC` | arbitrary/high configured precision | preferred production type for economy values requiring SQL arithmetic |
| decimal `TEXT` | arbitrary digits | preferred cross-backend snapshot/log pattern when SQL arithmetic is not required |

### Incident proof

The Ferronit Mine L387 → L388 cost crossed signed i64 in one component:

- metal cost ≈ **9,678,870,497,752,199,168**
- signed BIGINT max = **9,223,372,036,854,775,807**

This caused the Ferro-only queue failure and led to migration 163 / exact build-cost snapshots.

---

# 2. Status legend

- 🟢 **READY** — arbitrary/exact path exists end-to-end for intended domain.
- 🟡 **READY BY CAP** — fixed gameplay cap keeps the value safely below its numeric type; cap is part of the safety contract.
- 🟠 **P1 GROWTH RISK** — currently usable but unbounded / growth can reach numeric limit.
- 🔴 **P0 NOT READY** — current production-scale values can already overflow or lose integer precision.
- ⚫ **STALE DOC** — documentation contradicts current PostgreSQL production reality.

---

# 3. Audit matrix

## 3.1 Core economy and resources

| Domain | Current storage / code | Status | Finding | Required direction |
|---|---|---|---|---|
| Planet metal / crystal / fuel cells | schema `REAL`; PG rewrite → `DOUBLE PRECISION`; pervasive Python `float` | 🔴 P0 | exact integer precision is lost above 2^53; Genesis balances already operate beyond that scale | define exact resource contract; PG `NUMERIC(...,0)`; remove float amount arithmetic |
| Resource production/tick | `production_formula.py` uses `1.075 ** level`, float modifiers/rates | 🔴 P0 | DB-only migration would still receive already-rounded values | define deterministic rounding at formula boundary; integer/Decimal amount accumulation |
| Atomic resource spend/add | mixed int parameters + float resource columns; Ferro hotfix has >i64 float bind fallback | 🔴 P0 | protects from immediate i64 bind crash, not from precision loss | one canonical exact resource mutation helper for PG NUMERIC |
| Storage capacities | Python int outputs, but modifiers/rates may be float | 🟠 P1 | capacities can become huge as levels grow | keep output integer; audit formula rounding; serialize safely |
| Exchange/Trader balances | `exchange_log.give_amount/receive_amount REAL`; daily-used REAL; Python float arithmetic | 🔴 P0 | exact input digits are preserved in one frontend path, then precision is lost server-side | NUMERIC exact amounts + integer/Decimal server arithmetic |
| Debris fields | `metal/crystal REAL` | 🟠 P1 | combat-derived values scale with fleet size | exact resource domain / NUMERIC |
| Asteroid resources | persistent resource quantities use REAL | 🟠 P1 | resource-scaled persistent state | exact resource domain / NUMERIC |
| Planet Evolution special resources | REAL, deliberately small explicit caps | 🟡 CAP | fractional/small capped domain | retain only while cap contract remains explicit/tested |

### P0 evidence: directive production delta

`emit_resource_produced_events()` stores the full production tick delta in `directive_progress.delta`, which is only BIGINT.

A production example observed during this incident chain was ~419,628,449,373,482,434,560 metal/day:

- ≈ 4,856,810,756,637,528 / second
- signed BIGINT is exceeded after ~1,899 seconds (~31.7 minutes) if accumulated in one tick/delta.

This is a current production risk, not a theoretical future limit.

---

## 3.2 Buildings, research and production queues

| Domain | Current storage | Status | Finding | Required direction |
|---|---|---|---|---|
| Build queue cost snapshot | legacy BIGINT + migration 163 exact decimal TEXT snapshots | 🟢 READY | L388 Ferro regression proves >i64 snapshot survives | use as reference pattern |
| Build queue refund | exact snapshot + Decimal/integer-safe refund | 🟢 READY | no binary-float refund loss for huge build costs | keep |
| Research queue costs | BIGINT only; mostly uncapped research | 🟠 P1 HIGH | research levels are generally unbounded; cost formulas grow with level and use float internals | exact cost snapshots analogous to build queue; exact cost formula |
| Shipyard queue amount | BIGINT | 🟠 P1 | 9,999,999,999 ships already valid; still finite i64 ceiling | decide explicit quantity cap or NUMERIC/TEXT exact quantity |
| Shipyard cost M/C | BIGINT | 🟠 P1 | batch cost = unit cost × quantity; can exceed i64 before quantity does | exact snapshots |
| Shipyard fuel cost | REAL/DOUBLE | 🟠 P1 | binary-float cost snapshot | exact snapshot / NUMERIC |
| Defense stock `planet_defense.amount` | statically widened BIGINT | 🟠 P1 | no arbitrary precision but stock can grow | cap or NUMERIC |
| Defense queue `amount` | INTEGER/int4 | 🔴 P0 | max build amount is resource-derived with no comparable int4 cap | widen immediately; add domain cap/exact policy |
| Defense queue cost M/C | INTEGER/int4 | 🔴 P0 | total cost grows with quantity | exact snapshot / NUMERIC |
| Defense queue fuel cost | REAL/DOUBLE | 🔴 P0/P1 | same queue can already hold huge orders | exact snapshot |
| Troop stock / queue amount | INTEGER/int4 | 🟡 CAP | barracks capacity curve stays below int4 under current building cap (~100M at L50) | add regression locking cap below int4 |
| Troop queue cost M/C | statically widened BIGINT | 🟡/P1 | quantity cap currently protects cost growth in practice | document/test upper bound |
| Stellar Forge `hull_mass_progress` | BIGINT | 🟠 P1 | derived from potentially massive ship production | exact / explicit cap |

### Research note

The main research tree deliberately has no generic hard max; e.g. navigation fleet slots continue after fixed tiers. Therefore BIGINT research costs are a **temporary ceiling**, not a valid long-term numeric contract.

---

## 3.3 Fleet, combat, loot and progression

| Domain | Current storage | Status | Finding | Required direction |
|---|---|---|---|---|
| Planet ship stock | BIGINT | 🟠 P1 | safely passed 32-bit, but not arbitrary | cap or NUMERIC if “no max” applies to quantities |
| Fleet movement resources | JSON TEXT | 🟠 P1 | text can preserve digits, but source values/frontend may already be rounded | canonical decimal-string serialization |
| Fleet fuel cost | REAL/DOUBLE | 🟠 P1 | precision loss for large fuel costs | integer/NUMERIC contract |
| Expedition daily value | BIGINT | 🟠 P1 | loot/fleet-derived values can continue growing | NUMERIC or decimal TEXT |
| Chronicle `score_value` | BIGINT | 🟠 P1 | combat/expedition/asteroid-derived; can exceed i64 | NUMERIC/TEXT |
| Pirate intel resource/fleet/defense scores | BIGINT | 🔴 P0 | `resources_score = metal + crystal`; current rich planets can exceed i64 | NUMERIC/TEXT; opportunity ratio can remain float after bounded projection |
| Directive progress delta | BIGINT | 🔴 P0 | raw resource-produced/spent event delta can exceed i64 today | exact delta storage or store only bounded objective contribution |
| Combat Hall of Fame loss/total scores | INTEGER/int4 | 🔴 P0 | every attack can write raw destroyed score; huge fleets make int4 invalid immediately | migrate score columns to NUMERIC/TEXT |
| HoF loot/debris SQL sort | JSON values cast to REAL | 🟠 P1 | ordering becomes approximate for huge values | exact extracted/canonical sortable numeric values |
| World Boss HP/damage | current bounded design scale | 🟡 CAP | present values are far below int4/i64 | preserve explicit cap/test if design changes |

---

## 3.4 Market, alliance and inventory

| Domain | Current storage | Status | Finding | Required direction |
|---|---|---|---|---|
| Auction listing start/current bid | INTEGER/int4 | 🔴 P0 | no meaningful bid hard cap; current economy far exceeds int4 | NUMERIC exact bids |
| Auction bid history amount | INTEGER/int4 | 🔴 P0 | same | NUMERIC exact bids |
| Auction frontend input | generic JS `Number` parser | 🔴 P0 | >2^53 bid digits round before API | decimal-string/BigInt input path |
| Alliance pools | INTEGER/int4 | 🟡 CAP | project catalog has fixed low max levels; pool cap is derived from bounded project costs | keep with cap regression |
| Alliance donations/projects | INTEGER | 🟡 CAP | bounded by alliance pool/project catalog today | cap regression required |
| Inventory quantities | INTEGER | 🟡/P1 | most catalog items are naturally small, but no universal numeric-domain contract | classify each high-volume item family or enforce cap |
| Case battle reward amount/value | INTEGER | 🟡/P1 | catalog-driven today; not economy-authoritative | explicit catalog upper bound |
| Timekeeper balance / ledger seconds | INTEGER/int4 | 🟠 P1 | no hard account-balance cap; positive int4 range is ~68 years | BIGINT at minimum or explicit lifetime cap; JS-safe transport if ever large |
| Space Lottery pool / wager ledger | INTEGER/int4 | 🟠 P1 LOW | per-bet/daily caps exist, but weekly pool has no global player-count hard cap | document bounded horizon or widen |
| Pirate bounty credits | INTEGER/int4 | 🟠 P1 | cumulative damage/destroy rewards have no lifetime cap | BIGINT/NUMERIC or explicit bounty cap |

---

# 4. PostgreSQL widening is not a complete numeric contract

`game/schema_bootstrap.py::_POSTGRES_I64_COLUMNS` is a **cutover compatibility list**, not a future-proof Genesis numeric model.

It currently includes selected fields such as:

- build/research queue costs
- planet ships
- shipyard queue amounts/costs
- planet defense
- chronicle score
- directive delta
- expedition values
- pirate intel scores
- troop queue costs
- Stellar Forge hull mass

It does **not** cover every growing domain, including notable examples:

- defense queue amount/costs
- auction prices/bids
- Combat HoF scores
- troop stock/queue amount (currently safe only via cap)
- alliance pools (currently safe only via cap)

The dynamic SQLite→PG overflow scan only widened columns that already exceeded int4 in the imported snapshot. It cannot protect a column that grows beyond its type **after cutover**.

**Conclusion:** static widening must be supplemented by an explicit numeric-domain registry / CI contract.

---

# 5. Python precision audit

## Unsafe patterns for economy-scaled integers

These patterns remain in production paths and must not be used for arbitrary economy values:

- `float(resource)`
- `int(float(resource))`
- `float(give_amount)` before persistence
- float-based accumulation of total costs
- SQL columns mapped from SQLite `REAL` to PG `DOUBLE PRECISION`

Examples exist in:

- `game/resources.py`
- `game/exchange.py`
- `game/shipyard.py`
- `game/defense.py`
- research MAX preview/cost aggregation
- several fleet/resource serializers

Float remains valid for:

- percentages
- bounded ratios
- timing / Unix timestamps
- probability
- interpolation inputs **only if the final integer rounding contract is explicit**

---

# 6. JSON and browser precision audit

## Existing good pattern

`game/ranking.py` already has the correct transport concept:

- Python `int` remains authoritative
- values beyond JS safe integer are emitted as decimal strings
- `_json_safe_bigints()` recursively protects payloads
- frontend display accepts exact decimal strings via `BigInt`

## Current systemic gap

There is no app-wide equivalent for general gameplay state.

`static/main.js` has:

- `parseDisplayBigInt()` — exact **display** support ✅
- `formatNumber()` — exact string/BigInt display ✅
- `parseIntNumber()` — generic gameplay parser based on JS `Number` ❌ for >2^53

The generic number-input selector includes:

- Shipyard quantity
- Defense quantity
- Fleet ship quantities
- Fleet metal/crystal/fuel
- Auction bid
- Logistics resource amount
- Alliance donation
- Scrapyard
- Trader/exchange

Only the main exchange input currently has a dedicated digit-preserving BigInt/string path.

### Required browser contract

For unbounded integer gameplay domains:

1. input digits remain a decimal string (or BigInt locally)
2. API request sends decimal string
3. Flask parses to Python `int`
4. DB persists exact NUMERIC/TEXT
5. API returns decimal strings whenever value exceeds JS safe integer
6. browser uses BigInt only for integer comparison/formatting; server remains gameplay authority

---

# 7. Reference implementations already in repo

## 🟢 Ranking / score

Migration 154 + `game/ranking.py`:

- score columns stored as decimal TEXT
- Python arbitrary integers
- PostgreSQL casts TEXT to `NUMERIC` for ordering/arithmetic
- JSON safe-string conversion beyond 2^53

**Use this pattern for snapshots/leaderboards that do not require frequent atomic SQL arithmetic.**

## 🟢 Alliance War raw values

Migration 155:

- raw scores and destroyed-unit totals persisted as TEXT
- Python integer semantics retained

## 🟢 Build queue exact cost snapshots

Migration 163:

- exact decimal TEXT cost snapshot
- rolling-compatible legacy BIGINT fields
- exact refund math

**Use this pattern for queue/log snapshots.**

---

# 8. Target numeric architecture

## 8.1 Production PostgreSQL

For economy-scaled integer values that require atomic SQL arithmetic / comparison:

**Candidate canonical type:** `NUMERIC(78,0)`

Examples:

- planet resource balances
- auction prices/bids
- resource exchange amounts
- resource-scaled pool/value fields that remain unbounded

Precision 78 is a design proposal, not a magic requirement; the important contract is “deliberately larger than any supported gameplay horizon, integer scale 0”.

For snapshots/history where SQL arithmetic is unnecessary:

- decimal TEXT + Python `int`
- cast to PG NUMERIC only when sorting/aggregating

## 8.2 SQLite local/dev

SQLite `INTEGER` cannot exactly represent >i64, and SQLite NUMERIC affinity may convert oversized integers to REAL.

Therefore SQLite cannot be treated as a transparent arbitrary-precision mirror.

Required design choice for exact big-number domains:

- store decimal TEXT locally and use application-side integer mutation for those fields, **or**
- implement backend-specific exact storage adapters with explicit parity tests.

Do not rely on SQLite NUMERIC affinity alone.

---

# 9. Priority plan

## P0-A — Exact Resource Core

1. Define canonical exact integer resource contract.
2. Migrate PostgreSQL `planets.metal/crystal/fuel_cells` → exact NUMERIC.
3. Remove binary-float balance mutation paths.
4. Define deterministic production rounding/accumulation.
5. Introduce one canonical exact resource add/spend/compare owner.
6. Make game-state/API resource serialization JS-safe.
7. Convert generic resource gameplay inputs to decimal-string/BigInt-safe transport.
8. Migrate Exchange, Debris and Asteroid persistent resource amounts.

## P0-B — Current derived overflows

9. Fix `directive_progress.delta` raw large-event storage.
10. Fix `pirate_intel.resources_score/fleet_score/defense_score`.
11. Fix Auction prices/bids + frontend bid input.
12. Fix Combat HoF score columns.
13. Fix Defense queue amount/cost snapshot types.

## P1 — Unbounded queue/value domains

14. Research exact cost calculation + exact queue snapshots.
15. Shipyard exact cost snapshots including fuel; decide stock/queue quantity policy.
16. Fleet fuel/resource transport exactness.
17. Chronicle / expedition / Stellar Forge large scalar fields.
18. Review inventory/high-volume reward amount domains.
19. Widen or explicitly cap Timekeeper / Lottery / Pirate Bounty cumulative counters.

## P2 — Contract enforcement

20. Add a numeric-domain registry:
    - `arbitrary_exact`
    - `bounded_int4`
    - `bounded_int8`
    - `fractional_double`
    - `timestamp_double`
21. CI rejects new numeric gameplay columns that are not classified.
22. CI verifies all “bounded” domains have a tested upstream cap.
23. Add PostgreSQL parity tests using values:
    - > int4
    - > JS safe integer
    - > int8
    - ~10^30 / 10^60 exact decimal

---

# 10. Documentation drift found during audit

The code/repo currently contains contradictory database statements.

### Current truth

`docs/GC_PERF_CORE.md` says PostgreSQL is production-authoritative after the 2026-08-31 cutover; SQLite is local/dev + backup.

### Stale statements to reconcile

At minimum audit/update:

- `docs/ROADMAP.md` — still says production remains SQLite / PG cutover not planned
- `docs/CAPABILITY_STATUS.md`
- `docs/RAILWAY_OPERATOR.md`
- `docs/CONTRIBUTING.md`
- `docs/ARCHITECTURE.md`
- `docs/GC_PERF_DB_001_POSTGRES_AUDIT.md`
- `.env.example`
- older performance/runbook docs referring to “1 SQLite writer” as current production architecture

These should be handled in the dedicated Code↔Docs reconciliation pass. Do not use stale SQLite-production text as implementation authority.

---

# 11. Definition of “Postgres numeric ready”

A gameplay domain may be marked **READY** only when all relevant layers pass:

- [ ] schema type cannot overflow within supported gameplay horizon
- [ ] Python path avoids lossy float conversion for integer authority
- [ ] arithmetic/refund/cost math has deterministic integer rounding
- [ ] SQL compare/update is exact
- [ ] API transport preserves >2^53 integers
- [ ] browser input preserves exact digits
- [ ] display formats exact decimal strings
- [ ] SQLite dev behavior is explicitly defined (not assumed)
- [ ] migration/backfill is idempotent
- [ ] regression covers int4, JS-safe, int8 and arbitrary-large boundary values
- [ ] docs identify whether the domain is exact or safe-by-cap

Until those checks are satisfied, “it uses BIGINT” is **not** sufficient evidence of PostgreSQL readiness.
