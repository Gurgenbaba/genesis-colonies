# Imperial Mandates — Late-Game Colony Capacity

> **Epic:** EPIC-15 Imperium & Expansion × PE Cap  
> **Status:** Implemented (GC-M1–M4)  
> **Owner:** `game/planet_evolution/imperial_mandates.py` → merge in `expansion_protocol.expansion_gameplay_cap`  
> **Stand:** 2026-08-07

---

## Produkt-These

> **Ark-Reife öffnet das Kernreich (sechs Kolonien). Acht Imperial Mandates ermöglichen maximal 15 Welten inklusive Genesis Ark. Ein Cap-Resolver — kein zweites Kolonie-System.**

Spieler-Copy: kein „Slot“, sondern *Reichweite* / Mandate-Name. Siehe [EXPANSION_PROTOCOL.md](EXPANSION_PROTOCOL.md).

---

## Kapazitätsformel

```text
ark_slots          = min(6, table_slots(hw_level))     # L5…L30 only
legacy_slots       = players.expansion_legacy_slots    # Snapshot Bestand
mandate_slots      = count earned mandates             # 0…8
late_slots         = min(8, mandate_slots)              # alte Legacy-Credits maximal 4
directive_bonus    = flags.max_colonies_bonus          # temp
effective_worlds   = 1 + ark_slots + late_slots + directive_bonus
gameplay_cap       = min(effective_worlds, admin_ceiling)  # default 15
```

`can_found_colony` / Fleet colonize blockieren nur **neue** Gründungen — nie bestehende Welten.

### Colony Maturity Gate (PE ≥ 15)

Vor **jeder weiteren** Kolonie (ab der 2.) müssen alle bestehenden Nicht-Heimwelt-Kolonien `planet_level >= 15` haben. Die erste Kolonie ist ausgenommen. Reason: `colony_maturity_required`. Owner: `colony_maturity_gate()` in `expansion_protocol.py`.

### Rechenbeispiele

| Fall | HW | Legacy | Mandates | Directive | Cap |
|------|---:|-------:|---------:|----------:|----:|
| Neu, Ark L10 | 10 | 0 | 0 | 0 | 3 (1+2) |
| Soft-Lock Ark L30, 6 Kolonien | 30 | 0 | 0 | 0 | 7 — nächster Schritt Survey Mandate |
| Bestand früher L40 (8 Ark-Slots alt) | 40 | 2 | 0 | 0 | 9 (1+6+2) |
| Altes Endgame | 30 | 0 | 4 | 0 | 11 |
| Neues Endgame | 30 | 0 | 8 | 0 | 15 |

---

## Migrationsvertrag (flawless)

1. Keine Welt löschen/sperren.
2. Cap sinkt nie unter Stand vor Deploy: einmaliger Lazy-Snapshot `expansion_legacy_slots = max(0, old_extrapolated_ark_slots − 6)`.
3. Der frühere Admin-Default wurde **9 → 11** migriert. Migration 190 hebt **nur Werte 11 → 15** an; abweichende Admin-Limits bleiben unverändert.
4. Idempotent: `expansion_legacy_migrated = 1` verhindert Doppel-Snapshot.

---

## Acht Mandate (sequentiell)

| # | Key | Earn |
|---|-----|------|
| 7 | `survey` | Lifetime completed expeditions ≥ 12 (`expedition_daily_recorded`) — UI: **Expeditionen** |
| 8 | `presence` | ≥ 3 distinct `(galaxy, system)` among owned planets — UI: **Systempräsenz** |
| 9 | `directive` | ≥ 1 vote for galactic directive `expansion` (`gd_votes`) — UI-Name = **`gd_dir_expansion_title`** (DE: Expansionsprotokoll) in **Galaktischer Politik** |
| 10 | `apex` | Any `world_boss_claims` row **or** homeworld `ascension_key` — UI: **World Boss** / **Ascension** |
| 11 | `maturity` | 10 bestehende Kolonien ab PE 15 → Welt 12 |
| 12 | `infrastructure` | 11 Kolonien ab PE 20 → Welt 13 |
| 13 | `dominance` | 12 Kolonien ab PE 15 und mindestens sechs verschiedene Sternsysteme → Welt 14 |
| 14 | `legacy` | 13 Kolonien ab PE 20 und Genesis Ark `ascension_key` → Welt 15 |

Copy-Regel: Mandate-Labels nutzen dieselben Produktnamen wie die Ziel-UI (kein „Expansion-Directive“ neben „Expansionsprotokoll“).

Colony-Maturity-Checkliste zeigt `underleveled` mit Namen + aktueller Stufe; Imperium-Registry zeigt `L{planet_level}`.

Grants are lazy-synced in `ensure_player_mandate_state` (called from `expansion_gameplay_cap`).

---

## UI / Reasons

| Reason | Wann |
|--------|------|
| `planet_evolution_colony_slot_required` | Kernreich — Ark-Stufe zu niedrig |
| `imperial_mandate_required` | Spätreich — nächstes Mandat fehlt |
| `colony_maturity_required` | Bestehende Kolonien noch unter PE 15 |
| `colony_limit_reached` / `expansion_admin_ceiling_reached` | Admin-Ceiling |

Limit-Block + PE Expansion-Checkliste zeigen Mandate-Fortschritt (`current`/`required`), nicht Ark 30/35.

---

## Was PE danach noch tut

DNA, Specs, Ascension, Planet-Tech, Welttypen / Command-Map-Reach (`WORLD_TYPE_GATES`, `interstellar_expansion`). **Nicht** Slot 7+ für neue Progression.

**Schutzregeln:** Historische Ark-Extrapolation gibt höchstens vier Mandate. Die neuen Stufen benötigen tatsächlich vorhandene entwickelte Kolonien. Die Kolonisierung bleibt auf dem bestehenden `can_found_colony`-Pfad. Keine Datenlöschung, kein Reset.
