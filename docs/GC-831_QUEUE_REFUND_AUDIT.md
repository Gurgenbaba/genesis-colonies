# GC-831 — Queue Cancellation & Refund Consistency

**Priorität:** KRITISCH

## Problem

Build- und Research-Cancel haben Ressourcen abgezogen, aber bei Abbruch **nichts erstattet** — effektiver Resource Sink.

## Lösung

- Zentrale Refund-Logik: `game/queue_refund.py`
- Kosten-Snapshot beim Enqueue: Migration `076_queue_job_cost_snapshot.sql`
- Einheitliche Genesis-Regeln (siehe `docs/QUEUE_STATE_RULES.md`)

## Refund-Regeln

| Zustand | Bedingung | Erstattung |
|---------|-----------|------------|
| Pending | `start > now` | 100% |
| Active | `start <= now < finish` | 50% |
| Done | `finish <= now` | nicht abbrechen |

## Abgedeckte Queues

| Queue | Cancel-Handler | Refund |
|-------|----------------|--------|
| Buildings | `cancel_build_job_for_planet` | ✅ GC-831 |
| Account research | `cancel_research_job` | ✅ GC-831 |
| Planet evolution research | `cancel_planet_research_job` | ✅ GC-831 |
| Shipyard | `cancel_queue_job` | ✅ zentralisiert |
| Defense | `cancel_defense_job` | ✅ zentralisiert |

## Offen / später

- Expedition, Terraforming, Kolonisierung — prüfen wenn Cancel-UI existiert
- Ascensions-/Evolution-Jobs ohne Ressourcenkosten separat dokumentieren

## Tests

```bash
python -m pytest tests/test_gc831_queue_refund.py tests/test_queue_static_contract.py -v
```
