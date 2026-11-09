# GC-RESERVE-001 - reserve the next building (phase 1, buildings only)

Status: **implemented behind a feature flag, default OFF.** With the flag off nothing in the game changes (no query, no payload key, no button, no worker work). Not merged, not deployed. Spec and value measurement: `docs/GC_RESERVE_NEXT_PURCHASE.md` on the analysis branch (#566).

## What the player gets

On the buildings page a card that is not affordable (or whose queue is full) shows a small **Reserve** button. One reservation per planet. While it waits, a strip above the queue says what is reserved, what it waits for (resources / a free queue slot / vacation) and when it expires (48 h), with **Cancel**. When the server starts it, the build joins the queue exactly like a manual click; a toast says what happened (started / cancelled and why / expired) once per reservation, even if the player was away.

It is not a resource lock, not a refund trick, not a way around the queue limit, not a speed-up and not an automatic planner: the player names the building; the game never chooses.

## The four protections

| Protection | How it is enforced | Test |
|---|---|---|
| **No double charge** (parallel workers, replays, crashes) | The debit, the job insert and the claim `armed -> started` are ONE transaction inside the canonical owner `queue_build_for_planet`. The claim is a compare-and-swap (`UPDATE ... WHERE state = 'armed'`, `rowcount == 1`); a lost claim rolls the debit and the job back. PostgreSQL: the worker takes the planet row with `FOR UPDATE SKIP LOCKED` and never waits. The database refuses a second armed row per planet and a second reservation per job (partial unique indexes, migration 189). | replay, 4 racing threads, cancel racing the start, injected failure after the debit, random walk with an exact resource ledger |
| **No bypass of queue limits** | The start IS `queue_build_for_planet`: same `queue_limit` (admin setting), same level cap and Ascension gate, same requirements, same rebuild-cost share and timers; a full queue keeps the reservation armed (`waiting_slot`). | `queue_limit = 1`, Ascension cap |
| **Atomic processing** | Arming writes one row and touches no stock, queue row or timer. Starting is the owner's single transaction. | arm leaves stock and queue byte-identical |
| **Understandable end states** | `armed -> started`, `cancelled(player / replaced / superseded / invalid)`, `expired`; a worker that lost a race reports `skipped`, never a wrong outcome. The UI says which one, in 8 languages. | every state reachable in tests; locale parity |

The price is the canonical price **at the moment of the start** (never the one seen when arming). `superseded`: if the level the player meant is no longer the next one (they queued it by hand, or cancelled a queued level), nothing starts and nothing is charged. A manual build of a *different* building does not cancel the reservation.

## Feature flag and rollout

`GC_RESERVE_NEXT_PURCHASE` (environment, read per call):

| Value | Effect |
|---|---|
| `off` / unset (default) | Kill switch. Routes answer `disabled`, the worker does nothing, payload has no `reservation` key, the autoplay guard stays silent. Armed rows are left to expire; nothing is charged, nothing needs migrating back. |
| `test` | Only player ids in `GC_RESERVE_NEXT_PURCHASE_USER_IDS` (comma separated). The owner's test account first. |
| `on` | Everyone on that service. |

The flag is per service, so DEV (`main`) and UNI1 are switched independently. Suggested order: `test` on DEV with the owner's account -> `on` on DEV -> UNI1 through the normal sync PR.

## What changed

* `migrations/189_build_reservations.sql` - one new table, create-only (no existing row touched).
* `game/build_reservations.py` - arm / cancel / evaluate / heartbeat / payload / prune.
* `game/buildings.py` - `queue_build_for_planet(..., reservation=, lock_mode=, dry_run=)`: three keyword-only parameters, defaults give the historical behaviour; plus the payload attach for `build_queue.reservation`.
* `game/tick_runner.py` - one call after the due work; `game/auto_empire.py` - skip builds on a planet with an armed reservation; `game/config.py` - the flag.
* `app.py` - `POST /api/buildings/reserve` and `POST /api/buildings/reserve/cancel` (same idempotency cache and response envelope as `/api/buildings/upgrade`).
* `templates/buildings.html`, `static/main.js`, `static/style.css`, `locales/*.json` - Reserve button, strip, notices (square corners, 21 strings x 8 languages).

## Deviations from the spec (on purpose)

1. **Triggers: heartbeat only.** The spec also evaluates a planet in the same transaction that finishes a job. `queue_build_for_planet` owns its own connection, so calling it from inside `finish_due_work` would wait on the planet lock it already holds. The queue tick (cadence of the existing sidecar) starts a reservation within one tick; because a started build is appended behind running jobs (`start = max(now, last finish)`), the player loses nothing while the queue is busy - only an empty queue waits up to one tick.
2. **No `build_queue.reservation_id` column.** The link job -> reservation lives in `build_reservations.job_id` with a partial unique index, so the hot `build_queue` table is not altered. The guarantee is the same compare-and-swap.
3. **Pre-filter in the heartbeat.** To avoid one write transaction per armed reservation per tick, the worker first compares the planet's stock with the last known price and the queue's free slot (read-only, never authoritative). A wrong estimate costs one wasted owner call or a delay of one tick, never a wrong charge; the estimate is refreshed from the owner's own price.

## Verification done

* `tests/test_gc_reserve_001_build_reservations.py`: 43 tests (SQLite, real migrations applied through `migrate.py`).
* Build / queue / autoplay / tick / game-state / pirate test families (62 files) run side by side on pristine `origin/main` and on this branch in the same environment: **identical result on both** (644 passed, 18 failed, 8 errors, 1 skipped), same failing test ids - the failures are pre-existing in this local environment and not caused by the change. Locale / i18n / migration-number guards: 33 passed.
* Real app, throw-away local database, test account: Reserve button only on affordable-but-unfunded / queue-full cards with met requirements, strip with waiting reason and expiry, cancel, a second process (`python -m game.tick_runner`) starting the build with exactly one price charged, "started" toast shown once.

## Not done / needs proof before any release

* **PostgreSQL:** all tests ran on SQLite. The SKIP LOCKED path, the partial unique indexes and the migration rewrite must go through the repository's PostgreSQL CI jobs before anything is enabled.
* **Browser check:** the UI is covered by static contract tests and the server payload tests, not yet by a browser run (Sentinel) on a seeded account.
* Phase 2 (research) stays out: the measurement shows it can hurt the active style.
* Telemetry for armed / started / cancelled-by-reason and start latency is derivable from `build_reservations` (rows are kept 30 days) but there is no dashboard yet.
* Open owner decisions from the spec (expiry 48 h, strict `affordable_now`, autoplay skips) are implemented as recommended.
