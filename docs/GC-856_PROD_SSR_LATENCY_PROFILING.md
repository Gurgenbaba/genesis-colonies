# GC-856 — Prod/Ferdi SSR Latency Profiling

Measure-only ticket. **No runtime optimization** in this scope.

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
