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

Jeder Auftrag erscheint **unmittelbar nach Start** in der jeweiligen Bauschleife — ohne manuellen Reload. Actions liefern `{ ok, state }`; `applyActionState()` → `syncMountedQueuePagesFromState` / `patchQueuePanelsImmediate` patcht alle betroffenen Panels. Diet-Polls aktualisieren ebenfalls gemountete Queue-Pages (analog Fleet-Sync).

| Queue-Art | Presentation |
|-----------|----------------|
| Gebäude / Forschung / Planet Evolution | Job in zugehöriger Item-Card (+ Mini-Strip oben wo vorhanden) |
| **Unit-Queues** (Shipyard, Defense) | **Nur** zentrale Mini-Bauschleife oben (`#shipyard-mini-queue` / `#defense-mini-queue`) — **keine** Queue-UI in Unit-Cards (GC-UNIT-QUEUE-DEDUP-001) |

**Timekeeper ⚡ (eine pro Job):** nur Mini-Bauschleife (Build/Research/Shipyard/Defense) bzw. PE-Queue-Listen — **kein** zweites Boost auf Hero/Tech-Card.

### Timer pro Position

| Position | Anzeige |
|----------|---------|
| **Aktiver Job** (Queue-Position 1) | Echte verbleibende Restzeit bis `finish_at` |
| **Wartende Jobs** (Position ≥ 2) | `finish_at − now` = Restzeit aller Vorgänger **plus** eigene Bauzeit |

**Beispiel:** Job 1 noch 4 s · Job 2 dauert 12 s → Job 2 zeigt **16 s**. Nach Abschluss von Job 1: Job 1 verschwindet sofort, Job 2 wird aktiv und zeigt nur noch seine echte Restzeit; nachfolgende Jobs rücken nach.

Kanonisches Card-Feld: `remaining_seconds` aus `game/queue_card.py` — wartende Jobs **nie** nur `start_at − now`.

### Unit-Queues (Batch-Kapazität)

Schiffsbau, Verteidigungsbau und alle zukünftigen **Unit-Queues** nutzen die **Werft-Batch-Kapazität** (nicht `amount × unit_time`):

```text
cycles = ceil(amount / capacity)
Auftragsdauer = cycles × unit_seconds
```

Owner: `production_job_duration_seconds` / `production_live_order_remaining_seconds` in `game/shipyard.py`.  
Kapazität: `orbital_production_batch_capacity(yard_level)`. Restzeit und Timekeeper lesen denselben `finish_at` (Sync bei Level-Up / Live-Params).

**Beispiel:** Zyklus 21 s, Kapazität 63, Menge 2681 → `ceil(2681/63) × 21 = 903 s` (nicht `2681 × 21`).

Ein danach eingereihter Auftrag addiert dessen Anzeige: `Rest_vorherige_Aufträge + eigene_Auftragsdauer`.

Verboten: UI zeigt nur die Einzel-Zyklus-Zeit, während der Auftrag mehrere Zyklen blockiert; verboten auch `amount × unit_seconds` bei aktivem Kapazitätssystem.

Referenz: `order_total_seconds` / `order_remaining` in `game/shipyard_queue.py`, `game/defense.py`; Card-Adapter `map_shipyard_queue_to_card_jobs`, `map_defense_queue_to_card_jobs`.

### Completion state (GC-833)

| State | Condition | Server | Client |
|-------|-----------|--------|--------|
| **Active** | `remaining_seconds > 0` | Job in queue, position 1 active | Show progress + timer |
| **Completed** | `remaining_seconds <= 0` or `finish_at <= now` | Finish immediately, remove from queue, apply reward, start next | Remove card/HUD queue block immediately; refresh via `/api/game-state` |
| **Cancelled** | User cancel | Remove job, refund per GC-831, reschedule | Clear queue UI from action `state` |

**Forbidden** (must never appear in API or UI):

- `progress_pct = 100` + `remaining_seconds = 0` + `status = active`
- Completed job still visible in queue
- Cancelled job without refund

`coerce_skip_finish()` skips a second finish pass only after `mark_request_live_refreshed()` in the same HTTP request. Before that, queue read paths always run finish so due jobs cannot leak into payloads.

Card adapter: `is_queue_job_client_visible()` in `game/queue_card.py` filters due jobs from `card_jobs` / HUD slices.

**Buildings + Research payload parity:** `get_build_queue_status_for_planet` and `get_research_status` strip rows with `remaining <= 0` from `queue` / `summary.count` / free-slot math (GC-833). Finish cutoff uses `due_cutoff_ts()` (`max(ε, 1.0s)`) so jobs that the UI would show as `0s` are deleted before they can occupy a slot. Recalculate must never revive a due head to a full new duration.

Client: Research timer-zero uses the same `requestQueueTimerZeroRefresh` path as Buildings / Shipyard / Defense (not the slower `FINISH_REFRESH_MIN_MS` branch).

---

## Single Finish Pass pro Request

- Ein Aufruf von `finish_due_work_once` pro HTTP-Request (außer dokumentierte Admin/Cron-Pfade).
- Lesende Pfade: `skip_finish=True` nach bereits gelaufenem Refresh.
- Poll: `finish_source=game_state` — leichtgewichtig, siehe [STATE_AJAX.md](STATE_AJAX.md).
- **GC-PERF-WORKER-001:** Mit `GC_GAME_WORKER_PRIMARY=1` finish't der Poll nur noch bei tatsächlich fälliger Arbeit (Safety-Net). Reguläre Finishes: `POST /api/internal/cron/queue-tick` / `scripts/run_game_worker.py` → weiterhin `finish_due_work` (kein Parallel-System).

---

## APIs und State

Queue-Mutationen liefern immer frischen **`state`** (game-state payload) — siehe [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md).

Frontend zeigt Queue-Fortschritt aus `state.build_queue`, `state.research`, etc. — keine eigene Queue-Berechnung.

### Presentation (GC-536A ✅ / GC-UNIT-QUEUE-DEDUP-001)

Queue-**Logik** bleibt in `game/queue_engine.py` und den Domänen-Ownern. Presentation-Adapter: `game/queue_card.py` (**keine zweite Queue**).

- Gebäude / Forschung / PE: Jobs in Item-Cards (+ Mini-Strip)
- **Unit-Queues (Shipyard / Defense):** ausschließlich zentrale Mini-Bauschleife; `renderCardQueueBlock` liefert für `shipyard`/`defense` `null`; TK/Cancel nur im Strip
- **TK-Boost Dedup:** eine ⚡ pro aktivem Job — Mini-Strip (Build/Research/Shipyard/Defense) bzw. PE-Queue-List; Hero-/Tech-Cards hosten keinen Apply-Button
- **Live-Sync:** `syncMountedQueuePagesFromState` nach Actions und Diet-Polls; Finish → `queue_timer_zero` / `*_finished` + include_panel aktualisiert Levels/Stock
- Serializer (`map_*_queue_to_card_jobs`, `mini_queue_jobs`) bleiben für Strip/HUD — nicht für Unit-Card-DOM

---

## Cancel refunds (GC-831)

Owner: `game/queue_refund.py` — **single source** for cancel refund ratios and planet credit.

| Job state | Condition | Refund |
|-----------|-----------|--------|
| Pending | `start_time > now` | **100%** |
| Active | `start_time <= now < finish_time` | **50%** |
| Completed | `finish_time <= now` | **0%** (not cancellable) |

Applies to: `build_queue`, `research_queue`, `planet_research_queue`, `shipyard_queue`, `defense_queue`.

Stored-cost queues (shipyard, defense) refund from `cost_metal` / `cost_crystal` / `cost_fuel_cells` on the row.

Build/research: refund prefers **stored snapshot** on the row (`cost_metal`/`cost_crystal` from Migration 076 enqueue); falls back to recomputing from canonical formulas at cancel time.

Cancel handlers must call `finish_due_work` first, then refund, then delete job, then reschedule — see [QUEUE_STATE_RULES.md](QUEUE_STATE_RULES.md).

### Cancelled visibility (GC-833B)

**Cancelled** = row deleted from queue table + refund applied + reschedule. Forbidden client state:

- Job still in `build_queue` / `card_jobs_by_owner` after successful cancel API
- Hero time chip still running `[data-countdown-at]` after cancel (orphan timer)
- `0s` + queue overlay on the same card

Frontend: `GC.clearCardQueueBlock()` must strip hero overlay **and** hero-chip countdown attrs (`stripHeroTimeChipQueueTimer`). `patchCardQueuesFromOwnerMap` treats missing `card_jobs_by_owner` as empty map (clears stale cards).

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
