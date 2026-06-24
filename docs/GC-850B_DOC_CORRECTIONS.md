# GC-850B — Documentation Corrections (Post-Audit)

> **Parent:** [GC-850_RUNTIME_DOC_AUDIT.md](GC-850_RUNTIME_DOC_AUDIT.md)  
> **Status:** ✅ Shipped (2026-06-24, nach GC-850A)

---

## Scope

Kleine Doc-Fixes aus GC-850 ohne Mechanik-Änderungen:

| ID | Datei | Korrektur |
|----|-------|-----------|
| GC850-02 | `DEFENSE_SYSTEM.md` | Cancel: GC-831 100/50 % statt 60 %; `CANCEL_REFUND_RATIO` entfernen |
| GC850-03 | `ECONOMY_SYSTEM.md` | Ship/Defense-Loot-Floors: **5.000–10.000** (`LOOT_UNIT_FLOOR_*`), Ressourcen 12k–30k |
| GC850-04 | `CORE_ARCHITECTURE.md` §7 | Shipyard/Fleet `{ ok, data }` Ausnahme + Link STATE_AJAX |
| GC850-04 | `AJAX_PJAX_CONTRACT.md` | Gleiche Ausnahme dokumentieren |
| GC850-07 | `GC-821_ECONOMY_REBALANCE.md` | Military ×1.25: „eingebettet in `fleet_defs`/`defense_defs`, kein Runtime-Multiplier“ |

---

## Akzeptanzkriterien

- [ ] Kein Widerspruch QUEUE_STATE ↔ DEFENSE_SYSTEM
- [ ] CORE ↔ STATE_AJAX konsistent bei Action-Envelope
- [ ] ECONOMY Loot-Floors match `inventory_loot.py`

---

## Nicht in GC-850B

- Build-Time (→ GC-850A)
- Shipyard/Planet-Tech Formel-Docs (→ GC-850C)
