# Genesis Story Ops — Immersive Lore / Side Ops

> **Genesis Story Ops sind autorisierte Story-Arcs und Side Ops — kein Daily-Quest-System, kein Parallel-Fortschritt zu Imperial Directives.**  
> Fortschritt entsteht aus bestehenden Gameplay-Events (geteilter Bus) und Spieler-Choices in Transmissionen. Neue Missionen = Content-Pack + Locales.

Epic: **EPIC-25 Genesis Story Ops** · Tickets: GC-2500…GC-2505 · Owner: `game/story/`

---

## Kernthese

Der Spieler empfängt **Übertragungen** (High Command / Ark-Signal / Androgyn-Kontakt), handelt im echten Spiel, und die Story reagiert — nicht eine separate Quest-Insel.

```text
Gameplay-Event (Build, Fleet, Combat, …)
        │
        ▼
directives.progress.apply_directive_events  →  Imperial Directives
        │
        └── fan-out → story.apply_gameplay_events  →  Story Ops progress
                │
                ▼
Transmission UI (/story) + Flags + Meta-Rewards + Inbox/Codex hooks
```

---

## Abgrenzung (GC-000)

| System | Scope | Story Ops |
|--------|-------|-----------|
| **Imperial Directives** (`game/directives/`) | Rotierende Daily/Weekly Ops, Claim-Loot | **Anderer Owner** — teilt nur den Event-Bus |
| **PE Events** | Planet-scoped Random Choices | Kann als Gate/Flag genutzt werden; ersetzt PE nicht |
| **Codex** | Lore-Archiv | Story unlockt Fragmente (`story_flag`); keine zweite Wiki |
| **Chronicles** | Kampf-/Expeditions-Archiv | Delivery optional; kein Progress-Owner |
| **Messages** | Inbox | Story-Beats können System-Nachrichten senden |
| **Fleet missions** | Gameplay | Objectives hören Fleet-Events |

**Verboten:**

- Frontend-Zielberechnung (Regel 16)
- Eigenes Polling/Tick für Story-Progress
- Zweite Queue / Combat-P2W-Rewards
- Daily-Reset der Story (Story ist **persistent**)
- Parallel-Modul `game/quests/` neben Directives als Daily-Ops-Duplikat

---

## Owner & Dateien

| Rolle | Pfad |
|-------|------|
| Engine / State | `game/story/` |
| Content Packs | `game/story/packs/*.json` |
| Schema | `migrations/116_genesis_story_ops.sql` |
| UI | `templates/story.html`, CSS in `static/style.css`, JS in `static/main.js` |
| API | `/story`, `/api/story/state`, `/api/story/advance`, `/api/story/choice` |

---

## Pack-Schema (Authoring)

Packs liegen unter `game/story/packs/<pack_id>.json`.

```json
{
  "pack_id": "ark_signal",
  "version": 1,
  "arcs": [
    {
      "arc_id": "main",
      "kind": "main",
      "contact_key": "ark",
      "title_key": "story_ark_main_title",
      "start_when": { "always": true },
      "chapters": [
        {
          "chapter_id": "ch1",
          "beats": [
            {
              "beat_id": "intro",
              "type": "transmission",
              "title_key": "…",
              "body_key": "…",
              "cta_key": "story_cta_continue"
            },
            {
              "beat_id": "build_once",
              "type": "objective",
              "objective_key": "upgrade_buildings",
              "objective_kind": "count",
              "target": 1,
              "filters": {},
              "title_key": "…",
              "body_key": "…"
            },
            {
              "beat_id": "branch",
              "type": "choice",
              "title_key": "…",
              "body_key": "…",
              "choices": [
                { "id": "pursue", "label_key": "…", "set_flags": ["androgyn_pursue"] },
                { "id": "archive", "label_key": "…", "set_flags": ["androgyn_archive"] }
              ]
            },
            {
              "beat_id": "loot",
              "type": "reward",
              "grants": [
                { "kind": "inventory", "item_key": "container_basic", "amount": 1 },
                { "kind": "flag", "flag": "ark_signal_main_done" },
                { "kind": "codex_flag", "flag": "codex_ark_signal" },
                { "kind": "notify", "subject_key": "…", "body_key": "…" }
              ]
            },
            {
              "beat_id": "wait_flag",
              "type": "gate",
              "require_flags_all": ["ark_signal_main_done"]
            }
          ]
        }
      ]
    }
  ]
}
```

### Beat-Typen

| Type | Verhalten |
|------|-----------|
| `transmission` | Warte auf `POST /api/story/advance` |
| `objective` | Zählt Gameplay-Events (gleiche Keys wie Directives) |
| `choice` | Warte auf `POST /api/story/choice` mit `choice_id` |
| `reward` | Auto-grant, dann Advance |
| `gate` | Auto-advance wenn Flags erfüllt, sonst warten |

### `start_when`

- `{ "always": true }` — sofort
- `{ "flags_all": ["…"] }` / `{ "flags_any": ["…"] }`
- Side-Arcs starten erst wenn Conditions met (nach Main-Flags)

**Neue Sidequest ohne Engine-Änderung:** neues Pack-JSON + Locale-Keys (+ optional Asset).

---

## Belohnungen

Nur Meta:

- Inventory-Container / Booster (`grant_inventory_item`)
- Story-Flags / Codex-`story_flag`-Unlocks
- Inbox-Systemnachricht

**Kein** Schiff, Defense, Rohstoff-Stack, Combat-P2W.

Default: narrative Rewards **auto-grant** beim Reward-Beat (kein Claim-UI wie Directives).

---

## Immersion UX

- Route `/story` — Transmission-Surface (industrial sci-fi, eckig, Scanline)
- **Center Focus Layout:** zentrierter Hero-Orb (Story-Player) → Meta/Übertragung → **Audio-Controls** (getrennt von Story-Actions) → horizontales **Arc-Karussell** → optionale Mission-/Belohnungs-Zeile
- **Arc-Karussell** (ersetzt TOC links): Cards mit `kind_label`, Titel, Kapitel-Untertitel, Status; Focus `pack_id`+`arc_id` ohne Reload; Completed lesbar/anklickbar; Locked nur wenn Status `locked`
- **Nav:** rechte Meta-Leiste unter **Community** (nicht KOMMANDO links — Platz)
- Sidebar-Badge bei aktiver Transmission/Choice
- Kontakt/Hero: **gewählter Living Commander** als Sprecher-Portrait (`story.narrator` aus `commander_classes.story_narrator_slice`, Katalog-Pfad) — Fallback Kreis-Orb wenn keine Klasse gewählt; Wellen-Ringe + EQ bei TTS `is-speaking` / `is-paused`
- **Neural Contact Voice:** `edge-tts` (DE: **KillianNeural**, EN: ChristopherNeural) via `POST /api/story/tts` → MP3-Cache. Prosody **v6**: Plain-Text, Absatz-Pausen via `…`, Rate/Pitch `-6%`/`-3Hz`, `[G:S:P]` spoken as position labels. Client: **AbortController + Session-Token**; when neural is advertised, **no silent browser-woman fallback** (toast + retry). Server: 45s timeout, 2 attempts, volume cache beside `GC_DB_PATH`. Override: `STORY_TTS_VOICE` / `STORY_TTS_RATE` / `STORY_TTS_PITCH` / `STORY_TTS_TIMEOUT_S`. Fallback Browser-TTS only if `edge-tts` missing.
- Mission-Card nur bei Objective-Beat; Reward-Card = Auto-Grant-Hinweis + Ark-Bestand/Free-Shop (kein erfundenes Kapitel-Reward-Preview)
- PJAX: `GC.fetchGameAction` → `{ ok, state, story }` → `applyActionState` + lokales `_renderStoryOpsState`; TTS stoppt in `cleanupPage`; Carousel wheel/scroll unbound in `registerCleanup`
- Kein `location.reload()`

---

## Ticket-Zerlegung

| Ticket | Fokus |
|--------|-------|
| GC-2500 | Dieses Master-Doc + §17 / EPICS / Abgrenzung Directives |
| GC-2501 | Engine + Migration + Fan-out + Tests |
| GC-2502 | UI + APIs + i18n |
| GC-2503 | Pack `ark_signal` (Main + 2 Sides, Androgyn) |
| GC-2504 | Codex-Hooks + Inbox-Delivery |
| GC-2505 | Pack-Validation-Tests + Admin read-only Preview |
| **GC-2510** | Lore Bible + Phase-2 Act-Map |
| **GC-2511** | Act I Expansion (`ark_signal` v3+) |
| **GC-2512** | Act II `living_lattice` |
| **GC-2513…2515** | Birth / Heat / Anomaly+Unlabeled |
| **GC-2516** | Ark-Token (storage: `story_scrap_token`) |
| **GC-2517** | Free Shop (Ark-Token redeem on `/shop`) |
| **GC-2519** | Kapitel-Drip Ark-Token (Engine-owned, idempotent) |
| **GC-2518** | Side-Ops Year Band |
| **GC-WB-TAME** | Secondary Ark-Token earn: World Boss companion missions (`story_scrap_token` via inventory grant; Free Shop spend unchanged) |

## Phase 2 — Imperium Chronicle (Jahres-Lore)

Siehe [GENESIS_LORE_BIBLE.md](GENESIS_LORE_BIBLE.md). Packs: `ark_signal`, `living_lattice`, `birth_of_worlds`, `heat_and_shadow`, `anomaly_protocol`, `unlabeled_depth`, `side_ops_year` — je mit `season_code`/`season_key` (TOC-Badge). Side-Ops Year One: 7 Arcs. Contact-Orb + **Free Shop** (`/shop` Tab). **Ark-Token Kapitel-Drip:** Engine vergibt bei Kapitelabschluss (Main 2 / Finale 6 / Side 4), Catch-up in `ensure_player_story`. **Zusätzlich:** gezähmte World-Boss-Companions können Missionen für Ark-Token abschließen ([WORLD_BOSS_SYSTEM.md](WORLD_BOSS_SYSTEM.md) GC-WB-TAME) — gleiche Inventory-Währung, kein paralleler Token.

---

## Tests

- `tests/test_story_ops_engine.py` — fan-out, advance, choice, rewards, false-completion repair, **badge read-only** (no `ensure` on poll)
- `tests/test_story_packs_valid.py` — alle Packs gegen Schema
- `tests/test_story_ark_chapter_tokens.py` — Kapitel-Drip Ark-Token
- Nav badge: `count_story_attention` is **read-only** — never on the `/api/game-state` write path
- Ensure/Backfill/Auto-Advance only on Story-APIs, Story-Page und Directive-Fan-out
- Reward/chapter `notify` must reuse the open write `conn` (no nested `db()` — SQLite deadlock)

---

## Regel 19

- **Ersetzt:** nichts (neue Domäne)
- **Teilt:** Gameplay-Event-Sensorik mit Directives (Fan-out, keine zweite Call-Site-Lawine)
- **Nicht:** Daily-Ops-Duplikat neben `game/directives/`
