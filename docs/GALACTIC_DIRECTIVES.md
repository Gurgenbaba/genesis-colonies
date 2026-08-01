# Galactic Directives — Genesis Colonies

> **Galactic Directives sind die Macro-Politik-Schicht über Planet Policies.**  
> Planet Policies = Mikro (pro Kolonie, Spieler wählt). Galactic Directives = Makro (pro Galaxie, Community-Abstimmung).

Epic: **Galactic Politics** · Ticket: **GC-720A** (dieses Dokument) · Status: ✅ Implementiert (ohne Premium) · Stand: v1.1

Referenz (historisch, **nicht** 1:1 portieren):

- `BETA_OGX_GLAD` — `GovController.php`, `Gov_resultsController.php`
- `DiplomacyController.php` — nur zur Abgrenzung (Allianz-Diplomatie ≠ Galaxie-Politik)

---

## Kernthese

Genesis Colonies braucht **räumlich differenzierte Politik**, nicht einen globalen Buff:

```text
Spieler mit Kolonien in G1, G2, G3
  → interessiert sich für 3 verschiedene Primary/Secondary-Paare
  → Mining-Kolonie vs. Research-Kolonie vs. Shipyard-Kolonie werden strategisch
```

Das System sitzt oben auf der Imperium-Kette aus [IMPERIUM_VISION.md](IMPERIUM_VISION.md):

```text
Planet Evolution → Expansion / Command Map → Kolonien mit Rollen → Imperium → Galactic Directives
```

---

## Abgrenzung (GC-000)

| System | Scope | Ersetzt Galactic Directives? |
|--------|-------|----------------------------|
| **Planet Policies** (`planet_policies`, `pe_policy_definitions`) | Pro Planet, Spieler aktiviert Slots | Nein — komplementär |
| **Galaxy** (`game/galaxy.py`, `[G:S:P]`) | Koordinaten, Systemansicht | Nein — nur Lookup-Dimension |
| **Alliance Hub** (`/alliance`, EPIC-09) | Spieler-/Allianz-Diplomatie | Nein — später evtl. Stimmgewicht, nicht Owner |
| **Planet Evolution Mechanics** | `compile_planet_mechanics()` | Nein — separates Compile-Pipeline |
| **EffectResolver** | Autoritative Zahlen | Nein — **Consumer**, kein Owner |

**Verboten (Lesson aus altem Projekt):**

- `if active_directive == 'scientific': time *= 0.88` in `buildings.py`, `fleet.py`, …
- Frontend-Formeln für Directive-Boni (Regel 16)
- Paralleles `gov_*`-Modul neben `galaxy.py`
- Session-basierter Galaxie-Scope

---

## Architektur

### Zwei Ebenen, ein Mechanics-Format

```text
┌─────────────────────────────────────────────────────────────┐
│  GALACTIC DIRECTIVES (galaxy scope)                         │
│  Primary 100%  +  Secondary 40% (oder secondary_mechanics)  │
│  Quelle: Abstimmung + monatlicher Zyklus                    │
└──────────────────────────┬──────────────────────────────────┘
                           │ planets.galaxy → lookup
┌──────────────────────────▼──────────────────────────────────┐
│  PLANET POLICIES (planet scope)                             │
│  1–3 Slots, Archetype, Cooldowns — [PLANET_EVOLUTION.md]    │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│  EffectResolver (+ domain flags für Expedition/Map)         │
│  game/effects/effect_resolver.py                            │
└─────────────────────────────────────────────────────────────┘
```

### Owner-Modul (neu, Regel 17)

| Domäne | Owner | Doc |
|--------|-------|-----|
| Galactic Directives (State, Cycles, Votes, Resolution) | `game/galactic_directives/` | dieses Dokument |
| Zahlenboni (Produktion, Zeit, Combat, Fleet) | `game/effects/effect_resolver.py` | [EFFECTS.md](EFFECTS.md) |
| Ergebnis-Nachrichten | `game/messages.py` (`create_message`) | ARCHITECTURE |
| Command-Map-Unlocks | `game/planet_evolution/` (bestehende Unlock-Flags) | [GC-570_WORLD_MAP_DIRECTION.md](GC-570_WORLD_MAP_DIRECTION.md) |

Vorgeschlagene Modulstruktur:

```text
game/galactic_directives/
  __init__.py          # public API
  definitions.py       # gd_directive_definitions cache
  repository.py        # DB reads/writes
  cycles.py            # cycle create, phase transitions
  resolution.py        # vote tally, primary/secondary, tie, cooldown
  service.py           # vote submit, admin force, player galaxy list
  resolver.py          # get_active_directives(galaxy) → mechanics bundle
  constants.py         # phase keys, fallback directive, secondary scale
```

### Read-only API (für Banner, EffectResolver, Bots)

```python
# game/galactic_directives/__init__.py (Ziel-Signatur, GC-720C)

def get_active_directives_for_galaxy(galaxy: int, *, conn=None) -> dict:
    """Return primary_key, secondary_key, phase, cycle_id, effect_end_at."""

def get_directive_modifiers_for_planet(planet_row: dict, *, conn=None) -> dict:
    """Resolved EffectResolver delta for planet.galaxy (primary + secondary)."""

def get_player_vote_galaxies(player_id: int, *, conn=None) -> list[int]:
    """Distinct galaxies where player owns ≥1 colony (non-destroyed)."""
```

**Bot-Vote-API (vorbereitet, nicht implementieren in GC-720A–G):**

```python
def submit_vote_for_player(
    player_id: int, galaxy: int, directive_key: str, *, conn=None
) -> dict:  # {ok, status, directive}
    """Status: saved | closed | no_right | cooldown | invalid — BotGovernment später."""
```

---

## Scope: Galaxie

- Lookup über `planets.galaxy` (Migration `016`, [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md)).
- Galaxie-Bereich: `1 … game_settings.galaxy_count` (clamp 1–20).
- Effekte gelten für **alle Kolonien** des Spielers in dieser Galaxie — nicht empire-weit.
- Stimmrecht: Spieler mit **mindestens einem** bewohnten Planeten (`player_id`, Koordinaten gesetzt) in der Galaxie.
- Homeworld-only-Spieler in G1 sehen nur G1; Multi-Galaxy-Imperien sehen Galaxie-Summary (Port aus altem `gov_galaxy_summary`).

---

## Monatlicher Zyklus

Kalenderbasiert (Server-Zeit, UTC empfohlen):

| Phase | Zeitraum | `gd_cycles.status` | Verhalten |
|-------|----------|-------------------|-----------|
| Abstimmung | Tag 1, 00:00 — Monatsende 23:59 | `vote_open` | Stimmen abgeben/ändern (ganzer Kalendermonat) |
| Mandat | Folgemonat Tag 1 — Folgemonatsende | `active` | Primary + Secondary in Kraft (`gd_galaxy_state`) |
| Abgeschlossen | nach Folgemonatsende | `resolved` | Archiv; nächster Monat erzeugt neuen Cycle |

**Launch-Hinweis:** Bestehende Zyklen ohne echte Stimmen werden auf das Vollmonats-Fenster zurückgesetzt, damit die Abstimmung sofort nutzbar ist.

**Resolution-Trigger:** Cron/Request-Hook `resolve_due_cycles()` (Port: `GovController::resolveDueCycles()`):

1. Pro Galaxie: wenn `now > vote_end_at` und Status noch `vote_open` (oder `active` ohne Winner) → `resolve_cycle()`.
2. Wenn `now` in `[effect_start, effect_end]` → Status `active`.
3. Wenn `now > effect_end` → Status `resolved`.
4. Wenn **alle** Galaxien des Universums für `(year, month)` resolved → **einmalig** Ergebnis-Nachricht (GC-720G).

Timestamps in DB als Unix-Integer (`INTEGER`), konsistent mit GC-Queues.

---

## Abstimmung & Resolution

### Stimme

- **Eine Stimme** pro `(player_id, cycle_id)` — Wahl der **Primary-Kandidaten-Direktive**.
- Ändern und Zurückziehen erlaubt, solange `vote_open`.
- Ungültige / leere Stimme beim Submit → Fehler; leere Stimme mit bestehendem Vote → Delete (Port aus altem Cancel-Flow).

### Primary & Secondary (Neu gegenüber altem OGX)

**Alt:** Commander-Zweitstimme = zweite Stimme im **gleichen** Wahlgang → ein Gewinner.

**Genesis:**

| Rang | Quelle | Effektstärke |
|------|--------|--------------|
| **Primary** | Meiste Stimmen | `mechanics_json` × **100%** |
| **Secondary** | Zweitmeiste Stimmen | `secondary_mechanics_json` **oder** skaliertes Primary × **40%** |

**Secondary-Skalierung (wenn kein `secondary_mechanics_json`):**

- Nur **additive** Modifier (z. B. `weapon_bonus`, `discovery_roll_bonus`) werden mit `SECONDARY_SCALE = 0.4` multipliziert.
- **Multiplikative** Faktoren (z. B. `metal_prod_factor`) werden gegen 1.0 skaliert:  
  `factor' = 1.0 + (factor - 1.0) * 0.4`  
  Beispiel: Primary `1.20` → Secondary `1.08`.
- **Tradeoffs** (negative Effekte in `tradeoffs_json`) werden für Secondary **nicht** skaliert mitverstärkt, außer explizit in `secondary_mechanics_json` — verhindert „kostenlosen“ Primary-Malus über Secondary.

**Gleichstand:**

- Primary: zufällige Auswahl unter allen Kandidaten mit `top_votes` (Port: `array_rand` bei Tie).
- Secondary: nächster Rang; bei Tie auf Platz 2 ebenfalls Zufall; wenn nur ein Kandidat → `secondary_directive = NULL`.

**Keine Stimmen:**

1. Primary/Secondary aus vorherigem `gd_galaxy_state` behalten.
2. Wenn kein State: Fallback Primary = `defensive` (deterministisch, dokumentiert).

**Cooldown (2× Sieg in Folge):**

- Zähler `consecutive_primary_wins` auf `gd_galaxy_state`.
- Gewinnt dieselbe Direktive **zweimal hintereinander** als Primary → `cooldown_directive` + `cooldown_until_ym` (nächster Monat `YYYYMM`).
- Während Cooldown: Direktive in UI wählbar markiert als gesperrt; Submit lehnt ab (`cooldown`).

---

## Schema (GC-720B — nur dokumentiert)

Migration-Präfix-Vorschlag: `migrations/NNN_galactic_directives.sql`

### `gd_directive_definitions`

Statische Direktiven (Seed). Analog `pe_policy_definitions`, aber galaxy-politisch.

```sql
CREATE TABLE IF NOT EXISTS gd_directive_definitions (
    directive_key       TEXT PRIMARY KEY,
    family              TEXT NOT NULL,           -- industrial | scientific | ...
    tier                TEXT NOT NULL DEFAULT 'core',  -- core | variant | event
    eligible_as         TEXT NOT NULL DEFAULT '["primary","secondary"]',  -- JSON array
    mechanics_json      TEXT NOT NULL DEFAULT '{}',
    secondary_mechanics_json TEXT NOT NULL DEFAULT '{}',
    tradeoffs_json      TEXT NOT NULL DEFAULT '{}',
    label_key           TEXT NOT NULL,
    desc_key            TEXT NOT NULL,
    sort_order          INTEGER NOT NULL DEFAULT 0
);
```

### `gd_galaxy_state`

Aktueller Mandat-Zustand pro Galaxie (1 Zeile pro Galaxie).

```sql
CREATE TABLE IF NOT EXISTS gd_galaxy_state (
    galaxy                  INTEGER PRIMARY KEY,
    primary_directive       TEXT,
    secondary_directive     TEXT,
    primary_since           INTEGER,
    consecutive_primary_wins INTEGER NOT NULL DEFAULT 0,
    cooldown_directive      TEXT,
    cooldown_until_ym       TEXT,                -- 'YYYYMM'
    last_cycle_id           INTEGER,
    updated_at              INTEGER NOT NULL DEFAULT 0
);
```

### `gd_cycles`

Monatlicher Zyklus pro Galaxie.

```sql
CREATE TABLE IF NOT EXISTS gd_cycles (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    galaxy                  INTEGER NOT NULL,
    year                    INTEGER NOT NULL,
    month                   INTEGER NOT NULL,
    vote_start_at           INTEGER NOT NULL,
    vote_end_at             INTEGER NOT NULL,
    effect_start_at         INTEGER NOT NULL,
    effect_end_at           INTEGER NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'vote_open',
    winning_primary         TEXT,
    winning_secondary       TEXT,
    winning_primary_votes   INTEGER NOT NULL DEFAULT 0,
    winning_secondary_votes INTEGER NOT NULL DEFAULT 0,
    total_votes             INTEGER NOT NULL DEFAULT 0,
    total_voters            INTEGER NOT NULL DEFAULT 0,
    is_tie_primary          INTEGER NOT NULL DEFAULT 0,
    is_tie_secondary        INTEGER NOT NULL DEFAULT 0,
    results_sent            INTEGER NOT NULL DEFAULT 0,
    created_at              INTEGER NOT NULL,
    updated_at              INTEGER NOT NULL,
    UNIQUE (galaxy, year, month)
);
```

### `gd_votes`

```sql
CREATE TABLE IF NOT EXISTS gd_votes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id        INTEGER NOT NULL,
    galaxy          INTEGER NOT NULL,
    player_id       INTEGER NOT NULL,
    directive_key   TEXT NOT NULL,
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL,
    UNIQUE (cycle_id, player_id)
);
```

---

## Mechanics-JSON-Vertrag

Galactic Directives nutzen ein **erweitertes** PE-Mechanics-Format. Zwei Kanäle:

### 1. `effect_resolver` — Zahlen für `EffectResolver`

Additive und multiplikative Keys (werden in GC-720D in `get_modifiers()` gemerged):

| Key | Typ | Bedeutung |
|-----|-----|-----------|
| `metal_prod_factor` | mult | Ferronit-Produktion |
| `crystal_prod_factor` | mult | Crytite-Produktion |
| `fuel_prod_factor` | mult | Brennzellen-Produktion (neu, GC-720D) |
| `storage_factor` | mult | Lagerkapazität |
| `build_time_speed` | mult | >1 = schneller bauen |
| `research_time_speed` | mult | >1 = schneller forschen |
| `shipyard_time_speed` | mult | Werft (neu) |
| `defense_time_speed` | mult | Verteidigungsbau (neu) |
| `mine_energy_factor` | mult | >1 = **mehr** Verbrauch (Mines) |
| `solar_output_factor` | mult | Energieproduktion |
| `weapon_bonus` | add | Combat |
| `armor_bonus` | add | Combat |
| `shield_bonus` | add | Combat |
| `fleet_speed_multiplier` | mult | Fleet |
| `cargo_multiplier` | mult | Fleet |
| `fuel_efficiency_factor` | mult | <1 = weniger Brennstoff |

### 2. `flags` / `unlocks` / `queue_limits` — Domänen-spezifisch

Wie `planet_evolution/mechanics.py`, konsumiert von:

| Token / Flag | Consumer |
|--------------|----------|
| `unlock_queue: {"research": 1}` | `game/research.py` |
| `unlock_queue: {"planet_research": 1}` | `game/planet_evolution/planet_research.py` |
| `expedition_loot_mult` | Expedition-Resolver (`expedition_events.py`) |
| `expedition_slot_bonus` | `get_max_fleet_slots` / `get_fleet_slot_status` in `game/fleet.py` |
| `expedition_event_bonus` | Expedition event pick (`_pick_event_key`) |
| `expedition_legendary_bonus` | Legendary weight boost in `_pick_event_key` |
| `max_colonies_bonus` | Kolonisierungs-Limit |
| `colonize_cost_mult` | `world_colonization.py` / Fleet |
| `planet_xp_mult_cap_level` | `planet_level.py` (z. B. bis Level 10) |
| `trader_daily_limit_mult` | Trader Hub |
| `scrapyard_yield_mult` | Scrapyard |
| `trade_route_speed_mult` | Planet Evolution trade routes |
| `unlock:world:*` | Command Map / `strategic_worlds.py` |
| `unlock:expansion_site:*` | GC-562 Evolution gates |

**Beispiel (Industrial Complex, Primary):**

```json
{
  "effect_resolver": {
    "metal_prod_factor": 1.20,
    "crystal_prod_factor": 1.15,
    "fuel_prod_factor": 1.25,
    "storage_factor": 1.10,
    "build_time_speed": 1.176,
    "mine_energy_factor": 1.20
  },
  "flags": {
    "planet_research_speed_bonus": -0.05
  }
}
```

**Beispiel (Secondary, explizit):**

```json
{
  "effect_resolver": {
    "metal_prod_factor": 1.08,
    "crystal_prod_factor": 1.06,
    "fuel_prod_factor": 1.10
  }
}
```

---

## Die sieben Kern-Direktiven

Canonical keys (englisch, snake_case). UI-Labels via `label_key` / Locale.

> **Hinweis `military` vs. `defensive`:** Im alten OGX gab es nur `defensive`. Genesis trennt **Offensive** (`military`) und **Fortifikation** (`defensive`). Beide bleiben wählbar; Fallback ohne Stimmen ist `defensive`.

---

### 1. `industrial` — Industrial Complex

**Thema:** Massive Industrieoffensive, Produktion vor Wissenschaft.

| | Effekte |
|---|---------|
| **Primary** | +20% Ferronit, +15% Crytite, +25% Brennzellen, +10% Lager, −15% Bauzeit (speed ×1.176), **ABER** +20% Mine-Energieverbrauch, −5% Planet Research Speed (flag) |
| **Secondary** | +8% Ferronit, +6% Crytite, +10% Brennzellen, +4% Lager |
| **Tradeoffs** | +20% Energieverbrauch Mines; −5% Planet Research |

**`mechanics_json` (Primary):**

```json
{
  "effect_resolver": {
    "metal_prod_factor": 1.20,
    "crystal_prod_factor": 1.15,
    "fuel_prod_factor": 1.25,
    "storage_factor": 1.10,
    "build_time_speed": 1.176,
    "mine_energy_factor": 1.20
  },
  "flags": { "planet_research_speed_bonus": -0.05 }
}
```

**Consumer:** `EffectResolver` → `resources.py`, `buildings.py`; Planet Research flag → `planet_evolution/planet_research.py`

**Alt-Referenz:** +10% alle Ressourcen, −5% Fleet-Speed (nur Lang-Text) — Genesis trennt Fleet-Malus in `logistics`/`military`.

---

### 2. `scientific` — Scientific Directive

**Thema:** Forschung und Innovation vor Rohstoffpush.

| | Effekte |
|---|---------|
| **Primary** | +25% Account-Forschung, +1 Research-Queue, +10% Planet Research, +15% Discovery-Roll, +10% Fleet-Speed, **ABER** −15% Waffenbonus |
| **Secondary** | +10% Account-Forschung, +5% Planet Research |
| **Tradeoffs** | −15% `weapon_bonus` |

**`mechanics_json` (Primary):**

```json
{
  "effect_resolver": {
    "research_time_speed": 1.25,
    "fleet_speed_multiplier": 1.10,
    "weapon_bonus": -0.15
  },
  "queue_limits": { "research": 1 },
  "flags": {
    "planet_research_speed_bonus": 0.10,
    "discovery_roll_bonus": 0.15
  }
}
```

**Consumer:** `research.py`, `EffectResolver`, `planet_research.py`, `discoveries.py`, `fleet_calc.py`

**Alt-Referenz:** −12% Research-Zeit, −5% Bau, −8% Energieverbrauch.

---

### 3. `military` — Military Doctrine

**Thema:** Kriegswirtschaft — Werft und Waffen, Forschung und Wirtschaft leiden.

| | Effekte |
|---|---------|
| **Primary** | +20% Waffen, +15% Schild, +10% Panzer, +25% Schiffsbau, +25% Verteidigungsbau, **ABER** −20% Forschung, −10% Ressourcenproduktion |
| **Secondary** | +8% Waffen, +8% Schild, +10% Schiffsbau |
| **Tradeoffs** | −20% Research-Speed; −10% Metal/Crystal/Fuel-Produktion |

**`mechanics_json` (Primary):**

```json
{
  "effect_resolver": {
    "weapon_bonus": 0.20,
    "shield_bonus": 0.15,
    "armor_bonus": 0.10,
    "shipyard_time_speed": 1.25,
    "defense_time_speed": 1.25,
    "research_time_speed": 0.80,
    "metal_prod_factor": 0.90,
    "crystal_prod_factor": 0.90,
    "fuel_prod_factor": 0.90
  }
}
```

**Consumer:** `EffectResolver` → `combat.py`, `shipyard_queue.py`, `defense.py`, `research.py`, `resources.py`

---

### 4. `logistics` — Logistics Network

**Thema:** Flotte, Handel, Routen — das Imperium verbinden.

| | Effekte |
|---|---------|
| **Primary** | +50% Cargo, +20% Fleet-Speed, −25% Brennstoffkosten (fuel_efficiency), +50% Trader-Tageslimit, +20% Scrapyard-Ertrag, +25% Trade-Route-Geschwindigkeit, **ABER** −5% Solarenergie |
| **Secondary** | +20% Cargo, +10% Fleet-Speed, −10% Brennstoff |
| **Tradeoffs** | −5% `solar_output_factor` |

**`mechanics_json` (Primary):**

```json
{
  "effect_resolver": {
    "cargo_multiplier": 1.50,
    "fleet_speed_multiplier": 1.20,
    "fuel_efficiency_factor": 0.75,
    "solar_output_factor": 0.95
  },
  "flags": {
    "trader_daily_limit_mult": 1.50,
    "scrapyard_yield_mult": 1.20,
    "trade_route_speed_mult": 1.25
  }
}
```

**Consumer:** `fleet_calc.py`, `EffectResolver`, Trader Hub (`game/trader*` / economy), Scrapyard, `planet_evolution` trade routes

**Alt-Referenz:** +8% Speed, −12% Deut-Verbrauch, −5% Energie max.

---

### 5. `defensive` — Defensive Doctrine

**Thema:** Festungen, Schilder, Verteidigungslinien — **nicht** Offensive (siehe `military`).

| | Effekte |
|---|---------|
| **Primary** | +15% Schild, +10% Panzer, −10% Verteidigungsbauzeit, +10% Verteidigungs-Effizienz (Combat-Defender), **ABER** −5% Schiffsbau, −5% Fleet-Speed |
| **Secondary** | +6% Schild, −5% Verteidigungsbauzeit |
| **Tradeoffs** | −5% Shipyard-Speed; −5% Fleet-Speed |

**`mechanics_json` (Primary):**

```json
{
  "effect_resolver": {
    "shield_bonus": 0.15,
    "armor_bonus": 0.10,
    "defense_time_speed": 1.10,
    "shipyard_time_speed": 0.95,
    "fleet_speed_multiplier": 0.95
  },
  "flags": { "defense_combat_mult": 0.10 }
}
```

**Consumer:** `defense.py`, `combat.py` (Defender), `shipyard_queue.py`, `fleet_calc.py`

**Alt-Referenz:** −10% Def-Bau, +15% Def-Effizienz, −5% Schiffsbau — **Fallback-Direktive** wenn keine Stimmen.

---

### 6. `expansion` — Expansion Protocol

**Thema:** Kolonisierung, Wachstum, neue Grenzen.

| | Effekte |
|---|---------|
| **Primary** | +1 Max-Kolonie, −30% Kolonisierungskosten, +50% Planet-XP bis Level 10, −10% Bauzeit, +10% Lager, **ABER** −5% Account-Forschung |
| **Secondary** | −15% Kolonisierungskosten, +5% Lager |
| **Tradeoffs** | −5% Research-Speed |

**`mechanics_json` (Primary):**

```json
{
  "effect_resolver": {
    "build_time_speed": 1.10,
    "storage_factor": 1.10,
    "research_time_speed": 0.95
  },
  "flags": {
    "max_colonies_bonus": 1,
    "colonize_cost_mult": 0.70,
    "planet_xp_mult": 1.50,
    "planet_xp_mult_cap_level": 10
  },
  "unlocks": [
    "unlock:expansion_site:frontier_gate_discount",
    "unlock:world:expansion_pool_bonus"
  ]
}
```

**Consumer:** `world_colonization.py`, `planet_level.py`, `buildings.py`, Command Map unlocks, `research.py`

**Alt-Referenz:** −10% Bau, +10% Storage, −5% Research.

---

### 7. `exploration` — Exploration Era

**Thema:** Expeditionen, Anomalien, Command Map — passt zu Imperium/World Map.

| | Effekte |
|---|---------|
| **Primary** | +100% Expeditionsloot, +30% Ancient-Stash-Chance, +25% Wreckage-Chance, +10% Legendary-Discovery, +1 Expeditionsslot, neue Anomalien/Welten auf Karte sichtbar |
| **Secondary** | +40% Expeditionsloot, +10% Event-Chance |
| **Tradeoffs** | −5% Ferronit-Produktion (Ablenkung von Mining) |

**`mechanics_json` (Primary):**

```json
{
  "effect_resolver": { "metal_prod_factor": 0.95 },
  "flags": {
    "expedition_loot_mult": 2.00,
    "expedition_event_bonus": 0.30,
    "expedition_wreckage_bonus": 0.25,
    "expedition_legendary_bonus": 0.10,
    "expedition_slot_bonus": 1
  },
  "unlocks": [
    "unlock:world:anomaly_pool_extended",
    "unlock:world:legendary_sites_teaser"
  ]
}
```

**Consumer:** Expedition-Missionen, `world_progress.py`, `galaxy.py` (Slot 16), Command Map presentation

**Alt-Referenz:** +10% DM, +5% Event, +1 Slot.

---

## EffectResolver-Integration (GC-720D)

**Pflichtflow:**

```text
EffectResolver.__init__(planet_id, player_id, ...)
  → galaxy = planet_row["galaxy"]
  → gd_mods = galactic_directives.resolver.merge_for_galaxy(galaxy)
  → multiplicative keys: prod factors, time speeds, fleet — multiply in
  → additive keys: weapon/armor/shield — add in
  → sources[] Eintrag: {source: "gd_primary:scientific", ...}
```

- Resolver wird **pro Planet-Instanz** aufgebaut (planet scope bleibt).
- Galaxy-Directives sind **read-only** während Effect-Berechnung (kein Side-Effect).
- `get_active_directives_for_galaxy()` darf **keine** Migrations oder Cycle-Resolution auslösen (Lesson: statische Read-API im alten `getActiveDirectiveForGalaxy`).

Domain-Flags (Expedition, Kolonien, Trader) werden **nicht** in `EffectResolver` berechnet, sondern in jeweiligen Ownern via:

```python
from game.galactic_directives import get_directive_flags_for_galaxy
```

---

## UI & Präsentation (GC-720F — Galaxy Status Card)

Read-only **Status-Card** auf der **Galaxie**-Seite (PJAX-safe, serverseitig): Direktive + Diplomatie in einer neutralen Card, ein CTA.

| Surface | Verhalten |
|---------|-----------|
| Overview | Kein Banner (kein Doppel mit Galaxy) |
| Galaxy (system + command_map) | Unified Status-Card für aktuelle Nav-Galaxie |
| CTA | Ein Link zu `/galactic-politics` |

Daten-Owner: `game/galactic_directives/banner.py`, `game/galactic_diplomacy/banner.py`  
Presentation: `templates/partials/galactic_status_banner.html`

Weitere Surfaces (Buildings, Research, Command-Map-Badges) folgen in späteren Tickets.

| Surface | Verhalten (Port-Konzept) |
|---------|--------------------------|
| `/government` oder `/galaxy` Tab | Galaxie-Summary, Phase-Timer, Directive-Cards |
| Overview / Buildings / Research / Shipyard | Context-Banner nur wenn aktive Direktive relevante Effekte hat (alt: `directiveInfoBannerHtml`) |
| Command Map | Badge pro Galaxie-Region, Primary/Secondary-Chips |
| Galaxy Legacy View | `directiveBadgeHtml`-Äquivalent |

Actions: `GC.fetchGameAction` → `{ok, state}` → `applyActionState()` — kein Form-POST mit Redirect wie PHP.

### `/galactic-politics` Dual-Rail (GC-POL-00)

`build_galaxy_politics_entry()` liefert zusätzlich:

| Feld | Inhalt |
|------|--------|
| `mandate` | Geltendes Mandat (in-force election window aus `gd_cycles`, sonst latest/fallback) inkl. Stimmen, Monogramme, Countdown |
| `chronicle` | Letzte ≤6 entschiedenen Zyklen (Wahlmonat + Wirkmonat + Siegel) |
| `active` | Kompatibel (Primary/Secondary Keys für Banner/Legacy) |

Während `vote_open` sieht der Spieler klar: **was jetzt gilt** (vorherige Wahl) vs. **wofür gerade abgestimmt wird**.

Zusätzlich (GC-POL-01…08): `diplomacy` Payload (Personality, Emergency, Bloc-Landschaft, Resolution-Sessions), Chamber-Embleme unter `static/img/politics/`, Player-APIs `/api/galactic-politics/bloc`, `/resolution/propose`, `/resolution/vote`, Command-Map Politics-Strip.

---

## Admin & Tests

| Mode | Verhalten |
|------|-----------|
| `admin_force` | Schließt Abstimmung sofort; setzt Primary (optional Secondary); schreibt `gd_galaxy_state` |
| `admin_unforce` | Setzt Cycle zurück auf `vote_open`, löscht Winner-Felder, optional State-Reset |
| `cron_resolve` | `resolve_due_cycles()` — Worker/Cron-Endpoint |

Nur `user_authlevel` / GC-Admin-Guard — nicht in Spieler-UI.

---

## Ergebnis-Nachrichten (GC-720G)

**Owner:** `game/messages.py` — `create_message(recipient_player_id, subject, body, category="system", sender_name=...)`

**Trigger:** Alle Galaxien `(year, month)` resolved und `results_sent = 0` → Broadcast an alle aktiven Spieler.

**Inhalt (pro Galaxie):**

- Stimmen pro Direktive (Balken / Prozent)
- Gewinner Primary + Secondary
- Tie-Hinweis
- Link-Ziel: Government-Seite / Galaxy-Tab

**Metadaten:** `metadata_json: {kind: "gd_results", year, month, galaxies: [...]}`

Port aus `Gov_resultsController::buildBodyStatic()` — HTML-Body serverseitig, **kein** Client-Template für Zahlen.

---

## Ticket-Kette (nach GC-720A)

| Ticket | Fokus | Status |
|--------|-------|--------|
| **GC-720A** | Master-Doc | ✅ |
| **GC-720B** | Migration + Definitions Seed | ✅ |
| **GC-720C** | Active Directive Resolver | ✅ |
| **GC-720D/E** | EffectResolver + Banner | ✅ |
| **GC-720F** | Voting Cycle + Submit + Resolution + Cooldown | ✅ |
| **GC-720G** | Results Messages (`results_sent`, inbox `gd_results`) | ✅ |
| **GC-720H** | Community-Nav, government-Badge, Banner-CTA, Placeholder-Cleanup | ✅ |
| **GC-720I** | `resolve_due_cycles` Cron + Admin Force/Unforce | ✅ |
| **GC-720J** | Domain-Flag-Consumer (Kolonie, Trader, Scrapyard, Defense, Research-Queue, Planet-XP) | ✅ |

**Owner-Layout (live):** `game/galactic_directives/{definitions,state,mechanics,voting,results,banner}.py` · Routes `/galactic-politics`, `/api/galactic-politics/*`, `/api/internal/cron/galactic-directives`, `/api/admin/galactic-directives/*`

**Defer:** `unlock:world:*` / `unlock:expansion_site:*` — kein Unlock-Pipeline-Consumer; `trade_route_speed_mult` — kein Trade-Route-Owner.

---

## Erweiterungen (Backlog, nicht GC-720)

| Thema | Beschreibung |
|-------|--------------|
| **Commander / Premium** | Entscheidung: **gewichtete Stimme** oder **garantiertes Secondary-Pick** — **nicht** zwei Stimmen im selben Wahlgang. Kein Premium-Owner im MVP; Free behält 1 Stimme. |
| Allianz-Bloc-Voting | EPIC-09 — Stimmen aggregieren, Owner bleibt `galactic_directives` |
| 20–30 Direktiven | `tier: variant | event` in Definitions; Pools pro Galaxie-Region |
| DiplomacyController | Allianz-PNA/Krieg — separates System, keine Directive |
| Dynamische Zykluslänge | Saison-Events; aktuell: Kalendermonat fix |

---

## Tests

| Bereich | Datei |
|---------|-------|
| Definitions, Resolver, Mechanics, Voting, Cron, Admin, Results, Flags | `tests/test_galactic_directives.py` |
| Government Nav-Badge | `tests/test_nav_badges.py` |
| Politics Nav (kein Placeholder) | `tests/test_placeholder_nav.py` |

---

## Verwandte Dokumente

- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) — GC-000, Regeln 15–17
- [EFFECTS.md](EFFECTS.md) — EffectResolver
- [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md) — `planets.galaxy`
- [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md) — Planet Policies
- [IMPERIUM_VISION.md](IMPERIUM_VISION.md) — Imperiums-Entscheidungen
- [FLEET_SYSTEM.md](FLEET_SYSTEM.md) — Expedition, Kolonisierung
- [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) — Trader Hub, Produktion
- [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md) — Vote-Actions

---

## Changelog

| Version | Datum | Änderung |
|---------|-------|----------|
| v1.1 | 2026-07-26 | GC-720G/H/I/J — Politics fertig ohne Premium: Nav, Cron/Admin, Results, Domain-Flags |
| v1.0 | 2026-06-17 | GC-720A — Initial Master-Doc aus OGX Gov-Port + Primary/Secondary-Design |
