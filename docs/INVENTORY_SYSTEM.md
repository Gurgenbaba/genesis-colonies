# Inventory System — Genesis Colonies

**Owner:** `game/inventory.py`, `game/inventory_loot.py`, `game/inventory_use.py`  
**UI:** `/inventory` (`inventory_view`) · Case Battles Tab · Timekeeper HUD  
**Related:** [TIMEKEEPER_SYSTEM.md](TIMEKEEPER_SYSTEM.md) · [GC-864_LOOT_ECONOMY_REBALANCE.md](GC-864_LOOT_ECONOMY_REBALANCE.md) · [CASE_BATTLES.md](CASE_BATTLES.md) · [COLLECTOR_EXCHANGE.md](COLLECTOR_EXCHANGE.md)

Account-weites Meta-Inventar: Container, Items, Craft, Timekeeper-Einzahlung. Lootboxen sind **meta-only** (keine Ferronit-/Schiff-Drops). Keine zweite Loot-Engine.

---

---
## Player Article

```yaml
---
codex_id: inventory
band: III
difficulty: beginner
estimated_read: 4 min
surfaces:
  - quick_help
  - codex
  - faq
  - commander_tips
  - discord
routes:
  - inventory_view
related_codex:
  - liveops_retention
  - collector_exchange
  - case_battles
  - shop_identity
terminology: GENESIS_TERMINOLOGY
unlock:
  type: route_visit
  route: inventory_view
teaser_key: codex_unlock_inventory_teaser
---
```

## Quick Help

Das **Inventar** unter `/inventory` ist dein Meta-Tresor: Container öffnen, Items nutzen, Timekeeper aufladen und Craft/Exchange anstoßen.

## Summary

Hier landen Lootboxen, Booster, Fragmente und Utility aus Login, Battle Pass, Shop, Story, Expeditionen und Events. Container rollen **nur Meta** (Items/Booster — keine Ferronit-/Schiff-Drops). **Timekeeper** ist das imperiumsweite Zeitkonto: Guthaben aus Items/Rewards, manuell per Blitz auf laufende Queues anwenden. Tabs decken Container, Items und die Relikt-Arena (Case Battles) ab.

## Why

Meta-Progression braucht einen Ort ohne Economy-Druckmaschine. Das Inventar bündelt Verbrauch und Craft, damit Gebäude, Forschung und Kampf serverseitig autoritativ bleiben.

## How it works

- **`/inventory`:** State laden, Container öffnen, Items nutzen/craften.
- Loot-Pools sind meta-only; Sammlerstücke können später im Collector Exchange landen.
- **Timekeeper:** Legacy-Zeititems einzahlen, dann ⚡ auf Bau-/Forschungs-/Werft-/Defense-/PE-Queues — eine Anwendung pro Job-Kopf, Server clamp’t.
- Booster aktivieren serverseitig und erscheinen im State.
- Nav-Badge weist auf Case-Battles oder wichtige Inventory-Attention hin.

## Related Systems

- timekeeper
- collector_exchange
- case_battles
- liveops_retention
- shop_identity

## Commander Tips

- Timekeeper für lange Offline-Jobs sparen; kurze Filler ohne TK durchlaufen lassen.
- Container öffnen, wenn du Boosters sofort brauchst — sonst Inventar voller „später“.
- Fragmente nicht wegwerfen-Mentalität: Lifetime-Stats und Exchange lohnen Sammeln.

## FAQ

**Warum droppt keine Ferronit aus Boxen?**
Absicht (Meta-only). Rohstoffe kommen aus Minen, Handel, Kampf-Debris und Missionen.

**Ist Timekeeper automatisch?**
Nein für menschliche Sessions — du wendest ⚡ bewusst an. (Autoplay/KI ist Ops-Ausnahme.)

**Wo ist die Relikt-Arena?**
Inventar-Tab — Case Battles um versiegelte Container.

## Discord Summary

**Inventar — Container, Items, Timekeeper**

`/inventory`: Meta-Loot öffnen/nutzen, TK einzahlen und auf Queues anwenden. Keine Resource/Ship-Boxen. Case Battles als Tab.
