# GC-622 — Integer Overflow Audit

> **2026-09-04 superseded for production numeric readiness:** PostgreSQL is now production-authoritative and live Genesis values have crossed the old IEEE-754 warning range. The binding cross-backend audit is [GC_PG_NUMERIC_READINESS_001.md](GC_PG_NUMERIC_READINESS_001.md). This document remains historical context for the original SQLite-era INT32 audit.


**Status:** ✅ Abgeschlossen (Tech-Audit, kein Hotfix)  
**Stand:** 2026-06-17  
**Kontext:** Community-Vergleich mit InFlames (Spieler ~1,2 Mrd. Ressourcen; signed INT32-Maximum 2.147.483.647)

---

## Ziel

Prüfen, ob spielrelevante Zahlenfelder an ein **signed 32-bit-Integer-Limit** (2.147.483.647) stoßen — analog zu Legacy-Browsergames mit `INTEGER`/Frontend-Bitwise-Hacks.

---

## Ergebnis (Kurz)

| Frage | Antwort |
|-------|---------|
| INT32-Risiko in GC? | **Nein** — kein systemischer 32-bit-Ceiling |
| 1,2 Mrd. Ressourcen safe? | **Ja** |
| 2,147 Mrd. (INT32_MAX) safe? | **Ja** |
| 50 Mrd. (Trader-Admin-Cap) safe? | **Ja** |
| 1 Bio. (10¹²) safe? | **Ja** (serverseitig + JSON) |
| Wann wird es kritisch? | Ab ca. **9×10¹⁵** (Float/JS-Präzision), nicht bei INT32 |

**Kein Panik-Hotfix nötig.** Weiter mit echten Bugs; optionale Migration siehe [GC-622B](GC-622B_RESOURCE_INTEGER_MIGRATION.md).

---

## Geprüfte Bereiche

| System | Spalte / Feld | DB-Typ | INT32-Risiko | Anmerkung |
|--------|---------------|--------|--------------|-----------|
| `planets` | `metal`, `crystal`, `fuel_cells` | REAL | ❌ | Float-Präzision ab ~9×10¹⁵ |
| `planets` | `energy_total`, `energy_used` | INTEGER | ❌ | SQLite 64-bit |
| `player_scores` | `score_*` | INTEGER | ❌ | `MAX_SCORE` = 9×10¹⁵ in `ranking.py` |
| `exchange_log` | `give_amount`, `receive_amount` | REAL | ❌ | wie Ressourcen |
| `planet_ships` | `amount` | INTEGER | ❌ | |
| `planet_defense` | `amount` | INTEGER | ❌ | |
| `auction_house_*` | `amount`, `current_bid` | INTEGER | ❌ | |
| Trader Tageslimit | `exchange_daily_limit_max` | Setting | ❌ | Default 50 Mrd. |

---

## Code-Audit

### Server (Python / SQLite)

- SQLite `INTEGER` = **signed 64-bit** (±9,22×10¹⁸).
- Game-Logik nutzt durchgängig Python `int()` — **kein** `int32`, `numpy.int*`, `ctypes.c_int`.
- Ressourcen-Maths: `game/resources.py`, `game/exchange.py`, `try_spend_resources_conn` in `game/models.py`.
- Ranking: `game/ranking.py` — `_safe_int()` clamped auf `MAX_SCORE = 9_000_000_000_000_000`.

### Frontend (JavaScript)

- **Kein** `|0`, `~~`, Bitwise-Truncation für Ressourcen/Scores.
- Kanonisch: `GC.parseIntNumber`, `GC.fmtIntParts` in `static/main.js` (Spiegel von `game/number_format.py`).
- Reine Ziffernstrings → `parseInt(raw, 10)`; Display über `toLocaleString("de-DE")`.

### Bekannte Nicht-Spiel-Limits

| Limit | Wo | Scope |
|-------|-----|-------|
| `MAX_RESOURCE = 1_000_000_000` | `game/admin_api.py` | Nur Admin-Tools |
| Trader Floor 25 Mio. | `exchange_daily_limit_min` | Balance, kein Overflow |
| Trader Cap 50 Mrd. | `exchange_daily_limit_max` | Admin-Obergrenze |

---

## Grenzen (nicht INT32, aber dokumentiert)

1. **REAL-Spalten** (`metal`, `crystal`, `fuel_cells`) — IEEE-754 Double in SQLite; exakt bis ca. 2⁵³ (~9×10¹⁵).
2. **JSON → JS `Number`** — gleiche Grenze (`Number.MAX_SAFE_INTEGER`).
3. **Mittelfristige Tech Debt:** REAL → INTEGER Migration — Backlog [GC-622B](GC-622B_RESOURCE_INTEGER_MIGRATION.md).

---

## Community-Kurzantwort (Discord)

```text
Geprüft ✅
Genesis nutzt serverseitig kein 32-bit Limit für Scores/Ressourcen.
2,147 Mrd. ist bei uns kein Breakpoint.

SQLite INTEGER kann bis ca. 9,22e18, Python int ist ebenfalls safe.
Aktuelles Risiko liegt erst viel später bei Float/JS-Präzision ab ca. 9e15.

Heißt: InFlames mit 1,2 Mrd. ist komplett safe 😄
```

---

## Tests

```bash
python -m pytest tests/test_gc622_integer_overflow.py -v
```

Zusätzlich bestehende Abdeckung:

- `tests/test_number_format.py` — Display bis 10¹²+
- `tests/test_ranking.py` — Score-Pipeline
- `tests/test_exchange.py` — Trader-Limit bis 50 Mrd.
- `tests/test_effects.py` — `TestResearchEffectRealityAudit` (GC-622 Display/Gameplay-Sync)

---

## Verwandte Docs

- [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) — Ressourcen, Exchange
- [GC-622B_RESOURCE_INTEGER_MIGRATION.md](GC-622B_RESOURCE_INTEGER_MIGRATION.md) — optionales Backlog
- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) — Server-Autorität, keine Frontend-Math
