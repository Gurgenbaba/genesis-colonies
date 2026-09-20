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

If reserved Pirate faction accounts were created before the hard-off, UNI 1 uses
`GC_PURGE_PIRATE_AI_ON_BOOT=1` for one maintenance-worker boot while
`GC_PIRATE_AI_ENABLED=0`. The cleanup is restricted to the exact reserved
`gc_pirate_*` usernames, removes their FK-less Pirate runtime rows, preserves
human accounts, and rebuilds ranking positions. The flag is removed again after
the cleanup has been verified.

Even before the purge completes, public ranking hides reserved Pirate accounts
whenever the deployment hard-off is active, so a human-only universe cannot
present stale AI commanders as ranked players.

## Maintenance

An open UNI 1 requires a live maintenance owner:

- `GC_MAINTENANCE_WORKER=1` (preferred), or
- `GC_EMBEDDED_CRON=1`

The queue worker remains the dedicated short-cadence queue owner.

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

## Public-open gate

`GC_NETWORK_UNI1_OPEN=1` is fail-closed. Production config validation rejects an
open UNI 1 if the x1 profile, q4 Economy V2, first-entry bundle, synthetic hard-offs,
PayPal live configuration, maintenance owner or Nodebuster Ascension ruleset is
missing.

Until every gate is green, UNI 1 remains `GC_NETWORK_UNI1_OPEN=0`.
