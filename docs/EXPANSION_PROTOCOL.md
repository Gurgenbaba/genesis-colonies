# Expansion Protocol — Design-Charta

> **Epic:** EPIC-15 Imperium & Expansion  
> **Status:** 📋 Design-Charta (noch nicht implementiert)  
> **Stand:** 2026-06-27  
> **Vision:** [IMPERIUM_VISION.md](IMPERIUM_VISION.md) · **Technik heute:** [GC-582_DYNAMIC_COLONIZATION.md](GC-582_DYNAMIC_COLONIZATION.md) · [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md)

Dieses Dokument ist **keine Feature-Liste**. Es ist die verbindliche Design-Charta für alles, was künftig mit Expansion, Kolonisierung und Imperiumswachstum zu tun hat. Tickets GC-920–GC-929 implementieren diese Charta — sie definieren sie nicht neu.

---

## Grundregel

> **Expansion ist kein Freischalten eines Planetenslots. Expansion ist der Prozess, unbekannten Raum in einen Teil des eigenen Imperiums zu verwandeln.**

> **Welten werden nicht freigeschaltet. Sie entstehen.**

### Leitfrage für jedes Design-Ticket

> *Fühlt sich das nach Tabellenverwaltung an — oder danach, dass ein Sternenreich wächst?*

Wenn die Antwort „Tabellenverwaltung" ist → Design überdenken.

---

## Terminologie — Welten, nicht Planeten

In **Spieler-Copy, UI und Dokumentation** bevorzugen wir **Welt** statt Planet:

| Verboten (Copy) | Bevorzugt (Copy) |
|-----------------|------------------|
| Planet kolonisiert | Neue Welt erschlossen |
| Neuer Planet | Neue Welt entdeckt |
| Planet-Slot | — (Begriff existiert nicht) |
| 3 / 9 Planeten | Diese Welt liegt außerhalb der Reichweite deines Imperiums |

Technisch bleibt das Schema bei `planets` / `planet_id` — **kein** DB-Rename. Nur Präsentation und i18n (GC-929).

Ebenso: **Entwicklungsstufe** statt „Planet Level" in der UI.

| Intern (Schema) | Spieler-sichtbar |
|-----------------|------------------|
| `planet_level` | Entwicklungsstufe |
| Genesis Ark Stufe 18 | „Genesis Ark — Entwicklungsstufe 18" |
| Outpost Stufe 0 | „Außenposten — Etablierung" |

---

## Was ist überhaupt eine „Kolonie"?

**Definition:** Eine **Kolonie** ist eine Welt in der Phase **`colony`** — voll spielbar, etabliert, DNA enthüllt. Alles davor ist **keine** Kolonie.

Die Begriffe **Expansion Site**, **Claim**, **Outpost** und **Strategic World** sind **Lifecycle-Phasen**, keine Synonyme für „Kolonie".

### Offizieller Lifecycle (verbindlich)

| Phase | Intern (`expansion_phase`) | Gameplay | DB / State |
|-------|---------------------------|----------|------------|
| **Expansion Site** | `expansion_site` | Nur auf der Command Map sichtbar; noch nicht beansprucht | Site-Definition in `expansion_gates.py`; kein `planets`-Row |
| **Claimed Site** | `claimed_site` | Für den Spieler reserviert; Vorbereitung läuft | `world_claims.status = reserved` |
| **Seed Ark en route** | `seed_ark_en_route` | Flotte unterwegs; Seed Ark transportiert | Fleet-Mission `colonize`; noch kein Outpost |
| **Frontier Outpost** | `frontier_outpost` | Erste Produktion, stark eingeschränkt; Etablierung läuft | `planets`-Row; `colony_maturity = outpost` |
| **Colony** | `colony` | **Voll spielbar** — Werft, Forschung, Planet-Tech frei | `colony_maturity = colony`; Establishment abgeschlossen |
| **Strategic World** | `strategic_world` | Planet Evolution abgeschlossen; Spezialisierung gewählt | `colony_maturity = strategic_world`; Spec aktiv |

```text
Expansion Site → Claimed Site → Seed Ark en route → Frontier Outpost → Colony → Strategic World
```

**Regeln für Entwickler:**

1. Code, UI und Tests referenzieren **`expansion_phase`** — nicht pauschal „planet" oder „colony".
2. Eine Welt ist erst ab Phase **`colony`** eine Kolonie im Spielersinn.
3. **`frontier_outpost`** ist spielbar (primitive Mine, Lager, Solar), aber **keine** Kolonie.
4. **`strategic_world`** ist Endzustand der **Welt-Entwicklung**, nicht Ersatz für die Genesis Ark.
5. Kein paralleles Planet-System (GC-000 Regel 15) — ein Enum auf `planets` + `world_claims` + Fleet-State.

---

## Wann ist eine Kolonie „fertig"? — Meilensteine, nicht Timer

**Etablierung ist kein Warten.** Es gibt **keinen** festen Timer wie „24 Stunden → Kolonie".

Eine Welt wird zur Kolonie, wenn der Spieler **alle Etablierungs-Meilensteine** auf dem Outpost erfüllt hat:

| Meilenstein | Bedeutung |
|-------------|-----------|
| **Habitat errichtet** | Behausung steht; Basis-Infrastruktur vorhanden |
| **Energie stabil** | Energieversorgung dauerhaft gesichert (z. B. Solar/Fuel-Schwelle) |
| **Kommunikationszentrum** | Verbindung zum Imperium / Genesis Ark hergestellt |
| **Erste Bevölkerung** | Mindestbevölkerung / Belegung erreicht |

```text
Habitat + Energie stabil + Kommunikationszentrum + Erste Bevölkerung = Kolonie etabliert
```

**Alle vier** müssen erfüllt sein → Phase wechselt von `frontier_outpost` zu `colony` → DNA-Reveal → volle Spielbarkeit.

Einzelne Gebäude können Bauzeit haben — das ist in Ordnung. Der **Fortschritts-Gate** ist aber **Meilenstein-basiert**, nicht „Warte X Stunden unabhängig vom Spielen".

Implementierung (GC-923):

- Server prüft Meilenstein-Flags (Gebäude-Level, Mechanics, Quest-Steps)
- UI zeigt Checkliste auf Outpost-Panel und Command Map
- **Kein** `establishment_finish_at` als alleiniger Gate

---

## Genesis Ark — unersetzlich

> **Die Genesis Ark bleibt immer das Herz des Imperiums.**

Egal ob der Spieler später 5, 20 oder 50 Welten besitzt — **keine Welt ersetzt die Genesis Ark**.

| Auf der Genesis Ark (immer) | Auf Expansion-Welten (später / eingeschränkt) |
|-----------------------------|-----------------------------------------------|
| Imperiale Regierung | Lokale Produktion, Spezialisierung |
| Account-Forschung | Planet-Tech (Welt-Forschung) |
| Expansion Protocol (Gates, Launch) | Etablierung → Entwicklung |
| Imperial Directives | Events, Discoveries |
| Diplomatie | Trade Routes **zur** Ark |
| Ascension (Imperiums-Endgame) | — |

**Verboten:**

- Zweite „Hauptwelt" wählbar machen
- Account-Forschung auf Kolonien verlagern
- Expansions-Gates von Outpost-Level lesen (immer Genesis Ark Entwicklungsstufe)
- UI-Copy, die eine Strategic World als „neue Hauptwelt" darstellt

Strategic World = **Reife einer Expansion-Welt**, nicht **Ersatz der Ark**.

---

## Paradigmenwechsel vs. OGame

| OGame / klassische Browsergames | Genesis Colonies (Charta) |
|--------------------------------|---------------------------|
| Astrophysik → Slot +1 | Imperium entwickelt sich → Region erreichbar |
| Kolonieschiff → sofort volle Welt | Seed Ark → Outpost → Meilensteine → Kolonie |
| Alle Welten starten identisch | Welttyp bestimmt Startbedingungen |
| DNA sofort sichtbar | DNA verborgen bis Etablierung |
| „3 / 9 Planeten" | „Diese Welt liegt außerhalb der Reichweite deines Imperiums" |
| Galaxy = Koordinatenbrowser | Command Map = Spielbrett |
| Homeworld wird irrelevant | Genesis Ark bleibt permanent zentral |

**Der größte Unterschied zu OGame ist nicht Formel oder Schiff — es ist wie Expansion funktioniert.**

---

## Zwei Enabler — keine dritte Ressource

Keine Expansion Authority. Kein Slot-Counter. Kein `max_colonies`.

```text
can_expand(site, world_type) =
    genesis_ark_development_stage >= required_stage
    AND interstellar_expansion_tech >= required_tech
    AND world_type_allowed(world_type)
    AND seed_ark_available
    AND site_not_already_claimed
```

| System | Frage | Owner |
|--------|-------|-------|
| **Genesis Ark Entwicklungsstufe** | *Ist mein Imperium reif genug?* | `planet_level.py` / Homeworld |
| **Interstellar Expansion** (Account-Tech) | *Kann ich diese Region/Welttyp erreichen?* | `research.py` |
| **Welttyp-Matrix** | *Welche Bedingungen gelten hier?* | `strategic_worlds.py` |
| **Etablierungs-Meilensteine** | *Habe ich die Welt etabliert?* | Establishment-Modul + `mechanics.py` |

Account-Forschung = Reichweite. Planet Evolution (Ark) = Reife. Kein drittes System.

Expansions-Gates lesen **immer** die Entwicklungsstufe der **Genesis Ark** (`is_homeworld`).

---

## Kolonisierung — Fleet liefert, Spieler etabliert

### Heute (Legacy)

```text
Fleet colonize → seed_ark verbraucht → colonize_planet() → volle Welt sofort
```

### Ziel (Charta)

**Flotte** = Logistik (Seed Ark transportieren).  
**Etablierung** = eigenes Gameplay auf der Zielwelt.

```text
Seed Ark angekommen
        ↓
Frontier Outpost gegründet (eingeschränkt spielbar)
        ↓
Meilensteine: Habitat → Energie → Kommunikation → Bevölkerung
        ↓
Kolonie etabliert (voll spielbar, DNA enthüllt)
        ↓
Entwicklung → Strategic World
```

### Outpost-Restriktionen (`frontier_outpost`)

Via `compile_planet_mechanics()`:

```text
colony_maturity = frontier_outpost
  → outpost_mode: true
  → disabled_buildings: [shipyard, research_lab, ...]
  → max_building_slots: 5
  → trade_route_auto: genesis_ark
  → allowed: primitive Mine, Lager, Solar
```

Outpost ist **spielbar**, nicht **gesperrt**.

---

## Entwicklungsstufe 0 — neue Welten beginnen bei Null

```text
Neue Welt (Outpost)
  Entwicklungsstufe 0
        ↓
Etablierungs-Meilensteine
        ↓
Kolonie etabliert — Stufe 1–2
        ↓
Events, DNA sichtbar, Spezialisierung planbar
        ↓
Strategic World
```

Genesis Ark startet weiterhin bei Stufe 1. Breaking Change: Code-Audit für `planet_level or 1` (GC-924).

---

## DNA verborgen bis Etablierung

Beim Gründen:

```text
Unbekannte Welt
Klasse:    ???
DNA:       ???
Risiko:    ???
```

Erst wenn **alle Etablierungs-Meilensteine** erfüllt (`frontier_outpost` → `colony`):

```text
Welt analysiert → DNA entdeckt → Traits sichtbar → Spezialisierungen planbar
```

Technisch: DNA wird serverseitig sofort generiert (Determinismus); UI maskiert bis `establishment_complete`.

---

## Welttypen bestimmen den Start

### Vulkanwelt

| ✓ | ✗ |
|---|---|
| Energieüberschuss | Ferronit (Metal) erschwert |
| | Crytite (Crystal) extrem selten |

### Eiswelt

| ✓ | ✗ |
|---|---|
| Brennzellen, Crytite reichlich | Energieproblem |

### Ancient World

| Besonderheit |
|--------------|
| Keine klassischen Minen; Ancient Artefakte, Events, Discoveries |

Owner: `strategic_worlds.py` + `compile_planet_mechanics()` / `EffectResolver`.

---

## Keine Kolonie-Anzahl — nur Regionen und Sites

**Verboten in UI und Fehlermeldungen:**

```text
max_colonies_reached · 3 / 9 Planeten · Planet-Slot voll · Planet kolonisiert
```

**Stattdessen:**

```text
expansion_gate_homeworld_level · expansion_gate_interstellar_tech
expansion_gate_world_type · expansion_world_out_of_reach
expansion_world_established · expansion_new_world_discovered
```

Jede Region hat Expansion Sites. Jede Site / jeder Strategic World hat eine Gate-Matrix. `max_colonies_per_player` → **deprecated** (GC-927).

---

## Gate-Matrix (Illustration — Balancing später)

### Genesis Ark Entwicklungsstufe

| Stufe | Schaltet frei (Beispiel) |
|-------|--------------------------|
| 5 | Erste Expansion (Frontier Outposts) |
| 10 | Zweite Expansion / mittlere Regionen |
| 15 | Dritte Expansion |
| 20 | Vulkanwelten + Frontier IX |
| 30 | Eiswelten |
| 40 | Ancient Worlds |
| 60 | Void Space |

### Interstellar Expansion (Account-Tech)

| Tech | Effekt |
|------|--------|
| Expansion I | Frontier-Outposts |
| Expansion II | Mittlere Regionen |
| Expansion III | Vulkanwelten |
| Expansion IV | Eiswelten |
| Expansion V | Ancient Space |
| Expansion VI | Void Space |

Tech = Reichweite. Entwicklungsstufe = Reife. Beides nötig.

---

## Command Map = Spielbrett

```text
Command Map öffnen → Regionen / gesperrte Welten sehen
        ↓
Auf Genesis Ark Entwicklungsstufe hinarbeiten
        ↓
Site wird grün (Checklist vollständig)
        ↓
Expansion starten → Outpost erscheint → Imperium wächst sichtbar
```

### Site-Inspector (Ziel-UI)

```text
Frontier IX

  ✓ Entwicklungsstufe 20 (aktuell: 22)
  ✓ Interstellar Expansion III
  ○ Seed Ark bereit
  ○ Expansion starten          [Button wenn alles grün]
```

Payload-Erweiterung auf `build_expansion_unlock_block()` — kein neues Backend-Modul.

---

## Technische Zuordnung

| Konzept | Owner | Status |
|---------|-------|--------|
| Expansion Sites + Level-Gates | `expansion_gates.py` | ✅ |
| World Claims | `world_colonization.py` | ✅ Phase 1 |
| Strategic World Types | `strategic_worlds.py` | ✅ Präsentation |
| Map-Inspector | `command_center.py`, `command_map.py` | ✅ erweiterbar |
| Fleet Seed Ark | `fleet.py` | ✅ Transport-Step |
| `expansion_phase` / `colony_maturity` | `planets` Migration + `mechanics.py` | ❌ GC-920 |
| Etablierungs-Meilensteine | neues Establishment-Modul | ❌ GC-923 |
| Interstellar Expansion Tech | `research` definitions | ❌ GC-921 |
| DNA Reveal Gate | `bootstrap.py`, `dna.py` | ❌ GC-928 |
| Welten-Copy / Entwicklungsstufe | `locales/*` | ❌ GC-929 |

Kein `colonize_v2`, kein `expansion_authority`, kein zweites Fleet-System.

---

## Anti-OGame-Regeln (verbindlich)

| Verboten | Stattdessen |
|----------|-------------|
| `max_colonies` / Slot-Counter | Gate-Matrix pro Site/Welttyp |
| Expansion Authority | Entwicklungsstufe + Tech |
| Instant-Welt bei Fleet-Ankunft | Outpost + Meilensteine |
| Timer-only Etablierung | Habitat + Energie + Kom + Bevölkerung |
| Astrophysik = +1 Planet | Interstellar Expansion = Reichweite |
| Identische Welt-Starts | Welttyp-Startbedingungen |
| DNA sofort sichtbar | Reveal nach Etablierung |
| „Planet" in Copy | „Welt" |
| Zweite Hauptwelt | Genesis Ark unersetzlich |
| Outpost = Kolonie | Klare Lifecycle-Phasen |

---

## Ticket-Backlog (implementiert die Charta)

### Implementierungsregel (verbindlich)

> **Jedes Ticket GC-920–GC-929 muss mindestens einen Abschnitt aus dieser Charta referenzieren** — im Ticket-Text und im PR/Commit.

So bleibt jede Implementierung an der Design-Charta ausgerichtet; kein Ticket darf Slot-Counter oder Timer-only-Etablierung neu einführen.

| Ticket | Fokus | Charta-Abschnitt |
|--------|-------|------------------|
| **GC-920** | `expansion_phase` enum + Migration + Outpost-Mechanics | [Was ist eine Kolonie?](#was-ist-überhaupt-eine-kolonie) · Offizieller Lifecycle |
| **GC-921** | Interstellar Expansion Tech (Reichweite) | [Zwei Enabler](#zwei-enabler--keine-dritte-ressource) · Gate-Matrix |
| **GC-922** | Dual-Gate; ersetzt `max_colonies` | [Zwei Enabler](#zwei-enabler--keine-dritte-ressource) · [Keine Kolonie-Anzahl](#keine-kolonie-anzahl--nur-regionen-und-sites) |
| **GC-923** | Etablierungs-Meilensteine (nicht Timer-only) | [Wann ist eine Kolonie „fertig"?](#wann-ist-eine-kolonie-fertig--meilensteine-nicht-timer) |
| **GC-924** | Entwicklungsstufe 0 für neue Outposts | [Entwicklungsstufe 0](#entwicklungsstufe-0--neue-welten-beginnen-bei-null) |
| **GC-925** | Welttyp-Startbedingungen | [Welttypen bestimmen den Start](#welttypen-bestimmen-den-start) |
| **GC-926** | Command Map Checklist + Launch | [Command Map = Spielbrett](#command-map--spielbrett) |
| **GC-927** | Deprecate `max_colonies` + Grandfathering | [Anti-OGame-Regeln](#anti-ogame-regeln-verbindlich) · [Grandfathering](#grandfathering) |
| **GC-928** | DNA-Reveal nach Etablierung | [DNA verborgen bis Etablierung](#dna-verborgen-bis-etablierung) |
| **GC-929** | i18n: Welten, Entwicklungsstufe (8 Locales) | [Terminologie — Welten, nicht Planeten](#terminologie--welten-nicht-planeten) |

Reihenfolge: **920 → 922 → 923 → 924 → 926**, dann 925/928/929.

---

## Grandfathering

Bestehende Welten: `expansion_phase = colony` (oder `strategic_world`), keine rückwirkende Etablierung. Neue Expansionen folgen der Charta ab GC-923.

---

## Warum expandiert man überhaupt?

Expansion ist **nicht** da, um mehr Ressourcen zu farmen oder einen Slot zu füllen.

Expansion **eröffnet neue Möglichkeiten**:

```text
Neue Welten
        ↓
neue Rohstoffe & Startbedingungen
        ↓
neue Technologien (Planet-Tech pro Welt)
        ↓
neue Spezialisierungen
        ↓
neue Regionen auf der Command Map
        ↓
neue Expeditionen & Discoveries
        ↓
neue Geschichten
```

Der Spieler expandiert nicht, um **Quantität** zu steigern. Er expandiert, weil jede neue Welt **Bedeutung** und **Inhalt** eröffnet — eine andere DNA, ein anderer Welttyp, ein anderer strategischer Beitrag zum Imperium.

Die Genesis Ark entwickelt sich weiter und **öffnet** dabei neue Regionen. Jede etablierte Welt wird ein **Charakter** im Imperium, nicht eine Kopie der Ark.

---

## Charta-Satz

> **In Genesis Colonies expandiert der Spieler nicht, um mehr Planeten zu besitzen. Er expandiert, um sein Imperium um neue Möglichkeiten zu erweitern.**

Dieser Satz ist der Prüfstein für jede künftige Entscheidung zu Expansion, Kolonisierung, Imperiumsgrenzen und Command Map.

---

## Verwandte Docs

- [IMPERIUM_VISION.md](IMPERIUM_VISION.md) — Langfristige Imperiums-Vision
- [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md) — DNA, Planet-Tech, Tick
- [GC-562_EVOLUTION_UNLOCK_GATES.md](GC-562_EVOLUTION_UNLOCK_GATES.md) — Expansion Sites (shipped)
- [GC-582_DYNAMIC_COLONIZATION.md](GC-582_DYNAMIC_COLONIZATION.md) — World Claims
- [FLEET_SYSTEM.md](FLEET_SYSTEM.md) — Seed Ark Transport
- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) — GC-000 Regeln 15–17
