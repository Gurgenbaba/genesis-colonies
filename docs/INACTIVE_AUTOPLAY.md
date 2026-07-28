# Inactive Autoplay — Living Dormant Empires (EPIC-26)

> Owner: `game/inactive_autoplay.py` · Shared economy: `game/auto_empire.py` · Tick: fleet worker post-maint

Dormante Menschen-Konten werden gestaffelt auf einen **sticky Roster** geholt und bauen/forschen/Defense **dauerhaft** (Round-Robin pro Fleet-Cron). Ranking/Galaxy wirken lebendig.

## Regeln

| Regel | Verhalten |
|-------|-----------|
| Presence | Zwei getrennte Uhren auf `players.last_seen`: (1) frisch geweckte Accounts werden **sofort** touched, damit sie augenblicklich den mehrtägigen Ranking-Inactive-Threshold verlassen; (2) ein kleiner, **dynamisch nach % der echten Spielerbasis gedeckelter**, rotierender Ausschnitt des Rosters gilt je Tick als "online" (`online_visible_cap`, GC-2617) — nicht der gesamte Roster. So bleibt die gleichzeitige Online-Zahl plausibel, egal wie groß der Roster-Cap ist |
| Economy | `plan_passive_planet_tick` mit Soft-Caps (15/20 min) + Chain (bis 3 Jobs/Tick) |
| Sticky Roster | Einmal geweckt → bleibt auf Roster und baut weiter (kein 6h-Stop); zählt kumulativ `builds_done`/`research_done`/`defense_done` + `last_action` (GC-2615) |
| Roster-Rotation | Voller Roster: `batch`-älteste (`last_ticked_at`) werden **evicted** bevor neue Dormants nachrücken (LRU) — Coverage rotiert durch den gesamten Dormant-Pool. Das ist das "Dreischicht"/rotierende Online-Verhalten: kein festes Zeitfenster, sondern ein kontinuierlich rotierender Ausschnitt des Dormant-Pools bleibt online |
| Sichtbare Aktivität | Beim Eviction bekommt der Account **eine** Inbox-Nachricht ("Automatisierter Betriebsbericht") mit den kumulierten Zahlen (GC-2615, `_send_autoplay_report` → `messages.create_message`) — kein stiller Tick |
| Timekeeper-Boost | Defense-/Shipyard-Queues (kein `duration_cap`, da echte Formel) werden nach erfolgreichem Enqueue automatisch per **echtem** Timekeeper-Ledger beschleunigt: Auto-Credit auf 10h wenn Balance leer, danach Auto-Apply `mode="max"` (GC-2616, `_auto_boost_timekeeper` in `game/auto_empire.py`) — gilt für Inactive **und** Pirate-AI gleichermaßen, da beide `plan_passive_planet_tick` teilen |
| Ships | **nein** (Inactive) / ja (Pirate-AI, siehe unten) |
| Fleets / Expeditionen | **nie** (Inactive) |
| Stagger | Wake-Batches (default 3 / 10 min); Economy-Slice default 8/Cron |
| Revisit | ~36h — zieht Stale-Accounts wieder auf den Roster |
| Exclude | Vacation, Pirate-Bots, Combat-Balance-Bots |
| Soft-Off | `runtime_state.inactive_autoplay_enabled=0` oder `GC_INACTIVE_AUTOPLAY_ENABLED=0` |
| Cron | Läuft über Fleet post-maint inkl. **`embedded_cron`** / `game_worker` (Railway) — nicht nur `http_cron` |
| Scores | Finish schreibt `player_scores` (`update_scores=True`); Ränge via `ranking_worker` (~10 min) |
| Resource Floor | Soft-Floor am Home (75k/50k/15k) wenn Lager leer — kein Pirate-Seed |
| Admin | Tab "Inactive Autoplay" (mirror Pirate-Tab): KPIs, Roster-Tabelle, Soft-On/Off — `GET/POST /api/admin/inactive-autoplay[/toggle]` |
| Budget-Fairness | Post-Maint Stage-Reihenfolge: `inactive_autoplay` **vor** `pirates` (teuerste Stage darf Inactive nicht verhungern lassen); Budget-Skip zählt `runtime_state.post_maint_skip_streak_<stage>` hoch, Erfolg setzt zurück auf 0 — sichtbar im Admin-Panel als KPI |

## Tickets

| Ticket | Fokus | Status |
|--------|--------|--------|
| GC-2600 | Shared `game/auto_empire.py` + Pirate thin wrapper | done |
| GC-2601 | Sticky roster wake + Presence + autonomous economy | done |
| GC-2602 | Pirate AI Expeditions (`dispatch_expedition_from_home`) | done |
| GC-2603 | Autonomy pass: chain enqueue, economy-all pirates, sticky roster | done |
| GC-2604 | `embedded_cron` / `game_worker` in post-fleet allowlist | done |
| GC-2605 | Final chain finish + level/score contract | done |
| GC-2606 | Offline queue tick `update_scores=True` | done |
| GC-2607 | Inactive soft resource floor | done |
| GC-2608 | Admin panel + kill-switch (mirror pirates admin) | done |
| GC-2609 | Roster LRU rotation (voller Pool statt fixer 40) | done |
| GC-2610 | Post-Maint Stage-Order (inactive vor pirates) + Skip-Streak-Zähler | done |
| GC-2611 | Pirate AI Default-On in Production + Economy-KPIs im Admin-Payload | done |
| GC-2612 | Spieler-sichtbarer "Living Universe Pulse"-Chip in der Galaxie-Ansicht | done |
| GC-2613 | "Force Tick jetzt" — Admin kann Roster-Wake sofort auslösen (kein Warten auf Embedded-Cron) | done |
| GC-2614 | Admin-Roster: `players`/`users`-JOIN-Fix (Name/Zuletzt gesehen) + Bulk-Presence für ganzen Roster (durchgehend online, rotierender Pool) | done |
| GC-2615 | Sichtbare Aktivität: kumulative Zähler pro Roster-Eintrag + 1 Inbox-Betriebsbericht bei Eviction + "Letzte Aktion"-Spalte im Admin-Panel | done |
| GC-2616 | Timekeeper-Auto-Boost für Defense/Shipyard (Inactive + Pirate-AI, gemeinsamer Owner `auto_empire.py`) | done |
| GC-2617 | Realistischer Online-Cap: sichtbare Online-Zahl skaliert mit % der echten Spielerbasis statt mit Roster-Cap (60) | done |

## Env

| Env | Default | Bedeutung |
|-----|---------|-----------|
| `GC_INACTIVE_AUTOPLAY_ENABLED` | on | `0` = hard off |
| `GC_INACTIVE_AUTOPLAY_BATCH` | 3 | Neue Roster-Mitglieder pro Wake-Wave |
| `GC_INACTIVE_AUTOPLAY_INTERVAL_SEC` | 600 | Abstand zwischen Wake-Waves |
| `GC_INACTIVE_AUTOPLAY_REVISIT_SEC` | 129600 | Stale-Cutoff (~36h) |
| `GC_INACTIVE_AUTOPLAY_MAX_SESSIONS` | 60 | Max. Roster-Größe (Rotation statt Größe ist der eigentliche Skalierungsfix) |
| `GC_INACTIVE_AUTOPLAY_TICK_PER_CRON` | 8 | Economy-Ticks pro Fleet-Cron (RR) |
| `GC_INACTIVE_AUTOPLAY_ONLINE_PERCENT` | 15 | % der **echten** registrierten Spieler, die gleichzeitig als "online" (Autoplay) sichtbar sein dürfen (geclamped 1–50%, Ergebnis geclamped 2–40 Accounts) |

## Pirate AI (parallel)

- Jeder Soft-On-Tick: **Economy für alle** Faction-Bots (`chain_limit=3`, 90/120s Caps).
- Strategische Missionen (Spy/Raid/Expo/…) bleiben Round-Robin (`GC_PIRATE_PLAY_BOTS_PER_TICK`).

## Force Tick jetzt (GC-2613)

- Außerhalb von Production läuft kein `embedded_cron` (Default, siehe `game.config.is_embedded_cron_enabled`) — ohne HTTP-Cron passiert lokal nichts, bis jemand `run_inactive_autoplay_tick`/`maybe_tick_pirate_bases` aufruft.
- Der Inactive-Autoplay-Tab bekommt einen Button "Force Tick jetzt" (`POST /api/admin/inactive-autoplay/force-tick` → `admin_force_tick_inactive_autoplay`), der **denselben** Owner (`run_inactive_autoplay_tick(..., force=True, source="admin")`) aufruft wie der Fleet-Worker-Cron — kein zweiter Wake-Pfad.
- Der Pirates-Tab bekommt denselben Button (`POST /api/admin/pirates/force-tick` → `admin_force_tick`), der `maybe_tick_pirate_bases` direkt aufruft (Economy für alle Bots + eine RR-Strategie-Runde), ebenfalls derselbe Owner wie der Fleet-Worker-Cron.
- Gibt Admins sofortiges Feedback ("2-3 Accounts wachen jetzt auf") ohne auf das nächste Zyklus-Fenster zu warten — nützlich für lokale Tests und LiveOps-Verifikation nach Deploy.

## Live Universe: Dauerpräsenz, sichtbare Aktivität, Timekeeper-Boost (GC-2614…2616)

- **GC-2614 — Namen-Fix + Dauerpräsenz (später verfeinert durch GC-2617):** `build_admin_inactive_autoplay_payload` jointe fälschlich `username` direkt von `players` (Spalte existiert dort nicht, liegt auf `users`) — die Exception wurde verschluckt und jede Roster-Zeile zeigte `–`. Fix: `JOIN users u ON u.id = p.id` (gleiches Pattern wie `game/vote_reengagement.py`, `game/pirates/accounts.py`). GC-2614 hat außerdem `last_seen` für den **kompletten** Roster bei jedem Cron-Tick berührt ("immer online, rotierender Roster") — das erzeugte auf kleinen Servern eine unrealistisch hohe gleichzeitige Online-Zahl (bis zu `GC_INACTIVE_AUTOPLAY_MAX_SESSIONS`, Default 60), unabhängig von der echten Spielerzahl. **GC-2617 ersetzt diesen Teil** (siehe unten); der JOIN-Fix bleibt unverändert gültig.
- **GC-2615 — Sichtbare Aktivität statt stiller Ticks:** Jeder Roster-Eintrag zählt kumulativ `builds_done`/`research_done`/`defense_done` sowie `last_action` (menschenlesbarer String des letzten Build/Research/Defense/Ship-Jobs). Beim Evict (LRU) verschickt `_send_autoplay_report` **eine** Inbox-Nachricht ("Automatisierter Betriebsbericht") über den bestehenden Inbox-Owner (`game/messages.py::create_message`, gleiches Pattern wie Kampf-/Expeditionsberichte) — kein neues Feed-/Chronicle-System, kein Spam pro Tick. Admin-Panel zeigt eine "Letzte Aktion"-Spalte in der Roster-Tabelle.
- **GC-2616 — Timekeeper-Auto-Boost:** Build/Research sind über `duration_cap` + `chain_limit` bereits same-tick fertig; Defense/Shipyard laufen aber über die echte Formel ohne Cap. `_auto_boost_timekeeper` (`game/auto_empire.py`) füllt bei leerem Timekeeper-Konto automatisch 10h nach (`timekeeper.credit(..., source="autoplay_replenish")`) und wendet sie sofort maximal an (`timekeeper.apply_timekeeper(..., mode="max")`) — derselbe Ledger, den ein manuell spielender Account auch sehen würde (`timekeeper_balances`/`timekeeper_transactions`), keine parallele Speed-Mechanik. Da sowohl `game/inactive_autoplay.py` als auch `game/pirates/economy.py` denselben `plan_passive_planet_tick` aufrufen, profitieren Inactive- **und** Pirate-Accounts automatisch von einer einzigen Änderung.

## GC-2617 — Realistischer Online-Cap (Presence entkoppelt von Roster-Größe)

**Problem:** GC-2614s "touch whole roster every tick" ließ die sichtbare Online-Zahl mit dem Roster-Cap (Default 60, bis 80) mitwachsen — auf einem kleinen Server mit z. B. 20 echten Spielern sah das nach 40-60 gleichzeitig "online" befindlichen Autoplay-Accounts aus und fiel sofort als unrealistisch auf.

**Fix (`game/inactive_autoplay.py`):**

1. `online_percent()` (`GC_INACTIVE_AUTOPLAY_ONLINE_PERCENT`, Default 15%, geclamped 1–50%) und `online_visible_cap(conn)` = `round(get_registered_player_count() * online_percent / 100)`, geclamped auf `MIN_ONLINE_VISIBLE=2` … `MAX_ONLINE_VISIBLE=40`. Basis ist die **echte** registrierte Spielerzahl (`game.models.get_registered_player_count`, bestehender Owner) — nicht der Roster-Cap.
2. `run_inactive_autoplay_tick` touched `last_seen` pro Tick für genau zwei Gruppen statt für den ganzen Roster:
   - **Frisch geweckte Accounts** (`woke_ids`) — immer, sofort. Notwendig, damit ein gerade geweckter Account augenblicklich den mehrtägigen Ranking-Inactive-Threshold (`RANKING_INACTIVE_AFTER_SEC`) verlässt, statt auf seine Rotations-Runde zu warten.
   - Ein **zusätzlicher, unabhängig rotierender Ausschnitt** des gesamten Rosters (eigener Cursor `PRESENCE_CURSOR_KEY`, Größe = `online_visible_cap(conn)` minus bereits geweckte), damit über die Zeit jedes stehende Roster-Mitglied gelegentlich "online" sichtbar wird — ohne dass alle gleichzeitig sichtbar sind.
3. Der RR-Economy-Tick (`tick_per_cron`, baut/forscht weiter) läuft **unverändert unabhängig** davon — der gesamte Roster baut im Hintergrund weiter, auch wenn nur ein kleiner Teil davon gerade als "online" markiert ist. Das ist die geforderte Entkopplung von Bau-Aktivität und sichtbarer Online-Präsenz.
4. Admin-Panel zeigt neu `presence_visible_now` (live gemessen: wie viele Roster-Mitglieder liegen gerade im 5-Min-Online-Fenster) und `online_visible_cap`/`online_percent`/`real_player_count` zur Transparenz (`build_admin_inactive_autoplay_payload`, `static/admin.js`).

**Ergebnis:** Die sichtbare Online-Zahl aus Autoplay bleibt immer proportional zur echten Spielerbasis (z. B. 15% von 20 echten Spielern ≈ 3, nicht 60), unabhängig davon, wie groß der Roster-Cap für die reine Bau-Kapazität eingestellt ist.

## Living Universe Pulse (GC-2612)

- `game/galaxy.py` (`_attach_player_status_flags`) setzt `slot["recently_active"]` wenn `last_seen` < 2h alt — **unabhängig** von `is_ai`/`inactive`, damit auch echte Spieler, die kurz vorbei waren, den Chip zeigen.
- Rein visuell: kein Einfluss auf Ranking/PvP; Owner bleibt `game/galaxy.py` + `templates/partials/galaxy_slot_status_badges.html` (kein neues Feed-/Chronicle-System).
- Chip ausgeblendet während `vacation_active`; Legende in `templates/partials/galaxy_ring_view.html`.

## Fair Play

- Inaktive Autoplay-Konten **fliegen keine Expeditionen** und starten keine Angriffe.
- Pirate-AI (EPIC-21) darf Expeditionen fliegen — siehe [PIRATE_ECOSYSTEM.md](PIRATE_ECOSYSTEM.md).
- Ranking-Inactive-Schwelle bleibt 3 Tage; Autoplay hält Roster-Konten darunter.
