# Alliance System — Genesis Colonies (EPIC-09)

**Owner:** `game/alliance.py` · Catalog: `game/alliance_catalog.py`  
**UI:** `/alliance` · `GC.modules.alliance` · `templates/alliance.html`  
**API:** `POST /api/alliance/*` → `{ ok, state, alliance }`

## Scope (GC-AL-001 … GC-AL-006)

| Ticket | Feature |
|--------|---------|
| GC-AL-001 | Gründen, Beitreten, Verlassen, Tag/Name/Beschreibung, Ränge, Mitgliederlimit 5 |
| GC-AL-002 | Spendenpool (metal/crystal/fuel_cells), dynamischer Cap, Donation-Log |
| GC-AL-003 | `alliance_level` / `alliance_xp`, XP aus Spenden + Projekten, Tagescap Spenden-XP |
| GC-AL-004 | 5 Allianz-Technologien, Pool-Kosten, ein aktives Projekt, Effekte via EffectResolver |
| GC-AL-005 | 5 Allianz-Gebäude, `alliance_buildings` / `alliance_projects` (kein planetarer build_queue) |
| GC-AL-006 | Diplomatie MVP: neutral/nap/alliance/war, Anfragen, PlayerCard-Label |
| GC-AL-008 | Bewerbungssystem: `recruitment_mode`, Pending-UI, Withdraw, Accept/Decline |

## Recruitment & Applications (GC-AL-008)

**Migration 089:** `alliances.recruitment_mode` — `open` | `application_only` | `closed` (Default: `open`).

| Modus | Direktbeitritt (Tag) | Bewerbung |
|-------|----------------------|-----------|
| `open` | ja | ja |
| `application_only` | nein | ja |
| `closed` | nein | nein |

- Bewerbung erfordert **Nachricht** (max 256 Zeichen); genau eine pending-Bewerbung pro Spieler.
- Leader/Officer sehen pending-Bewerbungen im Mitglieder-Tab; Accept/Decline per AJAX.
- Optional: System-Nachricht an Leader/Officer bei neuer Bewerbung (`messages.create_message`).
- **Logo (GC-AL-009):** Officer/Leader upload via `POST /api/alliance/logo` (gleiche Pipeline wie Playercard-Avatar, 256×256 WebP). Auslieferung: `GET /api/alliance-logo/<id>`.
- Guest-UI: Pending-Panel + Withdraw; Create/Join ausgeblendet solange Bewerbung pending.
- API: `POST /api/alliance/apply`, `POST /api/alliance/application/withdraw`, `POST /api/alliance/application/respond`.
- Hook für P3: `can_manage_applications(role)` — später Recruiter-Rolle.

## Architecture

- **Single owner** — keine parallele Allianz-Domäne; Chat nutzt weiterhin `get_player_alliance()`.
- **Planet scope** — Spenden ziehen Ressourcen vom **Context-Planet** (`get_context_planet()`).
- **Projekt-Queue** — `alliance_projects` mit `finish_due_alliance_projects()`; aufgerufen aus `refresh_player_live_state()` für Mitglieder und beim Alliance-State-Load. **Nicht** in `queue_engine` (eigene Domäne, dokumentiert).
- **Boni** — `get_alliance_effect_modifiers()` → `EffectResolver._apply_alliance_mods()`; Expedition-Loot via `directive_flags.expedition_loot_mult` in `fleet.py`.

## Ränge & Rechte

| Rolle | Rechte |
|-------|--------|
| `leader` | Alles inkl. Transfer-Constraint beim Verlassen (letzter Leader löscht Allianz) |
| `officer` | Beschreibung, Bewerbungen, Projekte, Diplomatie |
| `member` | Spenden, Ansehen, Verlassen |

Legacy-Rolle `owner` wird bei Migration zu `leader` normalisiert.

## Spendenpool & Cap

```text
pool_cap[resource] = sum(2 günstigste verfügbare Projekt-Kosten[resource])
                   × (1 + logistics_depot% + trade_coordination%)
```

Keine Überfüllung: Spende schlägt fehl mit `pool_cap_exceeded`.

## Progression

- **XP:** Spenden (klein, `DONATION_XP_DAILY_CAP` pro Spieler/Tag) + Projektabschluss (`cost_sum / PROJECT_XP_DIVISOR`).
- **Level:** `alliance_level_from_xp()` — schaltet Gebäude/Tech-Voraussetzungen frei, keine Pflicht-Mega-Boni.

## Technologien (serverseitig)

| Key | Effekt | Max |
|-----|--------|-----|
| `research_network` | `research_time_speed` | +3 % |
| `expedition_coordination` | `expedition_loot_mult` | +5 % |
| `industrial_logistics` | Produktion (metal/crystal/fuel) | +2 % |
| `defensive_protocols` | `armor_bonus` / `shield_bonus` | +3 % |
| `trade_coordination` | Pool-Cap % + Projektdauer-Reduktion | +10 % Cap |

## Gebäude

| Key | Funktion |
|-----|----------|
| `alliance_headquarters` | +2 Mitglieder/Stufe (Basis 5) |
| `research_archive` | Voraussetzung Alliance-Techs |
| `expedition_office` | Voraussetzung Expedition Coordination |
| `logistics_depot` | Pool-Cap-Bonus |
| `diplomacy_center` | Diplomatie-Slots freischalten |

## Diplomatie

- Beziehungen: `neutral`, `nap`, `alliance`, `war`
- Krieg: sofort aktiv; NAP/Bündnis: Anfrage + Annahme
- Sichtbar auf Alliance-Tab und PlayerCard (`alliance_label`)
- **Noch keine** Combat-/Fleet-Hold-Integration

## Schema (Migration 088)

- `alliances` — erweitert um description, level, xp, pool_*, member_limit, recruitment_mode (089)
- `alliance_donations`, `alliance_buildings`, `alliance_technologies`, `alliance_projects`
- `alliance_applications`, `alliance_diplomacy`, `alliance_diplomacy_requests`

## Tests

```bash
python -m pytest tests/test_alliance.py -v
```

## Related

- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) §17 — Owner `game/alliance.py`
- [EFFECTS.md](EFFECTS.md) — Alliance modifier extension
- [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md) — Actions mit `applyActionState`
