# GC-599A — Foreign Empire Presence (Backlog)

> **Nicht vor GC-SEC-P0 und nicht vor GC-598.** Nur Presence — keine Missionen.

## Problem

Die Command Map behauptet „Gemeinsame Weltkarte — N Reiche sichtbar“, aber kleinere Fremdreiche wirken wie anonyme Punkte (schwarzer Kreis), während große Reiche (z. B. Aurora Prime) bereits als echtes Imperium lesbar sind.

```text
Aurora Prime     → Name, Struktur, Influence
papa-fanti       → kleiner schwarzer Kreis
```

Das widerspricht dem Versprechen einer **bewohnten, geteilten Weltkarte**.

## Ziel

Fremde Imperien sollen **als Imperien** erkennbar sein — noch ohne Angriff/Spionage-Buttons.

```text
Aurora Prime          papa-fanti
 ○──○                    ○
  \ /                    ▒▒
  ▒▒▒
```

## Scope (geplant)

- Homeworld sichtbar benannt
- 1–2 Kolonien pro sichtbarem Reich (wenn Daten vorhanden)
- Influence-Polygon / Territory-Fill (bestehende Influence-Layer erweitern)
- Verbindungslinien zwischen Kolonien desselben Reiches
- Hover: Reichsname, Spieler, Kolonieanzahl
- Inspector: „Fremdes Reich“ mit DEV-Fallback bis GC-598 (keine fake Mission-CTAs)

## Nicht in Scope

- Spionage / Angriff / Transport / Recycling aus Map (→ **GC-598**)
- Diplomatie / Allianz
- Neue API-Parallel-Systeme — nur bestehende `world_map` / `influence_layer` / `empire_identity` erweitern

## Abhängigkeiten

1. **GC-SEC-P0** — öffentliche Alpha-Sicherheit
2. **GC-599A** — glaubwürdige Fremdpräsenz
3. **GC-598** — Mission Actions im World Inspector
4. **GC-599** — Foreign Worlds / Enemy Nodes vollständig

## Akzeptanz (Entwurf)

- Jedes in „N Reiche sichtbar“ gezählte Reich hat mindestens benannten Homeworld-Knoten + Territory-Hint
- Hover zeigt Reichsidentität ohne leeres Modal
- Keine Regression für eigene Kolonien / Discovery / Activity Feed
- Command Map bleibt DEV Preview bis Mission-Actions live

## Referenzen

- `docs/GC-571_SHARED_WORLD_PRESENCE.md`
- `docs/GC-566_INFLUENCE_LAYER.md`
- `docs/GC-560_EMPIRE_IDENTITY_LAYER.md`
- `docs/GC-597E_FOREIGN_NODE_DEV_FALLBACK.md`
