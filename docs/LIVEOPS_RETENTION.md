# EPIC-22 — LiveOps Retention (Login + Battle Pass)

> BDO-artiger 30-Tage-Login-Kalender + Season Battle Pass (Free/Premium).  
> Kein Payment in diesem Epic — Premium per Entitlement-Hook; Payment = EPIC-23.

## Status

| Phase | Inhalt | Tickets | Status |
|-------|--------|---------|--------|
| 0 | Master-Doc + Owner-Registrierung | GC-980 | ✅ |
| 1 | 30-Tage Login-Kalender | GC-981…984 | ✅ |
| 2 | Battle Pass Free/Premium (ohne Payment) | GC-990…995 | ✅ |
| 3 | Payment / Shop | EPIC-23 | ✅ [PAYMENT_SHOP.md](PAYMENT_SHOP.md) |

## Philosophy

- **F2P first:** Login-Kurve fühlt sich wie High-Command-Willkommen an.
- **Premium:** FOMO-dicht (Katalog **v5**) — Stacks + Stunden-TK; Season-Themes + **Auras** + **Title-Flairs** + Badges. Base-Themes (`cyan`…`rose`) bleiben für alle frei.
- **Free-Kosmetik (schwach):** Themes `ash`/`steel`, Auras `rim_ash`/`rim_steel`, Flair `etched`, Badge `bp_s1_attendee` — nie bestehende Farben gate’n.
- **Prestige-Layer:** `aura_key` + `title_flair` auf `player_cards` (CSS `data-aura` / `data-flair`); Unlock in `player_card_unlocked_cosmetics`.
- **Admins:** alle Themes / Auras / Title-Flairs frei wählbar (kein Unlock nötig); normale Spieler weiter gated.
- Katalog-Version: `REWARD_CATALOG_VERSION` in `battle_pass.py` — stale Levels werden bei `ensure_default_season` reseeds (v5-Marker: L50 `imperial` flair).
- **Erlaubt:** Timekeeper-Sekunden, Container (meta-only, GC-864), %/Time-Boosters, Cosmetics/QoL.
- **Verboten:** Schiffe, Defense, Rohstoff-Stacks als Paid/Login-Reward; parallele Grant-Engines; Frontend-Reward-Math.
- **Abgrenzung:** Imperial Directives, Vote Center, Free Basic Container bleiben eigene Daily-Loops.

## Owners (CORE_ARCHITECTURE §17)

| System | Owner | Notes |
|--------|--------|-------|
| Login Attendance | `game/login_rewards.py` | Progress, claim, 30-day catalog |
| Battle Pass Season | `game/battle_pass.py` | Season, XP, tracks, claims |
| Premium Entitlement | `game/premium_entitlements.py` | Flag; Shop schreibt denselben via `unlock_premium` |

**Grant path (canonical):** `grant_inventory_item` + `timekeeper.credit` — keine zweite Inventory-/Loot-Engine.

## Phase 1 — Login Rewards

### Rules

- Rolling **30-day** track per player.
- One claim per **UTC day bucket** (`day_bucket = floor(ts / 86400)`).
- Sequential: day N only after day N−1 claimed.
- Missed day (gap > 1 bucket since last claim) → **streak reset** to day 1.
- After claiming day 30 → new cycle starts at day 0 (next claim = day 1).
- No catch-up / makeup in Phase 1.

### Schema

- `login_reward_progress` — `player_id`, `cycle_id`, `cycle_started_at`, `current_day` (0–30), `last_claim_day_bucket`, `updated_at`
- `login_reward_claims` — audit + idempotency (`player_id`, `cycle_id`, `day_index` unique)

### API

- `POST /api/login-rewards/claim` → `{ ok, reason, state, login_rewards }`
- Game-state slice `login_rewards`: `{ available, current_day, next_day, next_unlock_in_sec, cycle_id }`
- Page: `/login-rewards` — calendar UI marks **claimed** / **claimable** / **locked** clearly; streak days are projected onto UTC day-buckets and overlay **Server Events** (`event` + short effect chips) when the bucket overlaps an event window (read-only; no event loot on claim).

### Catalog highlights

| Days | Focus |
|------|-------|
| 1–3 | Welcome: basic box, small TK credit / 5m boosters |
| 7 / 14 / 21 / 30 | Milestones: rare→epic→relic→mythic + larger TK/boosters |

Default: Inventory time items; direct `timekeeper.credit` only for day-1 welcome seconds.

## Phase 2 — Battle Pass

### Rules

- Season: configurable length (default 60d), levels 1–50, XP per level (default 100 → **5000 XP** to finish).
- **Pace target:** daily Ops + drip + weekly → finish around day **28–30**; casual/missed days still completable within the 60d season.
- XP sources:
  1. **Season Ops** (primary, visible tasks) — claim grants BP XP.
  2. **Passive activity drip** from `activity_xp` — soft-capped at **40 XP/day** (planet XP uncapped).
- Ops owner: `game/battle_pass.py` (not a second Imperial Directives engine).
- Tracks: `free` + `premium`; one claim per `(level, track)`.
- Premium unlock: `premium_entitlements` / `player_battle_pass.premium_unlocked`.
- Mid-season premium unlock → already-reached premium rewards become claimable.

### Season Ops

Workload is stronger than trivial 1× finishes, but below Story Ops Q1 (e.g. build 5–8). XP rewards and pace are unchanged.

| Op | Cadence | Target | XP |
|----|---------|--------|----|
| `op_build_1` | daily | 3 building finishes | 40 |
| `op_research_1` | daily | 2 account researches | 45 |
| `op_fleet_1` | daily | 3 expedition / spy / recycle | 50 |
| `op_week_active` | weekly | 18 build/research/expedition | 160 |

Daily Ops total **135 XP** + drip **40** + weekly ≈ **23 XP/day** ≈ **~198 XP/day** → Level 50 in ~**28 Tage** bei täglicher Anwesenheit.

Progress hooks from `activity_xp` after a successful grant. Claim via `POST /api/battle-pass/claim-op`.
Unclaimed op rows sync catalog `xp_reward`/`target` on `ensure_ops_for_period` (pace retunes without waiting for a new period).

### Schema

- `battle_pass_seasons`, `battle_pass_levels`
- `player_battle_pass`, `battle_pass_claims`
- `battle_pass_ops_progress` — daily/weekly op counters + passive drip tracker
- `premium_entitlements` (player_id, kind, season_id nullable, granted_at, source)

### API

- `POST /api/battle-pass/claim` → `{ ok, reason, state, battle_pass }`
- `POST /api/battle-pass/claim-op` → `{ ok, reason, state, battle_pass }`
- Admin: grant premium entitlement
- Page: `/premium` (Season Ops panel + **horizontal trackboard**)

### UI — Trackboard (GC-BPUI)

Belohnungs-Tracks on `/premium` use a Fortnite-style horizontal board in Genesis industrial chrome:

- Columns = levels (paged, 6 per page); rows = **Free** (top) + **Premium** (bottom)
- Card selection updates a detail preview (server-rendered reward HTML cloned client-side)
- Claim still via `POST /api/battle-pass/claim` (`data-bp-claim`); no client XP/claim math
- Markers: `data-bp-trackboard`, `data-bp-card`, `data-bp-preview`

### UI — Season Ops cards

Daily Ops render as a **3-card grid** (icons, XP chip, claim CTA); Weekly as a wide card; drip as a compact progress strip. Markers: `battle-pass-op-card`, `data-bp-ops-drip`.

Ops panel carries `data-bp-daily-period`; game-state polls soft-reload `/premium` when the UTC `daily_period_key` changes. Login Rewards live-patch claim availability + cooldown from the same poll. `claim_op` always uses the server period (client `period_key` ignored). `claimable_count` includes completed unclaimed ops (nav badge). When an op newly becomes claimable, the client shows a success toast (`bp_op_ready_notify`) from `syncLiveOpsFromGameState` — same path as diet polls / queue finishes — so players notice XP-ready Ops even off `/premium` (track loot already surfaces via the premium nav badge). `/api/game-state` serializes battle pass with `include_tracks=True` so track claimable/claimed cards update on diet polls; `patchBattlePassDom` re-syncs the selected preview clone (Claim CTA) so players do not need to re-click the same card.

## Phase 3 — EPIC-23 Payment / Shop

Canonical doc: [PAYMENT_SHOP.md](PAYMENT_SHOP.md).

Stripe + PayPal Checkout set the **same** entitlement flag via `battle_pass.unlock_premium`. No second unlock system. No direct resource/ship shop. Convenience packs (Timekeeper / boosters / meta containers) fulfill through `timekeeper.credit` + `grant_inventory_item`.

## Ticket map

| Ticket | Focus |
|--------|-------|
| GC-980 | This doc + EPICS/WORKFLOW/CORE/ROADMAP |
| GC-981 | Migration + login progress/claim core |
| GC-982 | 30-day catalog + grants + tests |
| GC-983 | Routes + game-state slice |
| GC-984 | UI + locales |
| GC-990 | Season schema + battle_pass XP/level |
| GC-991 | activity_xp hook |
| GC-992 | Track catalog + claim grants |
| GC-993 | premium_entitlements admin grant |
| GC-994 | `/premium` UI |
| GC-995 | GAME_RULES sync + contract tests |

---

## Player Article

```yaml
---
codex_id: liveops_retention
band: II
difficulty: beginner
estimated_read: 4 min
surfaces:
  - quick_help
  - codex
  - faq
  - commander_tips
  - discord
routes:
  - login_rewards_view
  - premium_view
related_codex:
  - shop_identity
  - inventory
  - imperial_directives
terminology: GENESIS_TERMINOLOGY
unlock:
  type: route_visit
  route: login_rewards_view
teaser_key: codex_unlock_liveops_retention_teaser
---
```

## Quick Help

**Login-Kalender** (`/login-rewards`) und **Battle Pass** (`/premium`) sind die Free-to-Play LiveOps-Schiene: tägliche Anwesenheit und Season-Ops für Meta-Belohnungen.

## Summary

Der Login-Kalender ist eine rollierende Anwesenheits-Strecke: ein Claim pro UTC-Tag, streng sequentiell; Lücken setzen den Streak zurück. Meilenstein-Tage liefern stärkere Container und Timekeeper-nahe Rewards. Der **Battle Pass** hat Free- und Premium-Track, Season-Ops (täglich/wöchentlich) plus sanften Aktivitäts-Drip. Premium schaltet denselben Entitlement-Pfad frei wie der Shop — keine zweite Währung. Belohnungen bleiben Meta (Booster, Container, Cosmetics), keine Schiffe oder Ferronit-Stacks.

## Why

Retention ohne Pay-to-Win: High Command begrüßt dich täglich, die Season belohnt aktives Spielen. Paid ist Convenience und FOMO, Free bleibt wertvoll.

## How it works

- **`/login-rewards`:** Kalender mit claimed / claimable / locked; Server-Events können als Overlay erscheinen (read-only).
- Claim nur für den nächsten fälligen Tag — kein Aufholen verpasster Tage.
- **`/premium`:** horizontales Trackboard Free/Premium, Season-Ops-Karten, Claim für Level und Ops.
- XP kommt aus Ops und begrenztem Aktivitäts-Drip — Anzeige und Caps setzt der Server.
- Premium mitten in der Season: bereits erreichte Premium-Stufen werden claimbar.
- Nav-Badges signalisieren claimbare Ops/Rewards.

## Related Systems

- shop_identity
- inventory
- imperial_directives
- vote_center

## Commander Tips

- Login-Streak schützen — eine verpasste UTC-Nacht setzt dich zurück.
- Daily Ops vor dem Offline-Gang claimen; Weekly parallel mitlaufen lassen.
- Premium nur kaufen, wenn du die Season noch aktiv spielst — Mid-Season holt erreichte Stufen nach.

## FAQ

**Ist Battle Pass Pay-to-Win?**
Nein. Tracks geben Meta/QoL/Cosmetics — keine Schiffe, Defense oder Rohstoff-Stacks als Paid-Power.

**Unterschied zu Imperial Directives?**
Directives = rotierende Kommando-Ops mit eigenem Loot. Login/BP = Anwesenheit + Season-Track. Beide dürfen parallel laufen.

**Wo schalte ich Premium frei?**
Shop-SKU Season Pass oder Admin/LiveOps — derselbe Entitlement-Flag.

## Discord Summary

**LiveOps — Login-Kalender & Battle Pass**

`/login-rewards` + `/premium`: tägliche Streak, Free/Premium-Tracks, Season Ops. Meta-Rewards only. Premium = Shop-Entitlement.
