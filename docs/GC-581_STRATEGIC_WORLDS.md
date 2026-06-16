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
