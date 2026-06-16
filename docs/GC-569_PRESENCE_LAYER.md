# GC-569 — Galaxy Presence Layer (Overlay)

> **Epic:** [EPIC-15 Imperium & Expansion](IMPERIUM_VISION.md)  
> **Priorität:** **M** — nach GC-570 World Map Direction  
> **Status:** 📋 Superseded by [GC-571_SHARED_WORLD_PRESENCE.md](GC-571_SHARED_WORLD_PRESENCE.md) für Implementierung  
> **Stand:** 2026-06-12  
> **Voraussetzung:** GC-570 📋 · GC-566B 📋

Design: [GC-564B_SPATIAL_COMMAND_MAP.md](GC-564B_SPATIAL_COMMAND_MAP.md)

---

## Leitplanke

> **Command Map (Default) = Mein Imperium allein.**  
> **Präsenz = optionaler Overlay** — Toggle, **Standard AUS**.  
> Fremde Imperien **nie** ohne Opt-in auf derselben Ebene wie Ark/Kolonien.

---

## Drei Schichten — Gesamtvision

```text
Schicht 1  Imperium     Ark, Kolonien, Sites, Nebel     (heute + GC-565/566)
Schicht 2  Chokepoints  Helios Corridor, Pfade            (GC-565)
Schicht 3  Influence    Teal Eigenreich-Fläche            (GC-566)
Schicht 4  Präsenz      🔴🟢🟡 fremde Marker              (GC-569, optional)
```

---

## UI-Konzept

```text
[ Imperium ]  [ Präsenz ]
     ↑ default      ↑ optional
```

| Modus | Inhalt |
|-------|--------|
| **Imperium** | Genesis Ark, Kolonien, Gates, Sites, Nebel, Influence (566) |
| **Präsenz** | + Marker fremder/Allianz-Spieler (aggregiert, kein Voll-Scan) |

```text
            🔴 Enemy Empire
                    ✦
      🟢 Ally              🏛 Du
           🟡 Neutral
```

---

## Scope (MVP — später)

- Toggle in Command Map Header — **kein** Reload
- Daten: aggregierte Galaxy-Präsenz (nicht Live-MMO) — Owner TBD mit [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md)
- Marker `node_kind=presence` — nicht klickbar für Planet-Switch
- **Default:** Präsenz aus, nur Imperiumsschichten

---

## Explizit nicht

- Imperiumskarte dauerhaft mit allen Spielern
- Kampf/Scan an Presence-Markern (GC-568)
- Ersetzen klassischer `/galaxy?view=system`

---

## Reihenfolge

```text
GC-570 World Map → GC-566B Dynamic Influence → GC-571 Shared World (ersetzt GC-569)
```

**Implementierung:** [GC-571_SHARED_WORLD_PRESENCE.md](GC-571_SHARED_WORLD_PRESENCE.md)

---

## Ausgabe (nach Abschluss)

### Root Cause · Changed Files · Tests · Ergebnis
