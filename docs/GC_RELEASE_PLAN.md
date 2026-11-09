# Genesis Colonies - release plan (proposal)

> A planning document, not a change. **Nothing here is merged, deployed or changed in the live game.** Every item says what evidence exists, what it still needs, and what only the owner can decide. Evidence comes from the stacked analysis PRs #554-#565 and this branch; limits of that evidence are stated per item.

## 0. Ground rules this plan respects

* **A merge to `main` is a production deploy** (DEV and the public domains are one Railway service). `railway.toml` `watchPatterns` exclude `docs/`, `tests/`, `tools/`, `.github/` and `*.md`, but **not `scripts/`** - so merging the analysis stack (`scripts/*.py`, `.gitignore`) would redeploy production although nothing a player can see changes. See decision D1.
* UNI1 gets `main` through a sync branch from `u2/staging-runtime` and a merge commit; UNI1-only migrations 183 / 184 never reach `main`; new `main` migrations are numbered 189+ (`main` is at 188).
* No merge, deployment or live balance change happens without an explicit OK in chat, per item.
* Balance changes ship behind a per-universe flag where possible, DEV first, UNI1 second.

## 1. The three groups at a glance

| Group | Meaning | Items |
|---|---|---|
| **A - safe bugfixes and hygiene** | Small, no value or formula change, tested, reversible | A1 outpost-XP hold (#556), A2 stale locale test, A3 static cache busting (#196), A4 stale-PR triage, A5 analysis-stack merge hygiene |
| **B - playable comfort features** | New player-facing behaviour that adds no resources and no free speed-up, behind a flag | B1 reserve next purchase (builds, then research), B2 best depth shown next to the record, B3 expedition hint for the colony chain |
| **C - balance changes that need more tests** | Change how fast or how much; each needs a design decision plus evidence the current analysis cannot give | C1 colony gate, C2 Ascension V3, C3 expedition XP and loot cap, C4 casual crystal-reset asymmetry, C5 open economy questions |

## 1a. Order of work

Ranked by (certainty of value) x (smallness of risk), then by what unblocks what. Every step ends in an owner OK before anything is merged or deployed.

| Wave | What | Why now | Exit criterion |
|---|---|---|---|
| **0 - decisions and hygiene** (no gameplay change) | D1 how the analysis stack lands; A2 stale locale test; A3 cache busting (#196 rebased); A4 triage of the stale PRs; **T1 expedition-XP telemetry** (read-only, a copy of the DEV / UNI1 database) | Cheap, unblocks Wave 1 and 2, and T1 is the one number that decides C1 | D1 answered, A2 / A3 merged or consciously deferred, T1 numbers in hand |
| **1 - first player-facing changes** | A1 outpost-XP hold (#556) with the DEV sanity check; B2 best depth beside the record; **B1 phase 1 (build reservations) behind a per-universe flag**, first for the owner's test account | A1 is a known defect with a small measured pacing effect; B1 is the best-evidenced feature (casual +33..75 % income at 6-12 months from the building half, no resources created); B2 is display only | A1 verified on a fresh outpost; B1 tested on SQLite and PostgreSQL, flag on for the test account, telemetry flowing |
| **2 - decided by telemetry** | C1 colony gate (PL12 behind a flag, or stay on PL15); B3 expedition hint; decision on C3 | If expedition XP already feeds the colonies, the gate matters little | Owner decision with the T1 numbers |
| **3 - UNI1** | Sync whatever held up on DEV, flags per universe | UNI1 follows `main` through the sync PR; UNI1-only migrations stay out of `main` | Sync PR with green CI and `/health` revision / migrations check |
| **Not scheduled** | C2 Ascension V3, C4, C5 | No robust design yet; the analysis found tension in the mechanism, not a parameter to tune | Owner design decision (see C2), then a new simulation round |


## 2. Group A - safe bugfixes and hygiene

| # | Item | Evidence | Risk | Gate before merge | Blocker |
|---|---|---|---|---|---|
| A1 | **Hold XP on unestablished level-0 outposts** (#556, `fix/pe-outpost-xp-legacy-guard`, +285/-2, 3 files, mergeable, CI green) | Reproduced through the canonical owners (#555 repro test); 5 new tests, 140 passed in the planet-evolution families | Pacing: a new colony levels only after its three establishment buildings exist. Measured (`docs/GC_COLONY_GATE_FINAL.md` section 2.5, 18 style / gate / expedition pairs): 4th world +1.2 days on average, 11th world +2.5 days (later in 14 of 18), 24-month production -0.8 % (ranges -10 ... +9 days and -5.8 ... +6.8 %): a small delay at most, no gate-specific pattern. | One sanity check on a fresh outpost on DEV (`planet_level` stays 0 and `dna_reveal_tier` stays 0 until the buildings exist, then both appear, `planet_xp` unchanged) | Owner OK; "not yet confirmed on a live planet" in the PR |
| A2 | **Stale locale test** (`test_locale_mechanics_descriptions`, issue #557 part 2): the test expects storage tech 15 % per level, the text says 10 % since `a9d544d6` (#413) | Fails on `main` b0d0ba25 (re-run on this branch's base) | None (test only) | Confirm 10 % is the intended value, then update the assertion | Intended value confirmation |
| A3 | **Cache busting per deploy** (#196, +31/-3, 2 files, merges cleanly) | `app.py` `get_asset_version()` reads only the `VERSION` file and the static route is immutable-cached: a JS hotfix without a version bump stays in browsers forever. #196 appends the deploy SHA | Low: every deploy changes every asset URL once (one cold-cache load per player) | Re-run its tests on current `main`; check `/health` revision and asset URLs on DEV | Needed before B1 ships UI changes |
| A4 | **Triage of the stale PRs** #176, #194, #197, #198, #211, #227, #279, #280, #291, #474 | All except #474 (a draft test PR on the UNI1 branch, one failing check) are 715-990 commits behind `main`. Local merge test against `main`: clean for #176, #197, #211, #291 (and #196, A3); conflicts in #280 (2), #279 (2), #227 (1), #198 (1), #194 (9). #176 has 2 failing checks, #474 one | Merging an old patch whose surrounding code changed hundreds of times | For each: still needed on current `main`? If yes rebase and re-test, if no close. #194 (Nexus-to-Ascension contract, 9 conflicts) must be checked against the `nodebuster-v1` ruleset before anything else | Owner: close or keep |
| A5 | **Analysis stack merge** (#554-#565: `scripts/`, `tests/`, `docs/`, `.gitignore`; no `game/`, `migrations/`, `templates/`, `static/`, `locales/`) | Verified on every PR | A no-op production redeploy (see D1) and a large test/CI load | Decide how and when to land it | D1 |

Not safe, therefore **not** in A: issue #557 part 1 (`test_cargo_cap_includes_haulers_not_combat_escorts`): `calculate_expedition_loot_cap` returns 10,002,000 for two haulers (5,000,000 per hauler) where the test expects 52,000 (25,000 per hauler). Either the cap grew by a factor ~190 on purpose and the test is stale, or the cap grew unintentionally. That is a contract decision (C3), not a bugfix.

## 3. Group B - playable comfort features

| # | Feature | Evidence | What it needs | Notes |
|---|---|---|---|---|
| B1 | **Reserve next purchase** - phase 1 building queues, phase 2 research | `docs/GC_RESERVE_NEXT_PURCHASE.md` (full specification), executable reference model with 33 tests (charge-once under replay / race / injected failure, audit), value measured in the corrected model: the building half gives the casual style +61 / +37 / +11 % income at 6 / 12 / 24 months on one planet (+75 / +33 / +10 % on eleven), the research half only +7..23 % at 6 months and it can hurt (active style, eleven planets: -14 / -9 / -4 %), so phase 1 is builds only | One migration (189+), a start core callable inside the caller-owned planet transaction, two routes, UI + eight locales, autoplay guard, flag, telemetry, PostgreSQL re-proof | Comfort with a measurable early-game effect for casual players; it fades by month 24, so it is a retention feature, not an endgame one. A3 first (UI assets) |
| B2 | **Best depth next to the record** (owner decision: universe records keep the current mine level, the best depth is shown separately) | Audit in `docs/GC_ASCENSION_R4_CHECKS.md`: ranking already uses `max(current, best_depth)`; records read the current level (`game/records.py`) | A read-only column/tooltip on the records page, eight locales | Display only; no rule changes. Small |
| B3 | **"Launch expeditions from the colony that holds your chain" hint** | Expedition XP is granted to the *origin planet*, uncapped per day (+75 XP per 10); in the simulator, 3 expeditions per day launched from the colony under development bring the PL15 chain 119-193 days forward (PL12 alone: 131-138), `docs/GC_COLONY_GATE_FINAL.md` section 2.3 | A hint in the colony chain UI | Only informational; whether the mechanic is intended is C3 |

## 4. Group C - balance changes that still need tests

| # | Topic | Where the evidence stands | What is missing | Decision type |
|---|---|---|---|---|
| C1 | **Colony maturity gate** PL15 / PL12 / PL10 | `docs/GC_COLONY_GATE_FINAL.md`: PL12 delivers 61-63 % of PL10's date effect (11th world 131-138 days earlier than PL15, PL10 212-218) and about 60 % of its production lead; the long-run lead is small (+6..10 % income at 48 months, +2..5 % when expeditions feed the colonies); expedition XP moves the chain more than the gate does (3 per day: 119-193 days) | A staged variant (for example PL10 for colonies 2-5, PL15 beyond) is not simulated; real telemetry on how fast players chain today; real expedition rates | Owner (pacing / retention) |
| C2 | **Ascension V3** (First Awakening, record tiers, keep share) | `r4` is a research candidate: 1 of 19 neighbouring parameter sets passes, second-reset gain fails under PL12 / PL10, best response 1.277 under the weaker strategy; AP, ranking and records audits are clean | A design that does not give more to the weaker economy; the owner's open questions (restart below 200 invariant, legacy AP, Ascend-button behaviour after a lifted-ceiling reset); real player telemetry for the casual style. **No more parameter search** | Owner (design), then a second simulation round |
| C3 | **Expedition XP origin rule and loot cap** | Expedition XP: uncapped, origin planet, bonus per 10 per day (`game/activity_xp.py`); loot cap 5,000,000 per hauler (issue #557) | Is expedition XP meant to be a shortcut for the colony gate? Is the loot cap intended? Real expedition rates | Owner (contract) |
| C4 | **Casual crystal-reset asymmetry** (a crystal reset costs the same as a metal reset and is worth about half) | `docs/GC_ASCENSION_R4_CHECKS.md`, casual section | Why casual rebuilds take 3-4 days longer is not measured | Design, after C2 |
| C5 | **Open economy questions from the bottleneck report**: crystal lost to full depots (22-37 % in year 1), `storage_tech` / `buildtime_tech` dominated, fuel unused | `docs/GC_PROGRESSION_BOTTLENECK_REPORT.md` (pre-reconciliation matrix) | Re-measure in the corrected model before touching any value | Analysis first |

## 5. What this plan is not

* It does not recommend merging any Ascension candidate.
* It does not set the colony gate; it gives the owner the numbers (C1).
* It does not claim player behaviour: the simulator's player styles and online windows are assumptions, and the first real telemetry (queue idle time, start latency, expedition rates, colony cadence) would replace several of them (section 6).

## 6. Telemetry that would settle open questions

T1 reads data that already exists (`activity_xp_log`), on a copy of a DEV / UNI1 database. T2 and T3 need a data check first: finished jobs leave `build_queue`, so queue idle time may need a few lines of additive logging (job start / finish per planet) before it can be read.

| # | Question | Source | Settles |
|---|---|---|---|
| **T1** | How much of colony XP comes from expeditions launched *from the colony*, and how many expeditions per day do players really fly? | `activity_xp_log` (`scripts/expedition_xp_telemetry.py --print-sql`, three queries, tested against the real table definition, read-only) | C1, C3, B3 |
| T2 | How long does a planet's build queue sit empty while the player already has the funds, split by how often the player logs in? | Build-queue history (to be confirmed, see above) plus presence data; the sandbox assumes casual 09:00 / 21:00 | The real size of B1; the online-window assumption of every simulator result |
| T3 | Real colony cadence: days between colony foundings per player, and the share of time spent at the maturity gate | Planet creation timestamps (to be confirmed) | C1 (replaces the simulated chain with the observed one) |

## 7. Decisions needed from the owner

| # | Decision | Options | Recommendation |
|---|---|---|---|
| **D1** | How does the analysis stack (#554-#565 and the next one) land - and #511 (archive of incident repro docs and scripts, 20 files under `scripts/`)? The stack touches only `scripts/`, `tests/`, `docs/`, `.gitignore`, but `railway.toml` `watchPatterns` do not exclude `scripts/` | (a) merge as is - one no-op production redeploy per merge; (b) first a tiny `railway.toml` change that excludes the analysis scripts, then the stack; (c) keep the stack as drafts / an archive branch | (b), checked against Railway's watch-path rules; or (c) if the harness is not needed on `main` |
| D2 | A1: merge #556 to `main` after the DEV sanity check on a fresh outpost? | Yes / not yet | Yes - the measured pacing effect is small; the defect is reproduced in the sandbox through the canonical owners and the live confirmation is part of the DEV check |
| D3 | B1 phase 1 (build reservations): go for the implementation behind a flag? Open sub-decisions: expiry (48 h, renewable), `affordable_now` strict refusal, autoplay skips planets with a reservation, first the test account only | Go / not yet | Go, builds only, DEV test account first (`docs/GC_RESERVE_NEXT_PURCHASE.md` section 15) |
| D4 | C1: run T1 first, then choose PL12 behind a flag or stay on PL15? | After T1 / now | After T1 |
| D5 | C3: is expedition XP on colonies meant as a shortcut around the colony gate? Is a loot cap of 5,000,000 per hauler intended (issue #557)? | Intended / cap or rule needed | Needs your intent; both are one-line questions |
| D6 | C2: Ascension V3 stays frozen (no more parameter search). Which open design question first: restart-below-200 invariant, AP kept for legacy farmers (decided: yes), the Ascend button after a reset, or a mechanism whose value does not grow with a weaker economy? | Pick one | The last one: it is what the knife-edge result points at |
| D7 | A4: which stale PRs (#176, #194, #197, #198, #211, #227, #279, #280, #291, #474) are closed and which are re-validated? | Per PR | Re-validate #196 and #194 first; close what a later change superseded |
| D8 | Who runs T1 / T2 against a database copy? | Owner / I can write the T2 and T3 queries once the data is confirmed | Owner runs T1 (one command); I check what T2 / T3 can read and write them |

## 8. Evidence index

| Topic | Document | PR |
|---|---|---|
| Journey simulator, bottleneck matrix | `docs/GC_TRAIT_R3_PLAYER_JOURNEY_GATE.md`, `docs/GC_PROGRESSION_BOTTLENECKS.md` | #554, #555, #558 |
| Ascension in the corrected model | `docs/GC_ASCENSION_SIMULATION.md`, `docs/GC_SIMULATOR_RECONCILIATION.md` | #559, #560 |
| Colony gate PL10 vs PL15, then PL10 / PL12 / PL15 | `docs/GC_COLONY_GATE_PL10_VS_PL15.md`, `docs/GC_COLONY_GATE_FINAL.md` | #561, this branch |
| Ascension rewards, empire fairness, milestones, `r4` checks | `docs/GC_ASCENSION_REWARDS.md`, `..._EMPIRE_FAIRNESS.md`, `..._MILESTONES.md`, `..._R4_CHECKS.md` | #562, #563, #564, #565 |
| Outpost-XP defect | PR description | #556 (fix), #555 (repro tests) |
| Two failing tests on `main` | issue | #557 |
| Reserve next purchase | `docs/GC_RESERVE_NEXT_PURCHASE.md` (+ report) | this branch |

