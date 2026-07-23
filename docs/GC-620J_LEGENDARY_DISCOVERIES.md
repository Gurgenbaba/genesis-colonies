# GC-620J — Expedition Legendary Discoveries

**Status:** ✅ GC-620J-0 + J-A + J-B live (`lost_colony` / `rogue_ai`, Time-Anomaly-Kompression)  
**Epic:** EPIC-02 Fleet System  
**Voraussetzung:** [GC-620I](FLEET_SYSTEM.md) (Hazards + Treasure) auf `main`  
**Gate:** Weight-Tabelle aktuell **120** Punkte, Loot **60 %** (GC-EXPO-W1)  
**Owner:** `game/expedition_events.py`

---

## Ziel

Sehr seltene Expeditionsereignisse einführen, die sich wie besondere Entdeckungen anfühlen und im Chat teilbar sind — ohne neue DB, ohne Parallel-Logik, ohne permanente Buffs in Phase 1.

Legendary ≠ Jackpot-Farm. Rewards bleiben **unter** `ancient_stash` / Piraten-Salvage-Caps in der Gesamtbilanz.

---

## Nicht Teil von GC-620J

- Achievements / Titel
- Permanente Account-Buffs
- Neue Inventar-Systeme
- DB-Migrationen
- Änderungen an `game/combat.py` / `combat_models.py`
- Lost Colony / Rogue AI Station (Phase 2 — separates Ticket)

---

## Gate: GC-620J-0 — Expo Weight Audit (Pflicht vor Implementierung)

Die Event-Tabelle ist nach **GC-620J-0** **121 Weight-Points / 14 Events**. Legendary (+3× weight 1) bringt Total wieder auf **124**.

### Ist-Stand (nach GC-620J-0, `movement_id`-Roll)

| Kategorie | Events | Weight | Anteil |
|-----------|--------|--------|--------|
| **Loot** | mineral, fuel, debris, distress, ancient_stash | 74 | **61,2 %** |
| **Neutral / Story-leer** | void_scan, sensor_glitch | 16 | 13,2 % |
| **Delay** | nav_interference, ion_storm | 14 | 11,6 % |
| **Combat** | pirate_encounter | 6 | 5,0 % |
| **Hazard (Verlust)** | ancient_minefield | 4 | 3,3 % |
| **Treasure** | lost_container, abandoned_convoy, ancient_derelict | 7 | 5,8 % |
| **Summe** | 14 Events | **121** | 100 % |

### Soll-Richtung (Zielkorridor)

| Kategorie | Ziel | Ist | Delta |
|-----------|------|-----|-------|
| Loot | ~55–60 % | 61 % | ✅ getrimmt (GC-620J-0) |
| Neutral / Story | ~12–15 % | 13 % | ok |
| Delay / Hazard | ~12–15 % | 14,5 % | ok |
| Combat (Piraten) | ~5–7 % | 4,8 % | ok |
| Treasure | ~4–6 % | 5,6 % | ok |
| **Legendary (neu)** | **~1,5–2,5 % gesamt** | 0 % | +3 Events à weight 1 |

### Audit-Aktionen (GC-620J-0, kein neues Feature)

1. **Loot leicht entziehen:** `mineral_deposit` 32 → 28–30 (größter Hebel).
2. **Keine weiteren Mid-Tier-Events** ohne gleichzeitiges Weight-Trim.
3. **Legendary-Budget reservieren:** 3 × `weight: 1` → ~2,5 % bei Total 124.
4. **Sim-Test:** `test_expedition_weight_audit_gc620j0` + `test_expedition_empirical_category_distribution_gc620j0` ✅
5. **Doc-Sync:** `FLEET_SYSTEM.md` ✅

**Nächster Schritt:** GC-620J-A implementieren.

---

## Events Phase 1 (GC-620J-A)

Alle Legendary-Events teilen:

- `severity: "major"`
- `story_tier: "legendary"` im Outcome/Metadata
- `weight: 1` (nach Audit)
- Kein Eintrag in `_EXPEDITION_LOOTBOX_DROPS` Auto-Roll — explizite Resolver
- Report: Legendary-Theme in `messages.js` (`theme: "legendary"`, Badge `fleet_expedition_badge_legendary`)
- Determinismus: eigener `Random(movement_id * prime + salt)` pro Sub-Outcome

### Spatial Rift

**Fantasy:** Flotte durchquert instabilen Raum — Beute verzerrt oder Rückkehr verzerrt.

| Aspekt | Regel |
|--------|-------|
| Sub-Roll | 60 % **Amplified Find** · 40 % **Delayed Return** |
| Amplified | Ressourcen aus schwachem Loot-Profil × `1.4–1.8`, **hard-capped** auf `cargo_total` (kein Jackpot-Mult) |
| Delayed | `delay_extra = flight_seconds × uniform(0.25, 0.55)` |
| Verluste | keine |
| Lootbox | nein |

### Time Anomaly

**Fantasy:** Zeit läuft im Sektor anders — schneller oder langsamer heim.

| Aspekt | Regel |
|--------|-------|
| Sub-Roll | 50 % **Compressed Return** · 50 % **Dilated Return** |
| Compressed | `delay_extra = -flight_seconds × uniform(0.10, 0.25)` → **Clamp ≥ 0** (Phase 1: nur Verkürzung simulieren als „0 Delay Bonus-Text“, kein negative `return_at`) |
| Dilated | `delay_extra = flight_seconds × uniform(0.20, 0.40)` |
| Bonus | 30 % Chance auf kleines Ressourcen-Paket (Profil wie `lost_container`, halbe Mult) |
| Permanenter Buff | **nein** |

> **Phase-1-Vereinfachung:** „Compressed Return“ = Report-Flavor + optional kleine Ressourcen-Bonus, **keine** negative Flugzeit (kein Exploit). Echte Return-Verkürzung → GC-620J-B.

### Ancient Beacon

**Fantasy:** Precursor-Signal — Cache oder Forschungsfragment.

| Aspekt | Regel |
|--------|-------|
| Lootbox | 1× `alien_cache` (70 %) oder `premium_cache` (25 %) oder `research_capsule` (5 %) |
| Ressourcen | optional klein (Profil 0.15–0.30 Mult) |
| Schiffe | nein |
| Salvage | nein |

---

## Mechanik-Owner (keine Parallel-Systeme)

| Need | Bestehende Funktion |
|------|---------------------|
| Delay | `_resolve_event_delay_extra()` + event `delay_multiplier_range` |
| Ressourcen | `_compute_event_loot()` + neues `_EVENT_LOOT_PROFILES` Eintrag pro Legendary |
| Lootbox | `roll_*` Helper + `grant_expedition_lootboxes()` |
| Report | `build_expedition_report()` + `story_tier` Metadata |
| Cap | `_apply_cargo_cap_with_jackpot()` — Legendary **darf** Jackpot-Mult **nicht** triggern (explizit skip) |

---

## Betroffene Dateien

- `game/expedition_events.py`
- `static/js/messages.js`
- `static/style.css`
- `locales/de.json`
- `locales/en.json`
- `docs/FLEET_SYSTEM.md`
- `tests/test_expedition_events.py`

**Nicht anfassen:** `game/combat.py`, `game/fleet.py` (nur wenn `remaining_ships` — hier nicht nötig), DB/Migrationen

---

## UI / Report

- Inbox: `data-theme="legendary"`, Icon `✦` oder `◈`
- Hero-Badge: „Legendary“ / „Legendär“
- Metadata: `story_tier: "legendary"`, `legendary_variant: "amplified"|"delayed"|…`
- Teaser-Hint: kurzer Flavor-Satz (Locale-Key), kein Spoiler der Sub-Roll

---

## Akzeptanzkriterien

- [ ] GC-620J-0 Audit abgeschlossen; Loot-Anteil ≤ ~60 % oder dokumentierte Abweichung
- [ ] `spatial_rift`, `time_anomaly`, `ancient_beacon` in Event-Tabelle (`weight: 1` each)
- [ ] Gesamt-Legendary-Rate ~1,5–2,5 % (Sim-Test über 10k movement_ids)
- [ ] Reports klar als Legendary erkennbar (`story_tier`, Theme, Badge)
- [ ] Rewards hart gecapped — kein Legendary > `ancient_stash` Median bei gleicher Flotte
- [ ] Kein Totalverlust, kein permanenter Buff
- [ ] Determinismus: gleiches `movement_id` → gleiches Outcome
- [ ] Tests grün: `pytest tests/test_expedition_events.py`

---

## Ticket-Split (empfohlen)

| Ticket | Inhalt |
|--------|--------|
| **GC-620J-0** | Weight Audit + `mineral_deposit` Trim + Distribution-Test |
| **GC-620J-A** | Spatial Rift + Time Anomaly + Ancient Beacon (Phase 1) |
| **GC-620J-B** | Echte Return-Verkürzung (Time Anomaly), Lost Colony / Rogue AI — **später** |

---

## Referenz-Docs

- [ ] [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) — Owner `expedition_events.py`, keine Parallel-Engine
- [ ] [FLEET_SYSTEM.md](FLEET_SYSTEM.md) — Expedition Event Keys
- [ ] GC-620G/H/I — Piraten, Salvage, Hazards, Treasure (Vorgänger)

---

## Ausgabe (nach Abschluss)

### Root Cause

### Changed Files

### Tests

### Ergebnis
