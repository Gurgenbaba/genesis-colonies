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

## 9. WIP-Seiten

| Route | Erwartung |
|-------|-----------|
| `/galaxy` | Gelbes „Modul in Entwicklung“-Banner |
| `/shipyard` | Platzhalter-UI, kein Backend-Crash |
| `/defense` | Platzhalter-UI |
| `/fleet` | Platzhalter-UI |
| `/alliance` | Platzhalter-UI |

---

## 10. Regression-Check

| # | Prüfung | Erwartung |
|---|---------|-----------|
| 10.1 | Nach Neustart `python app.py` | Spielstand aus `game/game.db` erhalten |
| 10.2 | `/api/status` (eingeloggt) | JSON mit Ressourcen/Queues |

---

**Ergebnis dokumentieren:** Datum, Browser, Viewport, auffällige Fehler (Console + Screenshot).
