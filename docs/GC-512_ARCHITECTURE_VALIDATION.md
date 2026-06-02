# GC-512 — Architecture Validation Pass (GC-000)

Einmal das **gesamte Spiel** gegen [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) prüfen — **bevor** Defense, Combat, Recycler.

**Bereits erledigt (Commit `7a3ccc2`):**

- Verfassung + Verträge + pytest-Guards
- Build/Research Queue Reschedule (GC-510)
- Queue-Manual-QA: [GC-512_QUEUE_MANUAL_QA.md](GC-512_QUEUE_MANUAL_QA.md)
- Static Queue-Contracts: `tests/test_queue_static_contract.py`

**Dieses Dokument:** Modul-Matrix für den **vollständigen** Architektur-Audit.

---

## Prüfschema (pro Modul)

| # | Frage | Verstoß wenn … |
|---|--------|----------------|
| R1 | **Reloads?** | `location.reload()` / `location.href =` für Ingame-Nav |
| R2 | **Eigene Wahrheit?** | Client berechnet Mechanik (Ressourcen, Queue, Fleet, Kampf) |
| R3 | **Eigenes Spiel-Polling?** | Zweites `/api/game-state` oder paralleler „Live-State“ |
| R4 | **Eigenes Queue-Verhalten?** | Cancel ohne Reschedule / ohne `finish_due_work` |
| R5 | **Planet Scope?** | Session-Planet, Homeworld-Hardcode, falscher `planet_id` |
| R6 | **AJAX Contract?** | POST ohne `{ ok, state }` + `applyActionState()` |

**Legende:** ✅ ok · ⚠️ Ausnahme dokumentiert · 🔍 manuell prüfen · ❌ Fix-Ticket

---

## Modul-Matrix (Code-Voraudit)

Stand: nach `7a3ccc2`. Browser-Spalte **Manuell** erst nach Durchlauf ausfüllen.

| Modul | Owner | R1 Reload | R2 Wahrheit | R3 Polling | R4 Queue | R5 Scope | R6 AJAX | Manuell |
|-------|-------|-----------|-------------|------------|----------|----------|---------|---------|
| **Overview** | `overview_page.py` / `main.js` | ✅ PJAX | ✅ game-state | ✅ Singleton | — | ✅ context | ✅ | 🔍 |
| **Buildings** | `buildings.py` | ✅ | ✅ | ✅ | ✅ GC-510 | ✅ | ✅ cancel/upgrade | 🔍 [Queue-QA](GC-512_QUEUE_MANUAL_QA.md) §A |
| **Research** | `research.py` | ✅ | ✅ | ✅ | ✅ GC-510 | ✅ | ✅ | 🔍 §B |
| **Trader Hub** | `exchange.py`, … | ✅ | ✅ | ✅ | — | ✅ | 🔍 trade POST | 🔍 |
| **Shipyard** | `shipyard_queue.py` | ✅ | ✅ | ⚠️ `/api/shipyard` Intervall (kein game-state; Seiten-Snapshot) | ✅ recalculate | ✅ | ✅ applyActionState | 🔍 |
| **Fleet** | `fleet.py` | ✅ | ✅ | ⚠️ `/api/fleet/state` auf Fleet-Seite | ✅ engine | ✅ origin | ✅ send | 🔍 |
| **Galaxy** | `galaxy.py` | ✅ | ✅ | ✅ | — | ✅ mark active | ✅ GET | 🔍 |
| **Messages** | `messages.js` | ⚠️ `navigateTo` else `href` | ✅ | ✅ (kein game-state) | — | — | 🔍 | 🔍 |
| **Chat** | `chat.js` | ✅ | ✅ | ⚠️ `/api/chat/*` (GC-000 Ausnahme) | — | — | ✅ | 🔍 |
| **Planet Evolution** | `planet_evolution/` | ✅ `reloadCurrentPage` | ✅ | ✅ | ✅ planet research | ✅ URL+owner | ⚠️ teils `reloadCurrentPage` statt nur `state` | 🔍 |
| **Planet Switcher** | `repository.py` | ✅ | ✅ | ✅ | — | ✅ `active_planet_id` | ✅ `/api/planets/active` | 🔍 §C |
| **Ranking** | `ranking.py` | ✅ | ✅ | ✅ | — | — | ✅ read-only | 🔍 |
| **Alliance** | `alliance.py` | ✅ | ✅ | ✅ | — | 🔍 | 🔍 minimal | 🔍 |

---

## Manuelle Durchlauf-Reihenfolge

1. `python -m pytest tests/test_queue_static_contract.py tests/test_core_architecture_enforcement.py -v`
2. DevTools: Network (`game-state`, `fetch`), Console (Errors, Timer)
3. Pro Modul 5–10 Min — Tabelle **Manuell** auf ✅ oder Ticket

### Querschnitt (alle Module)

| ID | Schritt | Erwartung |
|----|---------|-----------|
| X1 | Nav Overview → Buildings → Research → Fleet → Galaxy → zurück | Kein Document-Reload; Shell bleibt |
| X2 | Während Queue: Planet wechseln | Scope korrekt; [GC-512_QUEUE_MANUAL_QA.md](GC-512_QUEUE_MANUAL_QA.md) §C |
| X3 | Während Queue: PJAX wechseln | §D; ein game-state-Rhythmus |
| X4 | POST-Aktion (Bau, Trade, Fleet send) | Response mit `state`; UI sofort aktualisiert |
| X5 | 2 Min warten | Keine negativen Timer; kein Progress-Flackern |

---

## Bekannte Follow-ups (nach Audit ggf. Tickets)

| Thema | Regel | Vorschlag |
|-------|-------|-----------|
| Planet Evolution POST → `reloadCurrentPage` | R6 | Auf `applyActionState` + partielles DOM umstellen |
| Shipyard/Fleet Seiten-Poll | R3 | Dokumentieren oder in game-state integrieren (nur wenn sinnvoll) |
| Messages `href`-Fallback | R1 | Nur No-JS; sonst entfernen |

Kein neues System vor grünem Audit.

---

## Abnahme

| Bereich | Static pytest | Manuell |
|---------|---------------|---------|
| GC-000 Guards | ☐ `test_core_architecture_enforcement` | — |
| Queue Contracts | ☐ `test_queue_static_contract` | ☐ [Queue-QA](GC-512_QUEUE_MANUAL_QA.md) |
| Modul-Matrix | — | ☐ alle Zeilen **Manuell** = ✅ |
| Querschnitt X1–X5 | — | ☐ |

**Wenn alles grün:** Roadmap → Defense → Combat → Recycler (auf stabilem Fundament).

---

## Referenzen

- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) — Regeln 1–17
- [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md)
- [QUEUE_STATE_RULES.md](QUEUE_STATE_RULES.md)
- [PLANET_SCOPE.md](PLANET_SCOPE.md)
- [ROADMAP.md](ROADMAP.md)
