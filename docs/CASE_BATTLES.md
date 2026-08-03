# Case Battles — Relikt-Arena

**Owner:** `game/case_battles.py`  
**Status:** MVP (GC-CB)  
**UI:** Inventar → Tab „Relikt-Arena“ (`/inventory#case-battles`)

Commander setzen versiegelte Container ein. Alle Bergungssiegel werden gleichzeitig gebrochen. Der wertvollste Fund beansprucht den gesamten Bergungspool.

## Prinzipien

- Keine zweite Loot-Engine — Rolls über `inventory.roll_single_loot_reward` / `inventory_loot.LOOT_POOLS`
- Auszahlung nur über `grant_inventory_item`
- Einsatz: Container werden beim Create/Join **atomar konsumiert** (Escrow); Cancel refundet
- **Battle Value (BV):** fester Container-Einsatzwert (Lobby)
- **Reward Value (RV):** serverseitige Bewertungszahl je Drop (kein auszahlbares Geld)
- Keine Frontend-Mathematik für BV/RV/Gewinner
- GC-864 bleibt: Meta-only Loot (Items/Booster)

## MVP-Scope (erweitert)

| In | Out |
|----|-----|
| 2–4 Spieler | 3v3 / 6+ |
| Standard, Crazy, Terminal, Share, Team 2v2 | Jackpot, Bots |
| 1–10 Kisten | Sponsoring |
| Public + Private | Zuschauer-Chat |
| Simultanes Arena-Theater (alle Lanes parallel) | Einzel-Loot-Modal |
| Seed-Hash + Reveal + Verify | Cashout |

**Team 2v2:** Slots 0–1 = Team A, 2–3 = Team B. Gewinner behalten eigenen Loot + teilen Gegner-Loot.

**Terminal:** Jede Runde separat — Rundengewinner erhält die Drops dieser Runde.

**Share:** Gesamter Pool proportional zum Reward Value (Largest Remainder).

## Statusmaschine

```text
open → running → finished
open → cancelled
```

- `open`: Creator hat Escrow; Join möglich
- `running`: Rolls vorab serverseitig geschrieben; Seed in DB, API zeigt nur Hash
- `finished`: Settlement idempotent; Seed offengelegt; Winner erhält gesamten Drop-Pool
- `cancelled`: nur Creator solange `open`; Escrow zurück

Auto-Settle: laufende Battles ≥ 120 s nach `started_at` werden bei State-Read settled.

## Fairness

```text
HMAC-SHA256(server_seed, "{battle_id}|{round}|{slot}|{nonce}") → RNG
```

Vor dem Battle: `sha256(server_seed)`. Nach Finish: Seed + Verify-API.

Pool-Snapshot beim Start aus Default-`LOOT_POOLS` (Admin-Overrides für laufende Battles irrelevant).

## APIs

| Route | Methode |
|-------|---------|
| `/api/case-battles/state` | GET |
| `/api/case-battles/create` | POST |
| `/api/case-battles/join` | POST |
| `/api/case-battles/cancel` | POST |
| `/api/case-battles/settle` | POST |
| `/api/case-battles/<id>` | GET |
| `/api/case-battles/verify` | POST |

Responses: `{ ok, reason, state?, inventory?, case_battles?, battle? }` + `applyActionState`.

## Nav-Attention

Offene/laufende Battles, in denen der Spieler Teilnehmer ist, erzeugen:

- Badge am Sidebar-Link **Inventar** (`data-nav-badge="inventory"`)
- Badge am Inventar-Tab **Relikt-Arena** (nicht Container / Items)

Zähler: `count_case_battles_nav_attention` → `nav_badges.inventory` in `/api/game-state` und `case_battles.attention_count`.

## Schema

Migration `130_case_battles.sql`: `case_battles`, `case_battle_players`, `case_battle_rolls`, `case_battle_settlements`.

## Verwandte Docs

- [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) — Container-Loot GC-864
- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) §17 Owner
