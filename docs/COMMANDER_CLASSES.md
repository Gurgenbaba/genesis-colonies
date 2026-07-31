# Commander Classes & Skill Trees (EPIC-27)

Account-weites Klassen-System à la Shakes & Fidget: eine dauerhafte Commander-Klasse, linearer Skill-Trunk, kein In-Class-Respec, Klassenwechsel nur gegen Timekeeper.

## Owner

| Modul | Verantwortung |
|-------|----------------|
| `game/commander_classes.py` | Pick, SP-Claim, Unlock, Capstone-Spend, Swap, Serialize |
| `game/commander_class_catalog.py` | Klassen, Skills, Milestones, TK-Swap-Kurve (code-first) |
| `game/effects/effect_resolver.py` | `_apply_commander_class_mods()` nach Alliance |
| `game/timekeeper.py` | Debit bei Class-Swap (`source=class_swap`) |
| `templates/skilltree.html` | PJAX-UI (GC-CLASS-UI-001 cinematic pick) |

Schema: `migrations/123_commander_classes.sql`.

## UI (GC-CLASS-UI-001 … UI-006)

Pick-Phase: Destiny-style **Command Staff** cards — WebP portraits (`static/img/classes/*.webp`), role icons as RGBA WebP (`static/img/classes/icons/{key}.webp`).

Trunk-Phase (GC-CLASS-UI-006): Active Commander bar + **compact skillmap** (5×4 grid fork silhouette, square nodes, SVG elbows). Unlock order remains strictly linear `1→2→3→4→5→6` (no fake branch choice). Node click selects for the inspector dock only; unlock only via dock button. Live patch after unlock (`applyActionState` + commander merge) keeps selection. Skill arts: `static/img/classes/skills/{skill_key}.webp` (`scripts/process_commander_skill_arts.py`). Role icons stay pick-card chips only.

## Design-Lock

| Regel | Wert |
|-------|------|
| Klassen | **Vanguard** · **Forge Lord** · **Archivist** · **Void Admiral** · **Envoy** |
| Scope | Account (`player_id`) — **nicht** PE-Specialization |
| Baum | Linearer Trunk — jeder Knoten notwendig |
| Respec | **Kein** In-Class-Respec |
| SP | Score-Milestones (`player_scores.score_total`) |
| Capstones | Extrem teure Ressourcen vom Context-Planet |
| Swap | Timekeeper → Skills löschen → SP refund → Klasse NULL → Re-Pick |
| Boni | Nur EffectResolver |

## Klassen → Playstyle

| Klasse | Stil | Kern-ER-Keys |
|--------|------|--------------|
| Vanguard | PvP / Raid | `weapon_bonus`, `armor_bonus`, `shield_bonus` |
| Forge Lord | Eco | `metal/crystal/fuel_prod_factor`, `build_time_speed`, `storage_factor` |
| Archivist | Forschung | `research_time_speed` |
| Void Admiral | Flotte | `fleet_speed_multiplier`, `cargo_multiplier`, `fuel_efficiency_factor`, `shipyard_time_speed` |
| Envoy | Intel / Support | `scan_range` (prepared), moderate Support-Keys |

Balance: ~5–15 % soft-cap auf Kern-Keys. Ersetzt weder Research, Buildings noch PE.

## Progression

1. Claim SP aus Score-Milestones (idempotent, `player_commander_sp_claims`).
2. Trunk-Nodes kosten SP; Node *n+1* erst wenn Vorgänger `max_rank`.
3. Capstones: hohe Ressourcenkosten (Ferronit/Crytite/Brennzellen) vom Context-Planet.
4. Swap: TK-Kosten steigen mit `swap_count` (Catalog-Kurve).

## API

| Route | Aktion |
|-------|--------|
| `POST /api/commander/class/pick` | Klasse setzen (nur wenn NULL) |
| `POST /api/commander/sp/claim` | fällige Milestones claimen |
| `POST /api/commander/skills/unlock` | nächsten Rank / Capstone |
| `POST /api/commander/class/swap` | TK-Debit + Refund |
| `GET /skilltree` | PJAX-Page |
| Game-State | `commander` Slice |

Responses: `{ ok, reason?, state, commander }` + `applyActionState`.

## EffectResolver

Merge order: … → Inventory Boosters → Alliance → **Commander Class**.

Shipyard/Defense lesen `shipyard_time_speed` / `defense_time_speed` über den vollen EffectResolver (nicht nur Directive-Helper).

## Tickets

| Ticket | Fokus |
|--------|--------|
| GC-CLASS-000 | Dieses Doc + CORE §17 / ROADMAP / EPICS |
| GC-CLASS-001 | Migration + Catalog |
| GC-CLASS-002 | Pick + SP + lineare Unlocks |
| GC-CLASS-003 | Capstone-Kosten |
| GC-CLASS-004 | ER-Hook + Shipyard/Defense-Bridge |
| GC-CLASS-005 | Timekeeper Swap |
| GC-CLASS-006 | `/skilltree` UI + Locales |
| GC-CLASS-007 | Admin Effects-Debug + Tests |

## Abgrenzung

- Keine aktiven Cooldown-Skills in v1
- Keine Ark-Token-/Shop-Währung für Swap
- Kein zweites Research / keine PE-Hijack
