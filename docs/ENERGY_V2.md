# Energy V2 — OGame-inspired power economy research

**Status:** global Candidate A remains simulation-only. The narrow endgame bridge is live: under Nodebuster, Solar may be upgraded beyond the historical Nexus L200 cap while all current supply/demand formulas remain unchanged.

## Why this exists

The current Genesis energy model is intentionally easy to reason about, but it
also makes the energy problem almost self-solving: at the same level,
`solar_energy_base_at_level()` is defined as the combined raw draw of the
Ferronit, Crytite and fuel-cell producers **plus one**. Energy Technology then
reduces mine draw by another 1% per level.

That is convenient in early progression, but it removes most long-term energy
strategy. It also collides with Ascension: production mines can continue beyond
the old building cap while Solar Plant still follows the Nexus-based production
cap.

## What was learned from OGame / clones

The useful pattern is not a literal formula copy. It is the existence of
multiple power choices with different trade-offs:

1. **Solar Plant** — stable, simple, resource-expensive ground power.
2. **Fusion-style source** — a later source whose output strongly benefits from
   Energy Technology and carries an operating/economy trade-off.
3. **Solar Satellites / orbital collectors** — cheap, flexible,
   temperature-dependent power that is exposed to combat loss.
4. **Production allocation** — when the grid is short, the player may lower
   selected producers instead of accepting one uniform empire-wide answer.

Genesis should copy that decision structure while keeping its own names,
resources and long-level curves.

## Candidate A used by the simulator

Candidate A deliberately stays on Genesis' existing `level^1.25` energy scale
so L500–L1000 remains numerically safe and comparable.

### Demand

Three equal-depth producers keep the existing demand weights:

- Ferronit: `10 × level^1.25`
- Crytite: `6 × level^1.25`
- Brennzellen: `8 × level^1.25`

**Energy Technology no longer linearly deletes mine demand.** This avoids the
current long-run march toward the 1% minimum draw floor.

### Solar Plant

`18 × level^1.25`

Ground Solar is stable and no longer defined as "all three mines + 1". With all
three producers and Solar at the same level, the raw grid is about **75%**.
Players can overbuild Solar, add a second source, use orbital capacity, or
improve individual Ascension mines.

The first V2-compatible bridge is now active: Solar is **unbounded in the
Nodebuster Buildings queue**, but it is not an Ascension mine and earns no AP.
This deliberately solves only the L200 structural-cap mismatch; Candidate A's
global Solar coefficient and demand rewrite remain inactive.

### Geothermal Nexus — Fusion role

Candidate direct output:

`4 × level² × (1 + 0.04 × effective Energy Technology)`

with:

`effective Energy Technology = 60 × ln(1 + level / 60)`

Geothermal is intentionally a **stronger second source**, not another tiny
percentage modifier. Energy Technology therefore stays valuable after L50 while
its contribution grows with diminishing returns instead of running away
linearly.

The live tech tree currently caps `energy_tech` at **L50**. Keep that cap while
the legacy `−1 % mine draw/level` behavior is active. Once Energy V2 replaces
that behavior, the protective cap can be removed in a separate migration/UI
slice.

A future active version may add Brennzellen upkeep after the fuel-economy
simulation is complete.

### Orbital Collectors — Satellite role (future content)

Per-unit candidate:

`floor((planet_max_temperature + 160) / 6)`, minimum 1.

This is intentionally OGame-inspired: inner/hot systems get stronger orbital
power, while the units should be combat-exposed. **Do not reuse
`solar_skiff`**; that hull is the Odyssey expedition ship in Genesis.

## Ascension Energy V3 shipped independently of the global rework

The Mine Ascension tree can improve a single mine without replacing the global
energy model:

- **Optimized Energy Use** — 10 ranks, −2% energy draw/rank, maximum −20%.
- **Adaptive Load Balancing** — 10 ranks, requires Optimized Energy 3; each rank
  recovers 2.5% of the *missing* grid efficiency for that mine. At a 60% grid,
  rank 10 makes that mine operate at 70%.

These effects are planet/mine-scoped and flow through the canonical
`EffectResolver` / `ProductionContext` path.

## Rollout gate

Before changing the global live curve:

1. Run `python scripts/sim_energy_v2.py`.
2. Review L50/L100/L200/L300/L500/L650/L1000.
3. Review hot/mid/cold slots (1/8/15).
4. Review Energy Technology 0/20/50/100 candidate behavior.
5. Verify Geo L50 remains meaningful at mine depths L300–L1000.
6. Keep the shipped unbounded-Solar bridge as the live L200+ pressure valve.
7. Add live shadow telemetry comparing current supply/demand with Candidate A.
8. Only then add an explicit `GC_ENERGY_V2_MODE=active` operator switch.
9. After activation, remove the temporary Energy-Tech L50 protection cap.
10. Add per-producer 0–100% allocation and orbital collectors as separate slices.

The current global energy behavior remains the fallback until those gates are
closed.
