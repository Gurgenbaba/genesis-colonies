# GC-973 — Planet Conversion Queue / Special Resource Processing

> **Epic:** EPIC-05 Planet Evolution  
> **Status:** 📋 Geplant — **Design-Spec**, kein Implementierungs-Scope von GC-972  
> **Vorgänger:** GC-972F (Entscheidung: Conversion **nicht** in Dead-Hook-Fix)  
> **Owner (geplant):** `game/planet_evolution/conversion.py` (neu, kanonisch laut CORE §17)

---

## Auslöser

Planet-Techs versprechen seit Seed `017` eine Konversions-Warteschlange:

| Tech | Seed-Mechanik | Compile heute |
|------|---------------|---------------|
| `industry_t1_automation` | `unlock_queue.conversion:1` | `queue_limits.conversion` gesetzt |
| `industry_t4_mass_foundry` | `conversion_batch_bonus:1` | **nicht** geparst |

Tabelle `planet_conversion_queue` existiert (Migration `016`). Es gibt **kein** Tick-/Queue-Modul, kein UI, kein API-Endpunkt.

**GC-972-Entscheidung:** Bis GC-973 live ist, UI/Locales beschreiben Conversion nur als *vorbereitet / folgt später*.

---

## Ziel (GC-973)

Spieler können Spezialressourcen (und ggf. Basis-Ressourcen) über eine **planetengebundene Konversions-Queue** in Batches umwandeln — analog zu Planet-Research-Queue, aber eigener `owner_type`.

### Nicht-Ziele

- Kein paralleles Queue-System außerhalb `queue_engine` / PE-Owner
- Kein Frontend-Math für Batch-Größe oder Dauer
- Keine neuen Imperiums-Boni oder Fantasy-Techs

---

## Kanonische Regeln

1. **Queue-Engine:** Jobs mit `owner_type = planet_conversion` (oder bestehendem kanonischen Key aus `016`), `finish_due_work_once` vor Mutation, Reschedule nach Cancel — siehe [QUEUE_STATE_RULES.md](QUEUE_STATE_RULES.md).
2. **Planet-Scope:** `get_context_planet()`; Jobs pro `planet_id`.
3. **Mechanics-Input:**
   - `queue_limits.conversion` aus `compile_planet_mechanics` (bereits von T1)
   - `conversion_batch_bonus` aus T4 (Parsing in `mechanics.py` ergänzen)
4. **Definitions:** Chain-Defs aus `pe_production_chain_definitions` als Vorlage für Inputs/Outputs; keine doppelte Formel im Client.
5. **Tick:** Abschluss in `evolution_tick_planet` / Economy-Pfad; Spezialressourcen via `ensure_special_resource_row` / bestehende Economy-Hooks.

---

## Vorgeschlagene Sub-Tickets

| Ticket | Titel | Scope |
|--------|-------|-------|
| **GC-973A** | `conversion_batch_bonus` parsen + Mechanics-Contract | `mechanics.py`, Tests |
| **GC-973B** | Conversion-Queue Engine (enqueue/finish/cancel) | `conversion.py`, `queue_engine`-Integration |
| **GC-973C** | API + `{ ok, state }` + Dashboard-Cards | Routes dünn, `dashboard.py`, Template |
| **GC-973D** | Tick + Spezialressourcen-Grant | `economy.py` / evolution tick |

Max. 3–5 Dateien pro Sub-Ticket.

---

## UI (später)

- Konversions-Jobs als `gc-card-queue-block` auf Planet-Evolution (Industry-Zone)
- Tech-Popover T1/T4: Text von „vorbereitet“ auf echte Effekte umstellen, sobald GC-973 live
- Keine `location.reload()` — PJAX + `applyActionState`

---

## Akzeptanz (Epic GC-973)

- [ ] T1 erhöht sichtbar `queue_limits.conversion` und erlaubt ersten Job
- [ ] T4 erhöht Batch-Größe messbar (Server-Tick)
- [ ] Cancel rescheduliert Queue korrekt
- [ ] Kein Frontend-Math; Tests decken enqueue/finish/batch ab
- [ ] Locales in allen 9 Sprachen aktualisiert (live, nicht „folgt später“)

---

## Referenzen

- [GC-972_PLANET_TECH_DEAD_MECHANICS.md](GC-972_PLANET_TECH_DEAD_MECHANICS.md) — abgeschlossene Dead-Hooks A–D; E/F deferred
- [GC-974_PLANET_EVOLUTION_BALANCING.md](GC-974_PLANET_EVOLUTION_BALANCING.md) — Alpha-Balancing-Pass (Analyse)
- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) — Owner, keine Parallel-Systeme
- [QUEUE_STATE_RULES.md](QUEUE_STATE_RULES.md)
- [ECONOMY_SYSTEM.md](ECONOMY_SYSTEM.md)
