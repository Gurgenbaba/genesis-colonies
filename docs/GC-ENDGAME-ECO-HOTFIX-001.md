# GC-ENDGAME-ECO-HOTFIX-001 — Endgame Economy Guardrail

Status: staged hotfix / shadow-first rollout

## Problem

The canonical mine curve is `base × level × 1.075^level`. At very high mine levels the permanent 7.5% exponential dominates every other balance lever. The live universe already contains high-level colonies, so a safe correction must not silently rewrite historical production during deployment.

## Rollout contract

The production owner now supports three process-local modes via `GC_ENDGAME_ECONOMY_MODE`:

- `legacy` — historical behavior, no telemetry, default/fail-closed mode.
- `shadow` — historical gameplay output is unchanged; high-level production emits one bounded diagnostic per player/planet/resource/level with the current modifier stack and the candidate-tail result.
- `active` — levels above the configured pivot use the tested C1-continuous polynomial continuation.

`active` is intentionally an operator action. Deploying this code does not activate the new curve by itself.

## Environment controls

- `GC_ENDGAME_ECONOMY_MODE`: `legacy|shadow|active` (default `legacy`)
- `GC_ENDGAME_PRODUCTION_PIVOT`: default `650`, hard-clamped to `120..100000`
- `GC_ENDGAME_PRODUCTION_TAIL_POWER`: default `2`, hard-clamped to `1..8`
- `GC_ENDGAME_SHADOW_MIN_LEVEL`: default `pivot-50` with lower bound `120`

Invalid mode values fail closed to `legacy`.

## Candidate curve

For pivot `P`, legacy output `f(P)`, `x = level - P`, and

`S = 1/P + ln(1.075)`

use:

`tail(P+x) = f(P) × (1 + S×x/q)^q`

where `q` is the tail power.

Properties:

- exact same output at the pivot;
- same first derivative at the pivot;
- monotone and unbounded after the pivot;
- polynomial long-run growth instead of another exponential tier;
- Decimal path remains finite at levels far beyond IEEE-754 range.

## Shadow telemetry

Shadow log prefix: `endgame_economy_shadow`.

Each line includes player id, planet id, resource, level, pivot, tail power, current total output, candidate total output, ratio, production speed, slot, temperature, research multiplier, mine-evolution building modifier, directive/overlay modifier, event modifier, season modifier, energy ratio, and the mining/crystal/drone research levels.

The process keeps a bounded de-duplication set (4096 keys) to avoid poll/log spam.

## Activation safety

Do **not** enable `active` from this hotfix alone until the matching endgame cost/reference-production pass is approved. `economy_balance.py` still derives several price/reference systems from the canonical mine curve, and activation therefore needs a coordinated cost-tail cutover rather than a blind production-only switch.

The safe production deployment sequence is:

1. deploy code with mode `shadow`;
2. verify health, CI and production logs;
3. collect real high-level level/research/modifier stacks;
4. finalize and test endgame cost/reference-production continuation against those live observations;
5. settle all pre-cutover resource ticks to cutover timestamp `T` before changing gameplay mode;
6. switch to `active` only after the coordinated cost cutover has its own rollback path.

## Tests

Dedicated regression file:

`python -m pytest tests/test_endgame_economy_guardrail.py -q`

It covers legacy parity, shadow parity, pivot continuity, monotonic tail growth, exponential taming, active-mode gating, huge-level Decimal safety, one-shot shadow telemetry, and fail-closed invalid configuration.
