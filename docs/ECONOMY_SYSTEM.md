# Economy System

Ressourcen, Produktion, Trader Hub und Unified Resource Trader.  
**Stand:** v1.5.9.x · Ankerkurven: [BALANCE_ANCHORS.md](BALANCE_ANCHORS.md)

Formeln: autoritativ in `game/production_formula.py` — siehe [PRODUCTION_FORMULA_SYSTEM.md](PRODUCTION_FORMULA_SYSTEM.md).  
Energie, Storage, Build-Time: `game/effects/effect_resolver.py` — [EFFECTS.md](EFFECTS.md).

---

## Ressourcen

| Key | UI-Name | Storage cap | Scope |
|-----|---------|-------------|-------|
| `metal` | Ferronit | Ja (`metal_storage` + Tech) | Planet |
| `crystal` | Crytite | Ja (`crystal_storage` + Tech) | Planet |
| `fuel_cells` | Brennzellen | Ja (`fuel_storage` + Tech) | Planet |
| `energy_total` / `energy_used` | Energie | Derived, persisted | Planet |

**Kein Deuterium** — Fuel für Schiffe = `fuel_cells`.

Spalten auf `planets`; Gebäude-Level auf `planet_buildings` pro `planet_id`.

---

## Produktions-Tick

Entry: `update_planet_resources()` in `game/resources.py`

```
finish_due_work_once()          # optional, wenn nicht skip_queue_finish
elapsed = now - last_update
EffectResolver → rates, energy
apply_production_delta(metal, crystal)  # capped by storage
fuel_cells += delta                     # capped by fuel_storage capacity
save last_update, energy_*
evolution_tick_planet()         # wenn Schema ready
```

Aufgerufen von:

- `refresh_player_live_state()` — context planet für Poll
- Admin/Worker ticks
- Nach Queue-Finish (`sync_derived_state_after_queue_finish`)

---

## Energie

- **Supply:** `solar_plant` (+ `geothermal_nexus` via `solar_output_factor`)
- **Demand:** `metal_mine`, `crystal_mine`, `fuel_cell_plant`
- **Skalierung:** `energy_ratio = min(1, total/used)` drosselt alle Produktionsraten
- **`energy_tech`:** reduziert nur Minen-Verbrauch (`mine_energy_factor`)
- **Klima (Galaxie-Slot 1–15):** `planet_visuals.climate_economy_modifiers_for_position` → `EffectResolver` multipliziert `solar_output_factor` (Slot 1 ≈ +42 % Solar, Slot 15 ≈ −50 %). Gleiche Quelle wie Temperatur/Hero-Theme.

---

## Klima & Produktion (Galaxie-Slot) — GC-820

**Solar:** weiterhin über `climate_economy_modifiers_for_position` → `solar_output_factor` in `EffectResolver`.

**Minen-Produktion:** Primär Slot- und Temperatur-Modifier in `game/production_formula.py`.

**Zusätzlich:** Klima-`metal_prod_factor` / `crystal_prod_factor` / `fuel_prod_factor` aus `planet_visuals.climate_economy_modifiers_for_position` fließen als **`directive_modifier`** in `ProductionContext` (`EffectResolver.prod_overlay_factor()` — Klima + Galactic Directives + Diplomacy).

| Ressource | Slot-Bereich (production_formula) | Max-Bonus |
|-----------|-----------------------------------|-----------|
| Ferronit | 4–9 | +20 % |
| Crytite | 1–3 | +25 % |
| Brennzellen | 10–15 | +20 % (+ Temperatur 0.75–1.35) |

Details: [PRODUCTION_FORMULA_SYSTEM.md](PRODUCTION_FORMULA_SYSTEM.md).

---

## Produktionsraten (GC-820)

Kanoniche Formel: `calculate_resource_output()` in `game/production_formula.py`.

| Ressource | Wachstum (pro Stunde) |
|-----------|------------------------|
| Ferronit | `24 × production_speed × level^1.55` × Modifier |
| Crytite | `16 × production_speed × level^1.50` × Modifier |
| Brennzellen | `8 × production_speed × level^1.42` × Modifier |

Modifier: Slot, Temperatur (nur Brennzellen), `mining_tech` (+3 % Ferronit/Lvl), `drone_tech` (+2 %/Lvl), Energie-Ratio, Galactic Directives/Diplomacy (`directive_modifier`).

Details: [PRODUCTION_FORMULA_SYSTEM.md](PRODUCTION_FORMULA_SYSTEM.md).

**Brennzellen-Lager:** Kapazität nur über Gebäude **`fuel_storage`** (`EffectResolver.fuel_cells_storage_capacity()`). Ohne Depot: **Cap 0** — Brennzellen-Produktion wird nicht angesammelt. Voraussetzung: `fuel_cell_plant` ≥ 4.

---

## Storage

- Basis **150.000** pro Typ (`STORAGE_BASE_CAPACITY` in `economy_balance.py` / `EffectResolver.BASE_STORAGE`)
- Wachstum: **×1,75** pro Storage-Stufe (`STORAGE_LEVEL_GROWTH`)
- Multiplier: `storage_tech` (+25 %/Lvl), `terraformer` (+5 % Kapazität/Lvl), `storage_factor`
- Produktion kann Storage nicht überschreiten; bestehendes Overflow wird nicht getrimmt
- **Trader Hub + Schrottplatz** dürfen jederzeit über Cap gutschreiben (Overflow bleibt erhalten)

---

## Trader Hub (`/trader-hub`)

Seite mit zwei Panels (Partials):

| Panel | Modul | API |
|-------|-------|-----|
| Unified Resource Trader | `game/exchange.py` | `POST /api/exchange` |
| Schrottplatz | `game/scrapyard.py` | `POST /api/trader/scrapyard` |

Scope: **context planet** für Salden; Tageslimit **pro Spieler**.

Poll liefert `exchange`, `scrapyard` in `/api/game-state`.

---

## Unified Resource Trader

Ein zentrales Tauschsystem für `metal`, `crystal`, `fuel_cells`.

### Erlaubte Routen

| Route | Rate (Default) |
|-------|----------------|
| metal → crystal | `exchange_rate_metal_to_crystal` (0.85) |
| crystal → metal | `exchange_rate_crystal_to_metal` (0.85) |
| metal → fuel_cells | `1 / fuel_exchange_metal_per_unit` (20 Ferronit → 1 Brennzelle) |
| crystal → fuel_cells | `1 / fuel_exchange_crystal_per_unit` (14 Crytite → 1 Brennzelle) |
| fuel_cells → metal | `fuel_exchange_metal_per_unit` (20 Ferronit pro Brennzelle) |
| fuel_cells → crystal | `fuel_exchange_crystal_per_unit` (14 Crytite pro Brennzelle) |

Gleiche Ressource als Input/Output ist verboten.

### Settings

| Setting | Default |
|---------|---------|
| `exchange_enabled` | 1 |
| `exchange_rate_metal_to_crystal` | 0.85 |
| `exchange_rate_crystal_to_metal` | 0.85 |
| `exchange_daily_limit` | 50.000.000.000 | Admin-Hardcap (zusätzlich zu computed limit) |
| `exchange_daily_limit_pct` | 80 | Prozent der Empire-Tagesproduktion (Fe+Cr+BZ/Tag) |
| `exchange_daily_limit_min` | 500.000 | Untergrenze pro Commander |
| `exchange_daily_limit_max` | 50.000.000.000 | Obergrenze pro Commander |
| `exchange_min_amount` | 100 |
| `fuel_exchange_enabled` | 1 |
| `fuel_exchange_metal_per_unit` | 20 |
| `fuel_exchange_crystal_per_unit` | 14 |
| `fuel_exchange_min_units` | 10 |
| `fuel_production_per_hour` | **Deprecated** — Anzeige/Legacy-Admin; Produktion via `LEVEL_GROWTH` base 8.0 |

### Regeln

- Abbuchung/Gutschrift vom **context planet**
- Trader Hub erlaubt **Overflow** über Lagerkapazität (Tausch + Schrottplatz)
- Tageslimit zählt `give_amount` pro Spieler
- **GC-557D:** `daily_limit = clamp(empire_day_total × pct / 100, min, max)`, dann `min(..., exchange_daily_limit)` — Empire-Tagesproduktion = Summe aller Kolonien (EffectResolver, ×24h)
- Log: `exchange_log`

Legacy: `POST /api/trader/fuel-exchange` delegiert an metal → fuel_cells; `game/fuel_exchange.py` deprecated.

Migrationen: `024`, `025`, `031`, `036` (fuel_cells in exchange_log)

---

## Scrapyard

Recycelt Schiffe vom context planet → Ressourcen-Rückerstattung nach `fleet_defs` / Scrapyard-Logik. Rückerstattung darf Lagerkapazität überschreiten (Overflow).

---

## Container-Loot (Inventar) — GC-540

Ressourcen-Drops in Lootboxen sind **nicht mehr fix**, sondern skalieren mit dem Imperium:

| Regel | Detail |
|-------|--------|
| Ferronit / Crytite | **50 %** der Stundenproduktion der **höchsten** Mine (× Container-Stufe); Floor **12 000–30 000** |
| Brennzellen | **10 %** des Bestands (× Stufe); Floor **12 000–30 000** |
| Schiffe / Verteidigung | Abnehmender %-Anteil (log-Kurve); Floor **5 000–10 000** (`LOOT_UNIT_FLOOR_*`); **max. 100 000** pro Roll |
| Container-Stufe | Multiplikator pro `container_*`-Key (`CONTAINER_RESOURCE_MULTIPLIER`) |
| Keine Minen | Fallback Stufe **1** für Ferronit/Crytite |
| Andere Drops | Items, Booster — feste min/max |

Owner: `game/inventory_loot.py` (Pools + Skalierung), `game/inventory.py` (Roll beim Öffnen).  
Skalierung: `LOOT_BASE_PRODUCTION_HOURS = 0.5` (50 % der höchsten Mine/h).

---

## Universe-Defaults (`DEFAULT_GAME_SETTINGS`)

| Setting | Default | Hinweis |
|---------|---------|---------|
| `production_speed` | 1.0 | Multiplikator Produktion |
| `build_speed` | 1.1 | Divisor Bauzeiten |
| `research_speed` | 0.85 | Divisor Forschungszeiten |
| `queue_limit` | 5 | Bau-Queue (Fallback in Code: 3 wenn Setting fehlt) |
| `start_metal` | 150.000 | Neukonto Homeworld |
| `start_crystal` | 100.000 | Neukonto Homeworld |
| `start_fuel_cells` | 25.000 | Neukonto Homeworld |

Details: [GC-836_ALPHA_STARTER_RESOURCES.md](GC-836_ALPHA_STARTER_RESOURCES.md) · Benchmark ×1: [BALANCE_ANCHORS.md](BALANCE_ANCHORS.md)

---

## Auktionshaus (`/auction-house`) — GC-550

Meta-System für rotierende Lootbox-Auktionen (Wirtschaft → Auktionshaus, neben Trader Hub).

| API | Methode | Owner |
|-----|---------|-------|
| Seite | `GET /auction-house` | `templates/auction_house.html` |
| State | `GET /api/auction-house/state` | `game/auction_house.py` |
| Gebot | `POST /api/auction-house/bid` | `game/auction_house.py` |

### Regeln

- Bis zu **3** aktive Auktionen; Laufzeit **6–12 h**; nach Ablauf neue Rotation (`generate_auction_rotation`).
- Gebote in `metal`, `crystal` oder `fuel_cells` — Währung pro Listing fest.
- Mindest-Erhöhung **5 %**; Abbuchung vom **context planet**; Überbotene erhalten sofort Refund auf ihre Bieter-Kolonie.
- **Gebotslimit:** max. **25** Gebote pro Commander und Listing (Anti-Spam / Ressourcen-Glitch-Schutz).
- Gewinner erhält Box in `lootbox_inventory` + `player_inventory_items` (kanonisches Inventar).
- **Eventboxen ausgeschlossen:** kein `event_container`, kein `event_*`-Prefix, keine Box mit `is_event` / Kategorie `event`.

### Erlaubte Box-Keys (Rotation)

`generic_supply_container`, `resource_cache`, `research_capsule`, `wreckage_container`, `military_cache`, `alien_cache`, `premium_cache` — gewichtet nach Seltenheit; `birthday_gift_container` nur manuell/admin.

Poll liefert `auction_house` in `/api/game-state` (Panel).

Migration: `047_auction_house.sql`

---

## Vote Center (`/vote-center`) — GC-551 / GC-552

Multi-Provider-Voting: Konfiguration in `vote_providers`, Postback erzeugt **pending** Reward, Claim im Vote Center.

| API | Methode | Owner |
|-----|---------|-------|
| Seite | `GET /vote-center` | `templates/vote_center.html` |
| Provider Postback | `GET/POST /api/vote/postback/{provider_key}` | `game/vote_rewards.py` |
| TopG (Alias) | `GET /api/vote/topg/postback?p_resp=USER_ID&ip=IP` | `game/vote_rewards.py` |
| GTop100 | `POST /api/vote/gtop100/pingback` (JSON oder Form) | `game/vote_rewards.py` |
| Arena-Top100 | `POST /api/vote/arena-top100/postback` | `game/vote_rewards.py` |
| GameToor IVN | `POST /api/vote/gametoor/ivn` | `game/vote_rewards.py` |
| GameToor (Alias) | `GET/POST /api/vote/gametoor/postback` | `game/vote_rewards.py` |
| Claim | `POST /api/vote/rewards/claim` | `game/vote_rewards.py` |
| Claim all | `POST /api/vote/rewards/claim-all` | `game/vote_rewards.py` |

### Provider (Seed)

| Key | Vote-URL | Postback |
|-----|----------|----------|
| `topg` | `https://topg.org/ogame-private-servers/server-683112-{user_id}#vote` | 6h Cooldown; `p_resp`, `ip` |
| `gtop100` | `https://gtop100.com/Ogame/server-106142?vote=1&pingUsername={user_id}` | 12h Cooldown; JSON/Form Pingback; `GTOP100_PINGBACK_KEY`, `siteid=106142`, `success=0` |
| `gametoor` | `http://gametoor.com/in/3277/{user_id}` | IVN + Klick; `GAMETOOR_IVN_KEY`; 12h Cooldown |
| `arena_top100` | `https://www.arena-top100.com/index.php?a=in&u=Gurgenbaba&id={user_id}` | Postback + Klick; `ARENA_TOP100_SECRET`; 12h Cooldown |

Neue Topliste: Zeile in `vote_providers` + optional Postback-Route — keine separaten Seiten.

### Regeln

- Postback nur nach echtem Vote; **kein** Reward beim Link-Klick.
- Dev/Test IP-Lock: `GC_VOTE_SKIP_IP_CHECK=1` (oder Legacy `GC_TOPG_SKIP_IP_CHECK=1`).
- Production TopG IP-Check: `TOPG_STRICT_IP_CHECK=1` (Default **0** — Railway/Proxy loggt nur, blockiert nicht).
- **Cooldown** pro User/Provider (TopG: 6h, GTop100/GameToor/Arena: 12h) — hart beim Klick via `POST /api/vote/visit`; `provider_ref = {provider}:{user_id}:{bucket}`.
- GTop100 Pingback-Key: Env `GTOP100_PINGBACK_KEY` (muss mit GTop100-Dashboard übereinstimmen).
- Pro Vote **eine** gewichtete Zufallsbelohnung (`lootbox` / `resources` / `ships` / `defense`) — Auszahlung beim Claim auf context planet.
- Dev-Test: `POST /api/dev/topg/postback-test` (Admin/Debug).
- **Keine Eventboxen** als Vote-Reward.

Migrationen: `048_vote_rewards.sql`, `049_vote_providers.sql`, `051_vote_provider_cooldowns.sql`, `052_vote_gtop100.sql`, `053_vote_arena_top100.sql`, `054_vote_arena_postback.sql`, `055_vote_gametoor_ivn.sql`, `056_vote_hard_cooldowns.sql`

---

## Shipyard-Kosten

Schiffsbau zieht metal, crystal **und fuel_cells** ab (siehe [FLEET_SYSTEM.md](FLEET_SYSTEM.md)).

---

## Dateien

| Datei | Rolle |
|-------|-------|
| `game/economy_balance.py` | GC-821 Kosten, Storage, Exchange, Loot, Forschungs-Anker |
| `game/resources.py` | Tick, deltas |
| `game/production_formula.py` | Produktionsformeln (GC-820) |
| `game/effects/effect_resolver.py` | Energie, Storage, Zeit, Modifier-Bundle |
| `game/exchange.py` | Unified Resource Trader |
| `game/fuel_exchange.py` | Legacy-Wrapper (deprecated) |
| `game/scrapyard.py` | Recycling |
| `game/auction_house.py` | Lootbox-Auktionen |
| `game/vote_rewards.py` | TopG Vote Rewards |
| `game/logic.py` | Poll-Fassade |
| `templates/trader_hub.html` | Trader Hub UI |
| `templates/auction_house.html` | Auktionshaus UI |
| `templates/vote_center.html` | Vote Center UI |

---

## Tests

```bash
python -m pytest tests/test_effects.py tests/test_exchange.py tests/test_fuel_exchange.py tests/test_scrapyard.py tests/test_fuel_cells_resource_bar.py tests/test_trader_hub.py tests/test_auction_house.py tests/test_vote_rewards.py -v
```
