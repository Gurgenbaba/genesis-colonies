# Galactic Diplomacy & Galaxy Personality — Genesis Colonies

> **Galactic Diplomacy ist die Makro-Politik-Schicht über Galactic Directives.**  
> Directives = *was* eine Galaxie tut (monatlicher Community-Buff). Diplomacy = *wer* die Galaxie formt (Blöcke, Resolutionen, Krisen, dauerhafter Charakter).

Epic: **EPIC-16 Galactic Politics** (Fortsetzung) · Ticket: **GC-721A** (dieses Dokument) · Status: 📋 Design / Master-Doc · Stand: v1.0

Referenz (historisch, **nicht** 1:1 portieren):

- `BETA_OGX_GLAD` — `DiplomacyController.php` (PNA, Bündnisse, Krieg, Beziehungsmatrix)
- `GovController.php` / `Gov_resultsController.php` — nur Abgrenzung: **Regierungs-Abstimmung ≠ Diplomatie**

Voraussetzung: [GALACTIC_DIRECTIVES.md](GALACTIC_DIRECTIVES.md) (GC-720) — aktive, galaxie-scoped Directives mit `EffectResolver`-Hook (GC-720E/E2).

---

## Kernthese

Genesis Colonies hat nach GC-720 **mechanische** Galaxie-Unterschiede. GC-721 macht Galaxien **politisch erzählbar**:

```text
Galaxie 1 — Scientific Bloc (CTX, NOVA, VOID)
  → Scientific Directive gewinnt oft
  → Trait „Academia Prime“ (+10% Forschung permanent)
  → Resolution blockiert Military für nächsten Zyklus

Galaxie 2 — Military Bloc (INFERNO, OMEGA, HELL)
  → Military + Industrial Dominanz
  → Trait „Forge of War“
  → Emergency Session nach Frontier-Krieg

Galaxie 3 — Frontier Bloc
  → Exploration + Expansion
  → Trait „Frontier Space“
  → Gate-Kontrolle durch Allianz CTX
```

**Strategische Frage für Spieler:**

> „Soll ich meine Research-Kolonie in G2 bauen? Die sind seit vier Monaten militaristisch. G1 ist wissenschaftlich stärker.“

Das ist der Moment, in dem eine Galaxie **Identität** bekommt — nicht nur einen Buff.

---

## Imperiums-Stack (Ziel-Loop)

```text
Planet Evolution
      ↓
Planet Policies          (Mikro — pro Kolonie)
      ↓
Galactic Directives      (Makro — pro Galaxie, monatlich)     ← GC-720
      ↓
Alliance Diplomacy       (Makro+ — Blöcke, Resolutionen)     ← GC-721
      ↓
Galaxy Personality       (Langzeit — dauerhafte Traits)        ← GC-721
      ↓
Emergency Events         (Kurzzeit — Krisen-Direktiven)        ← GC-721
      ↓
Galaxie verändert sich dauerhaft (Historie, Messages, Map)
```

---

## Abgrenzung (GC-000)

| System | Scope | Ersetzt Directives? | Owner |
|--------|-------|---------------------|-------|
| **Galactic Directives** | `planets.galaxy`, monatlicher Zyklus | — | `game/galactic_directives/` |
| **Galactic Diplomacy** | `planets.galaxy` + Allianz-Aggregation | **Nein** — erweitert | `game/galactic_diplomacy/` (neu) |
| **Alliance Hub** (`/alliance`, EPIC-09) | Spieler-/Allianz-Identität, Mitglieder, Chat | **Nein** — Consumer von Bloc-Metadaten | `game/alliance.py` |
| **Player Diplomacy (OGX)** | PNA, Krieg 1:1, Beziehungsstufen | **Nein** — spätere EPIC-Erweiterung | nicht GC-721 |
| **Planet Policies** | Pro Planet | Nein | `game/planet_evolution/` |
| **EffectResolver** | Zahlen | Nein — **Consumer** | `game/effects/effect_resolver.py` |
| **Command Map** | Regionen, Gates, Welt-Typen | Nein — **Flag-Consumer** | `game/planet_evolution/command_map.py` |

**Verboten:**

- Directives durch Diplomatie ersetzen oder doppelte Abstimmungs-Engines parallel betreiben (Regel 15)
- `if bloc == 'military':` in `fleet.py` / `combat.py` — nur `EffectResolver` + dokumentierte Flags (Regel 16)
- Frontend-Vote-Math oder Ergebnis-Balken aus Client-Daten
- Neues Allianz-System — nur **Bloc-Zuordnung** und Stimmgewicht auf bestehendem `alliance.py` aufsetzen
- Session-basierter Galaxie-Scope

**Lesson aus OGX `DiplomacyController.php` (Konzept, nicht Port):**

- PNA / NAP / War als **spieler-allianz**-Beziehungen — bleibt EPIC-09/Backlog
- **Galaxie-Politik** ist Community-Ebene: Blöcke konkurrieren um Directive-Einfluss, nicht nur „CTX vs XYZ“ im Vakuum

---

## Architektur

### Vier Säulen

```text
┌──────────────────────────────────────────────────────────────────┐
│  GALAXY PERSONALITY (slow, persistent)                          │
│  Traits aus Directive-Historie + Bloc-Dominanz                   │
│  kleine permanente EffectResolver-Modifier                       │
└────────────────────────────┬─────────────────────────────────────┘
                             │ liest Historie
┌────────────────────────────▼─────────────────────────────────────┐
│  EMERGENCY DIRECTIVES (fast, event-driven, 7–30 Tage)            │
│  Alien Invasion · Galaxy War · Resource Crisis · …               │
│  starke Boni + harte Tradeoffs, überschreibt nicht Primary-DB   │
└────────────────────────────┬─────────────────────────────────────┘
                             │ ausgelöst durch Resolution / Event
┌────────────────────────────▼─────────────────────────────────────┐
│  DIPLOMATIC RESOLUTIONS (galaxy vote, neben Directive-Zyklus)   │
│  Sperren · Verstärken · Emergency · Gate · Sanktionen            │
└────────────────────────────┬─────────────────────────────────────┘
                             │ Bloc-Stimmen aggregiert
┌────────────────────────────▼─────────────────────────────────────┐
│  ALLIANCE BLOCS (per galaxy, per alliance)                       │
│  Scientific · Military · Industrial · Frontier · Neutral        │
└────────────────────────────┬─────────────────────────────────────┘
                             │ baut auf
┌────────────────────────────▼─────────────────────────────────────┐
│  GALACTIC DIRECTIVES (GC-720 — unverändert Owner)               │
│  Primary + Secondary · monatlicher Zyklus                        │
└──────────────────────────────────────────────────────────────────┘
```

### Owner-Modul (neu, Regel 17)

| Domäne | Owner | Doc |
|--------|-------|-----|
| Bloc-Membership, Resolution-Cycles, Emergency-State, Personality | `game/galactic_diplomacy/` | dieses Dokument |
| Active Directives, Directive-Definitionen, Directive-Votes | `game/galactic_directives/` | [GALACTIC_DIRECTIVES.md](GALACTIC_DIRECTIVES.md) |
| Allianz-Identität, Mitgliederliste | `game/alliance.py` | EPIC-09 |
| Zahlenboni (Traits, Emergency, Resolution-Buffs) | `game/effects/effect_resolver.py` | [EFFECTS.md](EFFECTS.md) |
| Gate-/Region-Flags | `game/planet_evolution/command_map.py` | [GC-570_WORLD_MAP_DIRECTION.md](GC-570_WORLD_MAP_DIRECTION.md) |
| Broadcast / Resolution-Messages | `game/messages.py` | [ARCHITECTURE.md](ARCHITECTURE.md) |

Vorgeschlagene Modulstruktur:

```text
game/galactic_diplomacy/
  __init__.py           # public read API
  definitions.py        # bloc types, resolution types, emergency catalog, trait catalog
  blocs.py              # alliance ↔ bloc per galaxy
  resolutions.py        # resolution cycles, tally, effects
  emergency.py          # emergency sessions, duration, stacking rules
  personality.py        # historie → trait score → active trait
  repository.py         # DB access
  service.py            # submit vote, join bloc (alliance officer)
  constants.py
```

### Read-only API (Ziel-Signatur, GC-721C+)

```python
def get_galaxy_bloc_landscape(galaxy: int, *, conn=None) -> dict:
    """Blocs → alliances → member counts / vote weight preview."""

def get_active_galaxy_personality(galaxy: int, *, conn=None) -> dict | None:
    """trait_key, label_key, mechanics_json, since_ym, dominance_score."""

def get_active_emergency_directive(galaxy: int, *, conn=None) -> dict | None:
    """emergency_key, ends_at, mechanics overlay."""

def get_open_resolutions_for_galaxy(galaxy: int, *, conn=None) -> list[dict]:
    """Phase vote_open resolutions (if any)."""

def get_personality_modifiers_for_galaxy(galaxy: int, *, conn=None) -> dict:
    """Merged mechanics for EffectResolver (traits only, no side effects)."""
```

**Schreib-API (Actions, später):**

```python
def submit_bloc_membership(alliance_id: int, galaxy: int, bloc_key: str, *, conn=None) -> dict:
    """Alliance officer sets bloc for one galaxy. {ok, state}"""

def submit_resolution_vote(player_id: int, resolution_id: int, choice: str, *, conn=None) -> dict:
    """choice: yes | no — Stimmgewicht aus Kolonien in Galaxie + Bloc-Regeln."""
```

Alle POST-Actions: `{ ok, state }` → `applyActionState()` — [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md).

---

## 1. Alliance Blocs

### Konzept

Allianzen positionieren sich **pro Galaxie** in einem politischen Block — nicht global.

```text
GALAXY 1

  Scientific Bloc          Military Bloc
  ├─ CTX                   ├─ INFERNO
  ├─ NOVA                  ├─ OMEGA
  └─ VOID                  └─ HELL

  Industrial Bloc (solo)     Neutral Bloc
  └─ FORGE                   └─ (unaffiliated alliances)
```

### Canonical Bloc Keys

| `bloc_key` | Thema | Typische Directive-Affinität |
|------------|-------|------------------------------|
| `scientific` | Forschung, Akademien, Discovery | `scientific`, `exploration` |
| `military` | Krieg, Flotte, Verteidigung | `military`, `defensive` |
| `industrial` | Produktion, Werft, Wirtschaft | `industrial`, `logistics` |
| `frontier` | Kolonisierung, Expedition, Expansion | `expansion`, `exploration` |
| `neutral` | Kein Block / Schweigen | keine Affinität |

### Regeln (Design)

| Regel | Detail |
|-------|--------|
| **Scope** | `(alliance_id, galaxy)` — dieselbe Allianz kann in G1 `scientific`, in G3 `frontier` sein |
| **Wer darf wählen** | Allianz-Officer (Rolle aus EPIC-09; bis MVP: Allianz-Gründer) |
| **Wechsel** | Cooldown 1 Directive-Zyklus pro Galaxie; Wechsel während offener Resolution gesperrt |
| **Neutral** | Default wenn keine Zuordnung; zählt nicht für Bloc-Mehrheit |
| **Stimmgewicht (später)** | Basis: 1 Stimme pro Spieler mit Kolonie in Galaxie; Bloc-Bonus +10% wenn ≥3 Allianzen im Block (cap) |
| **Kein Krieg-Flag** | Bloc ≠ Kriegserklärung; Sanktionen nur über Resolutionen |

### UI (Spezifikation, nicht GC-721A)

- `/galactic-politics` oder Galaxy-Tab: Bloc-Map pro Galaxie
- Command Map: dezentes Bloc-Badge an Regionen mit Mehrheits-Bloc (GC-570+)
- Alliance Hub: „Unser Block in G1: Scientific“ (read-only bis EPIC-09 UI)

---

## 2. Diplomatic Resolutions

### Konzept

Galaxie-weite **Sonderabstimmungen** neben dem monatlichen Directive-Vote. Auslöser:

- Spieler-/Officer-Petition (Kosten: Fuel / Influence — Backlog)
- Automatisch vor Directive-Phase (Tag 0)
- Emergency-Kette
- Admin/Event-Worker

### Resolution-Typen (Seed-Katalog)

| `resolution_type` | Beispiel-Text | Bei JA |
|-------------------|---------------|--------|
| `ban_directive` | „Scientific darf nächsten Zyklus nicht gewählt werden.“ | `cooldown_directive` auf Ziel-Key für 1 Zyklus |
| `boost_directive` | „Exploration erhält +20% Loot statt +10% (Secondary-Schwellwert).“ | temporärer `flags`-Overlay auf aktive Exploration |
| `trigger_emergency` | „Emergency Session: Militär mobilisieren?“ | startet Emergency Directive (siehe §3) |
| `region_control` | „Allianz CTX kontrolliert Helios Gate.“ | Command-Map-Flag + Allianz-Bonus-Mechanics |
| `bloc_sanction` | „Sanktionen gegen Military Bloc.“ | −Stimmgewicht / Trader-Limit für Ziel-Bloc 1 Zyklus |

### Zyklus (Vorschlag)

| Phase | Zeit | Verhalten |
|-------|------|-----------|
| `proposed` | 24–48 h | Petition sichtbar; noch keine Stimmen |
| `vote_open` | 48–72 h | JA/NEIN; Quorum: ≥15% der stimmberechtigten Kolonien in Galaxie |
| `resolved` | sofort | Effekt aktiv; Message-Broadcast |
| `expired` | — | Kein Quorum → keine Wirkung |

**Koexistenz mit GC-720:** Directive-Vote Tag 1–5 bleibt unberührt. Resolution kann **vor** Tag 1 (Prep-Week) oder **parallel** in Woche 2 laufen — Implementierung wählt einen Slot; Design erlaubt beides.

### Stimmen

- Stimmberechtigt: Spieler mit ≥1 Kolonie in `galaxy` (wie `gd_votes`)
- Gewicht: 1 + Bloc-Modifier (später); Commander-Premium **nicht** in GC-721 MVP
- Gleichstand: Status `failed` — kein Effekt (kein Zufall bei Resolutionen; anders als Directive-Tie)

### Beispiel-Mechanics (Region Control)

```json
{
  "resolution_type": "region_control",
  "target": { "world_key": "helios_gate", "alliance_tag": "CTX" },
  "effects": {
    "alliance_mechanics": {
      "effect_resolver": { "research_time_speed": 1.05 },
      "flags": { "expedition_loot_mult": 1.05 }
    },
    "command_map": {
      "flags": { "controlled_by_alliance": "CTX", "gate_bonus_active": true }
    }
  },
  "duration_days": 30
}
```

---

## 3. Emergency Directives

### Konzept

Kurzfristige **Überlagerung** bei Krisen — nicht Ersatz für Primary Directive.

```text
EMERGENCY SESSION — Galaxy 2

  Militär mobilisieren?

  [ JA ]     [ NEIN ]

  Wenn JA (30 Tage):
    +35% Waffen
    +20% Schiffsbau
    −20% Forschung
    −15% Wirtschaft (metal/crystal prod)
```

### Canonical Emergency Keys

| `emergency_key` | Trigger (Beispiel) | Primary-Fokus |
|-----------------|-------------------|---------------|
| `alien_invasion` | World-Event / Admin | Combat + Defense |
| `pirate_war` | Galaxy Heat ≥700 / Pirate Ecosystem | Combat + Defense + fleet pressure |
| `galaxy_war` | Resolution / PvP-Metrik | Military mobilization |
| `resource_crisis` | Economy-Event, Trader-Engpass | Industrial + Logistics |
| `hyperstorm` | Map-Event | Defensive + reduced fleet speed |
| `frontier_collapse` | Colonization-Failure-Metrik | Expansion rescue |

### Regeln

| Regel | Detail |
|-------|--------|
| **Dauer** | 7–30 Tage (`ends_at`), konfigurierbar pro Emergency-Definition |
| **Stacking** | Max. 1 aktive Emergency pro Galaxie; keine Parallel-Emergency |
| **Overlay** | `emergency_mechanics_json` merged **nach** Primary+Secondary Directives; gleiche Merge-Regeln wie [GALACTIC_DIRECTIVES.md](GALACTIC_DIRECTIVES.md) § Mechanics |
| **Abstimmung** | Resolution `trigger_emergency` oder automatisch bei Event-Flag |
| **Nach Ende** | Message + optional Personality-Historie-Eintrag (`war_scar`, `survivor`) |

### Beispiel `galaxy_war` Emergency

```json
{
  "emergency_key": "galaxy_war",
  "label_key": "gd_emergency_galaxy_war_title",
  "duration_days": 30,
  "mechanics_json": {
    "effect_resolver": {
      "weapon_bonus": 0.35,
      "shipyard_time_speed": 1.20,
      "research_time_speed": 0.80,
      "metal_prod_factor": 0.85,
      "crystal_prod_factor": 0.85
    },
    "flags": {
      "fleet_attack_bonus": 0.10
    }
  },
  "tradeoffs_json": {
    "effect_resolver": {
      "research_time_speed": 0.80,
      "metal_prod_factor": 0.85
    }
  }
}
```

**EffectResolver (GC-721H):** `get_galaxy_diplomacy_mechanics()` liefert das merged Bundle (Personality → Resolution → Emergency, GC-721G). `EffectResolver.get_modifiers()` wendet es **nach** Galactic Directives an — siehe [EFFECTS.md](EFFECTS.md).

---

## 4. Galaxy Personality

### Konzept

Eine Galaxie entwickelt **langsam dauerhaften Charakter** aus ihrer Directive-Historie und Bloc-Dominanz — unabhängig vom aktuellen Monats-Buff.

```text
G1 Historie (letzte 6 Zyklen):
  scientific → scientific → logistics → scientific → scientific → scientific

  ⇒ Trait: Academia Prime
     +10% Forschung (permanent, klein)
```

### Canonical Traits (Seed)

| `trait_key` | Entstehung (Vorschlag) | Permanent-Bonus (klein) |
|-------------|------------------------|-------------------------|
| `academia_prime` | ≥4× `scientific` in 6 Zyklen | `research_time_speed` 1.10 |
| `forge_of_war` | ≥3× `military` oder `industrial` in 6 Zyklen | `weapon_bonus` 0.05, `shipyard_time_speed` 1.05 |
| `frontier_space` | ≥3× `exploration`/`expansion` in 6 Zyklen | `flags.expedition_loot_mult` 1.10 |
| `trade_nexus` | ≥3× `logistics` in 6 Zyklen | `cargo_multiplier` 1.10, `flags.trader_daily_limit_mult` 1.10 |
| `bastion_sector` | ≥3× `defensive` in 6 Zyklen | `shield_bonus` 0.05, `defense_time_speed` 1.05 |

### Regeln

| Regel | Detail |
|-------|--------|
| **Historie** | `gd_cycles` resolved winners → Rolling Window (6 Monate) |
| **Schwellwert** | Trait aktiv wenn Score ≥ threshold; Score decayt wenn Muster bricht (1 Punkt / Zyklus ohne Match) |
| **Permanent vs. saisonal** | MVP: **permanent** bis anderer Trait Schwellwert überholt; saisonal = Backlog |
| **Bloc-Verstärker** | +1 Score wenn gewinnende Directive mit dominierendem Bloc übereinstimmt |
| **Sichtbarkeit** | Galaxy-Banner, Messages bei Trait-Wechsel, Command-Map-Subtitle |
| **Kein Power-Creep** | Trait-Boni ≈ 50% einer Secondary-Direktive — Makro-Identität, nicht neuer Meta-Break |

### Personality ≠ Directive

| | Directive | Personality |
|---|-----------|-------------|
| Wechsel | monatlich | monatelang / permanent |
| Amplitude | groß (Primary 100%) | klein (+5–10%) |
| Quelle | Community-Vote | Historie + Blocs |
| Owner-Tabelle | `gd_galaxy_state` | `gdp_galaxy_personality` (später) |

---

## Mechanics-JSON-Vertrag (Erweiterung)

Wiederverwendet das PE/GD-Format aus [GALACTIC_DIRECTIVES.md](GALACTIC_DIRECTIVES.md):

| Kanal | Consumer |
|-------|----------|
| `effect_resolver` | `EffectResolver` (Traits, Emergency, Resolution-Buffs) |
| `flags` | Expedition, Trader, Command Map, Colonization |
| `command_map` | Region control, Gate-Boni |
| `alliance_mechanics` | Nur Mitglieder der kontrollierenden Allianz in Galaxie (später: per-player scope) |

**Merge-Reihenfolge (Ziel):**

```text
planet_policies
  → galactic_directives (primary + secondary)
  → galaxy_personality
  → emergency_directive (if active)
  → resolution_overlays (if timed)
```

Implementierung in **einem** Resolver-Pfad (`get_galaxy_layered_mechanics()` oder sequentielle Hooks in `EffectResolver`) — **kein** Copy-Paste-Merge in Consumern.

---

## Schema-Skizze (Design only — keine Migration in GC-721A)

```sql
-- Alliance bloc membership per galaxy
CREATE TABLE gdp_alliance_blocs (
    alliance_id     INTEGER NOT NULL,
    galaxy          INTEGER NOT NULL,
    bloc_key        TEXT NOT NULL,
    since_at        INTEGER NOT NULL,
    cooldown_until  INTEGER,
    PRIMARY KEY (alliance_id, galaxy)
);

-- Resolution cycles (parallel to gd_cycles)
CREATE TABLE gdp_resolutions (
    id              INTEGER PRIMARY KEY,
    galaxy          INTEGER NOT NULL,
    resolution_type TEXT NOT NULL,
    title_key       TEXT NOT NULL,
    body_key        TEXT,
    payload_json    TEXT NOT NULL,
    status          TEXT NOT NULL,  -- proposed | vote_open | resolved | expired | cancelled
    vote_start_at   INTEGER,
    vote_end_at     INTEGER,
    yes_votes       INTEGER DEFAULT 0,
    no_votes        INTEGER DEFAULT 0,
    result          TEXT,           -- yes | no | failed
    created_at      INTEGER NOT NULL
);

CREATE TABLE gdp_resolution_votes (
    resolution_id   INTEGER NOT NULL,
    player_id       INTEGER NOT NULL,
    choice          TEXT NOT NULL,  -- yes | no
    weight          INTEGER DEFAULT 1,
    created_at      INTEGER NOT NULL,
    UNIQUE (resolution_id, player_id)
);

-- Active / historical personality per galaxy
CREATE TABLE gdp_galaxy_personality (
    galaxy          INTEGER PRIMARY KEY,
    trait_key       TEXT,
    score_json      TEXT,           -- per-trait rolling scores
    active_since    INTEGER,
    updated_at      INTEGER NOT NULL
);

-- Emergency overlay state
CREATE TABLE gdp_galaxy_emergency (
    galaxy          INTEGER PRIMARY KEY,
    emergency_key   TEXT NOT NULL,
    started_at      INTEGER NOT NULL,
    ends_at         INTEGER NOT NULL,
    source          TEXT,           -- resolution | event | admin
    resolution_id   INTEGER
);
```

Definitionstabellen (`gdp_bloc_definitions`, `gdp_resolution_definitions`, `gdp_emergency_definitions`, `gdp_trait_definitions`) analog `gd_directive_definitions`.

---

## Messaging ([game/messages.py](game/messages.py))

| Event | `category` | `metadata.kind` |
|-------|------------|-----------------|
| Resolution passed/failed | `system` | `gdp_resolution_result` |
| Emergency started/ended | `system` | `gdp_emergency` |
| Trait gained/lost | `system` | `gdp_personality_change` |
| Bloc majority shift | `system` | `gdp_bloc_shift` |

Broadcast: alle Spieler mit Kolonie in betroffener Galaxie (wie GC-720G Directive-Results).

Body: serverseitig HTML/Text — **kein** Client-Template für Zahlen.

---

## Player Actions (GC-POL live)

| Action | Route | Owner |
|--------|-------|-------|
| Directive vote | POST /api/galactic-politics/vote | galactic_directives.voting |
| Alliance bloc set (officer) | POST /api/galactic-politics/bloc | galactic_diplomacy.politics_surface |
| Resolution propose (officer) | POST /api/galactic-politics/resolution/propose | galactic_diplomacy.sessions |
| Resolution JA/NEIN | POST /api/galactic-politics/resolution/vote | galactic_diplomacy.sessions |

Schema: migrations/125_galactic_resolution_sessions.sql (gd_resolution_sessions, gd_resolution_session_votes).

---

## UI & Präsentation (Spezifikation)

| Surface | Inhalt |
|---------|--------|
| `/galactic-politics` | Bloc-Übersicht, offene Resolutionen, Trait, Emergency-Banner |
| Galaxy-Seite | Unified Status-Card: Direktive + Diplomatie (Trait/Resolution/Emergency), ein CTA |
| Overview | Kein Diplomatie-Banner (kein Doppel mit Galaxy) |
| Command Map | Region-Control-Badge, Bloc-Farben (dezent) |
| Messages | Resolution/Emergency/Trait-Reports |

PJAX-safe; Actions via `GC.fetchGameAction`.

---

## Abhängigkeiten & Reihenfolge

```text
GC-720 (Directives live) ──► GC-721A (dieses Doc)
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
              GC-721B Schema   GC-721C Blocs   GC-721D Personality
                    │               │               │
                    └───────────────┼───────────────┘
                                    ▼
                              GC-721E Resolutions
                                    ▼
                              GC-721F Emergency
                                    ▼
                              GC-721G EffectResolver merge
                                    ▼
                              GC-721H UI + Messages
```

**Soft-Dependencies:**

- EPIC-09 Alliance Officer-Rollen → Bloc-Wechsel-UI
- GC-570 Command Map → `region_control` sichtbar
- GC-720F Directive-Voting → Resolution-Timing sinnvoll koordinieren

**Nicht blockierend für GC-721B:** Admin-seeded Blocs/Personality zum Testen (wie GD Admin-Force).

---

## Ticket-Kette (nach GC-721A)

| Ticket | Fokus | Dateien (Richtwert) |
|--------|-------|---------------------|
| **GC-721A** | Dieses Master-Doc | `docs/GALACTIC_DIPLOMACY.md` |
| **GC-721B** | Migration + Definition Seeds | `migrations/`, `game/galactic_diplomacy/definitions.py` |
| **GC-721C** | Alliance Blocs API + read resolver | `blocs.py`, `service.py` |
| **GC-721D** | Galaxy Personality scorer + read API | `personality.py` |
| **GC-721E** | Resolution cycles + vote + tally | `resolutions.py`, `app.py` |
| **GC-721F** | Emergency definitions + state | `emergencies.py` |
| **GC-721G** | Diplomacy mechanics merge bundle | `galactic_diplomacy/mechanics.py` |
| **GC-721H** | EffectResolver hook | `effect_resolver.py`, `tests/test_effects.py` |
| **GC-721I** | UI preview + Messages | `templates/`, `messages.py`, `static/main.js` |

**Bewusst nach GC-720E2 / Banner:** Spieler sollen Directive-Unterschiede **fühlen**, bevor Diplomatie-Layer live geht.

---

## Tests (für spätere Tickets)

| Bereich | Datei |
|---------|-------|
| Personality scoring / trait switch | `tests/test_galactic_diplomacy_personality.py` |
| Resolution quorum / tally | `tests/test_galactic_diplomacy_resolutions.py` |
| Emergency duration / no double-stack | `tests/test_galactic_diplomacy_emergency.py` |
| EffectResolver layered merge | `tests/test_effects.py` |
| Bloc cooldown | `tests/test_galactic_diplomacy_blocs.py` |

---

## Backlog (nicht GC-721)

| Thema | Beschreibung |
|-------|--------------|
| Player-level PNA / War | OGX `DiplomacyController` — EPIC-09 Erweiterung |
| Influence currency | Petitionen kosten Ressource |
| Cross-galaxy federations | Meta-Bloc über mehrere Galaxien |
| Dynamic trait names | Spieler-benannte Traits bei 12+ Zyklen Dominanz |
| Bloc vs Bloc Kriegsmetrik | PvP-Auswertung triggert `galaxy_war` Emergency |

---

## Verwandte Dokumente

- [GALACTIC_DIRECTIVES.md](GALACTIC_DIRECTIVES.md) — Directive-Zyklus, Mechanics-Format
- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) — GC-000, Regeln 15–17
- [EFFECTS.md](EFFECTS.md) — EffectResolver, Merge-Reihenfolge
- [IMPERIUM_VISION.md](IMPERIUM_VISION.md) — Imperiums-Entscheidungen
- [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md) — `planets.galaxy`
- [GC-570_WORLD_MAP_DIRECTION.md](GC-570_WORLD_MAP_DIRECTION.md) — Command Map Flags
- [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md) — Vote-Actions
- [ROADMAP.md](ROADMAP.md) — EPIC-09 Alliance, EPIC-16 Politics

---

## Changelog

| Version | Datum | Änderung |
|---------|-------|----------|
| v1.0 | 2026-06-17 | GC-721A — Initial Master-Doc: Blocs, Resolutions, Emergency, Personality |

---

## Player Article

```yaml
---
codex_id: diplomacy
band: IV
difficulty: advanced
estimated_read: 5 min
surfaces:
  - quick_help
  - codex
  - faq
  - commander_tips
  - discord
routes:
  - galactic_politics_view
related_codex:
  - imperial_directives
  - galactic_directives
  - galaxy
  - command_map
  - genesis_ark
terminology: GENESIS_TERMINOLOGY
unlock:
  type: route_visit
  route: galactic_politics_view
teaser_key: codex_unlock_diplomacy_teaser
---
```

## Quick Help

**Galactic Diplomacy** formt den Charakter deiner Galaxie: Allianz-Blöcke, Resolutionen, Krisen und langfristige Personality — Oberfläche unter `/galactic-politics`.

## Summary

Diplomatie ist die **Makro-Politik-Schicht** über Galactic Directives. Directives steuern, *was* die Galaxie im Zyklus betont; Diplomacy steuert, *wer* sie formt: Scientific, Military, Industrial, Frontier oder Neutral-Blöcke, Abstimmungen, Emergency-Sessions und dauerhafte Traits. Spieler-Oberfläche: **`/galactic-politics`**.

## Why

Galaxien sollen politisch erzählbar sein — nicht nur ein Buff. Bloc-Lage und Traits beeinflussen, wo Forschung, Krieg, Expansion oder Logistik langfristig stark wirken. Das ist Community-Ebene, kein 1:1-Kriegssystem zwischen einzelnen Commandern.

## How it works

- Seite **`/galactic-politics`**: Bloc-Landschaft, offene Resolutionen, aktive Personality, Emergency-Banner.
- **Alliance Blocs** pro Galaxie (Officer setzt Bloc): Scientific, Military, Industrial, Frontier, Neutral.
- **Directive-Vote** und **Resolutionen** (JA/NEIN, Vorschläge durch Officers) neben dem monatlichen Directive-Zyklus.
- **Galaxy Personality** entsteht aus Historie und Bloc-Dominanz — langsame, dauerhafte Ausrichtung.
- **Emergency Directives** sind zeitlich begrenzte Krisen-Overlays.
- Mechanische Boni laufen über den **EffectResolver** — UI zeigt Serverzustand, keine Client-Math.
- Nicht verwechseln mit **Imperial Directives** (persönliche High-Command-Befehle) oder Allianz-Chat.

## Related Systems

- imperial_directives
- galactic_directives
- galaxy
- command_map
- genesis_ark
- fleet

## Commander Tips

- Vor großen Investitionsentscheidungen Bloc und Trait der Galaxie checken.
- Imperial Directives ≠ Galactic Diplomacy — persönlich vs. Galaxie-Politik.
- Bloc-Wechsel hat Cooldown; während offener Resolution oft gesperrt.

## FAQ

**Was ist der Unterschied zu Imperial Directives?**
Imperial = deine persönlichen Daily/Weekly-Befehle. Diplomacy/Directives = Galaxie-weite Politik und Community-Ausrichtung.

**Muss ich in einer Allianz sein?**
Bloc-Zuordnung läuft über die Allianz. Unzugeordnet zählt als Neutral — Resolutionen und Directives bleiben galaktisch sichtbar.

## Discord Summary

**Diplomatie — Blöcke, Resolutionen, Galaxie-Charakter**

`/galactic-politics`: Allianz-Blöcke, Votes, Resolutionen, Personality, Emergencies. Ergänzt Galactic Directives. ≠ Imperial Directives. Freischaltung nach erstem Besuch.
