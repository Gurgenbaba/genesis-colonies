# Queue State Rules

Verbindliche Queue-Regeln für alle zeitbasierten Jobs in Genesis Colonies. Siehe [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md), [ARCHITECTURE.md](ARCHITECTURE.md) (Queue-Engine).

---

## Geltungsbereich

| Queue | Tabelle / Modul | Scope |
|-------|-----------------|-------|
| Buildings | `build_queue` | Planet |
| Account research | `research_queue` | Spieler |
| Shipyard | `shipyard_queue` | Planet |
| Defense | `defense_queue` | Planet |
| Planet evolution | Planet research / ascension | Planet |
| Fleet | `fleet_movements` | Spieler (Tick via `process_fleet_tick`) |

Neue Systeme nutzen dieselben Regeln und `game/queue_engine.py` wo möglich.

---

## Finish Before Mutate

Vor **jeder** Mutation (enqueue, cancel, modify, reorder):

```python
finish_due_work_once(...)   # oder finish_due_work(...) in derselben Transaktion
```

Danach erst enqueue / cancel / modify.

Request-Pipeline: `refresh_player_live_state()` ruft den Finisher einmal pro Request auf; `coerce_skip_finish()` verhindert Doppel-Finish ([STATE_AJAX.md](STATE_AJAX.md)).

---

## Reschedule After Cancel

Nach **jedem** Cancel (und nach Reorder/Move): die **gesamte Restqueue** neu terminieren.

| Verboten | Pflicht |
|----------|---------|
| Alte `finish_time` / `start_time` der verbleibenden Jobs unverändert lassen | Queue vollständig neu terminieren ab `now` |

**Referenz-Implementierung:** `recalculate_queue_finish_times()` in `game/shipyard_queue.py` und `game/defense.py` (nach cancel/move).

**Build / Account-Research:** `recalculate_build_queue_finish_times()` (`game/buildings.py`) und `recalculate_research_queue_finish_times()` (`game/research.py`) — nach Cancel und vor Enqueue (GC-510).

---

## No Expired Scheduling

Neue Jobs dürfen nicht auf abgelaufenen, fälligen oder veralteten Queue-Einträgen aufbauen.

Scheduling-Muster (Build enqueue):

```text
start_time = max(now, last_finish_time_in_queue)
finish_time = start_time + duration
```

Immer nach `finish_due_work` in derselben Transaktion, damit `now` und Queue-Rows konsistent sind.

---

## Single Finish Pass pro Request

- Ein Aufruf von `finish_due_work_once` pro HTTP-Request (außer dokumentierte Admin/Cron-Pfade).
- Lesende Pfade: `skip_finish=True` nach bereits gelaufenem Refresh.
- Poll: `finish_source=game_state` — leichtgewichtig, siehe [STATE_AJAX.md](STATE_AJAX.md).

---

## APIs und State

Queue-Mutationen liefern immer frischen **`state`** (game-state payload) — siehe [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md).

Frontend zeigt Queue-Fortschritt aus `state.build_queue`, `state.research`, etc. — keine eigene Queue-Berechnung.

---

## Tests

```bash
python -m pytest tests/test_queue_engine.py tests/test_race_conditions.py tests/test_shipyard_queue.py tests/test_queue_static_contract.py -v
```

Manuelle Abnahme: [GC-512_QUEUE_MANUAL_QA.md](GC-512_QUEUE_MANUAL_QA.md).

Pflicht-Szenarien pro Queue-Typ:

- enqueue bei voller Queue → Fehler
- cancel mittlerer Job → Restzeiten konsistent (wenn Reschedule implementiert)
- finish bei `finish_time <= now`
- Race: parallele enqueue/cancel
- near-finish enqueue (Job startet Sekunden vor Finish des Vorgängers)
- POST-Action → `json.state` enthält aktualisierte Queue
