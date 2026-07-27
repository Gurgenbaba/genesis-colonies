# Genesis Lore Bible — Story Ops Authoring Canon

> **Single source of truth for Story Ops authors.** Runtime-Owner bleibt `game/story/`.  
> Epic: **EPIC-25 Phase 2 — Imperium Chronicle (Jahres-Lore)** · Tickets GC-2510…GC-2518

Dieses Dokument listet **harte Spiel-Fakten**, die Transmissionen lehren dürfen. Keine Fan-Fiction, die Systeme widerspricht.

---

## Stimmen (Contacts)

| `contact_key` | Label | Ton |
|---------------|-------|-----|
| `ark` | Genesis Ark | Kalt, präzise, imperial, Lattice-Metaphern |
| `androgyn` | Androgyn-Echo | Gender-neutral, unmarkiert, zu nah am Befehlstakt |
| `high_command` | High Command | Militärisch, Ops-Sprache, Distanz zur Ark-Mystik |

UI: sprechender Kreis-Orb (Wellen bei TTS). Kein Cartoon-Gesicht.

---

## Prose-Canon (Buchband)

1. DE führend literarisch; EN gleichwertig; andere Locales EN-Parity bis Übersetzung.
2. Transmission-Body: **120–400 Wörter**, Szenen-Rhythmus, Bild, Spannung — kein „Tutorial“ / „Quest-Log“.
3. Objective-Hints bleiben kurz und klar getrennt vom Lore-Body.
4. Jeder Beat trägt intern ≥1 Fact aus der Whitelist unten.
5. TTS: Titel + Body; Absätze ok; keine Roh-Keys.

---

## Fact-Whitelist (nur Code/Owner-Docs)

| ID | Fact |
|----|------|
| F01 | GC ist ein **Imperium**-Spiel, kein Slot-Management von 18 gleichen Welten |
| F02 | **Genesis Ark** = permanenter Sitz (Regierung, Account-Research, PE-Kern, Ascension, Expansion-Gates) |
| F03 | Welten **entstehen**: Claim → Seed Ark → Outpost → Colony → Strategic World |
| F04 | **Planet Evolution** = echter Langzeit-Fortschritt; Gebäude/Flotte = Motor |
| F05 | Ressourcen: **Ferronite (FN)**, **Crytite (CT)**, **Brennzellen / Fuel Cells**, **Energie** |
| F06 | Galaxy `[G:S:P]`; Position **16** = Expedition |
| F07 | Piraten: Living Heat; Fraktionen Corsairs, Iron Collective, Void Cult, Nomad Swarm, Ash Raiders, Salt Cartel |
| F08 | World Boss: geteilte Anomalien (Leviathan, Void Titan, Planet Eater, Rogue AI Nexus, …) |
| F09 | Imperial Directives = rotierende High-Command-Ops — **nicht** die Story-Saga |
| F10 | Story Ops = persistente Lore-Arcs; Progress aus Gameplay-Events + Choices |
| F11 | Account-Tech (Ark) ≠ Planet-Tech (Welt) |
| F12 | Ark-Token = Story-Collectible; Free Shop auf `/shop` = Convenience-Meta unter EUR-Shop |

---

## Jahres-Act-Map (Year One)

| Season | Pack | Gate | Fassade | Schwierigkeit |
|--------|------|------|---------|---------------|
| Q1 | `ark_signal`, `living_lattice` | always → main_done | Ark / PE / Identitaet / Lexikon | Buildings 5–10+, Research 2+, Fleet 5+ |
| Q2 | `birth_of_worlds` | `living_lattice_done` | Seed / Rollen / Expansion | Expo complete 3+, launch/claim, Fleet 8+ |
| Q3 | `heat_and_shadow` | `birth_of_worlds_done` | Dossier / Piraten / Heat | Expo launch 6+, `defeat_pirates` 5+, combat ships |
| Q4 | `anomaly_protocol`, `unlabeled_depth` | Heat → Anomaly | Boss / Androgyn / Ascension-Teaser | Boss damage accumulate; Choices |

**Veteranen:** echte Completion-Flags → nächste Season. False Completion → reopen.

**Side-Ops** (`side_ops_year`, Season `Y1`): Debris Choir, Steel Ledger, Fortress Line, Return Protocol, Rare Ash, Void Teeth, Salt Watch — harte Count-Objectives + Scrap 3–5.

Pack-Felder: `season_code` (`Q1`…`Q4`/`Y1`) + `season_key` → TOC-Badge in Story Ops UI.

---

## Free Shop (Ark-Token)

- Item key (storage): `story_scrap_token` — UI: **Ark-Token**
- **Kapitel-Drip (Engine-Owner):** bei Kapitelabschluss in `game/story/engine.py` → `grant_chapter_ark_tokens`
  - Main-Kapitel: **2** · Act-Finale (letztes Main-Kapitel): **6** · Side-Kapitel: **4**
  - Idempotenz-Flag: `ark_ch:{pack}:{arc}:{chapter_index}`
  - Catch-up in `ensure_player_story` für bereits gespielte Kapitel
- Pack-`reward`-Beats: Flags / Codex / Notify / Container — **keine** Ark-Tokens mehr (Drip ist Engine-only)
- Sink: **Free Shop** auf `/shop` (Tab neben Premium) — Owner `game/story/free_shop.py`
- Grants Free Shop: TK 45m, Boosters 5–15m, Basic + Wreckage Container (unter EUR-Packs)
- Kein EUR-Checkout, kein Combat-P2W, kein zweiter Shop-Catalog

---

## Authoring-Regeln

1. Objectives nur Keys aus `gameplay_event_delta`.
2. Rewards: Flags, Codex, Scrap, knappe Container — keine Schiffe/Defense/Rohstoff-Stacks.
3. Locales: alle 8 Sprachen.
4. Pack-Validation muss grün sein.
