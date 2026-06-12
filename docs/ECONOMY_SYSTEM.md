# Economy System

Ressourcen, Produktion, Trader Hub und Unified Resource Trader (v1.5.4).

Formeln: autoritativ in `game/effects/effect_resolver.py` — siehe [EFFECTS.md](EFFECTS.md).

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
- **`energy_tech`:** reduziert nur Minen-Verbrauch (`mine_energy_factor`, min 40%)

---

## Produktionsraten (EffectResolver)

| Ressource | Basis |
|-----------|-------|
| Metal | `0.04 × metal_mine^1.4 × metal_prod_factor` |
| Crystal | `0.03 × crystal_mine^1.35 × crystal_prod_factor` |
| Fuel cells | `fuel_production_per_hour` × `fuel_cell_plant_level` × `1.35^(level-1)` |

Modifier: `mining_tech`, `drone_tech`, `storage_tech`, Settings (`production_speed`, `fuel_production_per_hour`).

**Brennzellenwerk:** Kein separates Lagergebäude — integriertes Lager skaliert mit der Werksstufe (~25 h Produktionspuffer × `storage_factor` / Terraformer).

---

## Storage

- Basis 100.000 pro Typ (metal/crystal)
- Wachstum via Storage-Gebäude + `STORAGE_GROW^1.8`
- Multiplier: `storage_tech`, `terraformer`, `storage_factor`
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
| `exchange_daily_limit_min` | 25.000.000 | Untergrenze pro Commander |
| `exchange_daily_limit_max` | 50.000.000.000 | Obergrenze pro Commander |
| `exchange_min_amount` | 100 |
| `fuel_exchange_enabled` | 1 |
| `fuel_exchange_metal_per_unit` | 20 |
| `fuel_exchange_crystal_per_unit` | 14 |
| `fuel_exchange_min_units` | 10 |
| `fuel_production_per_hour` | 4 (Stufe 1; Lager skaliert mit) |

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
| `game/resources.py` | Tick, deltas |
| `game/effects/effect_resolver.py` | Formeln |
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
