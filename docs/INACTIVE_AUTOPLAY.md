# Inactive Autoplay — Living Dormant Empires (EPIC-26)

> Owner: `game/inactive_autoplay.py` · Shared economy: `game/auto_empire.py` · Tick: fleet worker post-maint

Dormante Menschen-Konten werden gestaffelt auf einen **sticky Roster** geholt und bauen/forschen/Defense **dauerhaft** (Round-Robin pro Fleet-Cron). Ranking/Galaxy wirken lebendig.

## Regeln

| Regel | Verhalten |
|-------|-----------|
| Presence | Zwei getrennte Uhren auf `players.last_seen`: (1) frisch geweckte Accounts werden **sofort** touched, damit sie augenblicklich den mehrtägigen Ranking-Inactive-Threshold verlassen; (2) ein kleiner, **dynamisch nach % der echten Spielerbasis gedeckelter**, rotierender Ausschnitt des Rosters gilt je Tick als "online" (`online_visible_cap`, GC-2617) — nicht der gesamte Roster. So bleibt die gleichzeitige Online-Zahl plausibel, egal wie groß der Roster-Cap ist |
| Economy | `plan_passive_planet_tick` mit Soft-Caps (15/20 min) + Chain (bis 3 Jobs/Tick) |
| Anti-Klon-Varianz | Jeder Account (Inactive **und** Pirate-AI) bekommt eine deterministische `personality` (`auto_empire.personality_for_player`/`pirates._personality_for_bot`), die Bau-/Forschungsreihenfolge (`*_BY_PERSONALITY`), Ziel-Level-Jitter (`_stable_jitter`, ±2 Gebäude/±1 Forschung) und Defense-Bias steuert; standing Ticks (nicht Wake) rollen zusätzlich `AUTOPLAY_STANDING_IDLE_CHANCE` (25%) und lassen eine Runde aus (GC-2618) |
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
| Control Handback | Ein echter Login/Request (`models.touch_player_online`, ausgelöst von `require_login`/`require_admin`/`require_login_api`) entfernt den Account **sofort** vom Sticky Roster (`release_active_player_from_roster`) — kein Warten auf LRU-Eviction. Der Spieler behält volle Kontrolle, bis er erneut über die normale Dormant-Auswahl (`list_dormant_candidates`) inaktiv wird (GC-2619) |

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
| GC-2618 | Anti-Klon-Varianz: personality-basierte Bau-/Forschungsreihenfolge + Ziel-Level-Jitter + Idle-Chance auf standing Ticks (Inactive + Pirate-AI) | done |
| GC-2619 | Control Handback: echter Login entfernt Account sofort vom Sticky Roster statt auf LRU-Eviction zu warten | done |

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

## GC-2618 — Anti-Klon-Varianz (Accounts wirken nicht mehr wie Kopien)

**Problem:** Jeder Inactive-Account lief hart auf `personality="economy"`, und `BUILD_PRIORITY`/`RESEARCH_PRIORITY`/`BUILD_TARGETS` waren globale, für **alle** Accounts (Inactive **und** Pirate-„economy"-Bots) identische Listen. Kombiniert mit demselben Resource-Floor und denselben Duration-Caps liefen viele Accounts auf exakt denselben Gebäude-/Tech-Leveln zur exakt gleichen Zeit — im Ranking sah das nach geklonten Bots statt nach unterschiedlichen Spielern aus.

**Fix (`game/auto_empire.py`, einziger Owner — von `inactive_autoplay.py` **und** `pirates/economy.py` geteilt):**

1. **Personality-Zuweisung:** `personality_for_player(player_id)` (deterministischer Hash, MD5-basiert statt `hash()` — stabil über Prozess-Neustarts) wählt aus `ALL_PERSONALITIES` (= `PERSONALITY_SHIP_BIAS`-Keys: economy/aggressive/turtle/spy/swarm/elite). Bisher hatten nur Piraten eine Personality (`pirates/economy.py::_personality_for_bot`, pro Fakton fix); Inactive-Accounts bekommen jetzt über denselben Mechanismus eine **stabile, aber gestreute** Personality statt hartcodiert "economy".
2. **Bau-/Forschungsreihenfolge pro Personality:** `BUILD_PRIORITY_BY_PERSONALITY` / `COLONY_BUILD_PRIORITY_BY_PERSONALITY` / `RESEARCH_PRIORITY_BY_PERSONALITY` — jede Variante enthält exakt dieselben Keys wie die Basisliste, nur in anderer Reihenfolge (z. B. "turtle" baut zuerst Storage/Defense, "aggressive" zuerst Minen/Shipyard). `personality="economy"` bleibt exakt die ursprüngliche Reihenfolge (kein Verhaltenswechsel für den Default). `plan_passive_planet_tick` wählt die Variante über `personality`, fällt bei unbekannter Personality auf die Basisliste zurück.
3. **Ziel-Level-Jitter:** `_stable_jitter(player_id, key, spread)` (deterministischer Hash) verschiebt `BUILD_TARGETS`/`RESEARCH_TARGETS`-Caps um bis zu ±2 (Gebäude) / ±1 (Forschung) pro (Account, Gebäude/Tech) — verhindert, dass alle Accounts exakt auf demselben Level plateauen.
4. **Idle-Chance auf standing Ticks:** `AUTOPLAY_STANDING_IDLE_CHANCE=0.25` — nur die **wiederkehrenden** Roster-/Play-Loop-Ticks (nicht der Wake-Moment) rollen eine Chance, diese Runde **nichts Neues** zu starten (`plan_passive_planet_tick(..., idle_chance=...)`); bereits fällige Jobs werden trotzdem fertiggestellt. Default bleibt `0.0`, direkte Aufrufer/Tests sind dadurch unverändert deterministisch — nur `inactive_autoplay.py`s standing RR-Tick (`_run_player_economy(..., is_wake=False)`) und `pirates/play_loop.py`s `_run_bot_economy_only`/`run_bot_play_step` reichen den Wert explizit durch.

**Ergebnis:** Zwei Accounts mit unterschiedlicher Personality bauen in unterschiedlicher Reihenfolge, auf leicht unterschiedliche Ziel-Level und nicht in jeder Runde garantiert etwas — Fortschritt sieht über die Zeit nach unterschiedlichen Spielern statt nach synchron tickenden Bots aus. `game/pirates/economy.py` und `game/inactive_autoplay.py` importieren die neuen Konstanten aus `auto_empire.py`, keine zweite Formel/Liste.

## GC-2619 — Control Handback (echter Login gewinnt sofort)

**Problem:** Der Sticky Roster (GC-2601) verließ einen Account nur über LRU-Eviction (voller Roster, ältester `last_ticked_at` fliegt raus). Kam ein echter Mensch währenddessen zurück und loggte sich ein, blieb sein Account trotzdem auf dem Roster — Autoplay hätte parallel zum menschlichen Spieler weiter Gebäude/Forschung/Defense eingereiht und ggf. per Timekeeper-Auto-Boost (GC-2616) den echten Timekeeper-Ledger belastet, ohne dass der Spieler das wollte. `last_seen` alleine taugt dafür nicht als Signal, weil Autoplay dieselbe Spalte selbst für seine eigene Online-Präsenz beschreibt (GC-2617) — ein Vergleich "ist `last_seen` frisch?" kann nicht zwischen "Autoplay hat gerade getouched" und "ein Mensch ist gerade da" unterscheiden.

**Fix:**

1. `game/models.py::touch_player_online` ist der **einzige** kanonische Signalpunkt für "ein echter, authentifizierter Request ist gerade passiert" — aufgerufen aus `require_login`/`require_admin`/`require_login_api` (`game/auth.py`), throttled auf max. 1×/30s pro Spieler. Genau dort (nicht in `inactive_autoplay.py` selbst, das den Roster nicht "von außen" beobachten kann) wird geprüft, ob der Write tatsächlich stattgefunden hat.
2. Fand der Write statt, ruft `touch_player_online` `inactive_autoplay.release_active_player_from_roster(player_id, conn=conn)` **in derselben Transaktion** auf (kein zweiter Connect/Commit-Zyklus).
3. `release_active_player_from_roster` (Owner bleibt `game/inactive_autoplay.py`, kein neuer Parallel-Mechanismus) entfernt den Account — falls vorhanden — sofort aus dem Sticky Roster (`_load_roster`/`_save_roster`) und verschickt denselben "Was ist passiert, während du weg warst"-Bericht wie eine normale Eviction (`_send_autoplay_report`, GC-2615) — keine zweite Nachrichten-/Feed-Logik.
4. Der nächste Fleet-Cron-RR-Tick sieht den Account nicht mehr im Roster → keine weiteren Builds/Research/Defense/Timekeeper-Boosts mehr, bis er über die normale Dormant-Auswahl (`list_dormant_candidates`, mehrtägiger Inaktivitäts-Threshold) erneut aufgenommen wird — exakt "erst wenn er wieder inaktiv wird, wird er wieder aufgenommen".
5. Bereits laufende, von Autoplay eingereihte Jobs (Bau/Forschung) laufen reguär zu Ende — keine Job-Cancel-/Refund-Logik, das wäre unnötige Komplexität für einen bereits legitim mit echten Kosten eingereihten Job.

**Ergebnis:** Ein Spieler, der sich einloggt, bekommt beim allerersten authentifizierten Request die volle Kontrolle über sein Konto zurück — Autoplay rührt seine Warteschlangen und seinen Timekeeper-Ledger ab diesem Moment nicht mehr an.

## Living Universe Pulse (GC-2612)

- `game/galaxy.py` (`_attach_player_status_flags`) setzt `slot["recently_active"]` wenn `last_seen` < 2h alt — **unabhängig** von `is_ai`/`inactive`, damit auch echte Spieler, die kurz vorbei waren, den Chip zeigen.
- Rein visuell: kein Einfluss auf Ranking/PvP; Owner bleibt `game/galaxy.py` + `templates/partials/galaxy_slot_status_badges.html` (kein neues Feed-/Chronicle-System).
- Chip ausgeblendet während `vacation_active`; Legende in `templates/partials/galaxy_ring_view.html`.

## Fair Play

- Inaktive Autoplay-Konten **fliegen keine Expeditionen** und starten keine Angriffe.
- Pirate-AI (EPIC-21) darf Expeditionen fliegen — siehe [PIRATE_ECOSYSTEM.md](PIRATE_ECOSYSTEM.md).
- Ranking-Inactive-Schwelle bleibt 3 Tage; Autoplay hält Roster-Konten darunter.
