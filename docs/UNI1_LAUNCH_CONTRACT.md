# UNI 1 Launch Contract

UNI 1 is the stable public release universe. DEV (`main`) is the continuously
changing development/canary line. UNI 1 deploys from `u2/staging-runtime` only
after an explicit manual promotion.

## Speed profile — true x1

UNI 1 uses `GC_UNIVERSE_SPEED_PROFILE=x1`. The server resolves these universe
speed domains to exactly `1.0`, regardless of historical values persisted in
`game_settings`:

- production
- building construction
- account research
- shipyard / defense production
- peaceful fleet speed
- war fleet speed
- holding fleet speed

Player progression modifiers (research, Nanofactory, Commander, Galactic
Directives, etc.) still apply on top of the x1 universe baseline.

### Progression time floor

Normal progression/production queues have a hard **10-second minimum** after the
complete speed stack. This includes:

- building construction
- account research
- Planet Evolution research
- shipyard production
- defense production
- troop training

Research, Nanofactory, laboratories, Commander effects, directives, universe
settings and timed events may accelerate their domains, but normal calculated
jobs can never collapse to instant/1-second completion. Explicit skip mechanics
such as Timekeeper or deliberate admin actions remain separate from this scaling
floor.


## Economy V2

Required at public launch:

- `GC_ENDGAME_ECONOMY_MODE=active`
- `GC_ENDGAME_PRODUCTION_PIVOT=120`
- `GC_ENDGAME_PRODUCTION_TAIL_POWER=4`

This is the coordinated production/cost/research/progression-score cutover. UNI 1
must not launch on the old permanent exponential tail.

## Mine Ascension — Nodebuster ruleset

**Launch blocker until implemented and regression-tested.**

The currently implemented `phase1-no-reset` mine Ascension is not the final UNI 1
ruleset. UNI 1 requires `ASCENSION_RULESET=nodebuster-v1`.

Binding gameplay direction:

1. Production mines remain unbounded; Ascension is a voluntary progression loop,
   not a permanent max-level gate.
2. The first meaningful Ascension window begins around mine level 200.
3. Ascending resets the selected mine's current level to the run baseline.
4. The achieved run depth determines permanent Evolution/Ascension Points.
5. Points are spent in a permanent per-mine progression tree.
6. The tree must make rebuilding materially faster/stronger and support deeper
   future runs (reconstruction, economy/rebuild efficiency, production,
   storage/QoL and later capstones).
7. The player must see expected point gain, reset consequence, permanent bonuses
   and the next-run benefit before confirming.
8. Server authority owns reset, point grant and tree effects; no client-side
   economy math.
9. The system must preserve the Genesis rule: no permanent hard max level.

Exact point curves, node costs and capstone numbers are balance-owned and must be
locked by tests before the ruleset constant changes to `nodebuster-v1`.

## First-entry bundle

- `GC_NETWORK_START_RESOURCE_MULTIPLIER=10`
- `GC_NETWORK_START_TIMEKEEPER_SECONDS=259200` (72 hours)

Granted once when a network account enters UNI 1 for the first time.

## Synthetic activity

UNI 1 launches with human-only activity:

- `GC_INACTIVE_AUTOPLAY_ENABLED=0`
- `GC_PIRATE_AI_ENABLED=0`

Disabled systems must remain silent in worker/operator logs.

## Maintenance

An open UNI 1 requires a live maintenance owner:

- `GC_MAINTENANCE_WORKER=1` (preferred), or
- `GC_EMBEDDED_CRON=1`

The queue worker remains the dedicated short-cadence queue owner.

## Trader Hub

Public launch requires the unified resource Trader to pass an active-world smoke
test for Ferronit, Crytite and Brennzellen in both directions. Score-neutral
trades must not be rejected solely because integer display-score floors cross a
resource divisor boundary. Anti-arbitrage still compares exact canonical 3:2:1
resource value server-side.

## Shop

Public launch requires the real-money shop to be production-ready:

- `SHOP_ENABLED=1`
- `SHOP_TEST_PROVIDER=0`
- `SHOP_ENABLE_STRIPE=0` unless Stripe is deliberately enabled later
- `PAYPAL_MODE=live`
- `PAYPAL_CLIENT_ID`
- `PAYPAL_CLIENT_SECRET`
- `PAYPAL_WEBHOOK_ID`

PayPal secrets are deployment secrets and must never be committed.

## Release isolation

Merging to `main` does not update UNI 1. A release operator deliberately promotes
the reviewed current `main` SHA with the manual promotion workflow. Normal target
cadence is a bundled release (for example weekly), not continuous deployment.

## Final prelaunch normalization

UNI 1 remains closed while the final release is deployed. Before public opening,
the maintenance worker runs a **single tokenized reset** via
`GC_UNI1_PRELAUNCH_RESET_TOKEN`.

The reset is fail-closed and requires:

- current universe is `uni1`
- `GC_NETWORK_UNI1_OPEN=0`
- true x1 profile + active Economy V2 (pivot 120, q4)
- `ASCENSION_RULESET=nodebuster-v1`
- Pirate AI and inactive autoplay deployment hard-offs

The one-shot reset:

1. deletes only the exact reserved `gc_pirate_*` AI accounts
2. clears residual Pirate dynamic state (heat, bases, intel, bot state,
   infiltrations, smugglers, threat/bounty/log rows) while preserving faction
   definitions
3. wipes normal universe gameplay through the canonical account-preserving
   universe reset
4. preserves human accounts, Genesis Network links, inventory/meta ownership and
   legitimate Timekeeper balance
5. rebuilds a fresh homeworld for every account
6. normalizes already-linked human UNI 1 accounts to the same x10 starter
   resources future first-entry players receive
7. tops existing linked humans up to **at least 72h Timekeeper**; balances already
   above 72h are never reduced
8. refreshes their presence timestamp so accidental early entry cannot make them
   launch-day inactive/farmable
9. rebuilds ranking and writes a durable completion marker

The reset token is validated against the **exact** launch starter bundle:
`GC_NETWORK_START_RESOURCE_MULTIPLIER=10` and
`GC_NETWORK_START_TIMEKEEPER_SECONDS=259200`. A missing/default bundle aborts
before any destructive reset begins.

The rollout is deliberately two-stage to make Railway rolling replacement safe:

1. deploy this release to closed UNI 1 **without** a reset token
2. after that release is the currently serving code, add a unique
   `GC_UNI1_PRELAUNCH_RESET_TOKEN` and redeploy

On the tokenized deploy the entrypoint runs the reset **synchronously after
migrations and before maintenance worker, queue worker, or Gunicorn**. Before the
first destructive phase it writes a strict shared DB freeze marker. Any already
serving closed-UNI1 instance on this release sees that marker and returns 503 for
gameplay while health probes remain available. The freeze stays active after the
reset while UNI 1 remains closed; opening UNI 1 releases it.

The same token can never wipe twice: the completion marker is written through a
strict transaction-owned upsert and read back before commit. Any DB lock/error
aborts instead of being swallowed. Subsequent starts with the same token skip.
Production also refuses to boot an **open** UNI 1 unless the durable prelaunch
completion marker exists.

## Public-open gate

`GC_NETWORK_UNI1_OPEN=1` is fail-closed. Production config validation rejects an
open UNI 1 if the x1 profile, q4 Economy V2, first-entry bundle, synthetic hard-offs,
PayPal live configuration, maintenance owner or Nodebuster Ascension ruleset is
missing.

Until every gate is green, UNI 1 remains `GC_NETWORK_UNI1_OPEN=0`.
