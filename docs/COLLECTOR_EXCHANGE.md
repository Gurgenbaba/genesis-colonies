# Collector Exchange — Design-Charta

> **Epic:** EPIC-18 Collector Exchange (Erweiterung EPIC-04 Economy)  
> **Status:** 🔄 GC-965A/B + GC-966A/B implementiert · GC-967 Inventar-Hints · GC-969 Prestige 📋  
> **Stand:** 2026-06-27  
> **Vision:** Jeder Loot-Drop ist Fortschritt — sofort nutzbar oder sichtbar auf dem Weg zum nächsten Ziel.

Verwandte Docs: [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) · [GC-864_LOOT_ECONOMY_REBALANCE.md](GC-864_LOOT_ECONOMY_REBALANCE.md) · [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md) · [FLEET_SYSTEM.md](FLEET_SYSTEM.md) · [RESEARCH_SYSTEM.md](RESEARCH_SYSTEM.md)

---

## Grundregel

> **Sammlerstücke sind keine Tauschwährung mit festem Goldwert. Sie sind persönlicher Fortschritt mit zwei Rollen: Sammeln und Ausgeben.**

> **Der Spieler freut sich über jedes einzelne Fragment — nicht erst beim fertigen Item.**

### Leitfrage für jedes Design-Ticket

> *Fühlt sich der Drop an wie „Cool… und jetzt?" — oder wie „Noch 3 Wrack-Hüllen bis zum Werft-Booster"?*

Wenn die Antwort „und jetzt?" ist → Angebot, Progress-Bar oder Prestige-Milestone fehlt.

### Verhältnis zu GC-864 (Meta-only Loot)

| System | Schiffe / Ressourcen erlaubt? |
|--------|-------------------------------|
| Lootbox-Roll (`inventory_loot.py`) | **Nein** — nur `item` / `booster` |
| Collector Exchange (dieses System) | **Ja, kuratiert** — feste Offers, kein Zufalls-Inflations-Roll |
| Werft / Produktion / Kampf | Kanonische Quellen |

Wrackrekonstruktion (100× Wrack-Hülle → Schiffspaket) ist **kein** Lootbox-Roll, sondern ein definierter Exchange-Offer mit festem Input und gewichtetem Output-Pool — dokumentiert und balancebar.

---

## Problem

Nach GC-864 liefern Container sinnvolle Meta-Items — aber viele landen im Inventar mit Badge **„Sammlerstück — Endgame-Inhalt, später verfügbar"**. Das erzeugt tote Motivation:

1. Lootbox öffnen → Fragment erhalten → kein nächster Schritt sichtbar.
2. DNA-Fragmente haben Craft (50→Kapsel), aber kein breiteres Ökosystem.
3. Wrack-, Alien- und Hyperantriebs-Fragmente haben keinen klaren Zweck.
4. Keine Langzeit-Statistik — Sammeln lohnt sich nicht gegenüber sofortigem Verkauf (den es nicht gibt).

---

## Lösung — Collector Exchange im Trader Hub

Neuer Bereich **`/trader-hub`** mit **vier Spezialisten-Händlern**. Sie tauschen **keine Ressourcen**, sondern **Sammlerstücke gegen Fortschritt** (Booster, Utility, seltene Items, kuratierte Schiffspakete).

```text
Trader Hub
├── Unified Resource Trader   (bestehend — metal/crystal/fuel_cells)
├── Schrottplatz              (bestehend — Schiffe recyceln)
└── Collector Exchange        (neu)
    ├── 🧬 Xenobiologe
    ├── 🔧 Schrottmeister
    ├── ⚡ Energieingenieur
    └── 🚀 Hypertechniker
```

**Scope:** Account-weit (Inventar ist spielergebunden). Planet-Kontext nur wenn Belohnung planetengebunden ist (z. B. Planet XP → `get_context_planet()`).

---

## Zwei Rollen jedes Collectables

| Rolle | Persistenz | Sink? | Zweck |
|-------|------------|-------|-------|
| **Lifetime Collected** | `collector_lifetime_stats.lifetime_acquired` | **Nein** — nur hoch | Erfolge, Titel, Profil-Rahmen, Rankings |
| **Inventory Balance** | `player_inventory_items.amount` | **Ja** — bei Redeem | Tausch gegen Offers |

**Regel:** Jeder Grant ins Inventar (Lootbox, Expedition, Admin, Exchange-Output) inkrementiert `lifetime_acquired[item_key]`. Redeem dekrementiert nur Inventar — **nie** Lifetime.

**Spielerentscheidung:**

> 100 Wrack-Hüllen jetzt für Werft-Booster — oder weiter sammeln bis 500 für Titel **„Galaktischer Schrotthändler"**?

---

## Architektur (GC-000)

### Owner

| System | Owner | Doc |
|--------|-------|-----|
| Collector Exchange (Offers, Redeem, Stats) | `game/collector_exchange.py` | dieses Dokument |
| Offer-Katalog (Definitionen) | `game/collector_catalog.py` | dieses Dokument |
| Inventar-Grant / -Consume | `game/inventory.py` | [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) |
| Item-Metadaten | `game/inventory_catalog.py` | GC-540 |
| Trader Hub UI | `templates/trader_hub.html`, `templates/partials/collector_*.html` | [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) |
| Prestige-Titel / Rahmen | `game/collector_prestige.py` (Phase 3) | dieses Dokument |

**Verboten:** Paralleles Tauschsystem außerhalb `collector_exchange.py`. DNA-Core-Craft/Upgrade bleibt in `inventory_use.py` — ergänzt, ersetzt nicht.

### APIs

| Route | Methode | Response |
|-------|---------|----------|
| Trader Hub Seite | `GET /trader-hub` | PJAX partial inkl. `collector_exchange` Block |
| Redeem | `POST /api/collector-exchange/redeem` | `{ ok, state }` → `applyActionState()` |
| Live-State | `GET /api/game-state` | `collector_exchange` + `collector_prestige` |

**Redeem-Body:**

```json
{
  "offer_key": "xeno_dna_common_research_booster",
  "request_id": "…"
}
```

Idempotent via `request_id` / `X-Request-Id` (wie Exchange/Build).

### Live-State-Payload (Auszug)

```json
{
  "collector_exchange": {
    "ready": true,
    "specialists": [
      {
        "specialist_key": "xenobiologist",
        "name_key": "collector_spec_xenobiologist",
        "icon": "🧬",
        "offers": [
          {
            "offer_key": "xeno_dna_common_research_booster",
            "input_key": "fragment_dna_common",
            "input_amount": 50,
            "owned": 18,
            "progress_pct": 36,
            "can_redeem": false,
            "reward_preview": [
              {"reward_type": "booster", "reward_key": "booster_research_30m", "amount": 1}
            ],
            "name_key": "collector_offer_xeno_dna_common_research_booster",
            "category_key": "collector_cat_research"
          }
        ]
      }
    ]
  },
  "collector_prestige": {
    "lifetime_totals": {"fragment_wreck_hull": 247, "fragment_alien": 12},
    "milestones": [
      {"milestone_key": "scrap_dealer_bronze", "progress": 247, "target": 500, "unlocked": false}
    ],
    "active_title": null,
    "active_frame": null
  }
}
```

**Frontend:** Progress-Bars und `can_redeem` **nur** aus Server-Payload — keine Client-Math (GC-000 Regel 16).

---

## Schema (Migration `082_collector_exchange.sql`)

### `collector_lifetime_stats`

| Spalte | Typ | Beschreibung |
|--------|-----|--------------|
| `user_id` | FK | Commander |
| `item_key` | TEXT | Katalog-Key |
| `lifetime_acquired` | INT | Summe aller Grants (nie dekrementiert) |
| `lifetime_redeemed` | INT | Summe aller Redeems (Audit) |
| `updated_at` | TIMESTAMP | |

PK: `(user_id, item_key)`

### `player_collector_milestones`

| Spalte | Typ |
|--------|-----|
| `user_id` | FK |
| `milestone_key` | TEXT |
| `unlocked_at` | TIMESTAMP |
| `claimed_at` | TIMESTAMP NULL |

### `collector_exchange_log`

| Spalte | Typ |
|--------|-----|
| `id` | PK |
| `user_id` | FK |
| `offer_key` | TEXT |
| `input_key` | TEXT |
| `input_amount` | INT |
| `rewards_json` | TEXT |
| `created_at` | TIMESTAMP |

### `collector_exchange_redemptions` (GC-965B Idempotenz)

| Spalte | Typ |
|--------|-----|
| `id` | PK |
| `user_id` | FK |
| `offer_key` | TEXT |
| `request_id` | TEXT UNIQUE pro User |
| `input_key` | TEXT |
| `input_amount` | INT |
| `rewards_json` | TEXT |
| `created_at` | TIMESTAMP |

**Offer-Definitionen:** kanonisch in `game/collector_catalog.py` (`COLLECTOR_OFFERS`) — **keine** parallele DB-Tabelle (GC-000).

**Hook:** `inventory.grant_item()` ruft `collector_exchange.record_acquired(user_id, item_key, amount)` — zentral, nicht pro Loot-Quelle.

---

## Die vier Spezialisten

### 🧬 Xenobiologe (`xenobiologist`)

**Materialien:** DNA-Fragmente (Common/Rare/Epic), Alien-Fragmente, Forschungs-Artefakte (optional Phase 2).

**Thema:** Forschung, Planet Evolution, Xenobiologie.

| Offer-Key | Input | Menge | Belohnung (Auswahl 1× pro Redeem) |
|-----------|-------|-------|-----------------------------------|
| `xeno_dna_common_research_booster` | `fragment_dna_common` | 50 | `booster_research_30m` ×1 |
| `xeno_dna_common_research_pct` | `fragment_dna_common` | 50 | `booster_research_pct_2_24h` ×1 |
| `xeno_dna_common_planet_xp` | `fragment_dna_common` | 50 | `evo_planet_xp_250` ×1 |
| `xeno_dna_common_dna_capsule` | `fragment_dna_common` | 50 | `dna_core_common` ×1 |
| `xeno_dna_rare_research_bundle` | `fragment_dna_rare` | 25 | `booster_research_6h` ×1 |
| `xeno_dna_rare_evo_xp` | `fragment_dna_rare` | 25 | `evo_planet_xp_5000` ×1 |
| `xeno_dna_rare_research_crate` | `fragment_dna_rare` | 25 | `container_research_cache` ×1 |
| `xeno_dna_rare_random_module` | `fragment_dna_rare` | 25 | Gewichtet: `research_data_energy` / `mining` / `weapons` ×1 |
| `xeno_dna_epic_research_24h` | `fragment_dna_epic` | 10 | `booster_research_24h` ×1 |
| `xeno_dna_epic_planet_xp_big` | `fragment_dna_epic` | 10 | `evo_planet_xp_50000` ×1 |
| `xeno_alien_scanner` | `fragment_alien` | 15 | `utility_alien_scanner` ×1 |
| `xeno_alien_expo_booster` | `fragment_alien` | 10 | `booster_expedition_loot_25_24h` ×1 |
| `xeno_alien_loot_booster` | `fragment_alien` | 10 | `booster_container_luck_24h` ×1 |

**Hinweis Craft vs. Exchange:** 50× Common → DNA-Kapsel ist **identisch** zum Inventar-Craft — UI zeigt beide Wege; Exchange liefert alternative Offers auf gleicher Menge.

---

### 🔧 Schrottmeister (`scrapmaster`)

**Materialien:** Wrack-Hülle, Wrack-Reaktor, Flottenmodule (Computer, Fuel Optimizer — Phase 2).

**Thema:** Werft, Verteidigung, Bergung.

| Offer-Key | Input | Menge | Belohnung |
|-----------|-------|-------|-----------|
| `scrap_hull_shipyard_15m` | `fragment_wreck_hull` | 20 | `booster_shipyard_15m` ×2 |
| `scrap_hull_shipyard_1h` | `fragment_wreck_hull` | 20 | `booster_shipyard_1h` ×1 |
| `scrap_hull_repair_drones` | `fragment_wreck_hull` | 20 | `utility_repair_drone` ×3 |
| `scrap_hull_random_ship_small` | `fragment_wreck_hull` | 20 | Gewichtet: `spark_drone` ×5 / `mule_courier` ×3 |
| `scrap_hull_reconstruction` | `fragment_wreck_hull` | 100 | **Wrackrekonstruktion** (siehe unten) |
| `scrap_reactor_defense_booster` | `fragment_wreck_reactor` | 15 | `booster_build_1h` ×1 + `booster_shipyard_15m` ×1 |
| `scrap_reactor_fuel_cells` | `fragment_wreck_reactor` | 15 | `resource_pack_fuel` ×2 |
| `scrap_computer_fleet_slot` | `fleet_computer` | 5 | `utility_fleet_queue_plus_1` ×1 (24h) |

#### Wrackrekonstruktion (`scrap_hull_reconstruction`)

Einmaliger Offer — 100× `fragment_wreck_hull`:

| Gewicht | Output |
|---------|--------|
| 50 | `atlas_hauler` ×10 |
| 30 | `falcon_interceptor` ×5 |
| 20 | `ironclad_frigate` ×2 |

Schiffe werden dem **context planet** gutgeschrieben (`planet_fleet` oder kanonischer Fleet-Inventar-Pfad — Owner `game/fleet.py`). Kein Storage-Cap-Problem (Schiffe ≠ Ressourcen).

**Balance-Anker:** 100 Hüllen ≈ 33–50 Wrack-Container-Opens — Epic-Belohnung, kein Daily-Farm.

---

### ⚡ Energieingenieur (`energy_engineer`)

**Materialien:** Datenkerne (Energy/Mining/Weapons), Energie-Booster aus Loot.

**Thema:** Wirtschaft, Produktion, Energie.

| Offer-Key | Input | Menge | Belohnung |
|-----------|-------|-------|-----------|
| `energy_core_production_25` | `research_data_energy` | 3 | `booster_production_25` ×1 |
| `energy_core_production_50` | `research_data_energy` | 5 | `booster_production_50` ×1 |
| `energy_core_energy_surge` | `research_data_energy` | 5 | `booster_energy_surge_24h` ×1 |
| `energy_core_planet_xp` | `research_data_energy` | 8 | `evo_planet_xp_500` ×1 |
| `energy_mining_production` | `research_data_mining` | 3 | `booster_production_25` ×1 (Mining-Fokus-Label) |
| `energy_weapons_build` | `research_data_weapons` | 3 | `booster_build_1h` ×1 |

**Dual-Use:** Datenkerne bleiben **im Inventar nutzbar** (`use_kind: research_datacore`) — Exchange ist Alternative, nicht Ersatz.

---

### 🚀 Hypertechniker (`hyper_technician`)

**Materialien:** Hyperantriebs-Modul (epic — **niemals** „verkaufen" oder in Ressourcen tauschen).

**Thema:** Flotte, Expedition, Premium-Utility.

| Offer-Key | Input | Menge | Belohnung |
|-----------|-------|-------|-----------|
| `hyper_fleet_speed_25` | `fleet_hyperdrive_module` | 5 | `booster_fleet_speed_25_24h` ×1 |
| `hyper_instant_recall` | `fleet_hyperdrive_module` | 20 | `utility_fleet_instant_recall` ×1 |
| `hyper_legendary_crate` | `fleet_hyperdrive_module` | 50 | `container_relic` ×1 |
| `hyper_nav_expo_bundle` | `fleet_nav_chip` | 8 | `booster_expedition_loot_25_24h` + `expo_star_chart` ×1 |
| `hyper_pirate_scanner` | `fragment_alien` | 20 | `utility_pirate_scanner` ×1 |
| `hyper_anomaly_scanner` | `fragment_artifact_alpha` | 12 | `utility_anomaly_scanner` ×1 |

Hypertechniker hostet auch **seltene** Offers, die Items mehrerer Kategorien kombinieren — aber nur Items aus seinem Themen-Fokus.

---

## Progress-Bar UX

Jeder Offer im Specialist-Panel zeigt:

```text
DNA-Fragment (Common)
███████░░░░░░░░  18 / 50
Belohnung: Forschungsbooster (30 Min)
[ Noch 32 sammeln ]  oder  [ Einlösen ]  (wenn can_redeem)
```

**Regeln:**

1. Bar = `owned / input_amount` aus Server — `progress_pct` für `aria-valuenow`.
2. Mehrere Offers mit **gleichem Input** (50× Common → 4 verschiedene Belohnungen) teilen sich `owned`, unterscheiden sich in `input_amount` nur wenn unterschiedlich.
3. Inventar-Liste: Collectibles zeigen **nächstes erreichbares Offer** des zuständigen Spezialisten + Deep-Link „Im Trader Hub einlösen".
4. Lootbox-Reveal: optional Toast „+1 Wrack-Hülle — 19/20 bis Werft-Booster" (Phase 2, aus `game-state` diff).

Badge-Text **`inv_collectible_hint`** wird ersetzt durch dynamischen Hint aus nächstem Offer.

---

## Prestige & Meilensteine (Phase 3)

### Lifetime-Statistik

Profil / Empire Screen / Ranking:

- „1.247 Alien-Fragmente gefunden"
- „Wrack-Hüllen gesammelt: 892 · eingelöst: 640"

### Meilenstein-Tabelle (Auszug)

| Milestone-Key | Bedingung (`lifetime_acquired`) | Belohnung |
|---------------|----------------------------------|-----------|
| `dna_scholar_bronze` | `fragment_dna_common` ≥ 500 | Titel „DNA-Forscher" |
| `dna_scholar_silver` | `fragment_dna_rare` ≥ 200 | Profil-Rahmen „Xeno-Lab" |
| `scrap_dealer_bronze` | `fragment_wreck_hull` ≥ 500 | Titel „Galaktischer Schrotthändler" |
| `scrap_dealer_gold` | `fragment_wreck_hull` ≥ 2000 | Rahmen „Wracklegende" |
| `alien_archivist` | `fragment_alien` ≥ 100 | Titel „Xeno-Archivar" |
| `hyper_engineer` | `fleet_hyperdrive_module` ≥ 50 | Titel „Hypertechniker" + `container_void_artifact` ×1 (einmalig) |
| `genesis_curator` | `fragment_genesis` ≥ 25 | Prestige-only — **kein** Exchange, nur Anzeige |

**Prestige-only Items** (nie einlösbar): `fragment_genesis`, `mythic_genesis_core`, `mythic_ancient_nexus`, `artifact_core_fragment` (Phase 1), `fragment_quantum` — maximieren Langzeit-Jagd.

### Titel-Aktivierung

`POST /api/collector-prestige/claim-milestone` → `{ ok, state }`  
`POST /api/collector-prestige/set-title` — kosmetisch, kein Gameplay-Effekt.

---

## Neue Items (Katalog-Erweiterung)

Diese Keys werden in `inventory_catalog.py` ergänzt (Phase 1/2):

| Key | Typ | use_kind | Beschreibung |
|-----|-----|----------|--------------|
| `booster_research_30m` | booster | time_boost | 30 Min Forschungs-Queue |
| `booster_research_pct_2_24h` | booster | research_pct | +2 % Forschungsgeschwindigkeit, 24h (EffectResolver) |
| `booster_fleet_speed_25_24h` | booster | fleet_speed_pct | +25 % Flottengeschwindigkeit, 24h |
| `booster_expedition_loot_25_24h` | booster | expedition_loot_pct | +25 % Expeditionsloot-Chance, 24h |
| `booster_container_luck_24h` | booster | container_luck | Bessere Container-Roll-Tier-Chance, 24h |
| `booster_energy_surge_24h` | booster | energy_pct | +10 % Solar-Output, 24h |
| `evo_planet_xp_250` | consumable | planet_xp | 250 Planet XP |
| `utility_repair_drone` | consumable | repair_drone | −5 % Werft-Queue auf nächstes Item |
| `utility_fleet_instant_recall` | consumable | fleet_recall | Sofort-Rückruf ohne Zeitverlust (1×) |
| `utility_alien_scanner` | consumable | scanner | Alien-Signale auf Karte, 7 Tage |
| `utility_pirate_scanner` | consumable | scanner | Piraten-Aktivität, 7 Tage |
| `utility_anomaly_scanner` | consumable | scanner | Anomalie-Hinweise, 7 Tage |
| `utility_fleet_queue_plus_1` | consumable | fleet_slot_temp | +1 Flottenslot, 24h |

Booster mit `%`-Effekt: Integration über `EffectResolver` + `player_active_boosters` (bestehendes Muster prüfen in `inventory_use.py` / `effects/`).

---

## Offer-Katalog-Format (`game/collector_catalog.py`)

```python
COLLECTOR_SPECIALISTS = {
    "xenobiologist": {
        "name_key": "collector_spec_xenobiologist",
        "icon": "🧬",
        "description_key": "collector_spec_xenobiologist_desc",
        "sort": 10,
    },
    # ...
}

COLLECTOR_OFFERS = {
    "xeno_dna_common_research_booster": {
        "specialist_key": "xenobiologist",
        "input_key": "fragment_dna_common",
        "input_amount": 50,
        "rewards": [
            {"reward_type": "booster", "reward_key": "booster_research_30m", "amount": 1},
        ],
        "name_key": "collector_offer_xeno_dna_common_research_booster",
        "category_key": "collector_cat_research",
        "sort": 10,
        "enabled": True,
    },
    "scrap_hull_reconstruction": {
        "specialist_key": "scrapmaster",
        "input_key": "fragment_wreck_hull",
        "input_amount": 100,
        "rewards": [
            {"reward_type": "ship_weighted", "pool": [
                {"weight": 50, "ship_key": "atlas_hauler", "amount": 10},
                {"weight": 30, "ship_key": "falcon_interceptor", "amount": 5},
                {"weight": 20, "ship_key": "ironclad_frigate", "amount": 2},
            ]},
        ],
        "name_key": "collector_offer_scrap_hull_reconstruction",
        "category_key": "collector_cat_wreck",
        "sort": 100,
        "one_time": False,
        "enabled": True,
    },
}
```

**Reward-Typen:** `item`, `booster`, `ship`, `ship_weighted`, `container` — Validierung analog `sanitize_loot_pool`, aber **`ship` hier erlaubt** (nur in Offers, nicht in Loot-Pools).

---

## Redeem-Ablauf

```text
POST /api/collector-exchange/redeem
  → finish_due_work_once()          # Queues aktuell
  → validate offer_key, enabled
  → check inventory >= input_amount
  → consume input (inventory.py)
  → grant rewards (inventory / fleet / boosters)
  → log collector_exchange_log
  → increment lifetime_redeemed
  → build game-state payload
  → { ok: true, state: … }
```

**Fehlercodes:** `offer_not_found`, `insufficient_items`, `offer_disabled`, `prestige_only_item`, `planet_required`.

---

## UI — Trader Hub Erweiterung

### Layout

```text
┌─ Trader Hub ─────────────────────────────────────────────┐
│ [ Ressourcen ] [ Schrottplatz ] [ Sammler-Markt ]         │
├──────────────────────────────────────────────────────────┤
│ Sammler-Markt:                                            │
│ [ 🧬 Xenobiologe ] [ 🔧 Schrottmeister ] [ ⚡ ] [ 🚀 ]    │
├──────────────────────────────────────────────────────────┤
│ ┌ Offer Card ──────────────────────────────────────────┐ │
│ │ 🧬 DNA-Fragment (Common)                              │ │
│ │ ███████░░░░░░░░  18/50                                │ │
│ │ Belohnung: 30 Min Forschungsbooster                   │ │
│ │                              [ Einlösen ] (disabled)  │ │
│ └───────────────────────────────────────────────────────┘ │
│ … weitere Offers …                                        │
└──────────────────────────────────────────────────────────┘
```

- PJAX: Tab-Wechsel ohne Reload; `GC.initCollectorExchange()` + `GC.cleanupPage()`.
- Mobile: Specialist-Chips horizontal scroll; Offer-Cards stacked.
- `z-index` / Overflow: gleiche Regeln wie HUD-Selects ([genesis-colonies.mdc](../.cursor/rules/genesis-colonies.mdc)).

### Inventar-Integration

- Collectibles: Badge „Sammlerstück" bleibt; Hint = nächstes Offer.
- Link-Button: „Zum Sammler-Markt" → `GC.navigateTo('/trader-hub?collector=xenobiologist')`.
- Craft-Progress (DNA) bleibt parallel sichtbar.

---

## Balance-Philosophie

| Prinzip | Umsetzung |
|---------|-----------|
| Kein festes Gold | Offers in Fragment-Mengen, nicht in Ressourcen-Äquivalent |
| Schlechter Drop = Fortschritt | Jedes Fragment füllt mindestens einen Progress-Bar |
| Seltenheit = Wert | Alien/Hyper-Offers teurer; Prestige-only für Mythics |
| Keine Economy-Inflation | GC-864 bleibt für Lootboxen; Schiffe nur über Wrackrekonstruktion |
| Spend vs. Hoard | Lifetime-Stat macht Horten sinnvoll; Meilensteine belohnen es |
| Admin-tunable | `enabled` pro Offer; Settings `collector_exchange_enabled` |

**Referenz-Anker:** Ein aktiver Spieler öffnet ~2–4 Container/Tag → Common-DNA ~2–4/Tag → 50er-Offer in ~2 Wochen ohne Zusatzquellen. Rare Offers: Wochen–Monate. Hyper 50er: Quartals-Jagd.

---

## Ticket-Zerlegung

**Nicht als Epic implementieren** — Phasen à 3–5 Dateien:

| Ticket | Fokus | Dateien (ca.) |
|--------|-------|---------------|
| **GC-965A** | Schema + `collector_catalog.py` + Offer-Definitionen (ohne UI) | migration, `collector_catalog.py`, tests |
| **GC-965B** | `collector_exchange.py` — redeem, stats hook, game-state | `collector_exchange.py`, `inventory.py`, `app.py`, tests |
| **GC-966A** | Trader Hub Tab + Xenobiologe-Panel | `trader_hub.html`, partial, `main.js`, locales |
| **GC-966B** | Schrottmeister + Wrackrekonstruktion (Fleet-Grant) | partial, `fleet.py`, tests |
| **GC-966C** | Energieingenieur + Hypertechniker Panels | partials, locales |
| **GC-967** | Inventar-Hints + Progress deep-links | `inventory.html`, `inventory_use.py`, `main.js` |
| **GC-968** | Neue Booster/Utility-Items + EffectResolver | `inventory_catalog.py`, `effects/`, `inventory_use.py` |
| **GC-969** | Prestige — Milestones, Titles, Profile | `collector_prestige.py`, migration, empire UI |
| **GC-969B** | Loot-Reveal Toast + Codex Player Block | `main.js`, ECONOMY_SYSTEM Player Block |

Abhängigkeit: 965A → 965B → 966* → 967/968 parallel → 969.

---

## Tests (Pflicht)

| Test | Verhalten |
|------|-----------|
| `test_collector_exchange_redeem` | Happy path, consume, grant, state payload |
| `test_collector_lifetime_never_decrements` | Redeem senkt nicht `lifetime_acquired` |
| `test_collector_insufficient` | 400 + kein Inventar-Change |
| `test_collector_ship_reconstruction` | Schiffe auf context planet |
| `test_collector_idempotent` | Gleiches `request_id` |
| `test_collector_prestige_milestone` | Unlock bei Threshold |
| `test_collector_gc864_isolation` | Loot-Pools enthalten keine `ship`-Rewards |

---

## Player Article Block (Codex / GC-950)

```yaml
# ECONOMY_SYSTEM.md — Player Block (Entwurf)
player_article:
  id: economy_collector_exchange
  title_de: "Sammler-Markt im Trader Hub"
  unlock: { min_containers_opened: 1 }
  summary_de: >
    Sammle Fragmente aus Lootboxen und Expeditionen. Tausche sie bei
    Spezialisten im Trader Hub gegen Booster und seltene Belohnungen —
    oder horte sie für Titel und Meilensteine.
  faq:
    - q: "Verschwinden gesammelte Fragmente aus meiner Statistik?"
      a: "Nein. Deine Gesamt-Sammelstatistik wächst dauerhaft — auch wenn du Fragmente eintauschst."
```

---

## Offene Entscheidungen (vor Implementierung)

| # | Frage | Empfehlung |
|---|-------|------------|
| 1 | DNA-Kapsel: Craft und Exchange redundant? | Ja — bewusst; UI zeigt „oder beim Xenobiologen" |
| 2 | `artifact_core_fragment` eintauschbar? | Phase 2 nur Hypertechniker-Endgame-Offer |
| 3 | Tageslimit für Redeems? | Nein — Input-Rate limitiert natürlich |
| 4 | Alliance-weite Stats? | Nein — persönliches Prestige (Phase 4 optional) |

---

## Ausgabe (nach Implementierung)

- Root Cause
- Changed Files
- Tests
- Ergebnis
