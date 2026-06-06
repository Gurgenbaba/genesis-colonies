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

## Kanonische Bauschleifen-Regel (Timer-Anzeige)

Verbindlich für **alle** Queue-Systeme (Gebäude, Forschung, Werft, Verteidigung, Planet Evolution, zukünftige Queues). Server berechnet Zeiten; UI zeigt nur Serverwerte ([STATE_AJAX.md](STATE_AJAX.md)).

### Sofort sichtbar

Jeder Auftrag erscheint **unmittelbar nach Start** in der jeweiligen Bauschleife (Card-Queue + Kompaktstatus) — ohne manuellen Reload. Actions liefern `{ ok, state }`; `applyActionState()` patcht alle betroffenen Panels.

### Timer pro Position

| Position | Anzeige |
|----------|---------|
| **Aktiver Job** (Queue-Position 1) | Echte verbleibende Restzeit bis `finish_at` |
| **Wartende Jobs** (Position ≥ 2) | `finish_at − now` = Restzeit aller Vorgänger **plus** eigene Bauzeit |

**Beispiel:** Job 1 noch 4 s · Job 2 dauert 12 s → Job 2 zeigt **16 s**. Nach Abschluss von Job 1: Job 1 verschwindet sofort, Job 2 wird aktiv und zeigt nur noch seine echte Restzeit; nachfolgende Jobs rücken nach.

Kanonisches Card-Feld: `remaining_seconds` aus `game/queue_card.py` — wartende Jobs **nie** nur `start_at − now`.

### Unit-Queues (serieller Auftrag)

Schiffsbau, Verteidigungsbau und alle zukünftigen **Unit-Queues** bauen pro Auftrag **seriell**:

```text
Auftragsdauer = amount × Bauzeit_pro_Einheit
```

**Beispiel:** 1 Schiff = 5 s, Menge 100 → Auftrag = **500 s** in der Queue. Ein danach eingereihter Auftrag addiert dessen Anzeige: `Rest_vorherige_Aufträge + eigene_Auftragsdauer`.

Verboten: UI zeigt nur die Einzel-Einheit-Zeit (z. B. 5 s), während der Auftrag 500 s blockiert.

Referenz: `order_total_seconds` / `order_remaining` in `game/shipyard_queue.py`, `game/defense.py`; Card-Adapter `map_shipyard_queue_to_card_jobs`, `map_defense_queue_to_card_jobs`.

### Live-State / DOM

- Monotone Timer (`data-server-remaining`) **nur** für denselben aktiven Job (`job_id` + `finish_at` unverändert).
- Wechsel von `job_id`, Status (queued→active), `finish_at`, `start_at`, Position oder Menge → Block **neu rendern**, keinen alten DOM-State übernehmen.
- Countdown 0 → zentraler Refresh ([STATE_AJAX.md](STATE_AJAX.md)); leere Queue → Card-Block entfernen.

---

## Single Finish Pass pro Request

- Ein Aufruf von `finish_due_work_once` pro HTTP-Request (außer dokumentierte Admin/Cron-Pfade).
- Lesende Pfade: `skip_finish=True` nach bereits gelaufenem Refresh.
- Poll: `finish_source=game_state` — leichtgewichtig, siehe [STATE_AJAX.md](STATE_AJAX.md).

---

## APIs und State

Queue-Mutationen liefern immer frischen **`state`** (game-state payload) — siehe [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md).

Frontend zeigt Queue-Fortschritt aus `state.build_queue`, `state.research`, etc. — keine eigene Queue-Berechnung.

### Presentation (GC-536A ✅)

Queue-**Logik** bleibt in `game/queue_engine.py` und den Domänen-Ownern. Queue-**UX** wandert in Item-Cards — siehe [GC-536_QUEUE_CARD_UX.md](GC-536_QUEUE_CARD_UX.md).

- Kanonisches Card-Job-Format: `game/queue_card.py` (Presentation-Adapter, **keine zweite Queue**)
- GC-536A: Adapter + Tests + JS-Stub
- GC-536B–F: Cards produktiv; Kompaktstatus oben, Legacy-Panels entfernt (✅)

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
