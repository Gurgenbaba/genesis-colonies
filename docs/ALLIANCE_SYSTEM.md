# Alliance System — Genesis Colonies (EPIC-09)

**Status:** ✅ **MVP complete** (GC-AL-MVP-01 … GC-AL-MVP-09) — Beta Gate item erfüllt. Combat-/Diplomatie-Deep-Hooks (Kriegs-Meta, Bündnis-Transport) bewusst post-Beta.

**Owner:** `game/alliance.py` · Catalog: `game/alliance_catalog.py`  
**UI:** `/alliance` · `GC.modules.alliance` · `templates/alliance.html`  
**API:** `POST /api/alliance/*` → `{ ok, state, alliance }` (errors via `_alliance_error_json` with `state` + `alliance`)

## Scope (GC-AL-001 … GC-AL-009 + GC-AL-MVP)

| Ticket | Feature | Status |
|--------|---------|--------|
| GC-AL-001 | Gründen, Beitreten, Verlassen, Beschreibung, Ränge, Mitgliederlimit 5 | ✅ |
| GC-AL-002 | Spendenpool (metal/crystal/fuel_cells), dynamischer Cap, Donation-Log | ✅ |
| GC-AL-003 | `alliance_level` / `alliance_xp`, XP aus Spenden + Projekten, Tagescap Spenden-XP | ✅ |
| GC-AL-004 | 5 Allianz-Technologien, Pool-Kosten, ein aktives Projekt, Effekte via EffectResolver | ✅ |
| GC-AL-005 | 5 Allianz-Gebäude, `alliance_buildings` / `alliance_projects` (kein planetarer build_queue) | ✅ |
| GC-AL-006 | Diplomatie MVP: neutral/nap/alliance/war, Anfragen, UI (Deep-Gameplay-Hooks später) | ✅ |
| GC-AL-008 | Bewerbungssystem: `recruitment_mode`, Pending-UI, Withdraw, Accept/Decline, Notifications | ✅ |
| GC-AL-009 | Logo-Upload + Auslieferung | ✅ |
| GC-AL-MVP-02–04 | Rollenverwaltung, Rekrutierung, Profil, einheitliche Error-Payloads | ✅ |
| GC-AL-MVP-05 | Spenden transaktionssicher, Pool-Caps, Officer-Nachrichten, Donation-Log | ✅ |
| GC-AL-MVP-06 | Projekte: Rechte/Pool/1× aktiv, server-Timing-Payload, Finish wendet Level an | ✅ |
| GC-AL-MVP-07 | Boni via EffectResolver + Expedition-Hook + Same-Alliance-Hold | ✅ |
| GC-AL-MVP-08 | UI/PJAX: `GC.fetchGameAction`, `applyActionState`, kein Full Reload | ✅ |
| GC-AL-MVP-09 | Tests + Doc Reality Sync | ✅ |

## API routes (canonical)

| Method | Route | Notes |
|--------|-------|-------|
| GET | `/api/alliance/state` | Hub payload |
| GET | `/api/alliance/profile/<id>` | Public profile |
| GET | `/api/alliance-logo/<id>` | Logo blob |
| POST | `/api/alliance/create` | Founder → leader |
| POST | `/api/alliance/join` | Direct join (`open` mode) |
| POST | `/api/alliance/apply` | Application |
| POST | `/api/alliance/application/withdraw` | |
| POST | `/api/alliance/application/respond` | Officer accept/decline + applicant notify |
| POST | `/api/alliance/leave` | Leader solo → disband |
| POST | `/api/alliance/disband` | Leader only |
| POST | `/api/alliance/description` | Officer |
| POST | `/api/alliance/recruitment` | Officer — `mode`: open/application_only/closed |
| POST | `/api/alliance/donate` | Planet scope |
| POST | `/api/alliance/project/start` | Officer |
| POST | `/api/alliance/logo` | Officer upload |
| POST | `/api/alliance/profile` | Officer — `name`, `tag`, `description` (partial) |
| POST | `/api/alliance/member/role` | Leader — `player_id`, `role` (`officer`/`member`) |
| POST | `/api/alliance/member/kick` | Leader/Officer (Officer → members only) |
| POST | `/api/alliance/leader/transfer` | Leader — `player_id` (existing member; old leader → officer) |
| POST | `/api/alliance/diplomacy/send` | Officer |
| POST | `/api/alliance/diplomacy/respond` | Officer |

**Error envelope:** `{ ok: false, error, reason, state, alliance }` — immer frischer Game-State + Alliance-State.

## UI / PJAX (GC-AL-MVP-08)

- Modul: `static/main.js` → `GC.modules.alliance` / `initAlliance()`
- Alle Mutations-Actions: `allianceAction()` → `GC.fetchGameAction` + `applyActionState(res, reason)`
- Hub-Refresh nach strukturellen Änderungen: `allianceReloadHub()` → `GC.navigateTo("/alliance", { push: false, force: true })` oder `GC.reloadCurrentPage({ force: true })`
- **Verboten:** `location.reload()`, `location.href =`, `location.assign()` im Alliance-Modul
- Logo-Upload: multipart `fetch` (Ausnahme — kein JSON-Body); Response weiterhin `{ ok, state, alliance }`
- Native Form-Submit blockiert (`allianceBlockNativeSubmit`); Buttons `type="button"` + `data-alliance-submit`
- Projektfortschritt: SSR + Patch aus Server — `started_at`, `finish_at`, `duration_seconds`, `progress_pct` (keine clientseitige Dauer-Schätzung)

## Recruitment & Applications (GC-AL-008)

**Migration 089:** `alliances.recruitment_mode` — `open` | `application_only` | `closed` (Default: `open`).

| Modus | Direktbeitritt (Tag) | Bewerbung |
|-------|----------------------|-----------|
| `open` | ja | ja |
| `application_only` | nein | ja |
| `closed` | nein | nein |

- Bewerbung erfordert **Nachricht** (max 256 Zeichen); genau eine pending-Bewerbung pro Spieler.
- Leader/Officer sehen pending-Bewerbungen im Mitglieder-Tab; Accept/Decline per AJAX.
- Officer können `recruitment_mode` per `POST /api/alliance/recruitment` ändern (UI: Modus-Buttons im Hub).
- System-Nachricht an Leader/Officer bei neuer Bewerbung; an Bewerber bei Accept/Decline (`messages.create_message`, i18n).
- **Logo (GC-AL-009):** Officer/Leader upload via `POST /api/alliance/logo` (gleiche Pipeline wie Playercard-Avatar, 256×256 WebP). Auslieferung: `GET /api/alliance-logo/<id>`.
- Guest-UI: Pending-Panel + Withdraw; Create/Join ausgeblendet solange Bewerbung pending.
- Hook für P3: `can_manage_applications(role)` — später Recruiter-Rolle.

## Architecture

- **Single owner** — keine parallele Allianz-Domäne; Chat nutzt weiterhin `get_player_alliance()`.
- **Planet scope** — Spenden ziehen Ressourcen vom **Context-Planet** (`get_context_planet()`).
- **Projekt-Queue** — `alliance_projects` mit `finish_due_alliance_projects()`; aufgerufen aus `refresh_player_live_state()` für Mitglieder und beim Alliance-State-Load. **Nicht** in `queue_engine` (eigene Domäne, dokumentiert).
- **Ein aktives Projekt** — DB partial unique index (Migration 092) + Runtime-Guard `project_active`.
- **Boni** — `get_alliance_effect_modifiers()` → `EffectResolver._apply_alliance_mods()`; Expedition-Loot via `get_alliance_expedition_loot_multiplier()` in `fleet.py`.
- **Same-Alliance Hold** — `are_players_allied()` in `fleet.py` → `target_type = ally_planet` → Hold erlaubt wenn Alliance-Schema aktiv.

## Ränge & Rechte

| Rolle | Rechte |
|-------|--------|
| `leader` | Alles; Role/Kick/Transfer/Disband; Leave nur nach Transfer oder als letzter Member |
| `officer` | Beschreibung, Rekrutierung, Bewerbungen, Projekte, Diplomatie, Logo, Profil; Kick nur `member` |
| `member` | Spenden, Ansehen, Verlassen |

Legacy-Rolle `owner` wird bei Migration zu `leader` normalisiert.

## Spendenpool & Cap

```text
pool_cap[resource] = sum(2 günstigste verfügbare Projekt-Kosten[resource])
                   × (1 + logistics_depot% + trade_coordination%)
```

Keine Überfüllung: Spende schlägt fehl mit `pool_cap_exceeded`. Officer erhalten System-Nachricht bei Spende.

## Allianz-Projekte

- Start: Officer, Pool-Abzug transaktionssicher, genau ein `status = active`
- `active_project` Payload (serverseitig): `started_at`, `finish_at`, `duration_seconds`, `progress_pct`
- Finish: wendet `alliance_buildings` / `alliance_technologies` an, XP-Grant, Member-Nachricht
- **Keine** planetare Build-/Research-Queue

## Progression

- **XP:** Spenden (klein, `DONATION_XP_DAILY_CAP` pro Spieler/Tag) + Projektabschluss (`cost_sum / PROJECT_XP_DIVISOR`) + World-Boss-Schaden (`grant_alliance_xp`, Formel in `world_boss.alliance_xp_from_boss_damage`).
- **Level:** `alliance_level_from_xp()` — schaltet Gebäude/Tech-Voraussetzungen frei, keine Pflicht-Mega-Boni.

## Technologien (serverseitig)

| Key | Effekt | Max |
|-----|--------|-----|
| `research_network` | `research_time_speed` | +3 % |
| `expedition_coordination` | `expedition_loot_mult` + Expeditions-Fundchance | +5 % Beute, +4 % Fund |
| `industrial_logistics` | Produktion (metal/crystal/fuel) | +2 % |
| `defensive_protocols` | `armor_bonus` / `shield_bonus` | +3 % |
| `trade_coordination` | Pool-Cap % + Projektdauer-Reduktion | +10 % Cap |

## Gebäude

| Key | Funktion |
|-----|----------|
| `alliance_headquarters` | +2 Mitglieder/Stufe (Basis 5); Runtime-Limit wird aus HQ-Level abgeleitet |
| `research_archive` | Voraussetzung Alliance-Techs; fertige Projekte schalten Techs sofort im State frei |
| `expedition_office` | Voraussetzung Expedition Coordination; +Fundchance % pro Stufe |
| `logistics_depot` | Pool-Cap-Bonus |
| `diplomacy_center` | Diplomatie-Slots freischalten |

## Diplomatie

- Beziehungen: `neutral`, `nap`, `alliance`, `war`
- Krieg: sofort aktiv; NAP/Bündnis: Anfrage + Annahme
- Sichtbar auf Alliance-Tab und PlayerCard (`alliance_label`)
- **Post-Beta:** Combat-Integration (Kriegs-Meta), Fleet-Transport auf Bündnis-Planeten, Diplomatie-basierte Mission-Locks

## Schema (Migration 088–092)

- `alliances` — description, level, xp, pool_*, member_limit, recruitment_mode (089)
- `alliance_donations`, `alliance_buildings`, `alliance_technologies`, `alliance_projects`
- `alliance_applications`, `alliance_diplomacy`, `alliance_diplomacy_requests`
- **092:** Partial unique indexes (active project, pending diplomacy, pending application per player)

## Tests

```bash
python -m pytest tests/test_alliance.py -q
```

Abdeckung: Schema, CRUD, Spenden/Pool, Projekte, Boni/EffectResolver, Expedition-Hook, Hold-Permission, Rollen, Rekrutierung, Diplomatie, API-Envelopes, PJAX-JS-Contract, SSR-Projekt-Timing.

## Related

- [CORE_ARCHITECTURE.md](CORE_ARCHITECTURE.md) §17 — Owner `game/alliance.py`
- [EFFECTS.md](EFFECTS.md) — Alliance modifier extension
- [AJAX_PJAX_CONTRACT.md](AJAX_PJAX_CONTRACT.md) — Actions mit `applyActionState`
- [BETA_GATE.md](BETA_GATE.md) — Alliance MVP Gate
