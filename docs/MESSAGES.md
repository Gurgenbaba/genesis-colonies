# Messages — Inbox

**Owner:** `game/messages.py` · UI `static/js/messages.js`  
**Route:** `/messages` (`messages_view`)  
**Related:** [ARCHITECTURE.md](ARCHITECTURE.md) · [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) · [FLEET_SYSTEM.md](FLEET_SYSTEM.md)

Server-authored inbox for combat reports, expedition/logistics outcomes, and system notices. Chat remains a separate live surface.

---

## Player Article

```yaml
---
codex_id: messages
band: I
difficulty: beginner
estimated_read: 3 min
surfaces:
  - quick_help
  - codex
  - faq
  - commander_tips
  - discord
routes:
  - messages_view
related_codex:
  - combat
  - fleet
  - logistics
  - expeditions
terminology: GENESIS_TERMINOLOGY
unlock:
  type: always
---
```

## Quick Help

**Nachrichten** (`/messages`) ist dein Posteingang: Kampfberichte, Expeditions-Ergebnisse, Logistik, Systemhinweise und mehr — neben dem Chat offen halten.

## Summary

Der Posteingang sammelt serverautorisierte Berichte und Notices für deinen Commander. Kampf öffnet das volle Report-Modal; Expeditionen und Logistik landen als Event-Karten; System-Mail deckt Allianz, Direktiven und Ops ab. Archivieren und als gelesen markieren sind Client-Aktionen auf Serverzustand.

## Why

Flotten und Events lösen sich auf, während du woanders bist. Nachrichten sind das dauerhafte Log, damit du keinen Kampfausgang, Expo-Fund oder Logistik-Ankunft verpasst.

## How it works

- Öffne **`/messages`** aus der Navigation (immer verfügbar).
- Nach Kategorie filtern; Zeile öffnen für Detail oder Combat Theater.
- Gelesen / alle gelesen / archivieren — ohne lokale Report-Kopien zu erfinden.
- Chat ist separates Live-Social — Messages ist das Report-Archiv.

## Related Systems

- combat
- fleet
- logistics
- expeditions

## Commander Tips

- Nach Flottenankünften prüfen — Kampf- und Expo-Berichte landen hier zuerst.
- Ungelesen-Badge in der Nav bedeutet: etwas wartet.
- Unwichtiges archivieren; wichtige Kampfberichte behalten, bis Verluste geprüft sind.

## FAQ

**Messages vs. Chat?**
Chat ist Live-Unterhaltung. Messages ist der Posteingang für Berichte und System-Mail.

**Wo sind Kampfdetails?**
Kampf-Nachricht öffnen — voller Report / Theater aus dem Inbox-Eintrag.

## Discord Summary

**Nachrichten — Posteingang für Berichte**

`/messages`: Kampf, Expo, Logistik, System. Immer freigeschaltet. Chat bleibt getrennt.
