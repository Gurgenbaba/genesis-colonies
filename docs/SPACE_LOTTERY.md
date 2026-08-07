# EPIC-28 — Space Lottery (Chrono Chamber)

**Owner:** `game/space_lottery.py`  
**Fairness:** `game/provably_fair.py` (shared with Case Battles)  
**Stake:** Timekeeper only (`timekeeper.debit` / `credit`)  
**UI:** `/space-lottery` — Chrono Chamber Theater  
**Status:** MVP GC-2800…2807 + Void Mines UI GC-2808

## Games

| Mode | Live | Notes |
|------|------|--------|
| Wochen-Tombola | **yes** | Progressive pool (100% of ticket TK); UTC ISO week; draw **Sunday 20:00 UTC**; 1 winner |
| Void Mines | gated off | Code retained; `LIVE_MODES` / `modes.mines` |
| Orbit Crash | gated off | Code retained; `LIVE_MODES` / `modes.crash` |

Player-facing Chrono Chamber ships **Tombola only** until Mines/Crash are product- and counsel-cleared. Unlock by expanding `LIVE_MODES` in `game/space_lottery.py` (tests monkeypatch the full set).

## Tombola UI (GC-2807)

Mockup-layout under `.sl-tombola-layout`: countdown, winners rail, Hauptpreis (Chronosphäre + TK pool), ticket stepper, daily wager bar. Stake remains Timekeeper only — no item prize catalog.

## Void Mines UI (GC-2808)

Mockup-layout under `.sl-mines-layout`:

- Left: `mines_history` (cashout/bust) + `mines_today` (won / best / last high)
- Center: titled 5×5 board on pedestal, progress dots, HUD cards (current / next / potential)
- Right: TK stake presets (human labels), mine −/+ + range, live hits/cashout, Start/Cashout, fairness

State extras: `mines_history`, `mines_today`, round `hits` / `max_safe` / `potential_multiplier`, `mines_defaults.potential_by_mines`. Art: `sl-tile-safe-a/b/c`, `sl-tile-hidden`, `sl-tile-mine`.

## Orbit Crash UI (GC-2810)

Mockup-layout under `.sl-crash-layout` (same family as Mines/Tombola):

- Solo rounds on `space_lottery_rounds` (no parallel tables)
- Left: `crash_history` (color bands by mult) + `crash_today`
- Center: viewport-fit flight graph (ghost path + live tip); ship always at curve tip
- Side rails: history + controls (no vertical stack / doomscroll)
- Page chrome collapsed in crash mode (`data-sl-mode-active="crash"`)
- `CRASH_MAX_MULT = 1000`; client + server share `bust_after_ms` / progress curve
- After cashout: stage continues to the real `crash_point` and shows “would have crashed at ×N”; history lists `cashout · ×A → crash ×B`

Art: `sl-crash-reactor`, `sl-crash-ship`. SFX: `static/sounds/lottery/crash_*.wav`.
## Principles

- No parallel TK ledger — all stakes/payouts via `timekeeper`
- No frontend math as truth — server returns multipliers / `payout_sec`
- Provably fair: seed hash before settle, seed + verify after
- Caps: min/max bet; **per-game daily wager volume** (GC-2809) — Tombola 5h, Mines 10h, Crash 10h (UTC day; independent)
- Art: `static/img/lottery/*` — industrial cyan/amber, PE/Shop style

## Schema

Migration `146_space_lottery.sql` + `147_space_lottery_daily_by_game.sql`:

- `space_lottery_weeks`, `space_lottery_tickets`
- `space_lottery_rounds`, `space_lottery_wagers`
- `space_lottery_daily_game` (player + day_bucket + game) — replaces shared `space_lottery_daily` for caps

## APIs

| Route | Method |
|-------|--------|
| `/api/space-lottery/state` | GET |
| `/api/space-lottery/tombola/buy` | POST |
| `/api/space-lottery/mines/start` | POST |
| `/api/space-lottery/mines/reveal` | POST |
| `/api/space-lottery/mines/cashout` | POST |
| `/api/space-lottery/crash/bet` | POST |
| `/api/space-lottery/crash/cashout` | POST |
| `/api/space-lottery/crash/bust` | POST |
| `/api/space-lottery/verify` | POST |
| `/api/internal/cron/space-lottery-draw` | POST |

Responses: `{ ok, reason, state, timekeeper, space_lottery }` + `applyActionState`.

## UI / Art

- Theater layout under `.space-lottery-page.sl-chamber`
- Pedestal + mode stage (Tombola / Mines / Crash)
- Assets in `static/img/lottery/` (PNG + WebP), `mix-blend-mode: screen` on holo pieces
- Motions: bet lock, mines reveal, crash climb, tombola draw

## Related

- [TIMEKEEPER_SYSTEM.md](TIMEKEEPER_SYSTEM.md)
- [CASE_BATTLES.md](CASE_BATTLES.md) — fairness pattern only
- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) §17
