# GC-RESERVE-001 - reserve the next building (phase 1, buildings only)

Status: **implemented behind a feature flag, default OFF; the four merge gates set by the owner on 2026-11-09 are worked through (see "Merge gates" below).** With the flag off nothing in the game changes (no query, no payload key, no button, no strip markup, no worker work). Not merged, not deployed, not enabled anywhere. Spec and value measurement: `docs/GC_RESERVE_NEXT_PURCHASE.md` on the analysis branch (#566).

## What the player gets

On the buildings page a card that is not affordable (or whose queue is full) shows a small **Reserve** button. One reservation per planet. While it waits, a strip above the queue says what is reserved, what it waits for (resources / a free queue slot / vacation) and when it expires (48 h), with **Cancel**. When the server starts it, the build joins the queue exactly like a manual click; a toast says what happened (started / cancelled and why / expired) once per reservation, even if the player was away.

It is not a resource lock, not a refund trick, not a way around the queue limit, not a speed-up and not an automatic planner: the player names the building; the game never chooses.

## The four protections

| Protection | How it is enforced | Test |
|---|---|---|
| **No double charge** (parallel workers, replays, crashes) | The debit, the job insert and the claim `armed -> started` are ONE transaction inside the canonical owner `queue_build_for_planet`. The claim is a compare-and-swap (`UPDATE ... WHERE state = 'armed'`, `rowcount == 1`); a lost claim rolls the debit and the job back. PostgreSQL: the worker takes the planet row with `FOR UPDATE SKIP LOCKED` and never waits. The database refuses a second armed row per planet and a second reservation per job (partial unique indexes, migration 189). | replay, 4 racing threads, cancel racing the start, injected failure after the debit, random walk with an exact resource ledger; **on PostgreSQL also: 8 workers x 12 rounds, a held planet row, a manual click racing the worker** |
| **No bypass of queue limits** | The start IS `queue_build_for_planet`: same `queue_limit` (admin setting), same level cap and Ascension gate, same requirements, same rebuild-cost share and timers; a full queue keeps the reservation armed (`waiting_slot`). | `queue_limit = 1`, Ascension cap |
| **Atomic processing** | Arming writes one row and touches no stock, queue row or timer. Starting is the owner's single transaction. | arm leaves stock and queue byte-identical |
| **Understandable end states** | `armed -> started`, `cancelled(player / replaced / superseded / invalid)`, `expired`; a worker that lost a race reports `skipped`, never a wrong outcome. The UI says which one, in 8 languages, **also in a tab that stayed open** (see "Idle tab" below). | every state reachable in tests; locale parity; browser pass |

The price is the canonical price **at the moment of the start** (never the one seen when arming). `superseded`: if the level the player meant is no longer the next one (they queued it by hand, or cancelled a queued level), nothing starts and nothing is charged. A manual build of a *different* building does not cancel the reservation.

## Feature flag and rollout

`GC_RESERVE_NEXT_PURCHASE` (environment, read per call):

| Value | Effect |
|---|---|
| `off` / unset / anything unknown (default) | Kill switch. Arm and cancel routes answer `disabled` without touching the database, the worker does nothing, payload has no `reservation` key, the poll version is the legacy one, the strip host is not rendered, the autoplay guard stays silent. Armed rows are left to expire; nothing is charged, nothing needs migrating back. |
| `test` | Only player ids in `GC_RESERVE_NEXT_PURCHASE_USER_IDS` (comma / semicolon separated). The owner's test account first. An empty list admits nobody; the list never switches the feature on by itself. |
| `on` (also `1`, `true`, `yes`, `all`) | Everyone on that service. |

The flag is per service, so DEV (`main`) and UNI1 are switched independently. Suggested order: `test` on DEV with the owner's account -> `on` on DEV -> UNI1 through the normal sync PR.

## What changed

* `migrations/189_build_reservations.sql` - one new table, create-only (no existing row touched).
* `game/build_reservations.py` - arm / cancel / evaluate / heartbeat / payload / prune / poll fingerprint.
* `game/buildings.py` - `queue_build_for_planet(..., reservation=, lock_mode=, dry_run=)`: three keyword-only parameters, defaults give the historical behaviour; plus the payload attach for `build_queue.reservation`.
* `game/tick_runner.py` - one call after the due work; `game/auto_empire.py` - skip builds on a planet with an armed reservation; `game/config.py` - the flag.
* `game/live_state.py` - the diet poll version (the `?since=` short-circuit) carries `[armed id, last ended id]` while the feature is on for the player; without it the key is absent and the hash is the legacy one.
* `app.py` - `POST /api/buildings/reserve` and `POST /api/buildings/reserve/cancel` (same idempotency cache and response envelope as `/api/buildings/upgrade`); the buildings page renders the strip host only while the flag is on for the player.
* `templates/buildings.html`, `static/main.js`, `static/style.css`, `locales/*.json` - Reserve button, strip, notices (square corners, 21 strings x 8 languages).
* `.github/workflows/reserve-next-build.yml` - `reserve-sqlite` and `reserve-postgres` (postgres:16 service, schema applied twice to prove idempotence, then the suite).

## Deviations from the spec (on purpose)

1. **Triggers: heartbeat only.** The spec also evaluates a planet in the same transaction that finishes a job. `queue_build_for_planet` owns its own connection, so calling it from inside `finish_due_work` would wait on the planet lock it already holds. The queue tick (cadence of the existing sidecar) starts a reservation within one tick; because a started build is appended behind running jobs (`start = max(now, last finish)`), the player loses nothing while the queue is busy - only an empty queue waits up to one tick.
2. **No `build_queue.reservation_id` column.** The link job -> reservation lives in `build_reservations.job_id` with a partial unique index, so the hot `build_queue` table is not altered. The guarantee is the same compare-and-swap.
3. **Pre-filter in the heartbeat.** To avoid one write transaction per armed reservation per tick, the worker first compares the planet's stock with the last known price and the queue's free slot (read-only, never authoritative). A wrong estimate costs one wasted owner call or a delay of one tick, never a wrong charge; the estimate is refreshed from the owner's own price.

## Merge gates (owner, 2026-11-09)

### 1. PostgreSQL - done locally on PostgreSQL 16.11 (Docker, same image as CI) and wired into CI

* `python migrate.py` applies the whole chain including 189; a second run applies nothing. The table, the three partial unique indexes (`WHERE state = 'armed'`, `WHERE request_id IS NOT NULL`, `WHERE job_id IS NOT NULL`), the CHECK constraint and the cascading foreign key were read back with `\d`.
* The 43 original contract tests run **unchanged** against PostgreSQL (`GC_RESERVE_TEST_BACKEND=postgres` + `GC_TEST_POSTGRES_URL`), plus PostgreSQL-only tests of real concurrency: a worker leaves at once (`lock_busy`, under 5 s) when another transaction holds the planet row; 8 workers x 12 rounds charge exactly one price per round; two concurrent arms leave exactly one armed row; one request id from 6 threads is one reservation; a manual click racing the worker never charges one level twice. Final state: **73 passed, 1 skipped** (the SQLite-only SQL trace); SQLite: 68 passed, 6 skipped (the PostgreSQL-only ones).
* **Defects the PostgreSQL run found (fixed):** `prune_ended()` returned -1 because the PostgreSQL cursor wrapper reports "0 rows" as -1 (`rowcount or -1`); every other `rowcount == 1` check in the feature is immune (0 and -1 both mean "not mine"). A test leaked an open read transaction that blocked the fixture's `TRUNCATE` (test hygiene, fixed).
* The CI workflow `reserve-next-build.yml` repeats this on every push touching the feature.

### 2. Browser - done on a throw-away local database with a test account (real app, real worker process)

* **Desktop (1280 px) and mobile (375 x 812), all eight languages:** Reserve button on affordable-but-unfunded / queue-full cards only (none on requirement-blocked cards), strip text and wait reason, Cancel, toast "reservation cancelled" - text present, no horizontal page overflow, strip children inside the strip, buttons in the viewport.
* **Expiry:** a worker process expired an armed reservation (no charge); the open tab dropped the strip and showed "Reservation expired without a start (48 h)".
* **Automatic start:** a worker process started it with exactly one price charged (the stock after equals the funded amount minus one price); the open tab showed "Reservation started: Ferronite Mine" once and the queue gained the job.
* **Defect the browser pass found (fixed):** the first expiry run left the open tab showing "armed" for minutes. Cause: the `/api/game-state?since=` short-circuit hashes queues, fleets and notifications, not reservations; an end state that does not touch the queue never changed the version. Fixed (see "Idle tab").
* Not done: the repository's Sentinel (`browser-sentinel` runs in CI on the PR), a real phone, a real PostgreSQL behind the UI.

### Idle tab

While the feature is on for the player, the poll version includes `[armed id, last ended id]` (the cheap probe and the full payload derive the same two facts, tested for equality). A reservation the worker ends reaches an open tab at its next poll; the only delay is the existing process-local "diet probe skip" window (45 s) because the worker is a different process than the web server. Actions through the web process clear that cache, so arming and cancelling are immediate.

### 3. Flag isolation - tested

* Flag values fail closed (unknown, `0`, `false`, `no`, typos -> off); allow-list parsing; empty list admits nobody.
* **A full walk with the flag off** (payload, guard, autoplay, heartbeat, both routes, game state, buildings page, a manual build) issues **no SQL statement that touches `build_reservations`**, adds no payload key, renders no strip host and leaves the manual build path as it was; the same walk with the flag on does touch the table and renders the host (positive control).
* `test` mode: a second, unlisted account cannot arm or cancel, gets no payload key, is invisible to the autoplay guard, and a row of theirs that exists anyway is declined by the heartbeat and by a direct evaluation; the listed account's reservation starts.
* Poll version with the flag off equals the legacy hash (payload unit test; switching the flag off restores the probe value exactly).

### 4. Queue / autoplay regression - classified, no hidden regression

The same 62 queue / build / autoplay / tick / game-state / pirate test files run side by side on pristine `origin/main` (b0d0ba25) and on this branch: **identical on both - 17 failed + 8 errors, the same 25 test ids with the same normalised failure text** (an earlier run of mine said 18 failed; one of those was a flake). Causes, all pre-existing on `main` and none in CI's test lists:

| Count | Cause | Evidence |
|---|---|---|
| 8 errors (`test_gc831_queue_refund` 4, `test_gc833b_queue_cancel_state` 2, `test_gc833_queue_completion_state` 2) | **Stale fixtures**: they build the database with `init_db()` only, then `create_user` writes `users.notify_attack_sound`, a column only migration 131 creates ("table users has no column named notify_attack_sound") | With a local plugin that applies the real migrations first, **all 11 tests of the three files pass on `main` and on this branch** - so the queue refund / cancel / completion behaviour the feature touches is covered and green |
| 10 failures (`test_building_stage`, `test_buildings_card_queue` x2, `test_buildings_ui_preference`, `test_research_card_queue`, `test_building_live_affordability`, `test_gc859` x1, `test_gc861` x3) | **Stale markup contracts**: they search templates / HTML / JS for markers that have moved (`gc-card-queue-block` now lives in a partial, `data-bld-planet-stage`, `fetchpriority="high"` on more than the first card, ...) | identical assertion text on both trees |
| 7 failures (`test_gc858` audit-doc x2, nano diminishing 479 vs 480, `test_gc_pg_build_cancel_single_connection` `KeyError: 'cost_metal_exact'`, `test_gc2621` personal pace, `test_pirate_ecosystem` x2 `noob_protection_blocked`) | **Stale expectations**: documents superseded, a numeric expectation, a test double without a newer column, a pace constant, fresh test accounts now under noob protection | identical assertion text on both trees |

Also compared on both trees: the diet-poll / game-state families that read `game/live_state.py` (94 tests): 92 passed, the same 2 failed (`test_probe_poll_version_matches_compute_for_fixture`, `test_diet_probe_skip_expires_so_nav_badges_reprobe`) - they fail on `main` too.

These stale tests are not fixed here (separate hygiene PR); they are listed so nobody mistakes them for this feature.

## Known limits

* Start latency = one queue tick (deviation 1). An open tab learns of a worker-ended reservation at its next poll, up to about 45 s later (see "Idle tab").
* Existing, not touched here: the toast stack is about 6 px wider than a 375 px viewport (a plain test toast measures the same), and in es / fr / pl / tr / ru / pt the building name `building_metal_mine` reads like the pronoun "mine" ("Ferronite Mío", "Le mien", "Mój", "Benim", "Мой", "Meu") - visible in the strip text. Both are on `main` already.
* A real phone, the Sentinel run and a staging database with real accounts are not covered; DEV is the same Railway service as the public domains (see `docs/GC_556_MERGE_ACCEPTANCE.md` on #566 for the deploy mapping: Railway does not wait for CI).
* Phase 2 (research) stays out: the measurement shows it can hurt the active style.
* Telemetry for armed / started / cancelled-by-reason and start latency is derivable from `build_reservations` (rows are kept 30 days) but there is no dashboard yet.
* Open owner decisions from the spec (expiry 48 h, strict `affordable_now`, autoplay skips) are implemented as recommended.
