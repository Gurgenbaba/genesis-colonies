# Inactive Autoplay — Living Dormant Empires (EPIC-26)

> Owner: `game/inactive_autoplay.py` · Shared economy: `game/auto_empire.py` · Tick: fleet worker post-maint

Dormante Menschen-Konten werden gestaffelt auf einen **sticky Roster** geholt und bauen/forschen/Defense **dauerhaft** (Round-Robin pro Fleet-Cron). Ranking/Galaxy wirken lebendig.

## Regeln

| Regel | Verhalten |
|-------|-----------|
| Presence | Wake + Roster-Tick setzen `players.last_seen` → kein Inactive-Badge |
| Economy | `plan_passive_planet_tick` mit Soft-Caps (15/20 min) + Chain (bis 3 Jobs/Tick) |
| Sticky Roster | Einmal geweckt → bleibt auf Roster und baut weiter (kein 6h-Stop) |
| Ships | **nein** |
| Fleets / Expeditionen | **nie** |
| Stagger | Wake-Batches (default 3 / 10 min); Economy-Slice default 8/Cron |
| Revisit | ~36h — zieht Stale-Accounts wieder auf den Roster |
| Exclude | Vacation, Pirate-Bots, Combat-Balance-Bots |
| Soft-Off | `runtime_state.inactive_autoplay_enabled=0` oder `GC_INACTIVE_AUTOPLAY_ENABLED=0` |

## Tickets

| Ticket | Fokus | Status |
|--------|--------|--------|
| GC-2600 | Shared `game/auto_empire.py` + Pirate thin wrapper | done |
| GC-2601 | Sticky roster wake + Presence + autonomous economy | done |
| GC-2602 | Pirate AI Expeditions (`dispatch_expedition_from_home`) | done |
| GC-2603 | Autonomy pass: chain enqueue, economy-all pirates, sticky roster | done |

## Env

| Env | Default | Bedeutung |
|-----|---------|-----------|
| `GC_INACTIVE_AUTOPLAY_ENABLED` | on | `0` = hard off |
| `GC_INACTIVE_AUTOPLAY_BATCH` | 3 | Neue Roster-Mitglieder pro Wake-Wave |
| `GC_INACTIVE_AUTOPLAY_INTERVAL_SEC` | 600 | Abstand zwischen Wake-Waves |
| `GC_INACTIVE_AUTOPLAY_REVISIT_SEC` | 129600 | Stale-Cutoff (~36h) |
| `GC_INACTIVE_AUTOPLAY_MAX_SESSIONS` | 40 | Max. Roster-Größe |
| `GC_INACTIVE_AUTOPLAY_TICK_PER_CRON` | 8 | Economy-Ticks pro Fleet-Cron (RR) |

## Pirate AI (parallel)

- Jeder Soft-On-Tick: **Economy für alle** Faction-Bots (`chain_limit=3`, 90/120s Caps).
- Strategische Missionen (Spy/Raid/Expo/…) bleiben Round-Robin (`GC_PIRATE_PLAY_BOTS_PER_TICK`).

## Fair Play

- Inaktive Autoplay-Konten **fliegen keine Expeditionen** und starten keine Angriffe.
- Pirate-AI (EPIC-21) darf Expeditionen fliegen — siehe [PIRATE_ECOSYSTEM.md](PIRATE_ECOSYSTEM.md).
- Ranking-Inactive-Schwelle bleibt 3 Tage; Autoplay hält Roster-Konten darunter.
