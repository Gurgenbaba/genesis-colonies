# Genesis Colonies — Ankerkurven (Code-Stand, Universum-Speed ×1)

**Referenz:** Galaxieslot 9 · Energie 100% · Forschung 0 · `production_speed=1` · `build_speed=1` · `research_speed=1`

## 1) Produktionsformel (GC-820 / GC-860 Ferdi)

```
Produktion/h = Multiplikator × Level × 1.075^Level + 365
             × production_speed × Slot × Temperatur × Forschung × Energie × …
```

| Ressource | Multiplikator | Gebäude |
|-----------|---------------|---------|
| Ferronit | 100.0 | metal_mine |
| Crytite | 66.0 | crystal_mine |
| Brennzellen | 33.0 | fuel_cell_plant |

### Produktion/h (Slot 9, Speed ×1)

| Mine-Stufe | Ferronit/h | Crytite/h | Brennzellen/h |
|------------|------------|-----------|---------------|
| 10 | 2.4k | 1.7k | 1.2k |
| 20 | 8.9k | 6.0k | 3.6k |
| 30 | 27k | 18k | 10k |
| 40 | 73k | 48k | 28k |
| 60 | 460k | 304k | 175k |
| 80 | 2.61 Mio | 1.72 Mio | 989k |
| 100 | 13.83 Mio | 9.13 Mio | 5.25 Mio |
| 120 | 70.50 Mio | 46.53 Mio | 26.75 Mio |

### Produktionsgewinn pro Upgrade (+1 Stufe, Delta/h)

| Ziel-Stufe | Ferronit +/h | Crytite +/h | Brennzellen +/h |
|------------|--------------|-------------|-----------------|
| 10 | 336 | 221 | 127 |
| 20 | 988 | 652 | 375 |
| 30 | 2.6k | 1.7k | 1.0k |
| 40 | 6.7k | 4.4k | 2.5k |
| 60 | 39k | 26k | 15k |
| 80 | 212k | 140k | 80k |
| 100 | 1.09 Mio | 722k | 415k |
| 120 | 5.47 Mio | 3.61 Mio | 2.07 Mio |

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
| 10 | 2.5k | 1.7k | 834 |
| 20 | 10k | 6.7k | 3.3k |
| 30 | 22k | 15k | 7.3k |
| 40 | 40k | 27k | 13k |
| 60 | 120k | 80k | 40k |
| 80 | 400k | 267k | 133k |
| 100 | 1.20 Mio | 800k | 400k |
| 120 | 2.40 Mio | 1.60 Mio | 800k |

### Alle Technologien — Stufe 30 (Speed ×1, Labor L1, ohne Tech-Boni auf Zeit)

| Technologie | Ferronit | Crytite | Dauer | Tier Zeit | Tier Kosten |
|-------------|----------|---------|-------|-----------|-------------|
| armor_tech | 28k | 16k | 1.4 Tage | 1.42 | 2.00 |
| buildtime_tech | 22k | 12k | 11.6 h | 1.17 | 1.53 |
| drone_tech | 22k | 13k | 1.2 Tage | 1.25 | 1.60 |
| energy_tech | 15k | 7.3k | 1.0 Tage | 1.00 | 1.00 |
| engine_tech | 32k | 23k | 1.6 Tage | 1.58 | 2.53 |
| fuel_efficiency | 35k | 18k | 1.7 Tage | 1.67 | 2.40 |
| mining_tech | 18k | 8.8k | 1.1 Tage | 1.08 | 1.20 |
| navigation_tech | 29k | 22k | 1.5 Tage | 1.50 | 2.33 |
| shield_tech | 32k | 19k | 1.6 Tage | 1.58 | 2.33 |
| storage_tech | 12k | 12k | 22.0 h | 0.92 | 1.07 |
| weapon_tech | 26k | 13k | 1.3 Tage | 1.33 | 1.80 |

## 3) Minen-Upgrades — Kosten & Ziel-Amortisation (live)

Amortisation = Payback in **Produktionsstunden** der jeweiligen Ressource (Slot 9, Speed ×1).

### Ferronit-Mine

| Ziel-Stufe | Ferronit | Crytite | Gesamt | Amortisation |
|------------|----------|---------|--------|--------------|
| 10 | 17k | 5.6k | 22k | 50 h |
| 20 | 49k | 16k | 66k | 50 h |
| 30 | 187k | 62k | 250k | 71 h |
| 40 | 671k | 224k | 895k | 100 h |
| 60 | 7.84 Mio | 2.61 Mio | 10.46 Mio | 200 h |
| 80 | 106.01 Mio | 35.34 Mio | 141.34 Mio | 500 h |
| 100 | 1093.60 Mio | 364.53 Mio | 1458.13 Mio | 1000 h |
| 120 | 10930.43 Mio | 3643.48 Mio | 14573.91 Mio | 2000 h |

### Crytite-Mine

| Ziel-Stufe | Ferronit | Crytite | Gesamt | Amortisation |
|------------|----------|---------|--------|--------------|
| 10 | 8.9k | 6.2k | 15k | 28 h |
| 20 | 26k | 18k | 44k | 28 h |
| 30 | 99k | 69k | 167k | 39 h |
| 40 | 354k | 246k | 600k | 56 h |
| 60 | 4.14 Mio | 2.88 Mio | 7.01 Mio | 111 h |
| 80 | 55.93 Mio | 38.87 Mio | 94.80 Mio | 278 h |
| 100 | 577.03 Mio | 400.99 Mio | 978.01 Mio | 556 h |
| 120 | 5767.36 Mio | 4007.82 Mio | 9775.18 Mio | 1111 h |

### Brennzellen-Anlage

| Ziel-Stufe | Ferronit | Crytite | Gesamt | Amortisation |
|------------|----------|---------|--------|--------------|
| 10 | 9.8k | 6.5k | 16k | 129 h |
| 20 | 29k | 19k | 48k | 129 h |
| 30 | 110k | 73k | 183k | 182 h |
| 40 | 393k | 262k | 655k | 257 h |
| 60 | 4.59 Mio | 3.06 Mio | 7.65 Mio | 514 h |
| 80 | 62.05 Mio | 41.37 Mio | 103.42 Mio | 1286 h |
| 100 | 640.15 Mio | 426.77 Mio | 1066.92 Mio | 2571 h |
| 120 | 6398.30 Mio | 4265.53 Mio | 10663.83 Mio | 5143 h |

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
| 10 | 22k | 15k | 5.6k | 16k | 13k | 13k | 11k | 22k | 30k | 36k | 35k | 41k | 21k | 23k | 60k | 83k | 114k | 128k | 174k |
| 20 | 66k | 44k | 15k | 48k | 38k | 38k | 32k | 62k | 85k | 101k | 98k | 116k | 59k | 63k | 171k | 242k | 332k | 374k | 514k |
| 30 | 250k | 167k | 28k | 183k | 69k | 69k | 58k | 114k | 158k | 184k | 181k | 214k | 107k | 115k | 317k | 452k | 623k | 701k | 967k |
| 40 | 895k | 600k | 42k | 655k | 106k | 106k | 89k | 177k | 245k | 282k | 278k | 329k | 164k | 176k | 490k | 704k | 974k | 1.10 Mio | 1.52 Mio |
| 50 | 3.10 Mio | 2.08 Mio | 58k | 2.27 Mio | 148k | 148k | 124k | 249k | 344k | 392k | 389k | 460k | 229k | 245k | 688k | 992k | 1.38 Mio | 1.55 Mio | 2.15 Mio |

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

**Forschung Kosten:** L10=2.5k, L20=10k, L30=22k, L40=40k, L60=120k, L80=400k, L100=1.20 Mio, L120=2.40 Mio

**Minen ROI:** L20=50.0h, L40=100.0h, L60=200.0h, L80=500.0h, L100=1000.0h, L120=2000.0h