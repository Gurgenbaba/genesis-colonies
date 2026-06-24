# GC-856 — Prod/Ferdi SSR Latency Profiling

Measure-only ticket. **No runtime optimization** in this scope.

## Status

**DONE** — Fleet is not the primary SSR bottleneck locally. Prod/Ferdi measurement optional; see classification below.

## Erkenntnis (lokal)

```text
fleet_panel / logistics   → 8–60 ms   (not the driver)
live_context              → 120–390 ms (shared across routes)
template                  → 30–350 ms (cold spike)
```

Ferdi's *"mal Fleet, mal Buildings, mal andere Seiten"* → pattern fits **global live_context / Prod host**, not a Fleet-specific bug.

GC-854 already delivered Buildings SSR: ~1613 ms → ~600 ms warm.

**GC-857:** deferred until repeated player reports or Prod logs justify it.

## Classification

| Case | Signal | Next |
|------|--------|------|
| A | `live_context` > 1000 ms multi-route | Global live context |
| B | `fleet_panel` > 1000 ms | Fleet panel |
| C | `template` > 1000 ms | Template render |
| D | Prod high, local low | DB/host profiling |

**Parallel track:** GC-859 Building hero image LCP (`img.gc-bld-card-hero-img`) — client-side, not SSR.

---

## Problem

Ferdi measures ~**2,31 s** browser *Waiting for server response* on `/fleet`. Local dev does not reproduce that magnitude (~400–750 ms cold on Bobby/admin). Ferdi's prod account is the relevant benchmark.

## Tooling

```powershell
$env:GC_SSR_PERF_DEBUG="1"
python tools/ssr_measure.py --username <ferdi_username> --all 3
```

Single route:

```powershell
python tools/ssr_measure.py <user_id> /fleet 3
python tools/ssr_measure.py <user_id> "/buildings?tab=resources" 3
```

Prod/staging:

1. Set `GC_SSR_PERF_DEBUG=1` on the host (Railway env).
2. Resolve Ferdi `user_id` (`SELECT id, username FROM users WHERE username = '…'`).
3. Ferdi opens each route 3× (cold → warm → warm) **or** run `ssr_measure.py` against a DB copy.
4. Copy `[GC SSR PERF]` lines from server logs.
5. **Disable** `GC_SSR_PERF_DEBUG` after measurement.

Instrumented routes: `/fleet`, `/buildings`, `/shipyard`, `/defense`, `/overview`.

Log format:

```text
[GC SSR PERF] route=… tab=… total=… live_context=… finish=… resource_sync=…
  buildings_panel=… cards=… tech_data=… fleet_panel=… logistics_panel=… template=… bytes=…
```

## Local baseline (Bobby, `game.db`, 2026-06-24)

Not used for GC-857 decisions — reference only.

| Route | Cold total | live_context | Route panel | template (cold) | Warm total |
|-------|-----------|--------------|-------------|-----------------|------------|
| `/fleet` | 422 ms | 122 ms | fleet 7 ms | 282 ms | 164–180 ms |
| `/buildings?tab=resources` | 415 ms | 118 ms | cards 158 ms | 111 ms | 316–335 ms |
| `/shipyard` | 198 ms | 128 ms | — | 69 ms | 164–165 ms |
| `/defense` | 216 ms | 146 ms | — | 69 ms | 159–167 ms |
| `/overview` | 186 ms | 124 ms | — | 59 ms | 165 ms |

Pattern locally: **`live_context` ~120–150 ms** on all pages; **`fleet_panel` not hot**; **`template` spikes cold** then ~35–70 ms warm.

## Prod / Ferdi — fill after measurement

```text
# TODO: paste 3× logs per route from prod

/fleet cold:
[GC SSR PERF] …

/fleet warm:
[GC SSR PERF] …

/buildings cold:
…

/shipyard cold:
…

/defense cold:
…

/overview cold:
…
```

Ferdi `user_id`: _TBD on prod_

Browser DevTools reference: `/fleet` ≈ **2310 ms** TTFB (Ferdi).

## Auswertung → GC-857

| Case | Signal | Next ticket |
|------|--------|-------------|
| A | `live_context` > 1000 ms on multiple routes | GC-857 Global Live Context Optimization |
| B | `fleet_panel` > 1000 ms (Fleet only) | GC-857 Fleet Panel Optimization |
| C | `template` > 1000 ms | GC-857 Template Render Optimization |
| D | Prod high, local low (same account copy) | GC-857 Production DB/Host Profiling |

## Related

- GC-853/854 — Buildings SSR profiling + optimization
- GC-855 — Fleet SSR profiling instrumentation
- GC-856A — Remove hot-path `print()` / logging cleanup
