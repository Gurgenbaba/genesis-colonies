# Game Rules — Genesis Colonies

> **Status:** ✅ Master-Doc v1.0 · **Stand:** 2026-06-27  
> **Owner (Dokument):** `docs/GAME_RULES.md` — kanonische Quelle für **alle** Spielregeln, Support-Policy und Fair-Play-Definitionen.  
> **Enforcement (Code):** verteilt — primär `game/fleet.py`, `game/options.py`, `game/exchange.py`, `game/auth.py`, `game/admin_api.py` (Appendix §9).  
> **Surfaces:** Bottom Utility Bar (`Regeln` special window), Options-Link — **nicht** Codex. Player-Text: `rules_panel_*` in `game/game_rules_panel.py` → `scripts/sync_rules_panel_locales.py`.

**Nicht verwechseln mit:**

| Begriff | Bedeutung | Doc |
|---------|-----------|-----|
| **Game Rules** (dieses Dokument) | Fair Play, Accounts, PvP-Policy, Sanktionen | `GAME_RULES.md` |
| **Galactic Directives** | Galaxie-Politik, Community-Abstimmung | [GALACTIC_DIRECTIVES.md](GALACTIC_DIRECTIVES.md) |
| **Imperial Directives** | Persönliche High-Command-Befehle | [IMPERIAL_DIRECTIVES.md](IMPERIAL_DIRECTIVES.md) |
| **Queue State Rules** | Technische Queue-Invarianten (Dev) | [QUEUE_STATE_RULES.md](QUEUE_STATE_RULES.md) |

**Terminologie (Spieler-Copy):** [GENESIS_TERMINOLOGY.md](GENESIS_TERMINOLOGY.md) · Welten/Kolonien: [EXPANSION_PROTOCOL.md](EXPANSION_PROTOCOL.md).

---

## Legende — Enforcement-Typ

| Tag | Bedeutung |
|-----|-----------|
| **`[Enforced]`** | Server blockiert die Aktion technisch |
| **`[Policy]`** | Regel gilt; Prüfung durch Support/Admin (kein Auto-Enforcement) |
| **`[Partial]`** | Teilweise technisch, Teilweise Support |

Bei Widerspruch zwischen Spieler-Copy und Appendix §9 gilt **Appendix §9** (Code-Ist-Stand) bis Doc/Code-Sync-Ticket.

---

## 1. Philosophy

### Was ist Genesis Colonies?

Genesis Colonies ist ein browserbasiertes Imperiums-Strategiespiel: Kolonien entwickeln, Flotten führen, Wirtschaft steuern, Welten erschließen. Mechanik und Zahlen sind **serverseitig autoritativ** — die UI zeigt nur Serverdaten ([CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) Regel 1, 16).

### Fair Play

Spieler sollen sich **ausschließlich über legitime Spielmechaniken** verbessern — nicht durch Ausnutzung von Fehlern, Mehrfachaccounts, Push, Bots oder Echtgeldhandel.

### Server Authority

- Flugzeiten, Kampf, Loot, Produktion, Queues, Handelslimits: berechnet in Python (`game/`), nicht im Frontend.
- `[Enforced]` Limits (Bash, Noobschutz, Urlaubssperren, Exchange-Arbitrage-Guard) sind im Code implementiert.
- `[Policy]`-Regeln (Push, Sitting, Multiaccount) werden administrativ durchgesetzt.

### Support entscheidet Zweifelsfälle

Das Genesis-Team entscheidet in unklaren Fällen **endgültig**. Siehe §8 Sanktionen und §3.7 Support-Policy.

### Regeländerungen

`[Policy]` Das Team kann dieses Regelwerk bei Bedarf anpassen (Balance, neue Systeme, Exploit-Schutz). Wesentliche Änderungen werden im **Changelog** (unten) und in der **Rules-Panel-Version** (`rules_panel_version`) veröffentlicht. Fortbestehende Verstöße gegen den **Geist** des Regelwerks können auch nach Regeländerungen berücksichtigt werden, wenn sie vor der Änderung begannen.

---

## 2. Accounts

### 2.1 Account

`[Policy]` Ein Account gehört **einer natürlichen Person**. Pro **Universum** genau **ein** spielbarer Commander-Account.

| Erlaubt | Nicht erlaubt |
|---------|---------------|
| Ein Account pro Person pro Universum | Zweitaccounts |
| Passwort sicher verwahren | Account für Dritte „halten“ |
| Support kontaktieren bei Kompromittierung | Identität verschleiern, um Regeln zu umgehen |

Technisch: Login über `game/auth.py`; Session an `user_id` / `player_id` gebunden.

### 2.2 Multiaccount

`[Policy]` **Verboten** pro Universum:

- Farmaccounts (Ressourcen sammeln für Hauptaccount)
- Ressourcenspeicher-Accounts
- Spionage-/Angriffs-Alts
- Accounts nur für Ranking-Manipulation

Erkennung: IP-/Verhaltensanalyse, Support-Meldungen, Admin-Tools. Kein automatischer Permaban allein durch Heuristik — menschliche Prüfung.

### 2.3 Account Sharing

`[Policy]` **Verboten:** dauerhafte Weitergabe von Zugangsdaten an Dritte (Freunde, Allianzoffiziere, „Reichsverwalter“), außer im engen Rahmen von **Sitting** (§2.4).

### 2.4 Sitting (Account-Vertretung)

`[Policy]` Account Sitting ist **temporär** erlaubt unter diesen Bedingungen:

| Bedingung | Wert |
|-----------|------|
| Maximale Dauer | **48 Stunden** am Stück |
| Ressourcen | **Keine** absichtliche Weitergabe an den Gesitteten oder Dritte |
| Dauerhafte Vertretung | **Verboten** |
| Sitting-Log | Empfohlen: schriftliche Vereinbarung (Allianz-Forum / Ticket) |

**Hinweis (Produkt):** Sitting ist derzeit **nicht** als eigene Login-Rolle implementiert — technisch läuft es über geteilte Credentials und fällt unter Account Sharing, sofern die Sitting-Regeln verletzt werden.

**Optional (Roadmap):** Sitting kann später komplett deaktiviert werden.

### 2.5 Accountübernahme

`[Policy]` **Verboten:** Kauf, Verkauf, Tausch oder Schenkung von Accounts oder Imperiumsfortschritt gegen Echtgeld oder externe Gegenleistungen außerhalb der offiziellen Spiele-Monetarisierung (falls vorhanden).

---

## 3. Fair Play

### 3.1 Push — Definition

`[Policy]` **Push** = absichtliches Verschaffen eines **unfairen Vorteils** durch Ressourcen-, Flotten- oder Punkteübertragung, die **nicht** dem normalen, marktgerechten Spielzweck entspricht.

**Verboten (Beispiele):**

| Szenario | Warum Push |
|----------|------------|
| Schenken großer Ressourcenmengen ohne Gegenleistung | Stärkerer Account wird künstlich gefüttert |
| Absichtlich Flotten verlieren, damit der Gegner Beute/Loot erhält | Umgehung des Handels |
| Mehrstufige Transportketten (A→B→C), um Bash/Push-Detection zu umgehen | Indirekte Übertragung |
| Handel zu extrem einseitigen Kursen (weit unter/über Markt) | Versteckte Schenkung |
| Recycler-/Wrack-Manipulation: absichtlich Schrottfelder erzeugen, die ein Verbündeter abbaut | Push über Wracks |
| Auktionshaus: Scheingebote zum Verschieben von Ressourcen | Push über Gebote |
| Logistics-Sammel-/Verteil-Routen zugunsten fremder Imperien | `[Partial]` — nur eigene Welten technisch erlaubt; Missbrauch melden |

**Erlaubt:**

| Szenario | Begründung |
|----------|------------|
| Regulärer **Trader Hub**-Tausch innerhalb Server-Limits | Mechanik + `[Enforced]` Anti-Arbitrage |
| **Transport** / **Logistics** zwischen **eigenen** Welten | Imperiums-interne Planung |
| **Allianzunterstützung** über erlaubte Mechaniken (z. B. koordinierter Handel zu marktnahen Kursen, gemeinsame ACS — wenn implementiert) | Fair, wenn kein Schenken |
| **Beute** aus legitimen Angriffen | Kampfmechanik ([COMBAT_SYSTEM.md](COMBAT_SYSTEM.md)) |
| Gegenseitiger Handel zu **marktüblichen** Konditionen | `[Policy]` — Support prüft Extremfälle |

### 3.2 Bugusing / Exploit-Policy

`[Policy]` + `[Partial]`

| Regel | Detail |
|-------|--------|
| Meldepflicht | Bugs **meldens** (Support/Ingame) statt ausnutzen |
| Einmaliges versehentliches Ausnutzen | Kann Verwarnung ohne harte Strafe sein — Einzelfall |
| **Bewusstes** wiederholtes Ausnutzen | Sanktionen auch **ohne** explizite Regelzeile (§1 Fair-Play-Grundsatz, §3.8) |
| Bekannte Kategorien | Duplizieren von Ressourcen, Endlosschleifen, Queue-Manipulation, Handels-/Rundungsfehler, Expeditions-Event-Bugs, Kolonisierungs-Regionsfehler |

**Referenz (behoben):** Crytite-Rundungs-Exploit im Trader Hub — `[Enforced]` via `would_roundtrip_profit()` in `game/exchange.py`.

### 3.3 Echtgeldhandel (RMT)

`[Policy]` Verboten: Handel von Accounts, Ressourcen, Flotten, Dienstleistungen oder Schutz gegen **Echtgeld** oder externe Zahlungsmittel außerhalb autorisierter Kanäle.

### 3.3a Official LiveOps / Premium / Shop (EPIC-22 / EPIC-23)

`[Policy]` Offizielle Kanäle (Login-Kalender, Battle Pass, **Shop**) dürfen **Convenience** verkaufen oder vergeben: Timekeeper-Zeit, Container (meta-only), Boosters, Cosmetics/QoL, Season-Pass-Entitlement.

Battle-Pass-XP: sichtbare **Season Ops** (daily/weekly) + soft-capped Activity-Drip; Pace zielt auf Season-Abschluss bei täglicher Anwesenheit (~28–30 Tage), ohne zweite Quest-Engine neben Imperial Directives.

Shop (Stripe/PayPal): erfüllt über denselben Entitlement-/Grant-Pfad — kein paralleles Unlock-System, keine Hard-Currency-Wallet im MVP. Doc: [PAYMENT_SHOP.md](PAYMENT_SHOP.md), [LIVEOPS_RETENTION.md](LIVEOPS_RETENTION.md).

**Nicht** über Premium/Login/Shop: Kampf-Power (Schiffe, Defense) oder Rohstoff-Stacks, die Ranking verzerren.

### 3.4 Bots, Makros, Scripts, Automation

`[Policy]`

**Verboten:**

- AutoHotkey, Makros, Clicker, Browserbots, Selenium, API-Bots
- Automatisiertes Expeditions-/Angriffs-/Handels-Farming
- Skripte, die Spielzustand auslesen und Aktionen ohne menschliche Entscheidung ausführen

**Erlaubt (Ausnahme, `[Policy]`):**

- Browser-Erweiterungen **ohne** Spielautomatisierung (Ad-Blocker, Passwort-Manager, Accessibility)
- Offizielle API/Cron des Betreibers (`/api/internal/…`)

### 3.5 Respektvoller Umgang

`[Policy]` Siehe §7 Community — Beleidigungen, Diskriminierung, Hassrede, Drohungen nicht toleriert.

### 3.6 Allgemeines Bug-Melden

`[Policy]` Spieler, die Fehler **verantwortungsvoll melden**, werden nicht bestraft. Wiederholtes Ausnutzen nach Meldung oder stillschweigendes Farmen gilt als Exploit.

### 3.7 Support-Policy

`[Policy]`

| Thema | Regel |
|-------|-------|
| Eigene Fehler | **Kein** Anspruch auf Wiederherstellung verlorener Flotten, Ressourcen oder Baufortschritt durch falsche Spielerentscheidungen |
| Server-/Spielfehler | Nach **nachgewiesenem** Bug: Prüfung durch Support; Rollback/Compensation **nach Team-Ermessen** |
| Bearbeitungszeit | Keine garantierte SLA in Alpha/Beta |
| Beweise | Screenshots, Zeitstempel, Koordinaten/Welt-Keys, Request-IDs helfen |
| Entscheidung | **Endgültig** durch Genesis-Team (§1) |

Audit-Log: Urlaub, Löschung, Neustart → `write_account_audit()` in `game/options.py`.

### 3.8 Fair-Play-Klausel (Catch-All)

`[Policy]` Alles, was **offensichtlich** Mechaniken umgeht oder anderen einen unfairen Vorteil verschafft, kann sanktioniert werden — **auch wenn** es nicht wortwörtlich in diesem Dokument steht.

---

## 4. PvP Rules

Alle **technisch erzwungenen** Kampfrestriktionen — mit Verweis auf Mechanik-Docs.

| Mechanik | Doc | Code-Owner |
|----------|-----|------------|
| Angriff, Flotten, Missionen | [FLEET_SYSTEM.md](FLEET_SYSTEM.md) | `game/fleet.py` |
| Kampf, Loot, Debris | [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) | `game/combat.py` |
| Verteidigung | [DEFENSE_SYSTEM.md](DEFENSE_SYSTEM.md) | `game/defense.py` |

### 4.1 Bash-Regel (Angriffslimit)

`[Enforced]` — siehe Appendix §9.1

- **Maximal 5 Angriffe** (`mission_type = attack`) pro **Angreifer-Account → Ziel-Welt** innerhalb eines **rollierenden 24-Stunden-Fensters**.
- Gilt **pro Zielplanet/Welt**, nicht imperiumsweit beim Verteidiger.
- **Origin-Welt** des Angreifers wird **ignoriert** — Weltwechsel im Imperium umgeht das Limit **nicht**.
- **Beispiel (dieselbe Ziel-Welt):** Du hast Kolonie A und Kolonie B. Angriffe auf **dieselbe** feindliche Welt X: 3× von A + 2× von B = **5 gesamt** (Limit voll) — **nicht** 5+5.
- **Beispiel (verschiedene Ziel-Welten):** 5× auf feindliche Welt X **und** 5× auf feindliche Welt Y = **10 gesamt** (je 5 pro Ziel-Welt).

UI: `fleet_attack_limit_remaining` / `fleet_error_attack_limit_reached`.

### 4.2 Noobschutz (Imperiumspunkte-Schutz)

`[Enforced]` — siehe Appendix §9.2

- Angriff nur erlaubt, wenn das Verteidiger-Imperium im **Schutzbereich** liegt (Faktor **5×** auf `score_total`) **oder** der Verteidiger **inaktiv** ist.
- **Inaktiv:** kein `last_seen` innerhalb von **3 Tagen** (`RANKING_INACTIVE_AFTER_SEC`).
- **Inactive Autoplay (EPIC-26):** Gestaffelte Sessions wecken dormante Menschen-Konten (Gebäude/Forschung/Defense + `last_seen`-Refresh). Ranking/Galaxy wirken lebendig; Autoplay startet **keine** Flotten/Expeditionen. Details: [INACTIVE_AUTOPLAY.md](INACTIVE_AUTOPLAY.md).
- Inaktive Imperien können **außerhalb** des Punkte-Schutzes angegriffen werden — beabsichtigt für Inaktiven-Räumung, nicht für Push auf aktive Alt-Accounts.

UI: `noob_protection_blocked` in Fleet-Preview/Send.

### 4.3 Urlaubsmodus

`[Enforced]` + `[Policy]` — siehe Appendix §9.3

**Spieler-Intent:** Schutz vor Angriffen während Abwesenheit.

| Phase | Verhalten |
|-------|-----------|
| **Aktivierung** | Mindestdauer **48 h**; Blocker wenn aktive Flotten, Auktionsgebote oder Queues offen |
| **Während Urlaub** | Keine ausgehenden Flotten; kein Trader Hub; kein Bau/Forschung/Werft/Verteidigung; Produktion und Queues pausiert; eingehende Angriffe/Spionage prall ab |
| **Deaktivierung** | Erst nach Ablauf der Mindestdauer — **bleibt aktiv bis manuell beendet** |

**Abweichung (Ist-Stand Code):** ~~Produktion, Forschung und Bauqueues sind während Urlaub **nicht** pausiert~~ — seit GC-871 pausiert (Stand 2026-07-05).

Ranking: Urlaub-Badge in Rangliste (`ranking_vacation_badge`).

Owner: `game/options.py` (`enable_vacation_mode`, `vacation_blocks_outbound`, `vacation_blocks_incoming_attack`).

### 4.4 Spionage

| Regel | Enforcement |
|-------|-------------|
| Unbegrenzt erlaubt (Fair Play) | `[Policy]` |
| Ziel im Urlaub | `[Enforced]` — Spionage prall ab wie Angriff |
| Bash | `[Enforced]` — **Nein** — Spionage zählt **nicht** zum Bash-Limit |

### 4.5 Expeditionen

| Regel | Enforcement |
|-------|-------------|
| Unbegrenzt (Fair Play) | `[Policy]` |
| Während eigenem Urlaub | `[Enforced]` — keine ausgehenden Flotten inkl. Expedition |
| Event-/Loot-Bug-Farming | `[Policy]` — Exploit-Policy §3.2 |

Doc: [FLEET_SYSTEM.md](FLEET_SYSTEM.md), `game/expedition_events.py`.

### 4.6 Halteflüge (`hold`)

| Regel | Detail |
|-------|--------|
| Erlaubt | Mission `hold` — Flotte bleibt am Ziel |
| Bash | Angriffe im `holding`-Status zählen **zum Bash-Limit** mit (`ATTACK_LIMIT_COUNT_STATUSES`) |
| Push | `[Policy]` — absichtliches Halten zur Ressourcenübergabe verboten |

### 4.7 Recycling (`recycle`)

| Regel | Detail |
|-------|--------|
| Unbegrenzt (Fair Play) | `[Policy]` |
| Wracks | Siehe [COMBAT_SYSTEM.md](COMBAT_SYSTEM.md) — Debris-Felder nach Kampf |
| Push über Wracks | `[Policy]` — §3.1 |

Doc: [GC-800_RECYCLER.md](GC-800_RECYCLER.md), [GC-584_WRECKAGE_SALVAGE.md](GC-584_WRECKAGE_SALVAGE.md).

### 4.8 ACS / Gemeinsame Angriffe

`[Policy]` **Geplant (Roadmap)** — noch nicht implementiert. Bis dahin: koordinierte Einzelangriffe erlaubt, sofern Bash/Noob/Urlaub eingehalten werden.

**Nicht geplant:** Monde / Mondbasen — existieren in Genesis Colonies **nicht**.

### 4.9 Übersicht PvP-Enforcement

| Restriktion | `[Enforced]` | Angriff | Spionage | Transport | Expedition |
|-------------|-------------|---------|----------|-----------|------------|
| Bash (5/24h pro Ziel-Welt) | ✅ | ✅ | ❌ | ❌ | ❌ |
| Noobschutz | ✅ | ✅ | ❌ | ❌ | ❌ |
| Urlaub (eigen) | ✅ | ❌ senden | ❌ senden | ❌ senden | ❌ senden |
| Urlaub (Ziel) | ✅ | ❌ eingehend | ❌ eingehend | ✅ | ✅ |

---

## 5. Economy Rules

Doc-Owner: [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md)

### 5.1 Trader Hub

`[Enforced]` + `[Policy]`

- Scope: **aktive Kolonie** für Salden; **tägliches Limit accountweit** (Commander).
- Unified Resource Trader + Scrapyard — `/trader-hub`.
- Anti-Arbitrage: Rundtrip-Gewinn auf Metal/Crystal blockiert (`exchange_arbitrage_disabled`).
- Während Urlaub: `[Enforced]` gesperrt.

### 5.2 Ressourcenhandel & Push

Siehe §3.1 Push. Marktgerechter Handel im Trader Hub ist `[Enforced]` limitiert, nicht unbegrenzt schenkbar.

### 5.3 Logistics (Imperiums-intern)

`[Enforced]` — nur **eigene** Welten als Quelle/Ziel (`collect_resources`, `distribute_resources` in `game/fleet.py`).

`[Policy]` — absichtliche Umwege über mehrere eigene Welten zugunsten Dritter (Push-Vorbereitung) verboten.

Doc: [GC-900_LOGISTICS.md](GC-900_LOGISTICS.md)

### 5.4 Recycler & Wracks

- Recycler-Mission: `[Enforced]` — Mechanik in Fleet-System.
- Absichtliches Erzeugen von Wracks zum Vorteil Dritter: `[Policy]` Push.

### 5.5 Expeditionen (Wirtschafts-Loot)

Expeditions-Loot über `[Enforced]` Event-Engine — kein Frontend-Raten. Bug-Farming: §3.2.

### 5.6 Auktionshaus

`[Enforced]` — Gebote, Limits, Refunds ([ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) § Auktionshaus). Push über Scheingebote: `[Policy]`.

---

## 6. Empire Rules (Genesis-spezifisch)

Diese Regeln existieren in OGame **nicht** in dieser Form — sie sind Genesis-Colonies-spezifisch.

### 6.1 Planet Evolution

`[Policy]` Kein Missbrauch von DNA-, Trait-, Event- oder Evolutionsmechaniken (Queue-Skip-Bugs, unautorisierte Spec-Wechsel, Kultur-Exploits).

Doc: [PLANET_EVOLUTION.md](PLANET_EVOLUTION.md) · Owner: `game/planet_evolution/`

### 6.2 Kolonisierung & Expansion

`[Policy]` + `[Enforced]`

- Kolonien entstehen **nur** über Expansion Protocol (Claim → Seed Ark → Outpost → Kolonie).
- Kein Ausnutzen von Regions-/Gate-Fehlern, Doppel-Claims, Phasen-Desync.

Doc: [EXPANSION_PROTOCOL.md](EXPANSION_PROTOCOL.md) · [IMPERIUM_VISION.md](IMPERIUM_VISION.md)

### 6.3 Command Map

`[Policy]` Keine Ausnutzung von Kartengrenzen, Sichtbarkeits- oder Regions-Bugs für unfaire Kolonisierung oder Spionage.

Owner: `game/planet_evolution/command_map.py`

### 6.4 Galactic Directives

`[Policy]` Manipulation oder Exploits der **Community-Abstimmung** (Multiaccount-Stimmen, Bot-Votes, Bug in Vote Tally) verboten.

**Nicht** Imperial Directives — siehe Abgrenzung oben.

Doc: [GALACTIC_DIRECTIVES.md](GALACTIC_DIRECTIVES.md)

### 6.5 Imperial Directives

`[Policy]` Kein Scripting/Account-Sharing zum automatisierten Claim-Farmen; kein Exploit der Fortschritts-Tracker.

Doc: [IMPERIAL_DIRECTIVES.md](IMPERIAL_DIRECTIVES.md)

### 6.6 DNA, Traits, Discoveries

`[Policy]` Kein Bugusing bei Legendary Discoveries, Chronicle-Injection oder DNA-Enthüllung.

Doc: [GC-620J_LEGENDARY_DISCOVERIES.md](GC-620J_LEGENDARY_DISCOVERIES.md)

---

## 7. Community

### 7.1 Chat

`[Policy]` — Owner: `game/chat.py`

**Nicht erlaubt:** Spam, Werbung, Echtgeldangebote, politische/extremistische Inhalte, NSFW, Drohungen, Beleidigungen, Hassrede.

Chat-Bans: Admin-Tooling / `chat_bans`-Tabelle.

### 7.2 Namen (Commander, Imperium, Allianz)

`[Policy]` **Nicht erlaubt:**

- Beleidigende, rassistische, sexistische Namen
- Irreführende Team-/Admin-Namen („Genesis Support“, „Admin“, …)
- Impersonation des Betreiberteams

### 7.3 Allianz

`[Policy]`

| Erlaubt | Nicht erlaubt |
|---------|---------------|
| Gemeinsame Angriffe (Bash/Noob beachten) | Multiaccount-Unterstützung |
| Ressourcenhilfe über faire Mechaniken | Push |
| Verteidigung, Handelsabkommen | Dauerhaftes Account-Sharing |
| Koordination im Chat/Discord | Sitting-Verstöße |

Doc: [GALACTIC_DIPLOMACY.md](GALACTIC_DIPLOMACY.md)

### 7.4 Discord & externe Kanäle

`[Policy]` Gleiche Fair-Play- und Respekt-Standards gelten sinngemäß. Offizieller Discord kann zusätzliche Moderationsregeln haben.

### 7.5 Werbung

`[Policy]` Werbung für fremde Spiele/Dienste, RMT oder Bot-Angebote in Chat, Nachrichten oder Profilen verboten.

---

## 8. Sanctions

`[Policy]` — technische Hilfsmittel in `game/admin_api.py`, `game/auth.py` (`bans`-Tabelle).

| Stufe | Maßnahme | Typische Anwendung |
|-------|----------|-------------------|
| 1 | **Verwarnung** | Erstverstoß, geringfügig |
| 2 | **Temporäre Sperre** | `banned_until` — Push, Sitting, Chat |
| 3 | **Permanente Sperre** | Multiaccount, schwerer Exploit, RMT |
| 4 | **Ressourcenentzug** | Push-Rückbuchung |
| 5 | **Flottenentzug** | Push / Bugusing |
| 6 | **Rollback** | Nach nachgewiesenem Exploit |
| 7 | **Accountlöschung** | schwerster Fall / auf Wunsch |

Admin-Bestätigung: z. B. `BAN PLAYER` für `ban_player_api`.

Kein Anspruch auf bestimmte Sanktionsform — Team wählt **verhältnismäßig**.

---

## 9. Appendix — Code Truth (Support-Referenz)

> **Zweck:** Support und Dev müssen **nicht** im Code suchen. Bei Abweichung Doc ↔ Code: Code-Ist-Stand + Sync-Ticket.

### 9.1 Bash (Attack Limit)

```text
Limit:           5
Window:          24 Stunden (rolling, created_at)
Scope:           (attacker_player_id, target_planet_id)
Nicht im Scope:  origin_planet_id, defender_player_id allein
Mission:         attack
Statuses gezählt: outbound, returning, completed, holding
Reset-Anzeige:   oldest_created + 24h (wenn Limit voll)
Konstanten:      game/fleet.py — ATTACK_LIMIT_*
Tests:           tests/test_fleet.py — test_attack_limit_*
Locale:          fleet_error_attack_limit_reached
```

### 9.2 Noobschutz

```text
Factor:          5  (NOOB_PROTECTION_FACTOR)
Score-Feld:      score_total  (player_scores, via ranking cache)
Berechnung:      min_def = ceil(attacker_score / factor)
                 max_def = attacker_score * factor
Erlaubt wenn:    min_def <= defender_score <= max_def
Ausnahme:        defender inactive → Angriff erlaubt (is_player_id_inactive)
Inactive:        last_seen älter als 3 Tage (RANKING_INACTIVE_AFTER_SEC)
Selbstangriff:   erlaubt (kein Gate)
Konstanten:      game/fleet.py — NOOB_PROTECTION_FACTOR
Tests:           tests/test_fleet.py — test_noob_protection_*
```

### 9.3 Urlaubsmodus

```text
Mindestdauer:    48 h  (VACATION_MIN_DURATION_SEC)
Spalten:         players.vacation_mode_active, vacation_locked_until
Aktivierung:     Blocker bei active_fleets, active_auctions, active_queues
Während aktiv:
  - vacation_blocks_outbound → alle Fleet-Sends blockiert
  - vacation_blocks_incoming_attack → attack/spy prall ab (Bounce)
  - exchange.py → Trader Hub blockiert
  - queue_build / queue_research / shipyard / defense enqueue → blockiert
  - finish_due_work → Bau/Forschung/Werft/Verteidigung/PE pausiert
  - update_planet_resources → Produktion pausiert (last_update läuft weiter)
  - Deaktivierung: locked_until = früheste Endzeit; bleibt aktiv bis manuell disabled
  - repair_account_safety_state: deaktiviert NICHT automatisch nach Mindestdauer
Audit:           vacation_mode_enabled / disabled
Owner:           game/options.py
Tests:           tests/test_fleet.py — test_vacation_mode_*
Locale:          options_vacation_*, fleet_vacation_bounce_*
```

### 9.4 Trader Hub Exchange

```text
Owner:           game/exchange.py
Urlaub:          blockiert (vacation_blocks_outbound)
Arbitrage-Guard: would_roundtrip_profit() → exchange_arbitrage_disabled
Daily limit:     accountweit; pct/min aus game_settings (exchange_daily_limit_*)
Scope Salden:    context planet (get_context_planet)
```

### 9.5 Fleet Missionen (Referenz)

```text
Missions:        transport, collect, deploy, spy, attack, hold, expedition,
                 colonize, recycle
Hold:            erlaubt; attack-hold zählt zu Bash wenn mission attack → holding
Spionage:        kein Bash-Zähler
Expedition:      EXPEDITION_POSITION; Events in expedition_events.py
```

### 9.6 Bans

```text
Owner:           game/admin_api.py — ban_player_api
Player-Feld:     players.banned_until
Historie:        bans (reason, banned_until, created_at)
Permanent:       ~50 Jahre Offset (Admin-API)
Login-Check:     game/auth.py — _get_active_ban
```

### 9.7 Dokument-Sync-Pflicht

Änderungen an `[Enforced]`-Regeln **müssen** in diesem Appendix und im Changelog nachgezogen werden (idealerweise im selben PR wie Code).

---

## Changelog

| Version | Datum | Änderung |
|---------|-------|----------|
| v1.0 | 2026-06-27 | Initiales Master-Doc — Philosophy, Accounts, Fair Play, PvP, Economy, Empire, Community, Sanctions, Appendix |
| v1.1 | 2026-06-27 | Spieler-UI: Rules Panel (Bottom Nav), nicht Codex — `game/game_rules_panel.py` |
| v1.2 | 2026-06-27 | Rules Panel: Push, Community, FAQ, Support-CTA, erweiterte DE/EN-Copy |

---

## Rules Panel (Spieler-UI)

Regeln erscheinen im **Special Window „Regeln“** — geöffnet über die Bottom Utility Bar (`data-special-open-window="rules"`), Community-Hub, Options oder Support-Verweis.

| Schicht | Owner |
|---------|--------|
| Master-Doc (Support/Dev) | `docs/GAME_RULES.md` |
| Spieler-Text | `game/game_rules_panel.py` → `rules_panel_*` i18n |
| Locale-Sync | `scripts/sync_rules_panel_locales.py` |
| Template | `templates/partials/special_panel.html` |

**Abschnitte (v1.2):** Allgemein · Accounts · Kämpfe · Push · Wirtschaft · Urlaub · Imperium · Community · Sanktionen · FAQ

**Nicht im Codex.** Codex bleibt für Mechanik-Wissen (Fleet, Buildings, …).

Nach inhaltlichen Änderungen am Spieler-Text:

```bash
python scripts/sync_rules_panel_locales.py
```
