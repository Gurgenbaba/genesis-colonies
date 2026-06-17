# GC-622B — Resource INTEGER Migration (Backlog)

> **Status:** 💡 Backlog — kein Hotfix, nicht vor Completion-First-Bugs  
> **Parent:** [GC-622 Integer Overflow Audit](GC-622_INTEGER_OVERFLOW_AUDIT.md) ✅  
> **Epic:** — (reine Tech Debt)

---

## Problem

Ressourcen und Exchange-Beträge liegen historisch als **REAL** (IEEE-754) in SQLite, während Scores, Schiffe und Auktionen bereits **INTEGER** nutzen. Für Milliarden-Bereiche unkritisch; ab ca. **9×10¹⁵** wäre Float-Präzision die Grenze — nicht INT32.

Dieses Ticket **migriert nichts** — es dokumentiert die mittelfristige Schuld für einen späteren, geplanten Pass.

---

## Scope (wenn umgesetzt)

| Tabelle | Spalte | Aktuell | Ziel |
|---------|--------|---------|------|
| `planets` | `metal` | REAL | INTEGER |
| `planets` | `crystal` | REAL | INTEGER |
| `planets` | `fuel_cells` | REAL | INTEGER |
| `exchange_log` | `give_amount` | REAL | INTEGER |
| `exchange_log` | `receive_amount` | REAL | INTEGER |

Optional (separates Ticket):

- Große Zahlen in JSON-APIs als **Strings** serialisieren; Client parst via `GC.parseIntNumber`.
- `players.exchange_daily_used` REAL → INTEGER.

**Nicht im Scope:** `debris_fields.metal/crystal` (Combat-Loot, geringere Priorität).

---

## Anforderungen (bei Umsetzung)

1. Neue Migration `migrations/NNN_resource_integer.sql` — `ALTER` oder Rebuild mit Daten-Copy (`CAST(ROUND(v) AS INTEGER)`).
2. `game/models.py` — Schema-Definitionen REAL → INTEGER.
3. `save_planet`, `try_spend_resources_conn`, `exchange.py` — keine `float()`-Pfade mehr für Persistenz.
4. Admin `clamp_resource` — `int` statt `float` wo sinnvoll.
5. Keine Regression: `tests/test_gc622_integer_overflow.py` grün.
6. Kein Parallel-System — eine kanonische Spalte pro Ressource ([CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) Regel 15).

---

## Akzeptanzkriterien

- [ ] Migration idempotent; bestehende DBs upgraden ohne Datenverlust (bis 10¹² getestet).
- [ ] `PRAGMA table_info(planets)` zeigt INTEGER für `metal`, `crystal`, `fuel_cells`.
- [ ] Exchange-Log + Trader bei 50-Mrd.-Cap weiterhin korrekt.
- [ ] `pytest tests/test_gc622_integer_overflow.py tests/test_exchange.py -q` grün.

---

## Wann angehen?

| Priorität | Bedingung |
|-----------|-----------|
| **Nicht jetzt** | GC-622 Audit: Milliarden-Bereich safe |
| **Später** | Wenn Ressourcen/Scores dauerhaft > 10¹⁴ erwartet werden |
| **Optional vorher** | Wenn Schema-Hygiene-Batch ohne Feature-Drift geplant ist |

---

## Betroffene Dateien (Vorschau)

- `migrations/NNN_resource_integer.sql` (neu)
- `game/models.py`
- `game/resources.py`
- `game/exchange.py`
- `game/admin_api.py` (optional)

**Nicht bearbeiten ohne Ticket:** Frontend-Formeln, Parallel-Spalten, neue Ressourcen-Typen.

---

## Referenz

- [GC-622_INTEGER_OVERFLOW_AUDIT.md](GC-622_INTEGER_OVERFLOW_AUDIT.md) — Audit-Ergebnis
- [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md) — Ressourcen-Owner
