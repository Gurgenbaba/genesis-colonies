# Auction House — Player Surface

**Owner:** `game/auction_house.py`  
**UI:** `/auction-house` (`auction_house_view`)  
**Related:** [INVENTORY_SYSTEM.md](INVENTORY_SYSTEM.md) · [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md)

Timed lootbox auctions: Commanders bid context-planet resources; winners receive meta containers in Inventory. Event boxes are excluded from rotation.

---

## Player Article

```yaml
---
codex_id: auction
band: III
difficulty: beginner
estimated_read: 3 min
surfaces:
  - quick_help
  - codex
  - faq
  - commander_tips
  - discord
routes:
  - auction_house_view
related_codex:
  - inventory
  - resources
  - trader
terminology: GENESIS_TERMINOLOGY
unlock:
  type: route_visit
  route: auction_house_view
teaser_key: codex_unlock_auction_teaser
---
```

## Quick Help

Das **Auktionshaus** unter `/auction-house` listet rotierende Lootbox-Container. Biete mit Ressourcen vom **aktiven Planeten** — Gewinner erhalten Inventar-Container.

## Summary

Auktionen bieten eine Live-Rotation von Meta-Containern (keine Event-Boxen). Du bietest Ferronit, Crytite oder Brennzellen vom Kontext-Planeten. Listings laufen aus; das höchste gültige Gebot gewinnt und die Box landet im **Inventar**. Keine Schiffe und keine Rohstoff-Stacks als Auktionsloot.

## Why

Auktionen ergänzen einen zeitlich begrenzten Markt für Meta-Loot ohne zweite Ökonomie. Ressourcen-Gebote sinken Vermögen in Container, die du später öffnest — dieselbe Inventar-Pipeline wie andere Belohnungen.

## How it works

- Öffne **`/auction-house`** — aktive Listings, deine Gebote und Rotations-Countdown.
- Gebote vom **aktiven Planeten**-Wallet; Mindeststeigerung und Bid-Limits sind serverseitig.
- Nach Ende erhält der Gewinner den Container im Inventar; Verlierer behalten Ressourcen (außer überbotene Einsätze gemäß Serverlogik).
- Event-Boxen erscheinen nie in der Rotation.
- Nav-Badge kann neue Listings nach dem letzten Besuch markieren.

## Related Systems

- inventory
- resources
- trader

## Commander Tips

- Vor dem Bieten auf einen Planeten mit genug Ressourcen wechseln.
- Restzeit beobachten — Last-Second-Raises sind üblich.
- Gewonnene Boxen landen im Inventar — dort öffnen, nicht auf der Auktionsseite.

## FAQ

**Kann ich hier Schiffe kaufen?**
Nein — nur Meta-Container ins Inventar.

**Woher kommen die Ressourcen?**
Vom aktiven (Kontext-)Planeten — Header-Switcher prüfen.

## Discord Summary

**Auktionshaus — zeitlich begrenzte Container-Gebote**

`/auction-house`: Rotation, Gebote mit Aktiv-Planeten-Ressourcen, Gewinn → Inventar. Keine Event-Boxen. Freischaltung nach erstem Besuch.
