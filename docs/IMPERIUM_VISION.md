# Genesis Colonies 2.0 — Imperium & Expansion Design Manifest

> **Genesis Colonies soll langfristig kein Spiel über das Verwalten von 18 einzelnen Planeten sein. Genesis Colonies soll ein Spiel über die Entwicklung eines Sternenreiches sein. Planet Evolution ist das zentrale Fortschrittssystem. Die Command Map ist die visuelle Darstellung dieses Fortschritts. Alle neuen Systeme müssen auf den bestehenden Planet-Scope-, Fleet-, Galaxy- und Planet-Evolution-Systemen aufbauen und dürfen keine parallelen Architekturen erzeugen.**

Epic: **EPIC-15 Imperium & Expansion** · **MVP shipped** (Command Map, Colonization, Influence) · Vision-Backlog für GC-598+ · Stand: v1.5.9.2

Live-Status: [PROJECT_INVENTORY.md](PROJECT_INVENTORY.md) · Command Map: [GC-570_WORLD_MAP_DIRECTION.md](GC-570_WORLD_MAP_DIRECTION.md)

Referenz-Mockup (Richtung, **keine** 1:1-UI-Vorlage): Command Map / Empire Screen — Regionen, benannte Orte, Einflussgebiete, Handelsrouten, Chokepoints.

---

## Kernthese

> **Expansion ist kein Freischalten eines Planetenslots. Expansion ist der Prozess, unbekannten Raum in einen Teil des eigenen Imperiums zu verwandeln.**

> **Planeten werden nicht freigeschaltet. Sie entstehen.**

**Leitfrage für Design-Entscheidungen:** *Fühlt sich das nach Tabellenverwaltung an — oder danach, dass ein Sternenreich wächst?*

Vollständige Design-Charta: **[EXPANSION_PROTOCOL.md](EXPANSION_PROTOCOL.md)** (EPIC-15 Phase 2).

> **In Genesis Colonies expandiert der Spieler nicht, um mehr Planeten zu besitzen. Er expandiert, um sein Imperium um neue Möglichkeiten zu erweitern.**

**Planet Evolution ist nicht ein weiteres Feature. Planet Evolution ist das Spiel.**

Gebäude, Ressourcen, Forschung und Werft bleiben — sie sind der **Motor unterhalb** der Evolution, nicht der Hauptfortschritt.

### Architektur heute (OGame-Denkmuster)

```text
Gebäude
 ├─ Ressourcen
 ├─ Forschung
 ├─ Werft
 ├─ Flotte
 └─ Planet Evolution
```

### Architektur langfristig (Genesis Colonies 2.0)

```text
Planet Evolution
        │
        ▼
Neue Regionen / Orte
        │
        ▼
Neue Kolonien
        │
        ▼
Neue Spezialisierungen
        │
        ▼
Imperium wächst
```

Der Spieler soll primär sein **Sternenreich entwickeln**, nicht Mine 17 → 18 klicken.

---

## Das eigentliche Problem

Die Galaxy funktioniert technisch als Koordinatenbrowser:

```text
[1:42:7]
[1:42:8]
[1:42:9]
```

Das erzeugt kein Gefühl von Expansion, Territorium, Imperium, Entdeckung oder strategischer Kontrolle. Der Spieler verwaltet viele einzelne Planeten über Listen und Menüs.

**Ziel:** Genesis Colonies soll sich langfristig wie ein lebendiges Sternenreich anfühlen — nicht wie ein OGame-Klon mit Planet Evolution als Add-on.

---

## Empire Screen statt Galaxy

| OGame / heute | Vision |
|---------------|--------|
| Galaxy | **Command Map** (Evolution Layer über Galaxie) |
| Planet auswählen | **Imperium auswählen** |
| Koordinaten `[G:S:P]` | Benannte Orte (Genesis Ark, Titan Forge, Helios Gate) |
| 15 gleichwertige Slots | Genesis Ark + Kolonien mit Rolle |

Die **Genesis Command Map** ist die visuelle Darstellung des Imperiums — nicht Ersatz für das Koordinatenmodell, sondern eine zweite, strategische Ansicht darüber.

---

## Galaxy vs. Empire — strikte Trennung (aktualisiert GC-593)

| Seite | Zweck | Status |
|-------|-------|--------|
| **`/empire`** | Wirtschaft, Produktion, Ressourcen-Matrix | **Nicht anfassen** |
| **`/galaxy`** / **`/galaxy?view=system`** | **Haupt-Galaxy** — klassische Systemansicht, Slots, Fleet-Prefill | **Spieler-Default** |
| **`/galaxy?view=command_map`** | Weltkarte / Command Map | **Dev-Preview only** (`?dev=1` oder Env-Flag) |

```text
Empire     = Wirtschaft = Produktion = Ressourcenübersicht
Galaxy     = Koordinaten [G:S:P] = Slots = Fleet = Kolonisierung
```

**GC-593:** Die klassische Systemansicht ist wieder Hauptnavigation. Die Command Map bleibt im Code als Dev/Legacy-Preview; Koordinatenmodell `[G:S:P]` ist kanonisch.

Siehe [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md), [GC-570_WORLD_MAP_DIRECTION.md](GC-570_WORLD_MAP_DIRECTION.md) (historisch).

### Navigation (aktuell)

```text
/galaxy                    ← Default: klassische Ansicht (view=system)
├─ [ Klassische Ansicht ]  ← Slots 1–15, Expedition Pos 16, Fleet-Shortcuts
└─ [ Weltkarte ]           ← nur Dev-Preview (command_map + dev=1)
```

---

## Genesis Ark — Hauptsitz

Jeder Spieler besitzt **Genesis Ark** als wichtigste Welt des Imperiums.

Technisch: `planets.is_homeworld = 1` (bestehend). Langfristig: Identität, Copy und UI-Fokus auf dem Hauptsitz.

Dort bleiben zentral relevant:

- Gebäude
- Account-Forschung
- Werft
- Planet Evolution (Level, DNA, Events, Discoveries)
- Imperiums-Entscheidungen

**Genesis-Ark-Level entscheidet künftig, welche Orte und Regionen der Spieler betreten darf.**

Beispiel-Gates (illustrativ, Balancing später):

| Genesis Ark Level | Schaltet frei |
|-------------------|---------------|
| 3 | Frontier Outpost |
| 5 | Frontier IX |
| 7 | Bergbaugebiet / Mining-Sektor |
| 10 | Helios Gate |
| 15 | Ancient Sector |
| 20 | Dark Expanse |

Fortschrittskette:

```text
Planet Evolution
      ↓
Expansion (neue Orte / Regionen)
      ↓
Kolonien
      ↓
Imperium
```

Nicht:

```text
Minenlevel → mehr Ressourcen → mehr Minenlevel
```

---

## Kolonien mit Rollen

Nicht jede Kolonie ist langfristig ein vollständiger OGame-Planet. Kolonien bekommen **Rollen**:

| Rolle | Symbol | Phase-1-Ableitung (kein neues Schema) |
|-------|--------|---------------------------------------|
| Mining Colony | ⛏ | Dominante Minen-Gebäude |
| Research Colony | 🔬 | Dominantes Research Lab |
| Shipyard Colony | ⚓ | Dominante Werft |
| Fortress Colony | 🛡 | Dominante Verteidigung |
| Trade Colony | 🏪 | Trade Hub / Handelsgebäude |
| Frontier Outpost | 🌌 | Niedriges Level, wenig Infrastruktur |

Phase 1: Rolle **serverseitig aus Gebäuden ableiten**, nur Anzeige. Keine neue DB-Struktur.

---

## Command Map — Elemente

Das Referenz-Mockup zeigt die **Richtung**, nicht Pixel-Specs.

### Regionen

Beispiele: Genesis Core, Outer Rim, Ancient Sector, Dark Expanse.

Jede Region: Risiko, Belohnungen, Besonderheiten, spätere Inhalte. Mapping über `[G:S]`-Bereiche auf statische Definitionen — Koordinaten bleiben intern.

### Sichtbare Kolonien

Spieler sieht `Genesis Ark`, `Titan Forge`, `Helios Gate` — nicht `[1:42:7]`.

### Einflussgebiete

Eigene Kolonien erzeugen sichtbares Territorium. Spieler erkennt sofort: *Das gehört mir.*

Phase 1: Darstellung. Gameplay-Modifier optional später.

### Handelsrouten

Kolonien über sichtbare Verbindungen verbunden:

```text
Mining Colony → Genesis Ark → Shipyard Colony
```

Backend existiert: `planet_trade_routes` in Planet Evolution. Command Map visualisiert bestehende Routen.

### Chokepoints

Engstellen zwischen Regionen. Kontrolle → Kontrolle über Expansion, Routen, Zugänge. Natürliche Konflikte.

### Anomalien & Discoveries

Discoveries, Events und Expeditionen werden auf der Karte als **Orte** sichtbar — Anbindung an bestehendes Planet-Evolution-System.

---

## Alleinstellungsmerkmal

Genesis Colonies besitzt Systeme, die klassisches OGame nicht hat — **bereits implementiert**:

- DNA, Traits, Discoveries, Events, Policies
- Planet Research, Specializations, Ascension
- Culture, Production Chains, Trade Routes

Spieler-Erlebnis:

```text
Mein Planet hat sich entwickelt
und dadurch habe ich einen neuen Sektor erschlossen.
```

Nicht: `Metallmine 38`.

---

## Was NICHT passieren soll

| Verboten | Grund |
|----------|-------|
| Neues Spiel bauen | Migration auf bestehenden Systemen |
| Bestehende Systeme löschen | Galaxy, Fleet, Buildings bleiben |
| Koordinaten entfernen | `[G:S:P]` bleibt internes Modell |
| Planet Scope brechen | `active_planet_id` / `get_context_planet()` |
| Fleet-System ersetzen | Seed-Ark-Transport bleibt; Etablierung wird eigenes Gameplay ([EXPANSION_PROTOCOL.md](EXPANSION_PROTOCOL.md)) |
| Parallel-Architekturen (GC-000 Regel 15) | Kein zweites Galaxy/Fleet/Evolution-System |
| Frontend-Mechanik-Math (GC-000 Regel 16) | Server authority, EffectResolver |

---

## Technische Leitplanken

**Beibehalten:**

| System | Owner / Doc |
|--------|-------------|
| Planet Scope | `get_context_planet()` — [PLANET_SCOPE.md](PLANET_SCOPE.md) |
| Koordinatenmodell | `game/galaxy.py` — [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md) |
| Fleet & Kolonisierung | [FLEET_SYSTEM.md](FLEET_SYSTEM.md) |
| Planet Evolution | `game/planet_evolution/` — [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md) |
| PJAX / AJAX | [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md) |
| Galaxy-Liste als Fallback | `/galaxy` SSR + GET-Navigation |

**Prinzipien für jedes Ticket:**

1. **Presentation ≠ Model** — Command Map ist Ansicht, kein zweites Galaxy-Backend.
2. **Evolution unlockt Expansion** — Gates in `planet_mechanics` / Level-Unlocks, nicht freie Koordinaten.
3. **Imperium ist sichtbar** — Einfluss, Routen, Regionen aus Ownership + Trade + Evolution abgeleitet.

---

## EPIC-15 — Ticket-Zerlegung

Epic **nicht direkt implementieren**. Jedes Ticket: max. 3–5 Dateien.

| Ticket | Fokus | Phase |
|--------|-------|-------|
| **GC-560** | Empire Identity Layer — Genesis Ark, „Mein Imperium“-Card, Header-Rollen, Basis-Rollen-Ableitung — **[Spec](GC-560_EMPIRE_IDENTITY_LAYER.md)** | 1 |
| **GC-561** | Colony Roles Extended — PlayerCard, weitere UI-Surfaces, Rollen-Algorithmus v2 | 1b |
| **GC-562** | Evolution Unlock Gates — Level → Expansion Sites — **[Spec](GC-562_EVOLUTION_UNLOCK_GATES.md)** | 2 |
| **GC-563** | Command Map MVP — Hub-and-Spoke Graph — **[Spec](GC-563_COMMAND_MAP_MVP.md)** ✅ | 3 |
| **GC-564** | Regions & Sectors — statische Region-Definitionen, `[G:S]`-Mapping, Risiko-Metadaten | 4 |
| **GC-565** | Chokepoints — markierte Systeme, Fleet/Scan-Relevanz | 4 |
| **GC-566** | Influence System — Einflussgebiete visualisieren (Darstellung zuerst) | 5 |
| **GC-567** | Expansion Sites — benannte Kolonisierungs-/Entdeckungsorte statt leerer Slots | 5 |
| **GC-568** | Territorial Warfare — Chokepoint-/Region-Kontrolle im Kampf-/Fleet-Kontext | 6 |

Reihenfolge: **560 → 563 → 562 → 564 → 565 → 566 → 567 → 568** (562 vor 564: Evo-Gates vor Regionen-Dekoration)

Completion-First ([ROADMAP.md](ROADMAP.md)): EPIC-15 startet **nach** Alpha-Tier-1-Close-Out (GC-610-Pass), sofern nicht als reine Docs/Identity-Tickets (560–561) parallel möglich.

---

## Endziel

Genesis Colonies soll sich anfühlen wie:

```text
Die Stämme + Stellaris + OGame + Planet Evolution
```

Der Spieler:

- entwickelt sein Imperium
- erschließt neue Regionen durch Planet Evolution
- entdeckt besondere Orte
- breitet Einfluss aus
- **sieht** sein Sternenreich wachsen

Planet Evolution ist das zentrale Fortschrittssystem. Die Command Map ist seine visuelle Darstellung.

---

## Verwandte Dokumente

- [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md) — bestehendes Evolution-System
- [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md) — Koordinaten, Systemansicht (Fallback)
- [GC-560_EMPIRE_IDENTITY_LAYER.md](GC-560_EMPIRE_IDENTITY_LAYER.md) — ✅ Identität (Header, Rollen)
- [GC-563_COMMAND_MAP_MVP.md](GC-563_COMMAND_MAP_MVP.md) — ✅ Command Map Graph
- [GC-562_EVOLUTION_UNLOCK_GATES.md](GC-562_EVOLUTION_UNLOCK_GATES.md) — 📋 Nächster Schritt: Evo-Gates
- [PLANET_SCOPE.md](PLANET_SCOPE.md) — Active Planet, Empire-Scope
- [FLEET_SYSTEM.md](FLEET_SYSTEM.md) — Kolonisierung, Missionen
- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) — GC-000, Regeln 15–17
- [ROADMAP.md](ROADMAP.md) — Phase 9
- [EPICS.md](EPICS.md) — EPIC-15

---

## Player Article

```yaml
---
codex_id: genesis_ark
band: I
difficulty: beginner
estimated_read: 3 min
surfaces:
  - quick_help
  - codex
  - commander_tips
routes:
  - overview
related_codex:
  - planet_evolution
  - expansion
  - buildings
  - research
terminology: GENESIS_TERMINOLOGY
unlock:
  type: always
---
```

## Quick Help

Die Genesis Ark ist dein Hauptsitz — das Herz deines Imperiums. Hier entwickelst du dein Sternenreich; Gebäude, Forschung und Planet Evolution starten von dieser Welt.

## Summary

Jeder Commander besitzt eine **Genesis Ark** als wichtigste Welt des Imperiums. Sie ist nicht „nur ein Planet“ — sie ist der Sitz deiner Regierung, deiner Account-Forschung, deiner Werft und deiner Planet Evolution. Neue Welten erweitern dein Reich; keine von ihnen ersetzt die Ark.

## Why

Genesis Colonies ist kein Spiel über das Verwalten vieler gleichwertiger Planet-Slots. Es ist ein Spiel über die **Entwicklung eines Sternenreichs**. Die Genesis Ark bleibt der feste Mittelpunkt: Expansion, Kolonien und Spezialisierungen wachsen um sie herum. Die Entwicklungsstufe der Ark entscheidet mit, welche Regionen und Expansion Sites du erreichen kannst.

## How it works

- Nach der Registrierung landest du auf der **Overview** — dein Imperium im Überblick.
- Die Genesis Ark ist deine **Homeworld** — dein fester Hauptsitz im Imperium.
- Auf der Ark baust du zuerst **Produktion** (Ferronit, Crytite, Energie), startest **Account-Forschung** und später die **Orbitalwerft**.
- **Planet Evolution** auf der Ark schaltet neue Regionen und Expansion Sites frei — nicht einzelne Gebäudelevel als Hauptfortschritt.
- **Imperial Directives**, Diplomatie und Ascension bleiben an der Ark bzw. am Imperium — nicht an Außenposten.

## Related Systems

- planet_evolution
- expansion
- buildings
- research
- galaxy

## Commander Tips

- Denke in Imperium, nicht in „Mine 17 → 18“ — die Ark-Entwicklungsstufe öffnet neue Möglichkeiten.
- Account-Forschung und Imperiums-Entscheidungen gehören zur Ark; Planet-Tech gehört zu einzelnen Welten.
- Die Command Map visualisiert dein wachsendes Reich — die Ark bleibt der Hub.

## FAQ

**Was ist mein erstes Ziel?**
Stabile Produktion auf der Genesis Ark, laufende Bau- und Forschungsqueues — und verstehen, dass Planet Evolution der langfristige Fortschritt ist.

**Kann eine Kolonie die Genesis Ark ersetzen?**
Nein. Strategic Worlds sind reife Expansion-Welten, kein zweiter Hauptsitz.

## Discord Summary

**Genesis Ark — Hauptsitz deines Imperiums**

Die Genesis Ark ist der feste Mittelpunkt jedes Sternenreichs: Regierung, Account-Forschung, Werft und Planet Evolution. Expansion erweitert das Reich um neue Welten — nicht um austauschbare Slots. Entwicklungsstufe der Ark schaltet Regionen frei. Keine Kolonie ersetzt die Ark.
