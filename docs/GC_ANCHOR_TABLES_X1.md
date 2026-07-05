# Genesis Colonies — Ankerkurven (Code-Stand, Universum-Speed ×1)

**Referenz:** Galaxieslot 9 · Energie 100% · Forschung 0 · `production_speed=1` · `build_speed=1` · `research_speed=1`

## 1) Produktionsformel (GC-820 / Ferdi-Rebase)

```
Produktion/h = Standardbasis + (Mine-Basis × Level × 1.075^Level)
             × production_speed × Slot × Temperatur × Forschung × …
Energie-Drossel gilt nur für den Minen-Anteil (Standardproduktion läuft immer).
```

| Ressource | Standard/h | Mine-Basis | Gebäude |
|-----------|------------|------------|---------|
| Ferronit | 15k | 150 | metal_mine |
| Crytite | 10k | 100 | crystal_mine |
| Brennzellen | 5.0k | 50 | fuel_cell_plant |

### Produktion/h (Slot 9, Speed ×1)

| Mine-Stufe | Ferronit/h | Crytite/h | Brennzellen/h |
|------------|------------|-----------|---------------|
| 10 | 18k | 12k | 6.9k |
| 20 | 28k | 18k | 11k |
| 30 | 54k | 36k | 21k |
| 40 | 123k | 82k | 47k |
| 60 | 705k | 470k | 270k |
| 80 | 3.92 Mio | 2.61 Mio | 1.50 Mio |
| 100 | 20.76 Mio | 13.84 Mio | 7.96 Mio |
| 120 | 105.77 Mio | 70.51 Mio | 40.53 Mio |

### Produktionsgewinn pro Upgrade (+1 Stufe, Delta/h)

| Ziel-Stufe | Ferronit +/h | Crytite +/h | Brennzellen +/h |
|------------|--------------|-------------|-----------------|
| 10 | 503 | 336 | 193 |
| 20 | 1.5k | 988 | 568 |
| 30 | 4.0k | 2.6k | 1.5k |
| 40 | 10k | 6.7k | 3.9k |
| 60 | 59k | 39k | 23k |
| 80 | 318k | 212k | 122k |
| 100 | 1.64 Mio | 1.09 Mio | 629k |
| 120 | 8.20 Mio | 5.47 Mio | 3.14 Mio |

## 2) Forschung — Ankerkurven (GC-825, vor Speed-Boni)

### Basis-Dauer (Energieeffizienz-Tier = 1,0)

| Forschungsstufe | Anker (h) | Dauer Speed ×1 |
|-----------------|-----------|----------------|
| 10 | 1.5 | 1.5 h |
| 20 | 5 | 5.0 h |
| 30 | 24 | 1.0 Tage |
| 40 | 72 | 3.0 Tage |
| 60 | 336 | 2.0 Wochen |
| 80 | 1080 | 1.5 Monate |
| 100 | 2160 | 3.0 Monate |
| 120 | 4320 | 6.0 Monate |

### Basis-Kosten (Energieeffizienz-Tier = 1,0)

Formel: `research_cost_anchor_total(level)` = Referenzproduktion (Fe+Cr, Slot 9) × `research_cost_afford_hours(level)`

| Forschungsstufe | Gesamt (Anker) | Ferronit | Crytite |
|-----------------|----------------|----------|---------|
| 10 | 241k | 160k | 80k |
| 20 | 1.11 Mio | 750k | 350k |
| 30 | 8.70 Mio | 5.85 Mio | 2.90 Mio |
| 40 | 69.03 Mio | 46.00 Mio | 23.00 Mio |
| 60 | 1268.72 Mio | 847.00 Mio | 423.00 Mio |
| 80 | 14119.68 Mio | 9413.00 Mio | 4707.00 Mio |
| 100 | 149480.34 Mio | 99653.00 Mio | 49827.00 Mio |
| 120 | 1523043.49 Mio | 1015363.00 Mio | 507682.00 Mio |

### Alle Technologien — Stufe 30 (Speed ×1, Labor L1, ohne Tech-Boni auf Zeit)

| Technologie | Ferronit | Crytite | Dauer | Tier Zeit | Tier Kosten |
|-------------|----------|---------|-------|-----------|-------------|
| armor_tech | 7.25 Mio | 4.25 Mio | 1.4 Tage | 1.42 | 1.33 |
| buildtime_tech | 7.25 Mio | 4.25 Mio | 11.6 h | 1.17 | 1.33 |
| drone_tech | 8.75 Mio | 5.75 Mio | 1.2 Tage | 1.25 | 1.67 |
| energy_tech | 5.85 Mio | 2.90 Mio | 1.0 Tage | 1.00 | 1.00 |
| engine_tech | 8.75 Mio | 5.75 Mio | 1.6 Tage | 1.58 | 1.67 |
| fuel_efficiency | 8.50 Mio | 3.00 Mio | 1.7 Tage | 1.67 | 1.33 |
| interstellar_expansion | 14.50 Mio | 8.75 Mio | 2.0 Tage | 2.00 | 2.67 |
| mining_tech | 5.85 Mio | 2.90 Mio | 1.1 Tage | 1.08 | 1.00 |
| navigation_tech | 7.25 Mio | 4.25 Mio | 1.5 Tage | 1.50 | 1.33 |
| shield_tech | 7.25 Mio | 4.25 Mio | 1.6 Tage | 1.58 | 1.33 |
| storage_tech | 3.25 Mio | 3.25 Mio | 22.0 h | 0.92 | 0.67 |
| weapon_tech | 5.85 Mio | 2.90 Mio | 1.3 Tage | 1.33 | 1.00 |

## 3) Minen-Upgrades — Kosten & Ziel-Amortisation (live)

Amortisation = Payback in **Produktionsstunden** der jeweiligen Ressource (Slot 9, Speed ×1).

### Ferronit-Mine

| Ziel-Stufe | Ferronit | Crytite | Gesamt | Amortisation |
|------------|----------|---------|--------|--------------|
| 10 | 19k | 6.3k | 25k | 50 h |
| 20 | 56k | 19k | 74k | 50 h |
| 30 | 211k | 70k | 281k | 71 h |
| 40 | 755k | 252k | 1.01 Mio | 100 h |
| 60 | 8.82 Mio | 2.94 Mio | 11.76 Mio | 200 h |
| 80 | 119.26 Mio | 39.75 Mio | 159.01 Mio | 500 h |
| 100 | 1230.30 Mio | 410.10 Mio | 1640.39 Mio | 1000 h |
| 120 | 12296.73 Mio | 4098.91 Mio | 16395.64 Mio | 2000 h |

### Crytite-Mine

| Ziel-Stufe | Ferronit | Crytite | Gesamt | Amortisation |
|------------|----------|---------|--------|--------------|
| 10 | 10.0k | 6.9k | 17k | 50 h |
| 20 | 29k | 20k | 50k | 50 h |
| 30 | 111k | 77k | 188k | 71 h |
| 40 | 399k | 277k | 676k | 101 h |
| 60 | 4.66 Mio | 3.24 Mio | 7.89 Mio | 201 h |
| 80 | 62.93 Mio | 43.73 Mio | 106.65 Mio | 503 h |
| 100 | 649.16 Mio | 451.11 Mio | 1100.26 Mio | 1006 h |
| 120 | 6488.28 Mio | 4508.80 Mio | 10997.08 Mio | 2012 h |

### Brennzellen-Anlage

| Ziel-Stufe | Ferronit | Crytite | Gesamt | Amortisation |
|------------|----------|---------|--------|--------------|
| 10 | 11k | 7.4k | 18k | 95 h |
| 20 | 33k | 22k | 54k | 95 h |
| 30 | 123k | 82k | 205k | 135 h |
| 40 | 442k | 295k | 737k | 191 h |
| 60 | 5.17 Mio | 3.44 Mio | 8.61 Mio | 382 h |
| 80 | 69.81 Mio | 46.54 Mio | 116.35 Mio | 955 h |
| 100 | 720.17 Mio | 480.12 Mio | 1200.29 Mio | 1909 h |
| 120 | 7198.09 Mio | 4798.73 Mio | 11996.81 Mio | 3819 h |

### Minen ROI-Anker (explizite Zielwerte GC-821F)

| Stufe | Ziel-Amortisation |
|-------|-------------------|
| 20 | 50 h |
| 40 | 100 h |
| 60 | 200 h |
| 80 | 500 h |
| 100 | 1000 h |
| 120 | 2000 h |

## 4) Alle Gebäude — Upgrade-Kosten gesamt (F+C, live)

| Stufe | metal_mine | crystal_mine | solar_plant | fuel_cell_plant | metal_storage | crystal_storage | fuel_storage | research_lab | academy | command_center | orbital_shipyard | defense_factory | barracks | radar_array | shield_generator | terraformer | nanofactory | geothermal_nexus | planet_core_nexus |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 10 | 25k | 17k | 34k | 18k | 66k | 66k | 57k | 523k | 726k | 581k | 523k | 82k | 42k | 45k | 107k | 150k | 280k | 230k | 314k |
| 20 | 74k | 50k | 92k | 54k | 188k | 188k | 160k | 2.40 Mio | 3.34 Mio | 2.67 Mio | 2.40 Mio | 233k | 118k | 126k | 308k | 436k | 5.23 Mio | 673k | 925k |
| 30 | 281k | 188k | 166k | 205k | 345k | 345k | 292k | 5.86 Mio | 8.14 Mio | 6.51 Mio | 5.86 Mio | 427k | 215k | 230k | 570k | 813k | 97.55 Mio | 1.26 Mio | 1.74 Mio |
| 40 | 1.01 Mio | 676k | 252k | 737k | 531k | 531k | 446k | 11.04 Mio | 15.32 Mio | 12.26 Mio | 11.04 Mio | 658k | 329k | 352k | 882k | 1.27 Mio | 1820.89 Mio | 1.97 Mio | 2.73 Mio |
| 50 | 3.49 Mio | 2.34 Mio | 349k | 2.55 Mio | 742k | 742k | 621k | 18.03 Mio | 25.04 Mio | 20.03 Mio | 18.03 Mio | 919k | 458k | 490k | 1.24 Mio | 1.79 Mio | 33988.44 Mio | 2.79 Mio | 3.86 Mio |

*Normaler Max-Level: 50*

## 5) Gebäude-Bauzeit — Live (GC-821 / GC-850A, vor Speed-Boni)

Formel: `power_build_seconds` = `TIME_K × Level^Exponent` · ÷ `build_speed` / Tech-Boni im Resolver

| Stufe | Ferronit | Crytite | Solar | Brennzellen | Labor | Werft | Command |
|-------|----------|---------|-------|-------------|-------|-------|---------|
| 10 | 43 Min | 43 Min | 48 Min | 55 Min | 1.2 h | 1.8 h | 2.0 h |
| 20 | 1.8 h | 1.8 h | 2.1 h | 2.4 h | 3.1 h | 4.8 h | 5.2 h |
| 30 | 3.1 h | 3.1 h | 3.6 h | 4.1 h | 5.5 h | 8.4 h | 9.1 h |
| 40 | 4.6 h | 4.6 h | 5.3 h | 6.1 h | 8.1 h | 12.6 h | 13.6 h |
| 60 | 8.0 h | 8.0 h | 9.1 h | 10.6 h | 14.2 h | 22.3 h | 1.0 Tage |
| 80 | 11.7 h | 11.7 h | 13.4 h | 15.6 h | 21.1 h | 1.4 Tage | 1.5 Tage |
| 100 | 15.9 h | 15.9 h | 18.1 h | 21.1 h | 1.2 Tage | 1.9 Tage | 2.0 Tage |
| 120 | 20.3 h | 20.3 h | 23.1 h | 1.1 Tage | 1.5 Tage | 2.5 Tage | 2.6 Tage |

## 6) Speicher & Tausch

Speicher Basis ohne Depot: **150.000** · Depot-Bonus: Referenzproduktion/h × **120**

| Lager-Stufe | Ferronit | Crytite | Brennzellen |
|-------------|----------|---------|---------------|
| 1 | 1.97 Mio | 1.36 Mio | 847k |
| 5 | 2.08 Mio | 1.44 Mio | 889k |
| 10 | 2.32 Mio | 1.60 Mio | 982k |
| 20 | 3.48 Mio | 2.37 Mio | 1.43 Mio |
| 30 | 6.68 Mio | 4.50 Mio | 2.65 Mio |
| 40 | 14.94 Mio | 10.01 Mio | 5.82 Mio |
| 50 | 35.42 Mio | 23.66 Mio | 13.67 Mio |

Tausch Tageslimit: min. **500.000** oder **80%** Imperiums-Tagesproduktion

## 7) Code-Anker (Rohwerte)

**Forschung Zeit:** L10=1.5h, L20=5.0h, L30=24.0h, L40=72.0h, L60=336.0h, L80=1080.0h, L100=2160.0h, L120=4320.0h

**Forschung Kosten (Afford-h @ Tier 1.0):** L10=241k, L20=1.11 Mio, L30=8.70 Mio, L35=22.68 Mio, L38=43.68 Mio, L40=69.03 Mio, L50=352.71 Mio, L60=1268.72 Mio, L80=14119.68 Mio, L100=149480.34 Mio, L120=1523043.49 Mio

**Forschung Afford-Anker (h):** L10=8h, L20=24h, L30=96h, L35=168h, L38=252h, L40=336h, L50=720h, L60=1080h, L80=2160h, L100=4320h, L120=8640h

**Minen ROI:** L20=50.0h, L40=100.0h, L60=200.0h, L80=500.0h, L100=1000.0h, L120=2000.0h