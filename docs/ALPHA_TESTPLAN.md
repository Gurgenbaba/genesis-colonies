# Genesis Colonies — Alpha Testplan (manuell)

**Voraussetzung:** `python app.py` läuft auf [http://127.0.0.1:5000](http://127.0.0.1:5000)

Bestehende `game/game.db` **nicht löschen**, wenn du einen vorhandenen Spielstand testen willst.

---

## 1. Auth

| # | Schritt | Erwartung |
|---|---------|-----------|
| 1.1 | `/register` — neuen Commander anlegen | Erfolg, Redirect zu Übersicht |
| 1.2 | Logout → `/login` mit neuem Account | Login ok |
| 1.3 | Falsches Passwort | Fehlermeldung, kein Crash |

---

## 2. Übersicht (`/overview`)

| # | Schritt | Erwartung |
|---|---------|-----------|
| 2.1 | Seite laden | Ferronit, Crytite, Energie sichtbar |
| 2.2 | 10–15 s warten (Polling) | Ressourcenwerte aktualisieren sich |
| 2.3 | Gebäude-Tabelle | Mindestens Minen + Solar sichtbar |

---

## 3. Gebäude (`/buildings`)

| # | Schritt | Erwartung |
|---|---------|-----------|
| 3.1 | Tab „Ressourcen“ | Gebäudeliste lädt |
| 3.2 | Upgrade starten (wenn Ressourcen reichen) | Queue zeigt aktiven Bau |
| 3.3 | Countdown / Fortschrittsbalken | Läuft ohne Reload |

**Queue-Regression (GC-512):** Vollständige Checkliste [GC-512_QUEUE_MANUAL_QA.md](GC-512_QUEUE_MANUAL_QA.md) (Cancel active/middle/last, near-finish, PJAX, Planetwechsel).

---

## 4. Forschung (`/research`)

| # | Schritt | Erwartung |
|---|---------|-----------|
| 4.1 | Tech-Liste | Einträge mit Kosten/Zeit |
| 4.2 | Forschung starten | Active-Block erscheint |
| 4.3 | Zweite Forschung parallel | Blockiert (eine Queue) |

Siehe auch [GC-512_QUEUE_MANUAL_QA.md](GC-512_QUEUE_MANUAL_QA.md) § B.

---

## 5. Ranking (`/ranking`)

| # | Schritt | Erwartung |
|---|---------|-----------|
| 5.1 | Seite öffnen | Tabelle mit Spielern |
| 5.2 | Eigener Eintrag | Score sichtbar (wenn vorhanden) |

---

## 6. Admin (`/admin`) — nur mit Admin-Account

| # | Schritt | Erwartung |
|---|---------|-----------|
| 6.1 | Panel öffnen | Universe-Settings sichtbar |
| 6.2 | MOTD setzen (optional) | Banner auf Ingame-Seiten |
| 6.3 | **Kein Wipe** während Demo | Daten bleiben erhalten |

---

## 7. Mobile (390×844 — DevTools)

| # | Schritt | Erwartung |
|---|---------|-----------|
| 7.1 | `/overview` | Bottom-Nav sichtbar |
| 7.2 | Scrollen | Ressourcenleiste bleibt oben kleben |
| 7.3 | Bottom-Nav: Gebäude, Forschung | Navigation funktioniert |
| 7.4 | „Mehr“ → Drawer | Öffnet/schließt smooth |
| 7.5 | Kein horizontaler Page-Scroll | Nur Tabellen innerhalb Scroll-Container |

---

## 8. Desktop (1440×900)

| # | Schritt | Erwartung |
|---|---------|-----------|
| 8.1 | Sidebar links | Alle Nav-Links sichtbar |
| 8.2 | Keine Bottom-Nav | Nur Mobile-Layout |
| 8.3 | Zwei-Spalten-Grids | Overview/Research ok |

---

## 9. WIP / Platzhalter

| Route | Erwartung |
|-------|-----------|
| `/defense` | Platzhalter-UI, kein Backend-Crash |
| `/alliance` | Platzhalter-UI (sofern nicht freigeschaltet) |

**Live-Module (manuelle Fleet-QA):** `/fleet`, `/galaxy` — siehe § 11.

---

## 10. Regression-Check

| # | Prüfung | Erwartung |
|---|---------|-----------|
| 10.1 | Nach Neustart `python app.py` | Spielstand aus `game/game.db` erhalten |
| 10.2 | `/api/status` (eingeloggt) | JSON mit Ressourcen/Queues |

---

## 11. Fleet Missions (GC-525) — Manuelle Browser-QA

**Epic:** EPIC-02 Fleet System · **Nach:** GC-521–GC-524 (Ankunfts-Nachrichten, Galaxy-Prefill, Mission-Matrix, Tick-Idempotenz).

**Referenz:** [FLEET_SYSTEM.md](FLEET_SYSTEM.md), [GALAXY_SYSTEM.md](GALAXY_SYSTEM.md).

**Voraussetzung:** `python app.py` → [http://127.0.0.1:5000](http://127.0.0.1:5000), DevTools (Console + Network), eingeloggt mit **aktivem Planet** (Header-Scope).

| Vorbereitung | Zweck |
|--------------|-------|
| Shipyard + Schiffe auf Homeworld (`mule_courier`, `falcon_interceptor`, `veil_probe`, `solar_skiff`, `seed_ark`, ggf. `harvest_reclaimer`) | Senden aller Missionstypen |
| **≥ 2 eigene Kolonien** | `transport`, `collect`, `deploy` zwischen eigenen Slots |
| **Fremder belegter Slot** (anderer Spieler / Test-Account) | `spy`, `attack` |
| **Verbündeter Slot** (Alliance-Schema + Mitglied) | `hold`, Ally-`transport` |
| **Leerer Slot** | `colonize` + `seed_ark` |
| **Trümmerfeld** am Slot (`has_debris`) | `recycle` |
| Expedition-Zeile **Position 16** im aktiven System | `expedition` |

**Automatisiert (vor manueller QA):**

```bash
python -m pytest tests/test_fleet.py tests/test_galaxy.py tests/test_queue_engine.py -v
```

---

### 11.1 Ankunft vs. Rückkehr (Pflicht-Verständnis)

| Phase | Server-Status | Nachricht Posteingang | Ressourcen / Welt |
|-------|---------------|------------------------|-------------------|
| **Ziel-Ankunft** | `outbound` → `returning`, `holding` oder `completed` | **Ja** — Bericht entsteht **hier** (einmal pro `fleet_id`) | Missionseffekt (Cargo liefern, Spionage, Kampf, Kolonie, Expedition-Loot in `resources_json`, …) |
| **Rückkehr** | `returning` → `completed` | **Nein** — kein zweiter Ankunfts-/Missionsbericht für dieselbe `fleet_id` | Schiffe (+ ggf. Fracht) zurück auf **Origin**; bei `deploy`/`colonize` (ohne Rückflug) bereits bei Ankunft abgeschlossen |

**Kategorien (Filter `/messages`):**

| Mission | Kategorie (typ.) | Ankunft? | Rückkehr? |
|---------|------------------|----------|-----------|
| transport | `system` | Sender (+ ggf. Empfänger „eingehend“) | — |
| collect, recycle | `system` | Sender | — |
| deploy | `system` | Sender | — (Status `completed`) |
| spy | `espionage` | Spion | — |
| attack | `combat` | Angreifer (+ Verteidiger) | — |
| hold | `system` | Halte-Bericht | — |
| expedition | `expedition` | Expeditions-Karte | — |
| colonize | `combat` | Erfolg/Fehler-Koloniebericht | — |

**Nicht prüfen:** Dass beim Rückflug-Countdown eine *neue* Ankunftsmeldung erscheint — das wäre ein Bug (GC-521).

---

### 11.2 Galaxy-Shortcuts (Prefill)

Galaxy-Partial: `galaxy_fleet_actions.html` → Links `/fleet?target_galaxy=&target_system=&target_position=&mission=`.

| Shortcut-Kontext | Missionen im UI | QA-Schritt |
|------------------|-----------------|------------|
| Eigener Planet | transport, deploy | Link klicken → Fleet: Koordinaten + Mission vorausgewählt; Preview **ok** |
| Verbündeter Planet | transport, hold (wenn Alliance aktiv) | wie oben |
| Fremder Planet | spy, attack | wie oben; **kein** Transport-Link |
| Leerer Slot | colonize | Koordinaten + `colonize`; `seed_ark` manuell wählen |
| Expedition (Pos. **16**) | expedition | Position **16**, nicht Planet-Slot 1–15 |
| Trümmer am Slot | recycle | `recycle` + Recycler-Schiffe |

**Fleet-Seite:** `applyFleetUrlPrefill()` — nach PJAX auf `/fleet` Mission/Koordinaten noch korrekt; Mission-Dropdown nur erlaubte Missionen (`resolve-target` / Preview konsistent).

**Nur Fleet (kein Galaxy-Shortcut):** `collect` — Ziel = **eigene** Kolonie manuell setzen.

---

### 11.3 Missions-Matrix (pro Mission durchspielen)

Spalten: **F** = Start Fleet-Seite · **G** = Start Galaxy-Shortcut · **A** = Ziel-Ankunft · **M** = Nachricht Ankunft · **R** = Rückkehr/Completion.

| Mission | Zieltyp | F | G | A | M | R |
|---------|---------|---|---|---|---|---|
| **transport** | eigene / verbündete Kolonie | Cargo + Schiffe senden | Ja (own/ally) | Countdown endet; Status `returning` | `system`, Metadata `direction`: outbound/incoming | Schiffe + leere Cargo zurück Origin |
| **collect** | **eigene** Kolonie | Schiffe mit Cargo-Cap | — (manuell) | Ressourcen am Ziel sinken; Fracht in Bewegung | `system`, `mission_type`: collect | Origin erhält geladene Ressourcen **einmal** |
| **deploy** | eigene Kolonie | Schiffe (+ optional Cargo) | Ja (own) | Schiffe am Ziel; Status **`completed`** | `system`, `direction`: arrival | Kein Rückflug; Schiffe bleiben am Ziel |
| **spy** | fremd / eigen / verbündet | `veil_probe` | Ja (fremd) / F (eigen/ally) | Status `returning` | `espionage`, `fleet_id` in Metadata | Probes zurück Origin |
| **attack** | fremder Planet | Kampfschiffe | Ja (fremd) | Kampf ausgelöst; `returning` | `combat` (Angreifer/Verteidiger) | Überlebende Schiffe + Loot zurück |
| **hold** | verbündeter Planet | Hold-fähige Flotte | Ja (ally, wenn Alliance) | Status **`holding`**, `holding_until` gesetzt | `system`, Halte-Bericht | Nach Hold-Ende `returning` → dann **R** wie transport (ohne neue Ankunftsmeldung) |
| **expedition** | Pos. 16 | `solar_skiff` o. ä. | Ja (Expedition-Zeile) | Event-Roll; `returning` + Loot in State | `expedition`, Event-Card | Loot auf Origin bei **Rückkehr** (nicht doppelt bei Ankunft) |
| **colonize** | leerer Slot | `seed_ark` + Name | Ja (leer) | Neue Kolonie **oder** Fehlerbericht | `combat`, `mission_type`: colonize | Ark verbraucht; ggf. Rückflug Rest-Schiffe |
| **recycle** | Trümmerfeld | `harvest_reclaimer` | Ja (`has_debris`) | Trümmer reduziert; `returning` | `system`, recycle-Subject | Fracht bei Rückkehr auf Origin |

**Negative Checks (Matrix):**

| Schritt | Erwartung |
|---------|-----------|
| Transport auf **fremden** Planet (nur Fleet, Koordinaten manuell) | Preview/Send **blockiert** (`mission_blocked_foreign_planet`) |
| Angriff auf **eigene** Kolonie | **blockiert** (`same_origin_target` oder `mission_blocked_own_planet`) |
| Kolonisierung ohne `seed_ark` | `colonize_requires_ark` |
| Expedition auf Slot 1–15 | Preview blockiert / Position 16 erzwungen |

---

### 11.4 Ablauf je Mission (Detail-Checkliste)

Für **jede** Zeile in § 11.3:

| ID | Schritt | Erwartung |
|----|---------|-----------|
| .1 | **F:** `/fleet` — Ziel, Mission, Schiffe, Send | `POST /api/fleet/send` → `{ ok: true }`; Bewegung in Fleet-State; kein Full-Page-Reload |
| .2 | **G:** `/galaxy` — passenden Shortcut klicken (falls **G = Ja**) | Fleet öffnet mit Query-Prefill; Preview-Panel grün (`is-ok`) oder klare Block-Meldung |
| .3 | Countdown „Ankunft“ → 0 | `GET /api/fleet/state` (automatisch); Statuswechsel sichtbar |
| .4 | **A — Ziel-Ankunft** | Missionseffekt sichtbar (Ressourcen, Schiffe am Ziel, Spionage-Inhalt, Kampfbericht, …) |
| .5 | **M — Posteingang** | **Genau ein** neuer Bericht pro `fleet_id` **jetzt** (nicht erst nach Rückkehr) |
| .6 | **R — Rückkehr/Ende** | `returning` → `completed` **oder** sofort `completed` (deploy/colonize ohne Schiffe); Schiffe/Ressourcen auf Origin; **kein** zweiter Ankunftsbericht |

---

### 11.5 Regression — Idempotenz & Reload (GC-524)

Nach **erfolgreicher Ankunft** (Schritt .5 erfüllt):

| ID | Schritt | Erwartung |
|----|---------|-----------|
| R1 | `/messages` — Anzahl Berichte mit gleicher `fleet_id` (Metadata) | **1** Ankunftsbericht pro Mission |
| R2 | `/fleet` — **PJAX** zu anderer Seite und zurück **oder** Hard-Reload (F5) | Nachrichtenzahl unverändert; Fleet-State konsistent |
| R3 | DevTools → Network: `GET /api/fleet/state` **5×** hintereinander (Refresh-Button / Countdown-Expiry simulieren) | Keine zweite Ankunftsmeldung; Ressourcen/Kolonie/Loot **nicht** verdoppelt |
| R4 | Optional: Queue-Tick abwarten (`finish_due_work` / Overview-Poll) + erneut R3 | wie R3 |
| R5 | Rückflug abwarten (Countdown „Rückkehr“) | Schiffe zurück; **kein** neuer Ankunfts-/Expeditions-/Transport-Bericht für dieselbe `fleet_id` |

**Fail-Kriterium:** Zweiter identischer Bericht, doppelte Cargo am Ziel/Origin, zweite Kolonie am gleichen Slot, doppeltes Expeditions-Loot.

---

### 11.6 Ergebnis Fleet-QA

| Feld | Eintrag |
|------|---------|
| Datum / Browser / Viewport | |
| Missionen geprüft (Liste) | transport, collect, … |
| Galaxy-Shortcuts | ok / fehlgeschlagen (welcher Slot) |
| Ankunft vs. Rückkehr | ok / Bug (Beschreibung) |
| Regression R1–R5 | ok / fehlgeschlagen |
| Console-Fehler | |

---

**Ergebnis dokumentieren (gesamt):** Datum, Browser, Viewport, auffällige Fehler (Console + Screenshot).
