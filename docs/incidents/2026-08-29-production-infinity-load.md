# Incident
Production Infinity Load — 2026-08-29

## Impact
Dynamische Spielrouten wurden extrem langsam bzw. endeten als 499.
Spieler konnten teilweise nicht mehr spielen.

## Symptoms
Beobachtete Railway Network Logs (Client/Proxy gab auf, App noch nicht fertig):

| Route | ca. Dauer bis 499 |
|-------|-------------------|
| `/api/game-state` | 14–15 s |
| `/api/notifications/summary` | 11–12 s |
| `/fleet` | ~25 s |
| `/world-boss` | ~25 s |
| `/api/chat/bootstrap` | ~1 m 31 s |
| `/messages` | ~1 m 56 s |

Weitere Beobachtungen:

- Railway/Container nicht komplett down
- Statische Dateien schnell; `/` z. B. 302 in ~18 ms
- `/healthz` weiterhin 200
- CPU/RAM nicht auffällig hoch
- SQLite unter `/data/game.db`; Maintenance Worker separat
- Zusatz-Gunicorn-Worker (GC-PROD-AVAIL-001) behob die Ursache **nicht**
- Rollback auf bekannten stabilen Stand stabilisierte Production wieder
- Dieselbe Production-DB / dasselbe Volume lief mit Rollback stabil

## Terminology (wichtig)

| Stand | Bedeutung |
|-------|-----------|
| Stable boundary commit | `9027ec0934b68be8e6ea9ffce29854422e71dc15` |
| GitHub `main` (Recovery merge) | `fb8b94ed68260ce743de3f14ccb59b12f1a27ab0` |
| Tree SHA | `8edb0195d4161c815ceaafa18ba7be7d51b1c868` (= Tree von `9027ec0`) |
| Railway Production (nach Incident) | weiterhin manuelles stabiles Deployment von **`9027ec0`** |

GitHub `main` ist **nicht** automatisch gleich dem laufenden Railway-Deploy.
Der Recovery-Merge (`fb8b94ed` / PR #124) stellte den Repository-Tree wieder her, deployte aber wegen „No changes to watched files“ nicht neu auf Railway.

## Stable Boundary
`9027ec0934b68be8e6ea9ffce29854422e71dc15` — „perf: bulk Vote Center nav attention reads“

## Suspect Changes

| Commit | Ticket | Note |
|--------|--------|------|
| `b0fade8492ead95f0f9b36e7e317b4e692f57c19` | GC-PERF-STATE-012 | Directives nav attention read-only `COUNT(*)` |
| `7f3990b384b4197ec5c2e03d15d7e8f2ebba419d` | GC-PERF-STATE-013 | Government nav → status-first `COUNT` + `EXISTS`/`NOT EXISTS` |
| `826f2c92868c5564868d13530fdf9eb592e11c6c` | GC-PROD-AVAIL-001 | 2. Web-Worker + `/healthz` — Symptom-Mitigation, keine Root-Cause-Fix |

## Mitigation Attempts
- zusätzlicher Gunicorn Worker (AVAIL-001)
- `/healthz` als günstiger Healthcheck

Diese lösten die eigentliche Ursache nicht.

## Recovery
Rollback auf `9027ec0` stabilisierte Production.

PR #124 / `fb8b94ed` stellte `main` auf exakt denselben bekannten stabilen Repository-Tree zurück.

## Forensic A/B (local, 2026-08-29 follow-up)

Historische Worktrees mit **identischem Seed**:

- A = `9027ec0`
- B = `b0fade84` (…`e692f57c19`)
- C = `7f3990b`

Harness: `scripts/prod_infinity_load_ab.py`, Probe: `scripts/_prod_infinity_load_probe.py`,
CI-Gates: `tests/test_gc_prod_infinity_load_ab.py`.

Scale tiers (Hot-Table-Faktor): baseline / 10x / 100x (100x Seed ≈ 38 MB; Production-DB war ≈ 200 MB).

### Results (kurz)

- **Kein Multi-Sekunden-Hänger** auf A/B/C bei wiederholten `/api/game-state` (p95 typisch < 220 ms, keine Outliers > 2 s im gemessenen Fenster).
- STATE-012 (B) macht `count_claimable_directives` klar schneller (entfernt Write-on-Poll/`ensure`+`commit`).
- STATE-013-Query-Shape: `EXPLAIN` zeigt **`SCAN c`** auf `gd_cycles`; stabile Galaxy-IN-Query nutzt `idx_gd_cycles_galaxy_status`.
- Auch mit ~5k `vote_open` Cycles blieb die 013-Query im lokalen Adversarial-Test ~1–2 ms — **nicht** 15–25 s CPU.
- Paralleler `BEGIN IMMEDIATE`-Writer (3 s Hold): **Reads** bleiben schnell (WAL); **Writes** warten ~Hold-Dauer (≈ 2.8–3.0 s). Das passt besser zur beobachteten Multi-Sekunden-/499-Klasse als der reine 013-Scan allein.

### Lock-vs-SQL Klassifikation (lokal)

| Klasse | Befund |
|--------|--------|
| A) SQL CPU lang | Nicht reproduziert für Suspect-Queries in gemessenen Skalen |
| B) Lock/Transaction Wait | Reproduzierbar: Writer-Hold → Writer-Wait ≈ Hold-Zeit |
| C) anderer Python-Code | Nicht isoliert als Hang-Ursache |
| D) Hotpath-Summe | Game-state p50 steigt mit Scale moderat; kein Freeze |

## Root Cause
**Under investigation.**

STATE-012 / STATE-013 sind **Verdächtige im Deploy-Fenster**, aber nach dem Root-Cause-Gate **nicht bestätigt**:

Ein Commit gilt erst als Verursacher, wenn der Hänger auf seinem Tree reproduzierbar ist (und auf `9027ec0` nicht) **und** ein minimaler Fix denselben Fehler beseitigt.

Bisher: Hang nicht reproduziert; schlechter EXPLAIN allein reicht nicht als Beweis.

## Prevention
- Production-scale SQLite A/B / Wachstumskurven (`scripts/prod_infinity_load_ab.py`)
- Hot-path latency budgets + wiederholte Polls (`tests/test_gc_prod_infinity_load_ab.py`)
- `EXPLAIN QUERY PLAN` Gates für kritische Nav/Game-State Queries
- Lock-Wait vs SQL-CPU Trennung in Probes
- Keine Performance-Optimierung allein anhand winziger In-Memory-Fixtures freigeben
- STATE-013 status-first Shape nicht ohne Index-/Plan-Gate und Scale-Repro reintroducen

## Related
- PR #118 / #120 / #122 / #124
- `docs/GC_PERF_PROD_001.md` (Worker/Lock/Healthz Kontext)
- Open follow-ups: Battle Pass nav writes (STATE-014 / #121) bleiben relevant für Write-on-Poll Druck, sind aber nicht als dieser Hang bewiesen
