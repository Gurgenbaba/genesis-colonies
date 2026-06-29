# GC-974A — Policy Tier Semantics (Unlock-only)

> **Status:** ✅ Done  
> **Owner:** `game/planet_evolution/policies.py`

## Root Cause

GC-972C wired `policy_tier` as a **cap** (`def.tier > flag → blocked`). That inverted the seed intent (`unlock_policy_tier: 1`) and caused `governance_t1_civil_admin` to **lock** tier-2 policies that were available before research.

## Kanonische Semantik (Variante B′)

| Regel | Bedeutung |
|-------|-----------|
| `policy_tier` | Unlock-Hinweis (höchste freigeschaltete Policy-Def-Tier-Stufe), **kein Cap** |
| Tier 2+ Policies | Werden **niemals** durch `policy_tier` gesperrt |
| Tier 1 Policies | Erfordern `policy_tier >= 1`, **außer** Legacy: Flag fehlt komplett (`None`) → Tier 1 bleibt offen |
| `policy_unlock:{key}` | Unverändert — explizite Policy-Freischaltung (z. B. `mandatory_overtime`) |

Compile (`mechanics.py`): `unlock_policy_tier` → `flags.policy_tier` mit `max`-Merge bleibt.

## Changed Files

- `game/planet_evolution/policies.py` — Cap entfernt, unlock-only Gate
- `tests/test_planet_evolution.py` — Cap-Test ersetzt
- `locales/*.json` (9 Sprachen) — `desc_pe_gov_t1`, `pe_policy_tier_locked`
- `docs/GC-974_PLANET_EVOLUTION_BALANCING.md` — Paradox als erledigt markiert

## Tests

- `test_governance_t1_does_not_block_tier2_policies`
- `test_policy_tier_absent_keeps_tier2_policies_available`
- Bestehende `policy_unlock`-Tests unverändert grün

## Ergebnis

Governance T1 verschlechtert keine Policies. `martial_law` bleibt vor und nach Zivilverwaltung aktivierbar (Slot/Archetype vorausgesetzt). `mandatory_overtime` bleibt über `policy_unlock` gated.

## Zukunft

- `unlock_policy_tier: 2` kann neue Tier-2-Policies freischalten, ohne bestehende zu sperren
- Optional GC-974B: Tier-1-Pflicht ohne Legacy-Bypass, wenn Product das will (mit Save-Grandfather)
