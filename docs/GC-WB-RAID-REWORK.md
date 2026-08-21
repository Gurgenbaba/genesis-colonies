# GC-WB-RAID — World Boss Raid Rework

**Status:** Phase A implemented on `feature/world-boss-raid-rework` · Phase B specified  
**Owner:** `game/world_boss.py`  
**Goal:** World Bosses are server raids, not solo farm targets.

## Product intent

A World Boss should create a shared server moment:

```text
Boss appears
  -> everyone can contribute
  -> early burst cannot delete the event
  -> community actions create a shared power window
  -> strong fleets still matter
  -> individual + alliance competition stays meaningful
  -> late fight opens up so low-population servers can still finish
```

The design is inspired by the *structure* of classic mobile raid bosses (pre-boss objectives, shared burst windows, attack multipliers, contribution/guild ranking and critical windows), but keeps Genesis Colonies' own fleet/combat economy. No premium-only raid attack is introduced.

---

## Phase A — Encounter resistance (implemented)

Migration: `152_world_boss_raid_phase_balance.sql`

### Problem

`compute_instant_hp_damage()` maps damage as a fraction of `max_hp`. Therefore another raw HP multiplier does not materially increase the required hit count.

Additionally `_resolve_phase_stacks()` multiplies the chosen defender stacks by remaining HP ratio. Boss definitions without explicit stack overrides can therefore become progressively easier as their HP falls.

### Fix

Every boss phase now owns explicit encounter stacks. Phase values compensate for remaining-HP scaling so effective resistance stays approximately stable or rises slightly through the fight.

The first pass is roughly 7.5x the original catalog resistance. It deliberately does **not** change rewards, contribution ownership, cooldowns, catch/tame or normal combat math.

### Target

- regular players can always participate;
- a strong player remains a visible top contributor;
- the current "one roster deletes the boss" path is substantially reduced;
- later phases do not collapse into easier damage ratios.

---

## Phase B — Raid pacing & community burst

Implement in the existing `game/world_boss.py` owner. Do not create a parallel combat or state system.

### 1. Containment Protocol — first 2 hours

The first two hours are a protected raid-opening window.

Per-player cumulative effective damage uses diminishing returns:

| Personal damage vs max HP | Opening-window effectiveness |
|---|---:|
| 0–5% | 100% |
| >5–10% | 25% |
| >10% | 5% |

After two hours the containment modifier is removed.

**Why:** the strongest commander can lead the board, but cannot erase a freshly spawned event before other players see it. The server can still finish an under-populated boss later.

This is server-side damage application. The client only displays the active modifier.

### 2. Fleet Resonance — shared community meter

Each successful wave adds resonance:

- x1 attack: +1 resonance unit
- x5 attack: +5 resonance units
- unique active participants provide a small one-time event bonus, encouraging broad participation

At the server-defined threshold, **Fleet Resonance** activates for **10 minutes**:

- +50% effective World Boss damage
- +10 percentage points critical chance
- shared visual state/countdown for all players
- after expiry the meter resets and can be built again

Store event-specific resonance in the existing server authority layer (event state/runtime state); never calculate activation in frontend JavaScript.

### 3. Rebalance burst attacks

Current tuning allows extreme burst to remove too much shared HP in one action.

Target constants:

```text
WAVE_HP_FRACTION          0.020 -> 0.0125
MAX_WAVE_HP_FRACTION      0.080 -> 0.0300
OVERKILL_LOG_SCALE        0.150 -> 0.1000
x5 final HP ceiling       45%   -> 12.5%
```

The x5 action remains convenience/burst, not a boss-delete button. It consumes five waves and proportional cooldown exactly as today.

### 4. Raid phases become mechanics, not only visuals

Suggested shared phase language:

| HP | Phase | Intent |
|---|---|---|
| 100–55% | Containment | stable resistance, community assembles |
| 55–25% | Breach | stronger phase stack / higher pressure |
| <=25% | Exposed Core | catch/tame remains available; raid enters finish race |

Boss-specific stack identities remain data-driven in `world_boss_definitions.phases_json`.

### 5. Weak-point / critical loop

Keep the existing server critical owner. Add a deterministic raid-facing gauge rather than more uncontrolled RNG:

- successful attacks charge a personal Target Lock gauge;
- filled gauge guarantees the next World Boss critical;
- critical consumes the gauge;
- Fleet Resonance accelerates Target Lock gain.

No click-minigame is required for MVP. A later presentation ticket may visualize a boss weak point without moving combat truth to the client.

### 6. Competition without winner-takes-all

Keep existing damage and alliance boards, then add MVP markers to the payload/reward presentation:

- Top Damage
- Most Waves
- Resonance Initiator
- Finisher
- Discoverer

These should be recognition / small bonus grants, not rewards large enough to make lower-ranked participation pointless.

### 7. Low-population safety valve

If the event reaches 75% of its lifetime while still active, activate **Last Stand**:

- Containment is already gone;
- +25% server-wide damage;
- no increase to personal ranking damage beyond actual applied HP damage;
- boss can still expire if the server does not participate.

This prevents "community raid" from becoming "small server can never kill it".

---

## Explicit non-goals

- no second World Boss/combat module;
- no frontend damage formula;
- no ship losses for instant World Boss attacks in this ticket;
- no premium-only x50 attack or pay-to-win raid energy;
- no blanket max_hp inflation as the primary difficulty lever;
- no permanent hard solo lock after the opening window.

---

## Acceptance criteria — Phase B

1. A single x1 action can never remove more than 3% max HP.
2. A single x5 action can never remove more than 12.5% max HP.
3. Opening Containment diminishing returns are based on the player's existing event contribution and are applied atomically with HP debit.
4. Fleet Resonance is shared per event, server-authored and lasts 10 minutes.
5. Resonance can activate/expire without page reload and without client-side combat math.
6. x5 still counts as five waves and respects proportional cooldown.
7. Phase 3 catch/tame behavior remains compatible.
8. Contribution, alliance XP, directives and reward claims use **applied** HP damage after raid modifiers.
9. Active events can survive deployment without HP reset.
10. `tests/test_world_boss.py` covers containment boundaries, x1/x5 caps, resonance activate/expire, crit interaction, low-pop Last Stand and idempotent retries.

## QA target

Desired live outcome after telemetry:

- no fresh boss killed by one player in minutes;
- meaningful first-hour participation from multiple commanders;
- strong commander can dominate ranking without automatically owning the kill;
- normal active server kill target: roughly 6–24 hours;
- quiet server still has the full 48-hour window.
