# GC — 6/12 Month Endgame Magnitude Audit

> Generated/verified against canonical server owners by `scripts/audit_long_horizon_economy.py`.
> This document is a balance review, not a gameplay formula owner.

## Scope

The long-horizon record-mine simulation is deliberately optimistic. It measures
upper bounds, not an expected player route:

- 1 mature world self-funding one record Ferronit mine;
- 11 mature worlds pooling 100% of their mirrored output into one record mine;
- a zero-resource-cost queue ceiling;
- canonical mine upgrade costs and deep progression floors;
- live storage, Trader, energy, research, Timekeeper and shipyard owners.

Normal accounts spend on other mines, energy, research, storage, fleets, defense,
expansion and failed/idle opportunities, so real progression is slower.

## Record-mine anchors

| Topology | 6 months | 12 months |
|---|---:|---:|
| 1 world, self-funded | L237 | L273 |
| 11 mature worlds, fully pooled | L508 | L705 |
| zero resource cost | L769 | L836 |

There is no mine hard cap. The deep queue floor is the calendar guardrail.
Even free deterministic Login/Free-Pass Timekeeper only moves the one-year
zero-resource ceiling from **L836 to L857**.

## Magnitude at the key anchors

| Anchor | Ferronit/h | Next mine cost | Queue floor | AP if reset |
|---|---:|---:|---:|---:|
| 1 world / 6m / L237 | 12.76 B | 1.53 T | 12 s | 2 |
| 1 world / 12m / L273 | 25.14 B | 3.25 T | 16 s | 3 |
| 11 worlds / 6m / L508 | 345.15 B | 71.65 T | 3,922 s | 16 |
| 11 worlds / 12m / L705 | 1.20 T | 336.20 T | 103,762 s | 26 |
| zero-cost / 12m / L836 | 2.25 T | 741.06 T | 294,862 s | 32 |

The first year reaches low-trillion hourly output only in the hostile pooled
upper bound. The problem is therefore not an L2000/year runaway.

## Storage — healthy

Max depot progression still provides a production-relative endgame buffer:

- depot structural maximum used by the audit: L150;
- production-buffer window: **72 hours**;
- capacity is derived from current canonical production rather than a fixed
  late-game integer.

Result: storage remains relevant and does not become an accidental hard cap when
mine output reaches billions/trillions.

## Trader Hub — audit false positive corrected

The first audit accidentally read the legacy `exchange_daily_limit` /
`exchange_daily_limit_max` settings and treated their historical 50 B values
as a runtime hard cap.

The canonical owner `game/exchange.py::resolve_exchange_daily_limit()` does
**not** use those keys. Runtime is:

`max(exchange_daily_limit_min, floor(empire_day_total × daily_limit_pct / 100))`

and the existing regression
`test_exchange_daily_limit_ignores_legacy_admin_cap` explicitly locks this
behavior. At the default 80%, every 6/12-month stress anchor therefore remains
at **80% of empire daily production**. No Trader balance patch is needed here;
the docs/audit were stale, not the runtime.

## Energy — structural L200 wall resolved with a narrow bridge

The audit exposed a real mismatch: production mines were unbounded while Solar
stopped at the historical Nexus L200 structural cap. On cold worlds this became
a hard penalty despite mature Energy Tech and Ascension utility nodes.

The Nodebuster Buildings queue now lets Solar continue past L200 **without**
turning it into an Ascension mine and without changing the global energy formula.
Resolver structural previews can still report the Nexus anchor; mutation
authority is the Buildings queue.

Required Solar for a full grid under the existing live formula:

| Record depth | Slot 15, normal | Slot 15, Optimized Energy X |
|---|---:|---:|
| L508 | L245 | L205 |
| L705 | **L339** | **L284** |
| L836 zero-cost ceiling | L402 | L336 |

This preserves the climate trade-off: cold worlds need more power
infrastructure, but they are no longer mathematically stranded at Solar L200.
Candidate A in `docs/ENERGY_V2.md` remains simulation-only; no global
supply/demand rewrite was required for this fix.

## Research — sequential pacing still matters

The audit uses an intentionally mature research stack: Lab100, Academy50,
Buildtime Tech120 and Research Network Ascension V. It now measures **cumulative**
0→target cost/time, not just the final level.

Optimistic lower bounds at the 11-world / 12-month income anchor:

| Target tech level | Optimistic 0→target floor |
|---|---:|
| L60 | 0.7 d |
| L100 | 8.5 d |
| L120 | 19.5 d |
| L150 | 65.9 d |
| L200 | 268.1 d |

At the 1-world / 12-month income anchor, L120 alone is already ~319 days and
L150 ~1512 days under the same generous fixed-income assumption.

Result: research does **not** currently show the same runaway as pooled mine
production. The L120+ tail remains a long-term progression axis. Re-evaluate
individual tech effects separately (especially linear combat/fleet effects),
but do not globally nerf research pacing from this audit.

## Free Timekeeper / queue skips — material, not runaway

Deterministic rewards only; random container drops are excluded:

- perfect 30-day Login cycle: **146.3 h** Timekeeper-equivalent;
- perfect 365-day Login attendance: **1,757.1 h**;
- one complete Free Battle Pass L1–50: **27.7 h** equivalent, of which 1 h is
  direct Timekeeper;
- zero-resource one-year mine queue ceiling moves only **L836 → L857** when the
  deterministic Login + one Free Pass skip budget is added.

Therefore earned Free Timekeeper changes pacing meaningfully but does not defeat
the deep-mine calendar guardrail.

## Nodebuster AP — not runaway

The full current permanent tree costs **339 AP per mine**.

A reset at the hostile one-year L705 record grants 26 AP. A single deep reset
therefore buys less than 8% of the full tree. The AP economy is not the first
balance problem exposed by this review.

## Military economy — count inflation is the next sink risk

The audit uses the most expensive currently active static hull
(`planet_breaker`) and a Level-50 Orbital Shipyard:

| Anchor | Resource-affordable hulls/h | Yard R0/h | Forge Rank X/h | R0 bottleneck |
|---|---:|---:|---:|---|
| 1 world / 6m | 51,056 | 394,815 | 6,317,100 | resources |
| 1 world / 12m | 100,546 | 394,815 | 6,317,100 | resources |
| 11 worlds / 6m | 1,380,614 | 394,815 | 6,317,100 | queue |
| 11 worlds / 12m | **4,805,599** | 394,815 | 6,317,100 | queue |

Static hull prices stop being a meaningful resource sink in the pooled endgame;
the normal yard becomes the limiter. Stellar Forge can then reopen multi-million
units/hour throughput.

Do not simply multiply all ship prices: fleet counts, Forge campaigns, losses,
fuel, combat value and production throughput need a dedicated long-horizon
military simulation before changing live costs.

## Living Universe / inactive-human fairness

Resolved after this audit: dormant human accounts now pass **no artificial
build/research duration cap** into the shared planner. Their queues use the same
canonical timers as active humans, with one decision per tick and no same-tick
force-complete chain.

The old 900/1200-second constants remain only for compatibility/admin references;
the V6 human path does not consume them.

The shared auto-empire module still contains a 10-hour synthetic Timekeeper refill
for planner-driven Shipyard/Defense actions. Current V6 dormant-human ship and
defense decisions call the canonical domain owners directly and do **not** use
that refill. Pirate/shared AI paths can still opt into it.

Result: Living Universe can continue to choose actions for dormant humans, but it
no longer invents queue speed for them.

## Priority

1. **P1 — Structural-cap consistency audit:** verify remaining capped
   infrastructure against the persistent/no-max progression contract instead of
   waiting for another L500+ mismatch.
2. **P2 — Military long-horizon sink simulation:** quantify Forge rank, fleet
   losses, fuel and combat count inflation before touching prices.
3. **P2 — UX magnitude layer:** compact B/T/Qa display with exact value in
   tooltip/detail surfaces; keep one primary visible information location.
4. **Watch — Global Energy V2:** Candidate A remains a future strategic rework;
   the immediate L200 Solar wall is solved without it.
5. **Watch — Research/AP/Storage:** current audit does not justify a global nerf.

## Regression owner

`tests/test_long_horizon_economy_audit.py` locks the audit invariants.
`.github/workflows/endgame-economy-hotfix.yml` runs the audit on relevant
economy changes.
