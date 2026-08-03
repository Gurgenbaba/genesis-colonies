# GC-581 — Strategic Worlds (Presentation)

> **Epic:** EPIC-15 · **Status:** ✅ Implementiert · **Stand:** 2026-06-13

Freie Felder auf der Command Map werden zu **Strategic Worlds** — benannte Orte mit Typ, Risiko, Versprechen und Zukunftsaktion. Rein Präsentation + Payload, kein Gameplay.

## Ziel

```text
Vorher:  🟡 Freier Siedlungsplatz
Nachher: ☀ Helios Prime · Mining World · +Ferronit-Potenzial · Risiko: Piratenaktivität
```

Die Karte beantwortet nicht mehr nur „wo kann ich hin“, sondern „**wo will ich hin**“.

## Owner

| Domäne | Modul |
|--------|--------|
| Strategic World Metadaten | `game/planet_evolution/strategic_worlds.py` |
| Feld-Platzierung (Grid) | `game/planet_evolution/world_map.py` |
| Inspector + Nodes | `templates/partials/galaxy_command_map_panel.html` |
| Inspector JS | `static/main.js` — `initCommandMapSiteInspector()` |
| Tests | `tests/test_strategic_worlds.py` |

## Strategic World Types

| `world_type` | Beispiel-Rolle |
|--------------|----------------|
| `mining_world` | Ferronit-Potenzial, Piratenrisiko |
| `research_world` | Scan-Fokus, Forschungsbonus-Hint |
| `industrial_world` | Schiffsbau-Hint |
| `fortress_world` | Verteidigungsposition |
| `expedition_zone` | Artefakte, Wracks, Forschung |
| `ruins_world` | Antike Strukturen |
| `anomaly_zone` | Energie-Anomalie |
| `wreckage_field` | Bergung / Trümmer |

## Node-Payload (pro Feld)

| Feld | Beschreibung |
|------|----------------|
| `name_key` | Deterministischer Ortsname (Pool, z. B. `strategic_world_name_helios_prime`) |
| `world_type` | Kanonischer Typ-Slug |
| `type_key` | Locale-Key für Typ-Label |
| `role_icon` | Map-Marker |
| `risk_level` / `risk_key` | Risiko (Präsentation) |
| `promise_key` | Versprechen / Flavor |
| `reward_hint_key` | Bonus-Hint (**kein echter Bonus**) |
| `future_action_key` | Geplante Aktion (Kolonisierung / Expedition später) |
| `owner_key` | Immer `strategic_world_owner_unclaimed` |

Determinismus: `world_x`, `world_y` → Name + Typ (stable hash, seed 581).

## Inspector (rechts)

Bei Klick auf Strategic World:

- **Typ** (Kicker)
- **Name**
- **Status:** Unbeansprucht
- **Besitzer:** Niemand
- **Risiko**
- **Versprechen**
- **Bonus** (Hint only)
- **Zukünftige Aktion**

## Explizit nicht enthalten

- Keine Kolonisierung (→ GC-582)
- Keine echten Boni / Effekte
- Keine Migration
- Kein `/empire`, kein `/galaxy?view=system`
- Kein Sector Loader, Presence, Warfare

## Akzeptanz

- [x] Freie Felder tragen `name_key`, `world_type`, Risiko, Versprechen, Reward-Hint, Future-Action
- [x] Inspector zeigt Strategic-World-Daten rechts
- [x] Deterministische Namen/Typen pro Koordinate
- [x] Keine Gameplay-Wirkung

## Folge-Tickets

| Ticket | Inhalt |
|--------|--------|
| GC-582 | Dynamic Colonization — [GC-582_DYNAMIC_COLONIZATION.md](GC-582_DYNAMIC_COLONIZATION.md) |
| GC-583 | Expedition Worlds |
| GC-566B | Dynamic Influence |

---

## Player Article

```yaml
---
codex_id: strategic_worlds
band: IV
difficulty: advanced
estimated_read: 4 min
surfaces:
  - quick_help
  - codex
  - faq
  - commander_tips
  - discord
routes:
  - galaxy_view
  - planet_evolution_view
  - empire_view
related_codex:
  - expansion
  - command_map
  - planet_evolution
  - expeditions
  - galaxy
terminology: GENESIS_TERMINOLOGY
unlock:
  type: homeworld_level
  value: 15
teaser_key: codex_unlock_strategic_worlds_teaser
---
```

## Quick Help

**Strategic Worlds** sind benannte Orte auf der Weltkarte mit Typ, Risiko und Versprechen — und zugleich das Reifestadium einer Kolonie nach abgeschlossener Planet Evolution und Spezialisierung.

## Summary

Auf der Command Map werden freie Felder zu **Strategic Worlds**: Mining, Research, Industrial, Fortress, Expedition Zone, Ruins, Anomaly, Wreckage — jeweils mit Namen, Risiko und Flavor. Manche Typen kolonisiert du (Expansion), andere **expeditionierst** du. Im Expansion Protocol ist **Strategic World** außerdem die Phase nach voller Kolonie + Evolution/Spezialisierung.

## Why

Die Karte soll antworten „**wo will ich hin**“, nicht nur „wo ist ein Slot frei“. Typ und Versprechen steuern Erwartung: Ferronit-Potenzial, Forschung, Werft, Festung oder Expedition — Identität vor reiner Slot-Belegung.

## How it works

- Auf der **Weltkarte** Strategic-World-Knoten anklicken → Inspector: Typ, Status, Risiko, Versprechen, geplante Aktion.
- **Kolonisierbare** Typen: über Expansion/Fleet mit Seed Ark beanspruchen (siehe Expansion).
- **Expeditions-Typen** (`expedition_zone`, `anomaly_zone`, `ruins_world`): Mission Expedition, kein Claim als Kolonie.
- Eigene Kolonie kann zur **Strategic World** reifen, wenn Planet Evolution und Spezialisierung abgeschlossen sind — Charakterwelt, keine zweite Genesis Ark.
- Codex-Eintrag öffnet sich mit Ark-Entwicklungsstufe **15** (höhere Expansion-/Welt-Gates).

## Related Systems

- expansion
- command_map
- planet_evolution
- expeditions
- galaxy
- genesis_ark

## Commander Tips

- Inspector lesen, bevor du Flotte bindest — Typ entscheidet Kolonie vs. Expedition.
- Spezialisierung auf eigenen Welten ist dauerhaft; vor der Wahl nachdenken.
- Strategic World ≠ Ersatz-Hauptstadt — die Genesis Ark bleibt Zentrum.

## FAQ

**Ist jede Strategic World eine Kolonie?**
Nein. Manche sind unbeanspruchte Orte; Expeditions-Typen bleiben Erkundungsziele. Kolonien können später den Status Strategic World erreichen.

## Discord Summary

**Strategic Worlds — Orte mit Charakter**

Weltkarte: benannte Typen (Mining, Research, Expedition, Ruinen …). Kolonisieren oder expeditionieren je nach Typ. Reife Kolonien nach Evolution. Codex ab Ark-Stufe 15.
