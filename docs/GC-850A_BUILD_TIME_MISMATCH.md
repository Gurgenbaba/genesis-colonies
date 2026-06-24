# GC-850A — Build-Time: Design = Runtime

> **Parent:** [GC-850_RUNTIME_DOC_AUDIT.md](GC-850_RUNTIME_DOC_AUDIT.md) (GC850-01)  
> **Status:** ✅ Shipped (2026-06-24)  
> **Entscheidung:** Option A — `power_build_seconds()` ist Runtime-Wahrheit

---

## Delta-Tabelle (vor Umstellung)

Referenz: `build_speed = 1.0`, keine Tech-/Gebäude-Boni.  
**Legacy** = `BUILD_TIME_BASE × FACTOR^(L-1)` · **Design (jetzt live)** = `power_build_seconds(L)`.

### Ferronit-Mine

| Level | Legacy | Design (live) | Legacy ÷ Design |
|------:|-------:|--------------:|----------------:|
| 10 | 18 Min | 43 Min | 0,4× (Legacy war schneller) |
| 20 | 8,5 h | 1,8 h | 5× |
| 30 | 10,2 Tage | 3,1 h | 78× |
| 40 | 295 Tage | 4,6 h | 1.538× |
| 50 | 23,4 Jahre | 6,2 h | 32.911× |

### Crytite-Mine

Gleiche Kurven wie Ferronit-Mine (identische Legacy-Konstanten).

### Labor

| Level | Legacy | Design (live) | Legacy ÷ Design |
|------:|-------:|--------------:|----------------:|
| 10 | 2,3 h | 1,2 h | 2× |
| 20 | 10,5 Tage | 3,1 h | 81× |
| 30 | 3,2 Jahre | 5,5 h | 5.070× |
| 40 | 348 Jahre | 8,1 h | 375.000× |
| 50 | 38.216 Jahre | 11,1 h | 30 Mio× |

### Werft (`orbital_shipyard`)

| Level | Legacy | Design (live) | Legacy ÷ Design |
|------:|-------:|--------------:|----------------:|
| 10 | 6,6 h | 1,8 h | 4× |
| 20 | 55 Tage | 4,8 h | 277× |
| 30 | 30,6 Jahre | 8,4 h | 31.704× |
| 40 | 9.162 Jahre | 12,6 h | 4,3 Mio× |
| 50 | **1,24 Mio Jahre** | **17,3 h** | 630 Mio× |

**Lesart:** Ab Stufe ~15–20 war Legacy nicht mehr „hart“, sondern **kaputt**. Die Design-Kurve ist kein Feintuning — sie repariert Midgame/Endgame.

Mit Default-Universum `build_speed = 1.1` sind Live-Zeiten ~9 % kürzer als in der Tabelle.

---

## Umsetzung

```text
power_build_seconds(target_level)
  ÷ get_build_time_effective_speed(building_type)
```

Owner: `game/effects/effect_resolver.py` → `game/economy_balance.power_build_seconds`

Tests: `tests/test_gc850a_build_time_wiring.py`, `tests/test_gc821_economy_rebalance.py`

---

## Patchnotes (Community)

**Gebäude-Bauzeiten (Balance-Update)**

- Bauzeiten folgen jetzt der dokumentierten GC-821-Kurve (`power_build_seconds`), nicht mehr der alten Exponential-Formel.
- **Early Game (ca. Stufe 1–12):** Einige Upgrades können **länger** dauern als zuvor (Design ist konservativer).
- **Midgame+ (ab ~Stufe 20):** Bauzeiten fallen drastisch — z. B. Mine Stufe 30 von ~10 Tagen auf ~3 Stunden (bei `build_speed = 1`).
- **Endgame:** Werft/Labor/Nexus sind wieder spielbar statt astronomisch.
- Laufende Queue-Jobs: Dauer wurde beim Deploy **nicht** retroaktiv geändert; neue Enqueues nutzen die neue Kurve.
- Ankerwerte: [GC_ANCHOR_TABLES_X1.md](GC_ANCHOR_TABLES_X1.md) · [BALANCE_ANCHORS.md](BALANCE_ANCHORS.md)

---

## Akzeptanzkriterien

- [x] Genau **ein** Build-Zeit-System live
- [x] `get_build_time_seconds` == `power_build_seconds` bei Speed ×1 (Test)
- [x] Legacy §6 aus Anker-Tabellen entfernt
- [x] Keine Frontend-Build-Time-Math

---

## Changed Files

- `game/effects/effect_resolver.py`
- `tests/test_gc850a_build_time_wiring.py`
- `tests/test_effects.py`, `tests/test_gc821_economy_rebalance.py`
- Docs: `BUILDINGS_SYSTEM`, `EFFECTS`, `BALANCE_ANCHORS`, `GC_ANCHOR_TABLES_X1`
