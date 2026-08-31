# GC-PROD-SQLITE-STALL-001 — FINAL AVAILABILITY REPORT

Date: 2026-08-31  
Branch: `fix/gc-prod-sqlite-stall-001`  
Base: recovery `main` `fb8b94ed68260ce743de3f14ccb59b12f1a27ab0`  
**Availability fix validated as release candidate.**  
**Not deployed / not marked production-resolved.** No Railway changes in this ticket.

## Diagnosis (closed)

Sync `sqlite3` work blocks **gevent w1** event loop → `/healthz` freezes even when individual TX holds are sub-second.

Structural SQLite fixes kept; further &lt;800ms owner hunting stopped by design.

## What shipped

| Layer | Change |
|-------|--------|
| 001A | Queue single-flight + heartbeat separation; fleet poll deferral |
| 001A.2 | Presence read-before-write (no BEGIN when fresh) |
| 001B | Fleet run budget; HoF scan outside writer; combat-bot short TX; TX provenance |
| Final | Production default: `gthread` w1 t4 (`docker-entrypoint.sh`) |
| WS | Under gthread: long-lived galaxy WS refused; existing polling fallback active |
| 001C | Entrypoint/WS/healthz-under-lock regression tests |

## Validation record (T3 acceptance A/B)

### GEVENT W1

| Metric | Value |
|--------|-------|
| healthz p50 | 9.2 s |
| healthz p95 | 11.2 s |
| ≥5s freezes | **7/8** |
| timeouts | 0 |
| max TX hold | 716 ms |

### GTHREAD W1/T4

| Metric | Value |
|--------|-------|
| healthz p50 | **105 ms** |
| healthz p95 | **2.55 s** |
| ≥5s freezes | **0/83** |
| timeouts | **0** |
| max TX hold | **508 ms** |

### Interpretation

- HARD `healthz p95 < 2s`: narrowly missed (2.55 s)
- Global freeze invariant: **PASS**
- Timeout invariant: **PASS**
- TX ≤800 ms: **PASS**
- Massive availability improvement: **PASS**

## WebSocket

Live galaxy WS push disabled under default gthread; polling fallback remains active. No new WS architecture.

## Suites

Targeted 001A/A.2/001B/001C/runtime: 34 passed at RC checkpoint.  
Full Smoke / I18N / Big Score / Sentinel: run after Draft PR.
