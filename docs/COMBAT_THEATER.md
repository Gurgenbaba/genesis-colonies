# Combat Encounter Theater — Genesis Colonies

Cinematic face-off playback for combat reports. Server resolves battles as today; the client stages a dual-formation confrontation from report metadata before revealing the full report.

**Status:** ✅ GC-CT-001…005  
**Owner:** `static/js/combat_theater.js` (+ presentation hooks in `static/js/messages.js`)  
**Timeline contract (test mirror):** `game/combat_theater.py`  
**Epic:** Combat Encounter Theater (presentation layer on EPIC-08 Combat)

---

## Architecture (GC-000)

| Concern | Owner | Notes |
|---------|--------|--------|
| Battle resolution | `game/combat.py` + `game/fleet.py` | Unchanged — theater never computes losses |
| Report metadata | `build_combat_report()` | `attacking_ships`, `defending_ships`, `defending_defense`, `rounds[]`, winner |
| Theater playback | `GC.combatTheater` in `static/js/combat_theater.js` | Timeline from meta only |
| Timeline contract (pytest mirror) | `game/combat_theater.py` | Must stay in sync with JS `buildTimeline` |
| Cutout paths | `fleet_defs.ship_battle_icon_path`, `defense_defs.defense_battle_icon_path` | Fallback to normal icons |
| Combat report modal | `templates/partials/combat_report_modal.html` + `messages.js` | Opens theater first for combat kind |
| World Boss stage | `GC.modules.world_boss` | Separate owner; may reuse cutout URLs / projectile tokens; attack salvo SFX via `GC.playFightSalvoSound` |

**Forbidden:** frontend combat math; second combat engine; mid-fight player choices that alter outcomes; parallel report metadata builders; global CSS changes that break queue/cards.

---

## Player flow

1. Open combat report (Inbox / HoF / Chronicles).
2. Modal shows **Theater** stage (not numbers-first).
3. Playback: per combat round → attacker 2–3 salvos → side-switch beat → defender 2–3 salvos → resolve losses from `rounds[]`.
4. Finale shows winner + **Open report** / Replay — report appears **only** on click (or Skip). **No auto-reveal.**
5. Skip always available; `prefers-reduced-motion` → jump to finale, still requires click; Replay after first play.

---

## Salvo model

Per combat round (up to 6):

| Step | Behavior | Beat (approx.) |
|------|----------|----------------|
| Intro | Formations lunge | 650 ms |
| Round announce | Label update | 500 ms |
| Attacker salvos | 2–3 volleys left → right | 820 ms each |
| Side switch | Breath between sides | 420 ms |
| Defender salvos | 2–3 volleys right → left (ships and/or defense) | 820 ms each |
| Resolve | Hit FX + floating losses; counts shrink | 1100 ms |
| Round gap | Pause before next round | 450 ms |

Salvo count (2 or 3) is deterministic from `fleet_id` / round index (cosmetic only). Spike losses prefer 3 salvos.

Target duration **~5–7 s per combat round** with motion on (~16–20 s for a 3-round fight). Skip remains available.

---

## Projectile profiles (cosmetic)

**Per-unit signatures** (GC-CT-FX): each ship/defense key maps to `gc-ct-bolt--{key}` via `projectile_signature()` in `game/combat_theater.py` (JS mirror). Salvos fire **per formation slot** so mixed fleets show mixed bolts.

Legacy families (`kinetic_light` / `laser_mid` / `plasma_heavy` / `missile` / `flak`) remain as documentation aliases / unknown-key fallback (`laser_mid`).

Never used for damage.

---

## Expo pirate bridge (GC-CT-EXPO-001 / GC-EXPO-BATTLE)

`pirate_encounter` resolves via **real** `simulate_battle` (`resolve_pirate_encounter`). After resolve, `publish_expedition_pirate_combat_report` sends an inbox combat message with:

- `combat_kind=expedition_pirate`
- real pirate fleet stacks (`pirate_ships` from `pirate_points`)
- **real** `rounds[]` from battle (`theater_synthetic: false`)
- real attacker/defender losses; recyclers excluded from the fight and always return
- player combat tech applies (`combat_research_applicable: true`); defender tech N/A (NPC)
- battle metadata: `fighting_score`, `pirate_points`, `rounds_fought`

Expedition report (loot/salvage) is unchanged and still sent. Opening the combat report starts Combat Theater.

---

## Assets

| Domain | Cutout path | Fallback |
|--------|-------------|----------|
| Ships | `/static/img/ships/cutout/{key}.png` (+ webp) | `/static/img/ships/{key}.png` |
| Defense | `/static/img/defense/cutout/{key}.png` (+ webp) | `/static/img/defense/{key}.png` |

Generate / refresh: `scripts/generate_battle_cutouts.py`.

Helpers:

- `ship_battle_icon_path(key)` / `GC.shipBattleIconUrl(key)`
- `defense_battle_icon_path(key)` / `GC.defenseBattleIconUrl(key)`

---

## Tickets

| Ticket | Focus | Status |
|--------|-------|--------|
| GC-CT-001 | Master doc + architecture entry | ✅ |
| GC-CT-002 | Ship + Defense cutout pack + path helpers | ✅ |
| GC-CT-003 | Stage shell CSS/DOM | ✅ |
| GC-CT-004 | Playback engine + messages integration + locales + tests | ✅ |
| GC-CT-005 | Skip/Replay polish, pirate theming | ✅ |
| GC-CT-FX-001…003 | Per-unit bolt signatures + CSS | ✅ |
| GC-CT-EXPO-001 | Expo pirate → combat report Theater bridge | ✅ |

---

## Tests

- Timeline contract: salvo counts, profile mapping, defense fires when present
- Per-unit `projectile_signature` coverage for all ships/defense
- Report without rounds still opens (no theater crash)
- Icon path helpers return cutout URLs with expected shape
- Expo pirate synthetic rounds preserve Ratio loss totals
