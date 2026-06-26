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

| Forschungsstufe | Gesamt (Anker) | Ferronit | Crytite |
|-----------------|----------------|----------|---------|
| 10 | 3.0k | 2.0k | 1.0k |
| 20 | 12k | 8.5k | 4.0k |
| 30 | 50k | 32k | 18k |
| 40 | 2.00 Mio | 1.35 Mio | 650k |
| 60 | 50.00 Mio | 33.25 Mio | 16.75 Mio |
| 80 | 150.00 Mio | 100.00 Mio | 50.00 Mio |
| 100 | 500.00 Mio | 333.00 Mio | 167.00 Mio |
| 120 | 1000.00 Mio | 667.00 Mio | 333.00 Mio |

### Alle Technologien — Stufe 30 (Speed ×1, Labor L1, ohne Tech-Boni auf Zeit)

| Technologie | Ferronit | Crytite | Dauer | Tier Zeit | Tier Kosten |
|-------------|----------|---------|-------|-----------|-------------|
| armor_tech | 42k | 25k | 1.4 Tage | 1.42 | 1.33 |
| buildtime_tech | 42k | 25k | 11.6 h | 1.17 | 1.33 |
| drone_tech | 50k | 32k | 1.2 Tage | 1.25 | 1.67 |
| energy_tech | 32k | 18k | 1.0 Tage | 1.00 | 1.00 |
| engine_tech | 50k | 32k | 1.6 Tage | 1.58 | 1.67 |
| fuel_efficiency | 50k | 18k | 1.7 Tage | 1.67 | 1.33 |
| mining_tech | 32k | 18k | 1.1 Tage | 1.08 | 1.00 |
| navigation_tech | 42k | 25k | 1.5 Tage | 1.50 | 1.33 |
| shield_tech | 42k | 25k | 1.6 Tage | 1.58 | 1.33 |
| storage_tech | 20k | 18k | 22.0 h | 0.92 | 0.67 |
| weapon_tech | 32k | 18k | 1.3 Tage | 1.33 | 1.00 |

## 3) Minen-Upgrades — Kosten & Ziel-Amortisation (live)

Amortisation = Payback in **Produktionsstunden** der jeweiligen Ressource (Slot 9, Speed ×1).

### Ferronit-Mine

| Ziel-Stufe | Ferronit | Crytite | Gesamt | Amortisation |
|------------|----------|---------|--------|--------------|
| 10 | 25k | 8.4k | 34k | 50 h |
| 20 | 74k | 25k | 99k | 50 h |
| 30 | 281k | 94k | 374k | 71 h |
| 40 | 1.01 Mio | 336k | 1.34 Mio | 100 h |
| 60 | 11.76 Mio | 3.92 Mio | 15.69 Mio | 200 h |
| 80 | 159.01 Mio | 53.00 Mio | 212.02 Mio | 500 h |
| 100 | 1640.39 Mio | 546.80 Mio | 2187.19 Mio | 1000 h |
| 120 | 16395.64 Mio | 5465.21 Mio | 21860.86 Mio | 2000 h |

### Crytite-Mine

| Ziel-Stufe | Ferronit | Crytite | Gesamt | Amortisation |
|------------|----------|---------|--------|--------------|
| 10 | 13k | 9.2k | 23k | 28 h |
| 20 | 39k | 27k | 66k | 28 h |
| 30 | 148k | 103k | 251k | 39 h |
| 40 | 531k | 369k | 901k | 55 h |
| 60 | 6.21 Mio | 4.31 Mio | 10.52 Mio | 110 h |
| 80 | 83.90 Mio | 58.30 Mio | 142.21 Mio | 275 h |
| 100 | 865.54 Mio | 601.48 Mio | 1467.02 Mio | 550 h |
| 120 | 8651.04 Mio | 6011.74 Mio | 14662.77 Mio | 1100 h |

### Brennzellen-Anlage

| Ziel-Stufe | Ferronit | Crytite | Gesamt | Amortisation |
|------------|----------|---------|--------|--------------|
| 10 | 15k | 9.8k | 25k | 127 h |
| 20 | 43k | 29k | 72k | 127 h |
| 30 | 164k | 110k | 274k | 180 h |
| 40 | 590k | 393k | 983k | 255 h |
| 60 | 6.89 Mio | 4.59 Mio | 11.48 Mio | 509 h |
| 80 | 93.08 Mio | 62.05 Mio | 155.13 Mio | 1273 h |
| 100 | 960.23 Mio | 640.15 Mio | 1600.38 Mio | 2546 h |
| 120 | 9597.45 Mio | 6398.30 Mio | 15995.75 Mio | 5092 h |

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
| 10 | 34k | 23k | 34k | 25k | 66k | 66k | 57k | 523k | 726k | 581k | 523k | 82k | 42k | 45k | 107k | 150k | 280k | 230k | 314k |
| 20 | 99k | 66k | 92k | 72k | 188k | 188k | 160k | 2.40 Mio | 3.34 Mio | 2.67 Mio | 2.40 Mio | 233k | 118k | 126k | 308k | 436k | 5.23 Mio | 673k | 925k |
| 30 | 374k | 251k | 166k | 274k | 345k | 345k | 292k | 5.86 Mio | 8.14 Mio | 6.51 Mio | 5.86 Mio | 427k | 215k | 230k | 570k | 813k | 97.55 Mio | 1.26 Mio | 1.74 Mio |
| 40 | 1.34 Mio | 901k | 252k | 983k | 531k | 531k | 446k | 11.04 Mio | 15.32 Mio | 12.26 Mio | 11.04 Mio | 658k | 329k | 352k | 882k | 1.27 Mio | 1820.89 Mio | 1.97 Mio | 2.73 Mio |
| 50 | 4.65 Mio | 3.12 Mio | 349k | 3.40 Mio | 742k | 742k | 621k | 18.03 Mio | 25.04 Mio | 20.03 Mio | 18.03 Mio | 919k | 458k | 490k | 1.24 Mio | 1.79 Mio | 33988.44 Mio | 2.79 Mio | 3.86 Mio |

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

Speicher Basis L1: **150.000** · Wachstum **×1.75**/Stufe

| Lager-Stufe | Kapazität |
|-------------|-----------|
| 1 | 150k |
| 5 | 1.41 Mio |
| 10 | 23.09 Mio |
| 20 | 6220.34 Mio |
| 30 | 1675693.83 Mio |
| 40 | 451414139.08 Mio |
| 50 | 121606179561.53 Mio |

Tausch Tageslimit: min. **500.000** oder **80%** Imperiums-Tagesproduktion

## 7) Code-Anker (Rohwerte)

**Forschung Zeit:** L10=1.5h, L20=5.0h, L30=24.0h, L40=72.0h, L60=336.0h, L80=1080.0h, L100=2160.0h, L120=4320.0h

**Forschung Kosten:** L10=3.0k, L20=12k, L30=50k, L35=250k, L38=500k, L40=2.00 Mio, L50=25.00 Mio, L60=50.00 Mio, L80=150.00 Mio, L100=500.00 Mio, L120=1000.00 Mio

**Minen ROI:** L20=50.0h, L40=100.0h, L60=200.0h, L80=500.0h, L100=1000.0h, L120=2000.0h