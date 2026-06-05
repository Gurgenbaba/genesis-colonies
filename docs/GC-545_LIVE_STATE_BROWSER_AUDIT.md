# GC-545 – Live-State Browser Audit



**Epic:** STATE / PJAX / Live-Updates  

**Status:** ✅ Abgeschlossen (2026-06-05) — pytest + Browser-Matrix  

**Follow-up:** [GC-546 Live-State Fixes](GC-546_LIVE_STATE_FIXES.md) (546A–546E)



Automatische Tests (`test_static_live_updates`, Queue-Timer-Regression): **41 passed**. Browser-Audit lieferte **echte Findings** — Production Completion Layer, nicht Queue-Backend.



---



## Tests (Regression)



```bash

python -m pytest tests/test_static_live_updates.py tests/test_game_state_live.py -v

```



**Ergebnis 2026-06-05:** `41 passed` in ~220s.



---



## Flow-Matrix (Browser)



| Flow | Status | Notiz |

|------|--------|-------|

| **Build** | 🟠 | Queue ok; **Voraussetzungen** nach Finish stale bis Reload → F2 |

| **Research** | ✅ | Countdown/Finish ohne Blocker |

| **Shipyard** | 🔴 | Fertig, **Stückzahl stale**; Latenz/499 nach Completion → F3, F5 |

| **Defense** | 🔴 | Wie Shipyard (gleiche Completion-Architektur) → F4, F5 |

| **Fleet** | ✅ | Senden, Nachrichten — funktioniert |

| **Messages** | 🟠 | Lesen: **Badge bleibt** bis erneutes Öffnen → F6 |

| **Galaxy** | ✅ | Voll funktional |

| **Planet Evolution** | ✅ | Soweit ok — Balance/QA offen (GC-613) |

| **Ranking / Score HUD** | 🔴 | Delta **mehrfach** gerendert (+16.347×3) → F1 |



---



## Reifegrad — vor / nach Browser-QA



| System | Vor GC-545 (GC-610 Schätzung) | Nach Browser-QA |

|--------|-------------------------------:|----------------:|

| Buildings | 95 % | **90 %** (F2 Requirements) |

| Research | 90 % | **90 %** |

| Shipyard | 80 % | **70 %** (F3, F5) |

| Defense | 75 % | **65 %** (F4, F5) |

| Fleet | 80 % | **85 %** (positiv) |

| Galaxy | 70 % | **90 %** (positiv) |

| Planet Evolution | 70 % | **85 %** (positiv) |

| Messages | 85 % | **75 %** (F6) |

| Ranking | 85 % | **70 %** (F1) |



**Tier-1-Aggregat:** ~74 % (Schätzung) → **~78 %** nach positiven Galaxy/Fleet/Evolution, aber **Production Layer zieht Shipyard/Defense runter**.



---



## Findings (Browser-Beweis)



| ID | Schwere | Titel | Systeme |

|----|---------|-------|---------|

| **F1** | 🔴 Hoch | Punkte mehrfach gerendert (`+16.347` × n) | Ranking, Header, Delta |

| **F2** | 🟠 Mittel | Gebäude-Voraussetzungen nicht live nach Finish | Buildings |

| **F3** | 🔴 Hoch | Werft: Stückzahl nach Fertigstellung stale | Shipyard |

| **F4** | 🔴 Hoch | Defense: identisch Shipyard | Defense |

| **F5** | 🔴 Sehr hoch | Poll Storm / HTTP 499, 56s–85s Latenz nach Werft/Defense | Shipyard, Defense, game-state |

| **F6** | 🟠 Mittel | Nachricht gelesen, Badge bleibt | Messages, Shell HUD |



Details + Ticket-Zuordnung: [GC-546_LIVE_STATE_FIXES.md](GC-546_LIVE_STATE_FIXES.md)



---



## Root Cause (Epic-Ebene)



**Production Completion Layer** — nach Queue-Finish:



1. Client patcht Inventory/Requirements/Badge nicht zuverlässig

2. Möglicher **Request-Sturm** (F5) verschlimmert oder verursacht stale UI (F3/F4)

3. Score-Delta und Messages sind **Nebenpfade** desselben State-Sync-Problems



Nicht: Fleet-Missions, Galaxy, Evolution-Backend.



---



## GC-546 Zerlegung



| Ticket | Prio | Inhalt |

|--------|------|--------|

| **GC-546D** | 1 | Poll Storm Analyse/Fix |

| **GC-546C** | 2 | Shipyard + Defense Completion Refresh |

| **GC-546E** | 3 | Message Read / Badge |

| **GC-546B** | 4 | Building Requirements Live |

| **GC-546A** | 5 | Score Delta Dedup |



---



## Akzeptanzkriterien GC-545



- [x] Flow-Blöcke dokumentiert (Build, Research, Shipyard, Defense, Fleet, Messages + Galaxy/Evolution/Ranking)

- [x] Findings F1–F6 mit Schweregrad

- [x] Reifegrad-Tabelle vor/nach Browser

- [x] GC-546 Epic-Zerlegung (546A–E), **546D zuerst**

- [x] Kein Code-Fix in GC-545 (Doc only)



---



## Referenz-Docs



- [GC-546_LIVE_STATE_FIXES.md](GC-546_LIVE_STATE_FIXES.md)

- [GC-610_COMPLETE_DEFINITION_AUDIT.md](GC-610_COMPLETE_DEFINITION_AUDIT.md)

- [STATE_AJAX.md](STATE_AJAX.md)

- [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md)



---



## Ausgabe



### Root Cause



Production Completion Layer: Shipyard/Defense Completion + Poll-Lifecycle; sekundär Buildings Requirements, Messages Badge, Score Delta.



### Changed Files



`docs/GC-545_LIVE_STATE_BROWSER_AUDIT.md`, `docs/GC-546_LIVE_STATE_FIXES.md`, GC-610 Reifegrad-Update



### Tests



pytest 41 passed; Browser-Findings manuell.



### Ergebnis



**GC-546 abgeschlossen** — F1–F6 adressiert (546A–546E). Browser F1 kurz bestätigen.


