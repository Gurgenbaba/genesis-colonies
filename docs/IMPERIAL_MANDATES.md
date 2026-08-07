# Imperial Mandates — Late-Game Colony Capacity

> **Epic:** EPIC-15 Imperium & Expansion × PE Cap  
> **Status:** Implemented (GC-M1–M4)  
> **Owner:** `game/planet_evolution/imperial_mandates.py` → merge in `expansion_protocol.expansion_gameplay_cap`  
> **Stand:** 2026-08-07

---

## Produkt-These

> **Ark-Reife öffnet das Kernreich (Kolonien 1–6). Galaktische Mandate öffnen das Spätreich (Kolonien 7–10). Ein Cap-Resolver — kein zweites Kolonie-System.**

Spieler-Copy: kein „Slot“, sondern *Reichweite* / Mandate-Name. Siehe [EXPANSION_PROTOCOL.md](EXPANSION_PROTOCOL.md).

---

## Kapazitätsformel

```text
ark_slots          = min(6, table_slots(hw_level))     # L5…L30 only
legacy_slots       = players.expansion_legacy_slots    # Snapshot Bestand
mandate_slots      = count earned mandates             # 0…4
late_slots         = min(4, legacy_slots + mandate_slots)
directive_bonus    = flags.max_colonies_bonus          # temp
effective_worlds   = 1 + ark_slots + late_slots + directive_bonus
gameplay_cap       = min(effective_worlds, admin_ceiling)  # default 11
```

`can_found_colony` / Fleet colonize blockieren nur **neue** Gründungen — nie bestehende Welten.

### Colony Maturity Gate (PE ≥ 30)

Vor **jeder weiteren** Kolonie (ab der 2.) müssen alle bestehenden Nicht-Heimwelt-Kolonien `planet_level >= 30` haben. Die erste Kolonie ist ausgenommen. Reason: `colony_maturity_required`. Owner: `colony_maturity_gate()` in `expansion_protocol.py`.

### Rechenbeispiele

| Fall | HW | Legacy | Mandates | Directive | Cap |
|------|---:|-------:|---------:|----------:|----:|
| Neu, Ark L10 | 10 | 0 | 0 | 0 | 3 (1+2) |
| Soft-Lock Ark L30, 6 Kolonien | 30 | 0 | 0 | 0 | 7 — nächster Schritt Survey Mandate |
| Bestand früher L40 (8 Ark-Slots alt) | 40 | 2 | 0 | 0 | 9 (1+6+2) |
| Vollausbau | 30 | 0 | 4 | 0 | 11 |

---

## Migrationsvertrag (flawless)

1. Keine Welt löschen/sperren.
2. Cap sinkt nie unter Stand vor Deploy: einmaliger Lazy-Snapshot `expansion_legacy_slots = max(0, old_extrapolated_ark_slots − 6)`.
3. Admin-Default `max_colonies_per_player`: **9 → 11** (DB-Wert `9` wird auf `11` angehoben).
4. Idempotent: `expansion_legacy_migrated = 1` verhindert Doppel-Snapshot.

---

## Die vier Mandate (sequentiell)

| # | Key | Earn |
|---|-----|------|
| 7 | `survey` | Lifetime completed expeditions ≥ 12 (`expedition_daily_recorded`) — UI: **Expeditionen** |
| 8 | `presence` | ≥ 3 distinct `(galaxy, system)` among owned planets — UI: **Systempräsenz** |
| 9 | `directive` | ≥ 1 vote for galactic directive `expansion` (`gd_votes`) — UI-Name = **`gd_dir_expansion_title`** (DE: Expansionsprotokoll) in **Galaktischer Politik** |
| 10 | `apex` | Any `world_boss_claims` row **or** homeworld `ascension_key` — UI: **World Boss** / **Ascension** |

Copy-Regel: Mandate-Labels nutzen dieselben Produktnamen wie die Ziel-UI (kein „Expansion-Directive“ neben „Expansionsprotokoll“).

Colony-Maturity-Checkliste zeigt `underleveled` mit Namen + aktueller Stufe; Imperium-Registry zeigt `L{planet_level}`.

Grants are lazy-synced in `ensure_player_mandate_state` (called from `expansion_gameplay_cap`).

---

## UI / Reasons

| Reason | Wann |
|--------|------|
| `planet_evolution_colony_slot_required` | Kernreich — Ark-Stufe zu niedrig |
| `imperial_mandate_required` | Spätreich — nächstes Mandat fehlt |
| `colony_maturity_required` | Bestehende Kolonien noch unter PE 30 |
| `colony_limit_reached` / `expansion_admin_ceiling_reached` | Admin-Ceiling |

Limit-Block + PE Expansion-Checkliste zeigen Mandate-Fortschritt (`current`/`required`), nicht Ark 30/35.

---

## Was PE danach noch tut

DNA, Specs, Ascension, Planet-Tech, Welttypen / Command-Map-Reach (`WORLD_TYPE_GATES`, `interstellar_expansion`). **Nicht** Slot 7+ für neue Progression.
