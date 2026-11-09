# Reserve next purchase - specification (building queue first)

> Design and measurement only. **No game code, migration, template, locale, route or balance value is changed.** The executable reference model `scripts/reserve_next_purchase_model.py` (tests: `tests/test_reserve_next_purchase_model.py`, 33) is a sandbox contract, not game code; the value measurement is `scripts/reserve_next_purchase_analysis.py` (generated tables: `docs/GC_RESERVE_NEXT_PURCHASE_REPORT.md`, tests: `tests/test_reserve_next_purchase_analysis.py`).

## 1. What it is, in one paragraph

A player picks the building they want next on a planet. If they cannot afford it yet, or the queue is full, the game **remembers the intent**. The moment the funds exist and a queue slot is free, the server starts it exactly as if the player had clicked at that moment: the canonical cost is charged then (never at the reservation), the job joins the end of the queue, and the usual timers apply. A reservation holds no resources, adds no resources, shortens no timer and never starts a job earlier than the moment it was evaluated. It is a comfort for players who are not online when the funds arrive.

It is not: a resource lock, a refund trick, a way around the admin queue limit, a free speed-up, or an automatic planner (the player names the building; the game never chooses).

## 2. What the game already does (verified in code)

| Fact | Where | Consequence for the design |
|---|---|---|
| A build is charged **when it is queued** by an atomic conditional `UPDATE planets SET metal = metal - ?, crystal = crystal - ? WHERE id = ? AND metal >= ? AND crystal >= ?`; `rowcount == 1` means paid | `game/models.py` `try_spend_resources_conn`, called from `queue_build_for_planet` (`game/buildings.py`) | The start path reuses the same primitive: no second spending mechanism, no double charge by construction |
| The planet queue already holds several jobs (`queue_limit`, default 3, admin setting; `queue_mode="max"` fills up to 64) and each job is **paid up front** | `_resolve_build_queue_limit`, `queue_build_for_planet` | "Queue ahead" exists only for what is affordable *now*. The gap is exactly the unaffordable next purchase |
| One planet = one write transaction: `begin_write_transaction` + `lock_planet_for_update` (PostgreSQL row lock), background workers use `try_lock_planet_for_update` and skip a planet a request owns | `game/db.py`, `finish_due_work(..., skip_locked_planets=True)` | The start path runs inside that transaction; the worker never waits behind a request |
| Due work is finished lazily on every request that touches the planet, and by the tick runner | `finish_due_work` (`game/queue_engine.py`), `game/tick_runner.py` | Two natural evaluation points: right after a job finished (slot freed), and on every heartbeat |
| A client `request_id` is only a 120 s response cache (`action_idempotency`) | `game/models.py` | It protects an HTTP retry, **not** a durable "charge once": durable idempotency needs a database constraint (section 5) |
| Another automation exists for dormant accounts (`inactive_autoplay`, `plan_passive_planet_tick`) | `game/inactive_autoplay.py`, `game/auto_empire.py` | It must not race a reservation (section 8) |
| Build requests are `POST /api/buildings/upgrade` (`queue_mode`) and `POST /api/buildings/cancel` | `app.py` | The new routes follow this naming (section 9) |

## 3. The value (simulator, corrected model)

`scripts/reserve_next_purchase_analysis.py`, 24 scenarios (one planet S1 and up to eleven S11, three player styles, policy v2, UNI1 curve, 24 months, all simulator invariants hold). The sandbox lever reserves the next purchase and starts it at the exact moment the funds exist (no latency, cost at the start, a stale pick is dropped); it was split into the building half and the research half. Change of empire income against the same style without the feature (full tables: `docs/GC_RESERVE_NEXT_PURCHASE_REPORT.md`):

| Topology | Style | Builds 6 / 12 / 24 mo | Research 6 / 12 / 24 mo | Both 6 / 12 / 24 mo |
|---|---|---:|---:|---:|
| S1 | casual | +61 / +37 / +11 % | +7 / +10 / +3 % | +52 / +36 / +11 % |
| S1 | active | +34 / +14 / +5 % | +9 / +4 / +2 % | +28 / +13 / +4 % |
| S1 | optimizer | 0 / -6 / -1 % | 0 / -6 / -1 % | 0 / -6 / -1 % |
| S11 | casual | +75 / +33 / +10 % | +23 / +15 / +4 % | +36 / +20 / +9 % |
| S11 | active | +6 / -1 / -1 % | -14 / -9 / -4 % | +8 / +2 / +1 % |
| S11 | optimizer | -15 / -10 / -5 % | 0 / 0 / 0 % | -12 / -11 / -3 % |

1. **The building half carries the value.** For the casual style the reserved build is worth +61 % / +37 % / +11 % income at 6 / 12 / 24 months on one planet and +75 % / +33 % / +10 % on eleven; the research half alone is worth +7..23 % at 6 months and about +3..4 % at 24. The two together are *not* the sum (S11 casual +36 / +20 / +9 %): a reserved research waits for the best-stocked world and takes the stock the next building would use.
2. **It is an early-game effect.** At 24 months the income effect is +3..11 %; the cumulative production is +17..18 % (casual, S1) and +14..16 % (casual, S11) ahead. The deepest mine reaches L100 / L150 / L200 20 / 25 / 30 days earlier (casual, S1) and the 11th world comes 16 days earlier (casual, S11). It is a retention feature for the first year, not an endgame one.
3. **Who gains: the player who is away when the funds arrive.** Casual most; active modestly on one planet (+34 / +14 / +5 %) and not at all on eleven; the always-online optimizer not at all. The casual player's income relative to the always-online optimizer *without* the feature rises from 31 / 53 / 80 % to 51 / 73 / 89 % (S1) and from 18 / 36 / 54 % to 31 / 48 / 60 % (S11) at 6 / 12 / 24 months.
4. **The negative rows are the price of a forced commitment, not of the feature as specified.** In the simulator the lever reserves the policy's pick and cannot opt out, so an optimizer whose best next purchase changes pays for stale picks (-5..-15 % on eleven planets). As specified, the player names the item and an always-online player does not use it (an affordable item is refused as `affordable_now`). This is an interpretation: it is not simulated with a player who chooses.
5. **A reserved research can hurt.** For the active style on eleven planets the research-only reservation costs -14 / -9 / -4 %. That is why phase 2 (research) should not ship with phase 1 without its own measurement (section 11).
6. **It is not a pure comfort.** A +33..75 % income difference in months 6-12 for the casual style (building half) is a pacing change for new players, driven by the assumption that a casual player is online twice a day (09:00 and 21:00) and the queue is idle in between. The real size depends on real queue-idle time - the cheapest validation is queue telemetry from DEV / UNI1 (section 12).

## 4. Data model (proposed)

New table `build_reservations` (one migration; next free number on `main` is 189+, never the UNI1-only 183 / 184, guarded by `tests/test_migration_number_reservations.py`):

| Column | Meaning |
|---|---|
| `id` | primary key |
| `player_id`, `planet_id` | owner and planet (ownership is re-checked on every call) |
| `building_type` | what the player wants |
| `expected_level` | the level the player meant (`current + queued + 1` when armed); a mismatch at start means the world moved on |
| `state` | `armed`, `started`, `cancelled`, `expired` |
| `reason` | why it ended (`player`, `replaced`, `superseded`, `invalid`, `expired`) |
| `request_id` | client-generated, `UNIQUE (player_id, request_id)`: the same click twice is one reservation |
| `created_at`, `updated_at`, `expires_at` | audit and expiry (default 48 h, renewable by arming again) |
| `job_id` | the build job it became |

Constraints that carry the guarantees (they hold even if the application code is wrong):

* `UNIQUE INDEX ... ON build_reservations (planet_id) WHERE state = 'armed'` - at most one armed reservation per planet (partial indexes exist in SQLite and PostgreSQL).
* `build_queue.reservation_id UNIQUE NULL` - a reservation can own at most one job.

## 5. State machine

```
            arm (validated, request_id)
   (none) ───────────────────────────────▶ ARMED ──── funds + slot + still valid ───▶ STARTED   (job exists, cost charged once)
                                             │
                                             ├── player cancels ─────────────────────▶ CANCELLED(player)
                                             ├── player arms another with replace ───▶ CANCELLED(replaced)
                                             ├── the next level is no longer the one meant ─▶ CANCELLED(superseded)
                                             ├── requirement / cap no longer holds ──▶ CANCELLED(invalid)
                                             └── expires_at reached ─────────────────▶ EXPIRED
```

A started reservation is cancelled through its job (the canonical queue-refund rules); the reservation itself is final.

## 6. Arming (server-side validation, in this order)

1. Duplicate `request_id` -> return the existing reservation (idempotent).
2. The planet belongs to the caller (`not_owner`), vacation mode is off (`vacation`), the building type is known (`invalid_type`).
3. The target level (`current + queued same type + 1`) is within the cap (`max_level`; for mines the Ascension gate applies) and `has_building_requirements` holds (`requirements`).
4. If it could be started **right now** (affordable and a slot is free) the call is refused with `affordable_now`: the ordinary upgrade action is the right tool and a reservation would only delay it.
5. At most one armed reservation per planet: `reservation_exists`, unless the caller passes `replace`, which cancels the old one in the same transaction.

Arming changes no stock, no queue row and no timer (tested: `test_arm_holds_no_resources_and_changes_no_timer`).

## 7. Starting (one transaction, safe to repeat)

Inside the planet's write transaction (the same one `queue_build_for_planet` uses):

1. Finish due work (a job that just completed frees a slot and raises the level).
2. Load the armed reservation of the planet. None -> nothing to do (a replay is a no-op).
3. Vacation -> `paused` (the reservation stays, expiry is not applied). `now >= expires_at` -> `expired`.
4. Recompute `target = current + queued + 1`. `target != expected_level` -> `superseded` (nothing charged). Cap or requirement lost -> `invalid`.
5. Queue full -> stay armed (`waiting_slot`).
6. Cost = the **canonical cost at this moment** (including the Ascension rebuild share that applies now), never the cost seen when arming. Atomic debit; if it fails -> stay armed (`waiting_funds`).
7. Append the job exactly like a manual enqueue: `start = max(now, last finish)`, so the job waits behind running jobs and never starts earlier than `now` (no backdating).
8. Claim the reservation `armed -> started` with `job_id` (compare-and-swap on `state = 'armed'`); the job row carries `reservation_id`.
9. Commit. Any failure before the commit rolls back the debit, the job and the claim together.

**Why the charge cannot happen twice:** the debit, the job and the claim are one transaction; a second worker or a replay finds `state != 'armed'` and does nothing; and even a buggy second start would violate `UNIQUE (reservation_id)` and roll back. These are tested against a real SQLite database with four threads racing one reservation (exactly one start, one debit), with an injected failure between debit and commit (no trace, the retry charges once), with duplicated heartbeats, and with a random-walk audit that checks `stock + charged == credited` and "one job per reservation" after hundreds of operations (and that the audit itself detects a planted double debit).

## 8. Triggers, cadence, and other actors

| Trigger | What happens |
|---|---|
| A job finishes on the planet (`finish_planet_build_jobs`) | The planet is evaluated right away, in the same caller-owned transaction: a freed slot is used at the finish instant of the previous job |
| Any request that touches the planet | `finish_due_work` runs as today, then the planet is evaluated |
| Background heartbeat (existing tick runner / queue worker) | Evaluates planets that have an armed reservation, with `try_lock_planet_for_update` (skip-locked): it never waits behind a request. Cadence 30-60 s; start latency is therefore at most one heartbeat after the funds exist |
| Stored `eligible_at` (optional) | A non-authoritative estimate (time to afford from the production rates) used only to skip planets in the scan; the atomic debit is the only authority |

Concurrent actors:

* **Manual enqueue of the same building** (the player in another tab, or any automation): the level the reservation meant is gone -> `superseded`, nothing charged. A manual enqueue of a *different* building is allowed and only competes for the queue slot, as it does today.
* **`inactive_autoplay` / `plan_passive_planet_tick`:** a reservation implies a present player. The autoplay planner skips a planet with an armed reservation and never enqueues the reserved building type; conversely a reservation never starts for a player the autoplay is currently driving. (Needs one guard in the planner, covered by a test.)
* **Two workers / two app instances:** the row lock and the compare-and-swap decide; the loser sees `waiting`/nothing.
* **Vacation mode:** the reservation is paused, not cancelled, and expiry does not run while paused.
* **Ascension rebuild jobs and mine evolution:** the start path calls the same validation and cost functions as the manual enqueue; the reservation never bypasses `ascension_required`.
* **Research queue:** separate (section 11); a building reservation never touches research stock.

## 9. API and UI (proposed, to be finalised with the UI owner)

* `POST /api/buildings/reserve` `{building_type, planet_id?, request_id, replace?}` and `POST /api/buildings/reserve/cancel` `{reservation_id}`; the game-state payload carries the planet's reservation (`state`, `building_type`, `expected_level`, `expires_at`, estimated time to afford).
* Where the building card now shows "not enough resources", a **Reserve** button; once armed the card and the queue panel show "Reserved: Metal mine L47 - starts when 12,400 metal / 3,100 crystal are available (about 3 h)" with **Cancel**; a toast when it starts or is cancelled with the reason.
* Square corners (`--gc-radius-*`), all strings in the eight locales (de, en, es, fr, pl, pt, ru, tr).
* Server-rendered state first; polling only through the existing live-state channel.

## 10. Abuse and fairness review

| Concern | Answer |
|---|---|
| Creates or hoards resources | No: nothing is held or granted; audit invariant `stock + charged == credited` holds after random operation sequences |
| Skips timers or the queue order | No: `start = max(now, last finish)`, same as a manual enqueue |
| Gets around the admin queue limit | No: the start waits for a free slot (`waiting_slot`) |
| Prices drift between arming and start | Charged at the price of the moment of the start |
| Forgotten reservation starts something unwanted | Default expiry 48 h, one per planet, `superseded` on any level change, a toast at start |
| Spam (arm/cancel loops) | One armed row per planet by constraint; rate limit on the two routes like `/api/buildings/upgrade` |
| Bots | Server-side only; nothing a bot could not already do by polling the upgrade route |
| Advantage over players who are online | None when online (an affordable build is refused as `affordable_now`); the benefit is for the player who is away when the funds arrive (section 3) |
| Cross-universe | Per-universe table and flag; DEV first, UNI1 later via the sync PR |

## 11. Phasing

1. **Phase 1 - building queues (this document).** One reservation per planet.
2. **Phase 2 - account research queue.** One reservation per account; the payer planet is chosen at start (the best-stocked established world, as the manual path does); same state machine.
3. Not planned: shipyard, defense, troops, fleet.

## 12. Rollout, telemetry, kill switch

* Feature flag per universe (`reserve_next_purchase_enabled`), default off; DEV (main) first for the owner's test account, then enabled for everyone on DEV, then UNI1 through the sync PR.
* Metrics: reservations armed / started / cancelled by reason, **start latency** (start time minus the moment the funds existed), superseded and expired rates, share of players using it, queue-busy share before and after. Success: casual queue-busy share up, no change for the always-online style, `superseded + expired` below 25 %.
* Kill switch: flag off -> armed rows are ignored (not started) and left to expire; nothing is charged, nothing needs migrating back.

## 13. Test plan for the implementation

* Port `tests/test_reserve_next_purchase_model.py` one-to-one against the real owners on SQLite and PostgreSQL (the repository already has PostgreSQL sentinels): arming validation, charge once under replay / race / injected failure, cost at start, superseded, expiry, vacation, skip-locked worker, random-walk audit.
* Autoplay guard test; queue-limit test (admin setting 1 and 64); Ascension rebuild cost test; i18n completeness for the eight locales; PJAX / live-state payload test.
* Regression: `queue_build_for_planet` unchanged for callers that do not reserve (the only touch of the owner is the shared "start" core being callable inside a caller-owned transaction).

## 14. Limits of this document

* The value numbers are a simulator result: latency windows (casual 09:00 and 21:00, active 07 / 12 / 17 / 22, optimizer always) are assumptions about when players are online, not a measurement; the reserved item is the policy's pick, not a human choice, so the staleness cost (a pick that is no longer the best) is likely overstated for a player who names the item themselves.
* The model proves the transaction contract on SQLite; PostgreSQL row-locking behaviour must be re-proved on the real stack (point 13).
* No UI exists yet; the copy and the placement are proposals.

## 15. Decisions for the owner

1. Phase 1 scope: **building queues only is recommended** (the measurement attributes the value to that half; research can hurt the active style on eleven planets). Research in the same release?
2. Expiry: 48 h default and renewable - or no expiry?
3. Visible to everyone at once (flag on DEV) or first only to the test account?
4. `affordable_now` refusal: keep (strict) or auto-convert to a normal enqueue (friendlier, but the client then needs the same code path as the upgrade button)?
5. Autoplay: skip planets with a reservation (proposed) or cancel the reservation when autoplay acts?
