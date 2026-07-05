# Balance-Anker & Kurven (Code-Stand)

Referenztabellen aus dem **Live-Code** (`game/economy_balance.py`, `game/production_formula.py`, `EffectResolver`).  
Regenerieren:

```bash
python scripts/gen_anchor_tables.py docs/GC_ANCHOR_TABLES_X1.md
```

---

## Referenzbedingungen

| Parameter | Benchmark ×1 | Universe-Default |
|-----------|--------------|------------------|
| `production_speed` | 1.0 | 1.0 |
| `build_speed` | 1.0 | **1.1** |
| `research_speed` | 1.0 | **0.85** |
| Galaxieslot | 9 (neutral) | — |
| Energie | 100 % | — |
| Forschung | 0 (Benchmark) | — |

Vollständige Tabellen: **[GC_ANCHOR_TABLES_X1.md](GC_ANCHOR_TABLES_X1.md)**

---

## Owner & Formeln

| Domäne | Modul | Doc |
|--------|-------|-----|
| Produktion/h | `game/production_formula.py` | [PRODUCTION_FORMULA_SYSTEM.md](PRODUCTION_FORMULA_SYSTEM.md) |
| Upgrade-Kosten, ROI-Anker, Forschungs-Anker | `game/economy_balance.py` | [GC-821_ECONOMY_REBALANCE.md](GC-821_ECONOMY_REBALANCE.md) |
| Live Build-/Research-Zeit | `game/effects/effect_resolver.py` | [EFFECTS.md](EFFECTS.md), [BUILDINGS_SYSTEM.md](BUILDINGS_SYSTEM.md) |
| Queue-Refunds | `game/queue_refund.py` | [QUEUE_STATE_RULES.md](QUEUE_STATE_RULES.md) |
| Starter-Ressourcen | `game/models.py` `DEFAULT_GAME_SETTINGS` | [GC-836_ALPHA_STARTER_RESOURCES.md](GC-836_ALPHA_STARTER_RESOURCES.md) |

---

## Wichtige Code-Wahrheiten

1. **Upgrade-Kosten (Gebäude):** live via `power_upgrade_cost()` — **nicht** `BASE_COST × COST_FACTOR^level`.
2. **Build-Zeit:** live via `power_build_seconds()` in `EffectResolver.get_build_time_seconds()` (GC-850A).
3. **Forschung Kosten/Zeit:** live via `research_upgrade_cost()` / `research_time_anchor_hours()` (GC-825).
4. **Minen-ROI-Anker:** L20=50h … L120=2000h — Ziel für Ferronit-Mine; Crytite/Brennzellen weichen ab.
5. **Lager:** Basis-Cap wie Ferronit/Crytite/Brennzellen (`STORAGE_BASE_CAPACITY`); Storage-Gebäude skalieren progressiv (`storage_capacity_at_depot_level`: BASE × GROW^level), `storage_tech` multipliziert additiv mit +33 %/Level.
6. **Klima-Prod-Faktoren:** zusätzlich zu Slot/Temperatur in `production_formula.py` via `directive_modifier` (Klima + Galactic Directives + Diplomacy).
7. **Produktions-Basis (Ferdi-Rebase):** `Standard + MineBasis × level × 1.075^level` — Standard 15k/10k/5k; Energie nur auf Minen-Anteil — siehe [PRODUCTION_FORMULA_SYSTEM.md](PRODUCTION_FORMULA_SYSTEM.md).
8. **Forschung Kosten (GC-RESEARCH-COST-REBALANCE):** `research_cost_afford_hours × Referenzproduktion (Fe+Cr)` — steile Afford-Kurve (L10=8h … L120=8640h); Zeiten unverändert (GC-825).

---

## Ticket-Docs (Detail)

| Ticket | Inhalt |
|--------|--------|
| [GC-821_ECONOMY_REBALANCE.md](GC-821_ECONOMY_REBALANCE.md) | Storage, Exchange, Loot, Military ×1.25 |
| [GC-821E_PRODUCTION_DISPLAY_ROI.md](GC-821E_PRODUCTION_DISPLAY_ROI.md) | ROI-Anzeige in UI |
| [GC-821F_MINE_ROI_BULK.md](GC-821F_MINE_ROI_BULK.md) | Bulk-Upgrade, ROI-Anker |
| [GC-822_LIVE_ECONOMY_QA.md](GC-822_LIVE_ECONOMY_QA.md) | Live-Audit-Skript |
| [GC-823_TECHNICAL_DATA.md](GC-823_TECHNICAL_DATA.md) | Technische Detail-Modals |
| [GC-829_FRESH_ACCOUNT_PROGRESSION.md](GC-829_FRESH_ACCOUNT_PROGRESSION.md) | Progression-Sim |
| [GC-831_QUEUE_REFUND_AUDIT.md](GC-831_QUEUE_REFUND_AUDIT.md) | Refund-Regeln (→ Master: QUEUE_STATE_RULES) |
| [GC-836_ALPHA_STARTER_RESOURCES.md](GC-836_ALPHA_STARTER_RESOURCES.md) | Neukonto-Startwerte |
