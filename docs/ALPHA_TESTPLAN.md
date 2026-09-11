# Genesis Colonies — Alpha Testplan (manuell)

**Voraussetzung:** `python app.py` läuft auf [http://127.0.0.1:5000](http://127.0.0.1:5000)

Bestehende `game/game.db` **nicht löschen**, wenn du einen vorhandenen Spielstand testen willst.

**Spieler-Journey (empfohlen vor technischer Regression):** [GC-621 — First 30 Minutes](GC-621_FIRST_30_MINUTES.md) — frischer Account, Minute 0–15, „Will ich wiederkommen?“

---

## 1. Auth

| # | Schritt | Erwartung |
|---|---------|-----------|
| 1.1 | `/register` — neuen Commander anlegen | Erfolg, Redirect zu Übersicht | - klappt
| 1.2 | Logout → `/login` mit neuem Account | Login ok | - klappt
| 1.3 | Falsches Passwort | Fehlermeldung, kein Crash | - klappt

---

## 2. Übersicht (`/overview`)

| # | Schritt | Erwartung |
|---|---------|-----------|
| 2.1 | Seite laden | Ferronit, Crytite, Energie sichtbar | - klappt
| 2.2 | 10–15 s warten (Polling) | Ressourcenwerte aktualisieren sich | - klappt
| 2.3 | Gebäude-Tabelle | Mindestens Minen + Solar sichtbar | - klappt

---

## 3. Gebäude (`/buildings`)

| # | Schritt | Erwartung |
|---|---------|-----------|
| 3.1 | Tab „Ressourcen“ | Gebäudeliste lädt | - klappt
| 3.2 | Upgrade starten (wenn Ressourcen reichen) | Kompaktstatus oben (`🏗 N Bauaufträge`); aktiver Job in der Gebäude-Card | - klappt
| 3.3 | Countdown / Fortschrittsbalken | Nur in der Card — läuft ohne Reload | - klappt

**Queue-Regression (GC-512):** Vollständige Checkliste [GC-512_QUEUE_MANUAL_QA.md](GC-512_QUEUE_MANUAL_QA.md) (Cancel active/middle/last, near-finish, PJAX, Planetwechsel).

---

## 4. Forschung (`/research`)

| # | Schritt | Erwartung |
|---|---------|-----------|
| 4.1 | Tech-Liste | Einträge mit Kosten/Zeit | - klappt
| 4.2 | Forschung starten | Kompaktstatus oben; aktiver Job in der Tech-Card | - klappt
| 4.3 | Zweite Forschung anreihen | QUEUE #2 in passender Card, kein oberes Queue-Panel | - klappt

Siehe auch [GC-512_QUEUE_MANUAL_QA.md](GC-512_QUEUE_MANUAL_QA.md) § B.

---

## 4b. Queue Card UX — global (GC-536F / GC-UNIT-QUEUE-DEDUP-001)

Manuelle QA über alle Queue-Seiten. Kein großes Queue-Panel mehr.

| # | Seite | Schritt | Erwartung |
|---|-------|---------|-----------|
| Q1 | `/buildings` | Bau starten | Mini-Strip: AKTIV + Timer + Progress + ⚡; Card nur Katalog-Dauer + in-queue | - klappt
| Q2 | `/research` | 2. Tech anreihen | Mini-Strip aktualisiert; Tech-Card ohne Live-Timer/Footer-Dauer-Duplikat | - klappt
| Q3 | `/shipyard` | Schiff bauen | **Nur** zentrale Mini-Bauschleife oben (Menge, Timer, Progress, ⚡, Abbrechen); Schiff-Card ohne Queue-UI | - klappt
| Q3b | `/defense` | Verteidigung bauen | **Nur** zentrale Mini-Bauschleife oben; Defense-Card ohne Queue-UI | - klappt
| Q3c | `/shipyard` oder `/defense` | Timekeeper ⚡ | ⚡ nur in der oberen Bauschleife (aktiver Job); nach Apply sofort ohne Reload | - klappt
| Q4 | `/planet_evolution` | Planet-Tech starten | Live nur in `#pe-planet-tech-queue-list`; Tech-Card ohne `data-gc-card-queue` | - klappt
| Q5 | `/planet_evolution` | Ascension (Stufe ≥25) | Live in `#pe-ascension-queue-list`; Ascension-Card ohne Queue-Block; Kompaktstatus | - klappt
| Q6 | PJAX | Buildings → Research → Shipyard | Keine doppelte Unit-Queue in Cards nach Navigation | - klappt
| Q7 | Mobile 390px | Alle vier Seiten | Kein horizontaler Overflow; Mini-Strip / Cards umbrechen sauber | - klappt
| Q8 | Cancel | Job in Mini-Strip / PE-Liste abbrechen | Nächster Job wird aktiv ohne Reload; Item-Cards bleiben queue-frei | - klappt

Referenz: [GC-536_QUEUE_CARD_UX.md](GC-536_QUEUE_CARD_UX.md) · [GC-512_QUEUE_MANUAL_QA.md](GC-512_QUEUE_MANUAL_QA.md) F1–F5

---

## 5. Ranking (`/ranking`)

| # | Schritt | Erwartung |
|---|---------|-----------|
| 5.1 | Seite öffnen | Tabelle mit Spielern | - klappt
| 5.2 | Eigener Eintrag | Score sichtbar (wenn vorhanden) | - klappt

---

## 6. Admin (`/admin`) — nur mit Admin-Account

| # | Schritt | Erwartung |
|---|---------|-----------|
| 6.1 | Panel öffnen | Universe-Settings sichtbar | - klappt
| 6.2 | MOTD setzen (optional) | Banner auf Ingame-Seiten | - klappt
| 6.3 | **Kein Wipe** während Demo | Daten bleiben erhalten | - klappt

---

## 7. Mobile (390×844 — DevTools)

| # | Schritt | Erwartung |
|---|---------|-----------|
| 7.1 | `/overview` | Bottom-Nav sichtbar | - Broke
| 7.2 | Scrollen | Ressourcenleiste bleibt oben kleben | - Broke
| 7.3 | Bottom-Nav: Gebäude, Forschung | Navigation funktioniert | - Broke
| 7.4 | „Mehr“ → Drawer | Öffnet/schließt smooth | - Broke
| 7.5 | Kein horizontaler Page-Scroll | Nur Tabellen innerhalb Scroll-Container | - Broke

---

## 8. Desktop (1440×900)

| # | Schritt | Erwartung |
|---|---------|-----------|
| 8.1 | Sidebar links | Alle Nav-Links sichtbar | - klappt
| 8.2 | Keine Bottom-Nav | Nur Mobile-Layout | - klappt
| 8.3 | Zwei-Spalten-Grids | Overview/Research ok | - klappt

---

## 9. WIP / Platzhalter

| Route | Erwartung |
|-------|-----------|
| `/alliance` | Platzhalter-UI (sofern nicht freigeschaltet) | - Freigeschaltet schon!

---

## 9b. Defense (`/defense`) — Live

**Referenz:** [DEFENSE_SYSTEM.md](DEFENSE_SYSTEM.md) · GC-600 ✅

| # | Schritt | Erwartung |
|---|---------|-----------|
| 9b.1 | Seite laden | Fabrik-Stufe, Queue, Bestand, baubare/gesperrte Karten sichtbar | - klappt
| 9b.2 | Einheit bauen (wenn Ressourcen reichen) | Queue + Countdown ohne Full-Page-Reload | - klappt
| 9b.3 | Cancel aktiver Job | 60 % Erstattung; Restqueue neu terminiert (GC-510) | - klappt
| 9b.4 | Planetwechsel (Header) | `/defense` PJAX-Reload; `data-planet-id` = aktiver Planet | - klappt

**Automatisiert (optional vor manueller QA):**

```bash
python -m pytest tests/test_defense_detail_modal.py tests/test_queue_engine.py -v -k "defense"
```

**Live-Module (manuelle QA):** `/defense`, `/fleet`, `/galaxy`, `/logistics` — Fleet siehe § 11–12.

---

## 10. Regression-Check

| # | Prüfung | Erwartung |
|---|---------|-----------|
| 10.1 | Nach Neustart `python app.py` | Spielstand aus `game/game.db` erhalten | - klappt
| 10.2 | `/api/status` (eingeloggt) | JSON mit Ressourcen/Queues | - klappt

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
| **Rückkehr** | `returning` → `completed` | **Nein** für Transport/Recycle/Deploy/… — **Ausnahme Logistics Collect/Distribute** (siehe § 12) | Schiffe (+ ggf. Fracht) zurück auf **Origin**; bei `deploy`/`colonize` (ohne Rückflug) bereits bei Ankunft abgeschlossen |

**Kategorien (Filter `/messages`):**

| Mission | Kategorie (typ.) | Ankunft? | Rückkehr? |
|---------|------------------|----------|-----------|
| transport | `system` | Sender (+ ggf. Empfänger „eingehend“) | — |
| collect (Einzel + Bulk) | `system` | `logistics_collect_arrival` an Quelle; `logistics_collect_return` am Hub (wenn Fracht) | Rückkehrbericht nur Collect |
| recycle | `system` | Sender | — |
| distribute (Bulk) | `system` | `logistics_distribute_arrival` je Ziel; optional `logistics_distribute_return` (Schiffe, keine Lieferung) | Rückkehr ≠ zweite Lieferung |
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
| R3a | (Automatisiert GC-532) `test_api_fleet_state_five_calls_outbound_arrival_idempotent` | wie R3 |
| R4 | Optional: Queue-Tick abwarten (`finish_due_work` / Overview-Poll) + erneut R3 | wie R3 |
| R5 | Rückflug abwarten (Countdown „Rückkehr“) | Schiffe zurück; **kein** neuer Ankunfts-/Expeditions-/Transport-Bericht für dieselbe `fleet_id` (Logistics: siehe § 12.5) |

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

## 12. Fleet Logistics (GC-531) — Manuelle Browser-QA

**Epic:** EPIC-02 Fleet System · **Nach:** GC-526–530 (Bulk Collect/Distribute, Route-Builder, UI, Logistics-Reports).

**Referenz:** [FLEET_SYSTEM.md § Fleet Logistics](FLEET_SYSTEM.md#fleet-logistics-gc-526531), [GC-900_LOGISTICS.md](GC-900_LOGISTICS.md).

**Voraussetzung:** wie § 11, zusätzlich:

| Vorbereitung | Zweck |
|--------------|-------|
| **≥ 3 eigene Kolonien** (idealerweise **2+ Galaxien/Systeme**) | Collect/Distribute mit 2–3 Zielen, Galaxy-Kompatibilität |
| Hub-Planet mit **`mule_courier`** (oder anderem `role: cargo`) | Cargo-only-Regel |
| Quell-/Ziel-Kolonien mit **Metal/Crystal** (Collect) bzw. Hub mit Fracht (Distribute) | Sichtbarer Ressourcenfluss |
| Freie **Fleet-Slots** ≥ Anzahl gewählter Ziele | `fleet_slots_full` vermeiden |

**Automatisiert (vor manueller QA):**

```bash
python -m pytest tests/test_fleet.py -k "logistics or collect_creates_report or distribute" -v
```

---

### 12.1 Logistics-Matrix (Übersicht)

| Flow | UI-Tab | Hub-Feld | Ziele | Schiffe | Ressourcen | Slot-Verbrauch | Bericht Ankunft | Bericht Rückkehr |
|------|--------|----------|-------|---------|------------|----------------|-----------------|------------------|
| **Collect** | Collect | Hub (`data-logistics-hub`) | 2–3 **Quell**-Kolonien (≠ Hub) | Cargo-only, Split auf Quellen | Modus **all** | 1 Slot × Quelle | `logistics_collect_arrival` je Leg | `logistics_collect_return` am Hub (Fracht > 0) |
| **Distribute** | Distribute | Hub (`data-logistics-origin`) | 2–3 **Ziel**-Kolonien (≠ Hub) | Cargo-only, Split auf Ziele | **equal** oder **custom** | 1 Slot × Ziel | `logistics_distribute_arrival` je Leg | `logistics_distribute_return` (nur Schiffe, keine Liefermenge) |

**Negative Checks:**

| Schritt | Erwartung |
|---------|-----------|
| Nur Kampfschiffe (`falcon_interceptor`) | Preview/Send blockiert (`no_cargo_ships`) |
| Mehr Legs als freie Slots | `fleet_slots_full` |
| Distribute: Fracht > Cargo der Leg | `not_enough_cargo` |
| Hub in Quell-/Zielliste | Planet aus Liste ausgeschlossen / Validierung `no_planets` |

---

### 12.2 Collect — 2–3 Kolonien

| ID | Schritt | Erwartung |
|----|---------|-----------|
| C1 | `/logistics` → Tab **Collect**; Hub = aktiver Planet | Kolonienliste ohne Hub; Preview zeigt **N Legs** (N = Anzahl Quellen) |
| C2 | **2 Quellen** wählen, `mule_courier` ×2, Submit | `POST /api/fleet/logistics/collect` → `{ ok: true, state }`; **2** Bewegungen `mission=collect`, Batch `collect_resources`; kein Full-Reload |
| C3 | Ankunft Leg 1 (Countdown → 0) | Ressourcen an **Quelle 1** sinken; Posteingang: **1×** `logistics_collect_arrival` für diese `fleet_id` |
| C4 | Ankunft Leg 2 | wie C3 für Quelle 2; **getrennte** `fleet_id` pro Leg |
| C5 | Rückkehr beider Legs | Hub erhält Fracht **einmal**; je Leg **1×** `logistics_collect_return` (Metadata `origin_planet_id` = Hub) |
| C6 | **3 Quellen** wiederholen (wenn Slots reichen) | 3 Bewegungen; Schiffs-Split: Rest auf letzte Quelle (z. B. 5 Courier → 2+2+1) |

---

### 12.3 Distribute — 2–3 Kolonien

| ID | Schritt | Erwartung |
|----|---------|-----------|
| D1 | Tab **Distribute**; Hub mit Metal/Crystal; **equal**-Modus | Preview: Summe / Leg-Aufteilung serverseitig; Cargo-Cap ok |
| D2 | **2 Ziele**, Submit | Hub-Ressourcen debitiert; **2×** `transport`-Legs, Batch `distribute_resources` |
| D3 | Ankunft Ziel 1 | Ziel-Planet Metal/Crystal steigt; **1×** `logistics_distribute_arrival` mit gelieferter Menge in Metadata |
| D4 | Ankunft Ziel 2 | wie D3; **kein** gemeinsamer Bericht für beide Legs |
| D5 | Rückkehr | `logistics_distribute_return`: Schiffe im Text/Metadata; **keine** erneute Liefermenge (`resources` leer) |
| D6 | **custom** (`target_resources` unterschiedlich) auf 2–3 Ziele | Preview/Send ok; Ziele erhalten unterschiedliche Mengen (≤ Storage-Cap metal/crystal) |
| D7 | Ziel fast voll (metal cap) | Ankunft liefert nur bis Headroom; Bericht zeigt **tatsächlich** gelieferte Menge |

---

### 12.4 Planetwechsel

| ID | Schritt | Erwartung |
|----|---------|-----------|
| P1 | Hub-Kolonie A aktiv → Collect planen | Preview-Origin = A |
| P2 | Header: aktiven Planet auf **B** wechseln (`GC` planet switch / Overview) | `/logistics` neu laden oder PJAX: Hub-Select = **B**; Quellliste nur eigene Planeten ≠ B |
| P3 | Distribute von **B** starten | Schiffe von B `planet_ships`; Bewegungen `origin_planet_id = B` |
| P4 | Laufende Collect-Legs von A | Timer/Bewegungen unverändert; **kein** Scope-Bug (Fracht landet weiter auf A-Hub) |

---

### 12.5 Galaxy-Kompatibilität & Idempotenz

| ID | Schritt | Erwartung |
|----|---------|-----------|
| G1 | Quellen/Ziele in **verschiedenen Systemen/Galaxien** (falls Save das hat) | Preview zeigt Flugzeiten/Distanz; Send ok; keine Client-Fehler |
| G2 | `/galaxy` — eigene entfernte Kolonie identifizieren | Koordinaten konsistent mit Logistics-Planetliste (gleiche `planet_id`) |
| G3 | Nach **erfolgreicher Ankunft** Leg: `/messages` filtern | Pro `fleet_id` + `report_phase`: **genau 1** Ankunftsbericht |
| G4 | `GET /api/fleet/state` **5×** oder Countdown-Expiry + erneuter Tick | Kein zweiter `logistics_*_arrival` für dieselbe Leg |
| G4a | (Automatisiert GC-532) `test_api_fleet_state_five_calls_outbound_arrival_idempotent`, `test_logistics_*_double_tick_*` | wie G4 |
| G5 | Nach Rückkehr: R1–R4 aus § 11.5 auf Collect-Return / Distribute-Return | Return-Phase dedupliziert; **kein** doppeltes Crediting am Hub/Ziel |

**Fail-Kriterium:** Doppelter Bericht gleicher `report_phase`, doppelte Lieferung/Abholung, Hub-Fracht nach einem Rückkehr-Tick verdoppelt.

---

### 12.6 Ergebnis Logistics-QA

| Feld | Eintrag |
|------|---------|
| Datum / Browser / Viewport | |
| Collect C1–C6 | ok / fehlgeschlagen |
| Distribute D1–D7 | ok / fehlgeschlagen |
| Planetwechsel P1–P4 | ok / fehlgeschlagen |
| Galaxy G1–G2 | ok / n/a |
| Idempotenz G3–G5 | ok / fehlgeschlagen |
| Console-Fehler | |

---

**Ergebnis dokumentieren (gesamt):** Datum, Browser, Viewport, auffällige Fehler (Console + Screenshot).

---

## 13. Production Infinity-Load Regression (automatisiert)

Nach dem Incident 2026-08-29 ([Incident-Report](incidents/2026-08-29-production-infinity-load.md)):

| # | Schritt | Erwartung |
|---|---------|-----------|
| 13.1 | `pytest tests/test_gc_prod_infinity_load_ab.py -q` | Gates grün (EXPLAIN + wiederholte `/api/game-state`) |
| 13.2 | Optional lokal: `python scripts/prod_infinity_load_ab.py --scales baseline,10x` | A/B Worktrees A=`9027ec0` B=`b0fade84` C=`7f3990b` ohne Multi-Sekunden-Outliers; Report unter `artifacts/prod_infinity_load_ab/` |
| 13.3 | Manuell: eingeloggt 2–3 Min Overview/Fleet pollen | Kein Infinity-Load; `/api/game-state` bleibt responsiv |
