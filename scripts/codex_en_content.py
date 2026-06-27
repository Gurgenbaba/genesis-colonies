"""English Player Article content for GC-950 generator (DE source: Master Docs)."""

from __future__ import annotations

# codex_id -> section -> str | list
CODEX_EN_SECTIONS: dict[str, dict[str, object]] = {
    "genesis_ark": {
        "quick_help": (
            "The Genesis Ark is your seat of power — the heart of your empire. "
            "Build, research, and Planet Evolution begin on this world."
        ),
        "summary": (
            "Every Commander owns a **Genesis Ark** as the most important world of the empire. "
            "It is not “just a planet” — it is the seat of government, account research, shipyard, "
            "and Planet Evolution. New worlds expand your realm; none of them replaces the Ark."
        ),
        "why": (
            "Genesis Colonies is not about managing interchangeable planet slots. "
            "It is about **growing a star empire**. The Genesis Ark stays the fixed center: "
            "expansion, colonies, and specializations grow around it. The Ark's development stage "
            "helps decide which regions and Expansion Sites you can reach."
        ),
        "how_it_works": (
            "- After registration you land on **Overview** — your empire at a glance.\n"
            "- The Genesis Ark is your **homeworld** — your permanent capital.\n"
            "- On the Ark you first build **production** (Ferronite, Crytite, energy), start "
            "**account research**, and later the **orbital shipyard**.\n"
            "- **Planet Evolution** on the Ark unlocks new regions and Expansion Sites — not "
            "single building levels as the main progress bar.\n"
            "- **Imperial Directives**, diplomacy, and Ascension stay with the Ark or empire — "
            "not on outposts."
        ),
        "commander_tips": [
            "Think empire, not “mine 17 → 18” — Ark development stage opens new possibilities.",
            "Account research and imperial decisions belong on the Ark; planet tech belongs to individual worlds.",
            "The Command Map visualizes your growing realm — the Ark remains the hub.",
        ],
        "faq": [
            {
                "q": "What is my first goal?",
                "a": "Stable production on the Genesis Ark, running build and research queues — and understanding that Planet Evolution is the long-term progress path.",
            },
            {
                "q": "Can a colony replace the Genesis Ark?",
                "a": "No. Strategic Worlds are mature expansion worlds, not a second capital.",
            },
        ],
        "discord_summary": (
            "**Genesis Ark — capital of your empire**\n\n"
            "The Genesis Ark is the fixed center of every star empire: government, account research, "
            "shipyard, and Planet Evolution. Expansion adds worlds — not interchangeable slots. "
            "Ark development stage unlocks regions. No colony replaces the Ark."
        ),
    },
    "planet_scope": {
        "quick_help": (
            "Genesis Colonies plays per **active world**. The header switcher sets which colony "
            "shows buildings, resources, and shipyard — account research stays empire-wide."
        ),
        "summary": (
            "**Planet scope** is the context you play in: one **active world** that defaults "
            "resource display, build queue, shipyard, Trader Hub, and fleet origin. Your **empire** "
            "includes all worlds — but planet building actions always happen on the selected world."
        ),
        "why": (
            "Multi-colony play needs a clear context: which mine is producing, which yard is building? "
            "Scope separates **empire-wide** systems (account research, all fleet movements) from "
            "**world-bound** ones (buildings, resource tick, shipyard)."
        ),
        "how_it_works": (
            "- **Planet switcher** in the header: dropdown when you have multiple worlds.\n"
            "- Switching updates resources, queues, and labels via the active-planet API.\n"
            "- **Homeworld** = Genesis Ark; invalid context falls back to homeworld.\n"
            "- **Planet Evolution** always shows the **active** world.\n"
            "- Colonization and fleets use explicit targets; logistics moves between **your** worlds."
        ),
        "commander_tips": [
            "Before upgrading, check which world is active.",
            "Account research costs are paid from the active world — plan resources there.",
            "Inactive colonies still build in the background; scope only affects UI context.",
        ],
        "faq": [
            {
                "q": "Why do my resources change after switching?",
                "a": "Each world has its own storage and production. The switcher changes context, not your whole empire.",
            },
            {
                "q": "Can I delete a non-homeworld?",
                "a": "Yes — active non-homeworld can be deleted; active jumps to the Genesis Ark.",
            },
        ],
        "discord_summary": (
            "**Planet scope — active world vs. empire**\n\n"
            "Building, resources, and shipyard use the **active world** (header switcher). "
            "Account research and fleet overview are empire-wide. Homeworld = Genesis Ark."
        ),
    },
    "buildings": {
        "quick_help": (
            "Buildings are the engine under Planet Evolution: Ferronite mines, Crytite extractors, "
            "energy, storage, and later shipyard and defense — all per **active world**."
        ),
        "summary": (
            "The building system manages **infrastructure per world**: levels per building, a "
            "sequential **build queue**, costs in Ferronite and Crytite from the active planet."
        ),
        "why": (
            "Without buildings there is no production, labs, or shipyard. In Genesis Colonies they "
            "are not the end goal — they **enable** Planet Evolution, expansion, and fleets. "
            "Energy and storage prevent production from stalling."
        ),
        "how_it_works": (
            "- Open **Buildings** on the active world; upgrades enqueue build jobs.\n"
            "- **Resources tab:** Ferronite mine, Crytite extractor, solar plant, fuel cells, depots.\n"
            "- **Research tab:** research lab and academy — required for account research.\n"
            "- **Military tab:** orbital shipyard, defense factory, radar.\n"
            "- **Infrastructure:** command center, shield generator, terraformer, nexus buildings.\n"
            "- Many buildings have **requirements** — follow the chain (e.g. shipyard after command center).\n"
            "- ROI and level tables: **Technical Data** button — not in the Codex."
        ),
        "commander_tips": [
            "Stabilize energy before pushing mine levels.",
            "Expand storage early — full depots cap production.",
            "Use short builds as fillers before going offline; long jobs for absence.",
            "Mind the queue limit — plan the full queue, not only the first slot.",
        ],
        "faq": [
            {
                "q": "Why is my production dropping?",
                "a": "Usually energy shortage or full Ferronite/Crytite storage.",
            },
            {
                "q": "Where do I build the shipyard?",
                "a": "Orbital shipyard on the world you want to launch fleets from — planet-bound.",
            },
        ],
        "discord_summary": (
            "**Buildings — infrastructure per world**\n\n"
            "Production, labs, shipyard via build queue on the **active world**. "
            "Engine for evolution and expansion. ROI: Technical Data in UI."
        ),
    },
    "research": {
        "quick_help": (
            "Account research improves your **entire empire** — energy, production, fleet speed, "
            "and combat values. Costs are paid from the **active world**."
        ),
        "summary": (
            "**Account research** is **empire-wide**: one tech tree and queue, lab level across "
            "colonies as unlock gate, payment in Ferronite/Crytite from the context planet. "
            "This is **not** Planet Evolution planet tech."
        ),
        "why": (
            "Research solves empire-wide bottlenecks: storage, build time, mine efficiency, fleet "
            "slots, weapons. It links economy, fleet, and combat without forcing every planet alone."
        ),
        "how_it_works": (
            "- **Research lab** (empire-wide max ≥ 1) unlocks technologies.\n"
            "- Start research on the Research page; queue runs sequentially.\n"
            "- Techs have **requirements** — plan chains (energy before propulsion, etc.).\n"
            "- Key lines: extraction, storage, build time, navigation (fleet slots), combat tech.\n"
            "- **Interstellar Expansion** (account tech) gates new worlds — see Expansion Protocol.\n"
            "- Planet tech on `/planet-evolution` is **world research**, not this system."
        ),
        "commander_tips": [
            "Research should rarely sit idle — keep it parallel to the build queue.",
            "Keep a lab high on at least one world — empire-wide max counts for unlocks.",
            "Use the tech tree for dependencies; prioritize bottleneck techs.",
        ],
        "faq": [
            {
                "q": "Why can't I start a tech?",
                "a": "Missing lab level, prerequisite tech, or insufficient Ferronite/Crytite on the active world.",
            },
            {
                "q": "Planet tech vs. account research?",
                "a": "Account = empire. Planet tech = selected world in Planet Evolution.",
            },
        ],
        "discord_summary": (
            "**Account research — empire-wide technology**\n\n"
            "One tech tree for all worlds. Costs from active planet, levels account-wide. "
            "≠ Planet tech in Planet Evolution."
        ),
    },
    "resources": {
        "quick_help": (
            "Ferronite, Crytite, and fuel cells drive your empire — plus **energy** scaling production. "
            "All planet-bound with storage caps per world."
        ),
        "summary": (
            "Four visible resources: **Ferronite**, **Crytite**, **fuel cells**, and **energy** "
            "(ratio of supply to demand). Production ticks server-side; full depots stop growth."
        ),
        "why": (
            "Resources fuel daily play but are not the only goal — they power build, research, "
            "fleets, and expansion. Energy and storage are the usual bottlenecks."
        ),
        "how_it_works": (
            "- **Ferronite / Crytite:** mines on the active world; galaxy slot and climate modify output.\n"
            "- **Fuel cells:** fuel cell plant; storage only with **fuel depot** after infrastructure.\n"
            "- **Energy:** solar plant supplies; mines consume — shortage reduces all production.\n"
            "- **Storage:** base cap without depots; storage buildings and storage tech multiply.\n"
            "- Trader Hub and scrapyard can credit **above cap** — overflow kept.\n"
            "- Numbers and ROI: **Technical Data** on buildings — not here."
        ),
        "commander_tips": [
            "Stabilize energy before pushing output.",
            "Check storage before long offline periods.",
            "Fuel cells without depot do not accumulate — plan the depot.",
        ],
        "faq": [
            {
                "q": "Why is production zero?",
                "a": "Full storage or energy below effective 100%.",
            },
            {
                "q": "Deuterium?",
                "a": "Genesis uses **fuel cells** — not deuterium.",
            },
        ],
        "discord_summary": (
            "**Resources — Ferronite, Crytite, fuel cells, energy**\n\n"
            "Planet-bound with storage caps. Energy scales mine output. Trader can credit above cap."
        ),
    },
    "trader": {
        "quick_help": (
            "The **Trader Hub** exchanges resources and recycles surplus — unified trader and scrapyard, "
            "daily limit per player, balances on the **active world**."
        ),
        "summary": (
            "At `/trader-hub`: **Unified Resource Trader** and **scrapyard**. Context planet for "
            "balances; **daily limit** is per Commander."
        ),
        "why": (
            "Not every world produces evenly — the hub balances Ferronite, Crytite, and fuel cells "
            "without new mechanics. Scrapyard handles excess when storage or production is skewed."
        ),
        "how_it_works": (
            "- Open **Trader Hub** from the economy section (`/trader-hub`).\n"
            "- Balances use the **active world**; **daily limit** is per Commander account-wide.\n"
            "- **Unified trader:** swap Ferronite, Crytite, fuel cells — rates and remaining limit in UI.\n"
            "- **Scrapyard:** recycle surplus when storage is full or production is skewed.\n"
            "- Daily limit scales with empire production (formula shown in UI).\n"
            "- Auction house and inventory are separate routes — not mixed into the trader panel.\n"
            "- Debited and credited on the context planet; overflow rules match production.\n"
            "- Rates and limits come from the server UI only."
        ),
        "commander_tips": [
            "Use the hub when one resource stacks and another is short.",
            "Remember the daily limit when planning big upgrades.",
        ],
        "faq": [
            {
                "q": "Why is exchange limited?",
                "a": "Daily limit per Commander — economy rhythm and fairness.",
            },
        ],
        "discord_summary": (
            "**Trader Hub — exchange and scrapyard**\n\n"
            "`/trader-hub`: resource swap + scrapyard. Active world balances, daily player limit."
        ),
    },
    "planet_evolution": {
        "quick_help": (
            "Planet Evolution is the heart of your empire. Develop worlds through DNA, development "
            "stage, and specialization — and unlock new regions."
        ),
        "summary": (
            "**Planet Evolution** is **per-world progression**: DNA, traits, development stage/XP, "
            "planet class, planet tech (≠ account research), specialization, policies, events, "
            "discoveries, and trade routes."
        ),
        "why": (
            "Genesis differs through **identity per world** — not only building levels. Evolution "
            "decides reachable regions, specializations, and how worlds fit the empire. Buildings "
            "and account research are the engine **below** this layer."
        ),
        "how_it_works": (
            "- Open **Planet Evolution** for the **active world**.\n"
            "- **DNA & traits** shape research, events, and specialization options.\n"
            "- **Genesis Ark development stage** unlocks Expansion Sites.\n"
            "- Higher development: **specialization** (permanent), **policies**, narrative **events**.\n"
            "- **Planet tech** — research for this world only.\n"
            "- **Trade routes** link colonies to the empire visually.\n"
            "- **Ascension** — separate long-term path (see Ascension article).\n"
            "- Planet tech and Ascension queues show in their cards."
        ),
        "commander_tips": [
            "Raise Ark stage before blind mine pushing — it opens the Command Map.",
            "Specialization is permanent — read the Codex before choosing.",
            "Do not confuse planet tech with account research.",
        ],
        "faq": [
            {
                "q": "Why is my world different from the Ark?",
                "a": "Each world has its own DNA, traits, and optional specialization.",
            },
            {
                "q": "What is planet tech?",
                "a": "World-bound research in Planet Evolution — not the account tech tree.",
            },
        ],
        "discord_summary": (
            "**Planet Evolution — identity and progress per world**\n\n"
            "DNA, development stage, specialization, events, planet tech. Center on Genesis Ark. "
            "≠ Account research."
        ),
    },
    "ascension": {
        "quick_help": (
            "**Ascension** is long-term progress on the Genesis Ark — a queue in Planet Evolution "
            "that prepares endgame empire growth."
        ),
        "summary": (
            "**Ascension** is long-term progress on the Genesis Ark — a queue that prepares "
            "endgame empire growth through Planet Evolution."
        ),
        "why": (
            "Ascension bundles endgame decisions at the **imperial capital** — consistent with the "
            "Ark never being replaced by colonies. It complements specialization and Strategic Worlds."
        ),
        "how_it_works": (
            "- Reachable via **Planet Evolution** on the Genesis Ark when unlocked (development stage 15).\n"
            "- Jobs run in the **Ascension queue** — own card beside planet tech, sequential like other queues.\n"
            "- Steps are **long-term investments**: costs and duration in UI; numbers are server-only.\n"
            "- Requires prepared evolution (specialization, policies, stable Ark) — not early game.\n"
            "- Complements Strategic Worlds and Imperial Directives — not a substitute for colony buildout.\n"
            "- Coordinate queue time with planet tech and build jobs on the Ark.\n"
            "- Per-step details: Planet Evolution UI and queue cards — not in this Codex article."
        ),
        "commander_tips": [
            "Plan Ascension when core evolution and empire are stable.",
            "Coordinate queue time with other planet jobs.",
        ],
        "faq": [
            {
                "q": "Can every colony start Ascension?",
                "a": "Design focus is the Genesis Ark — check unlock on the active world in UI.",
            },
        ],
        "discord_summary": (
            "**Ascension — long-term on the Genesis Ark**\n\n"
            "Queue-based endgame path in Planet Evolution at the capital."
        ),
    },
    "expansion": {
        "quick_help": (
            "Expansion is not unlocking a planet slot. **Worlds are born** — from Expansion Site "
            "through Seed Ark and Frontier Outpost to a full colony."
        ),
        "summary": (
            "The **Expansion Protocol** turns unknown space into your empire: **Expansion Sites** "
            "on the Command Map, claims, Seed Ark transport, **Frontier Outpost**, milestone "
            "establishment, then **colony** and optional **Strategic World**. A **colony** exists "
            "only after establishment — before that it is an outpost."
        ),
        "why": (
            "Genesis avoids spreadsheet expansion. It is a **process**: places with promise and risk "
            "become character worlds with their own DNA — not instant full copies of the Ark."
        ),
        "how_it_works": (
            "**Lifecycle:**\n"
            "1. Expansion Site — visible on Command Map, not claimed.\n"
            "2. Claimed Site — reserved for you.\n"
            "3. Seed Ark en route — fleet carries Seed Ark.\n"
            "4. Frontier Outpost — limited production; **not a colony**.\n"
            "5. Colony — all establishment milestones complete.\n"
            "6. Strategic World — evolution complete, specialization chosen.\n\n"
            "**Establishment milestones (all four):** habitat, stable energy, communications hub, "
            "first population.\n\n"
            "**First expansion gates:** Genesis Ark **development stage 5** and **Interstellar "
            "Expansion** tech level 1 — read from the Ark.\n\n"
            "The **Genesis Ark** stays irreplaceable for account research and imperial systems.\n\n"
            "**Practical flow (first expansion):**\n"
            "1. Ark at **stage 5** + **Interstellar Expansion** tier 1.\n"
            "2. **Command Map** (`/galaxy`, world map) — Expansion Site visible.\n"
            "3. **Claim** site, prepare **Seed Ark** at shipyard.\n"
            "4. **Fleet** → colonize mission with Seed Ark to the site.\n"
            "5. **Frontier Outpost** appears — complete establishment checklist.\n"
            "6. After all milestones: full **colony** with DNA and full gameplay depth."
        ),
        "commander_tips": [
            "New world ≠ instant colony — play outpost establishment.",
            "Watch checklist on outpost and Command Map.",
            "Expansion Sites appear with Ark stage — evolution before slot thinking.",
        ],
        "faq": [
            {
                "q": "Why isn't my new world a colony yet?",
                "a": "Seed Ark first creates a **Frontier Outpost**. Colony after habitat, energy, comms, and population milestones.",
            },
            {
                "q": "Planet slots?",
                "a": "No OGame slot framing — empire reach and gates define expansion.",
            },
        ],
        "discord_summary": (
            "**Expansion Protocol — worlds are born**\n\n"
            "Site → claim → Seed Ark → outpost → colony → Strategic World. "
            "Outpost ≠ colony. Four milestones. Gates: Ark stage 5 + Interstellar Expansion."
        ),
    },
    "galaxy": {
        "quick_help": (
            "The **galaxy** shows your realm in space: **world map** (Command Map) with empire and "
            "expansion — plus classic **system view** for slots and fleet prefill."
        ),
        "summary": (
            "Coordinates `[G:S:P]` stay internal; players see **places**, **regions**, and "
            "**influence**. `/galaxy` has **world map** (default) and **classic system view** "
            "(15 slots + expedition slot)."
        ),
        "why": (
            "The galaxy links discovery, expansion, and fleets. The world map makes growth visible; "
            "system view remains legacy bridge and fleet helper."
        ),
        "how_it_works": (
            "- **World map:** Ark hub, colonies with roles, Expansion Sites, Strategic Worlds, "
            "chokepoints — actions depend on development stage and gates.\n"
            "- **System view:** 15 positions; empty slots → colonize via fleet; slot 16 = expedition.\n"
            "- Navigation remembers tab; coordinates often follow **active planet**.\n"
            "- Fleet prefill from galaxy links.\n"
            "- **`/empire`** is **not** the Command Map — it is the economy matrix."
        ),
        "commander_tips": [
            "Plan expansion on the **world map**, not only the slot list.",
            "Active planet marks the slot in system view.",
            "Expedition slot is not a normal colony planet.",
        ],
        "faq": [
            {
                "q": "World map vs. system view?",
                "a": "World map = empire and places. System view = classic slot map — both under `/galaxy`.",
            },
            {
                "q": "Where is the Command Map?",
                "a": "Default **world map** tab on `/galaxy` — not on `/empire`.",
            },
        ],
        "discord_summary": (
            "**Galaxy — world map and system view**\n\n"
            "`/galaxy`: Command Map + classic slots. `/empire` = economy, not the map."
        ),
    },
    "fleet": {
        "quick_help": (
            "Fleets connect your worlds: transport, Seed Ark colonization, expeditions, attack, "
            "and logistics — ships from the **origin world**, slots via navigation tech."
        ),
        "summary": (
            "Fleet system: **ships per world**, **movements empire-wide**, missions on arrival. "
            "Ships built at **orbital shipyard**. Fleet slots expanded by **navigation tech**."
        ),
        "why": (
            "Without fleets: no expansion (Seed Ark), no logistics, no expeditions, no PvP. "
            "Fleets are the **operational hand** — targets are **places** and coordinates."
        ),
        "how_it_works": (
            "- Build ships at **orbital shipyard** on the departure world.\n"
            "- **Fleet page:** select ships, mission, target (colony, map world, coordinates).\n"
            "- Missions: transport, logistics, deploy, spy, attack, hold, expedition, colonize, recycle.\n"
            "- **Colonization:** colonize mission with Seed Ark → outpost phase.\n"
            "- **Expedition:** event on arrival — reports in messages.\n"
            "- **Logistics** (`/logistics`): collect/distribute between your worlds.\n"
            "- Flight time and fuel: server preview only.\n"
            "- Ship stats: ship detail / Technical Data — not Codex."
        ),
        "commander_tips": [
            "Match fleet origin with active planet — ships are planet-bound.",
            "Prioritize navigation tech for more parallel fleets.",
            "Expedition: expo hulls for finds; cargo ships for salvage capacity.",
        ],
        "faq": [
            {
                "q": "Why can't I send a fleet?",
                "a": "No ships, no free slot, invalid target, or missing mission requirement (e.g. Seed Ark for colonization).",
            },
            {
                "q": "Where are all my fleets?",
                "a": "Overview and Fleet show **all** movements — not only the active world.",
            },
        ],
        "discord_summary": (
            "**Fleet — missions and operations**\n\n"
            "Ships per world, movements empire-wide. Orbital shipyard required. "
            "Colonize, expedition, attack, logistics. Navigation tech = more slots."
        ),
    },
    "combat": {
        "quick_help": (
            "Combat happens when an **attack** fleet reaches a defended world: fleet vs. hangar "
            "and planetary defense — reports for both sides."
        ),
        "summary": (
            "**Round-based combat** (up to six rounds): attacker fleet vs. defender hangar and "
            "**stationary defense**. Outcome: losses, debris, optional plunder, inbox reports. "
            "Research modifies combat values."
        ),
        "why": (
            "PvP and colony risk need server-side resolution. Combat links fleet, defense, research, "
            "and ranking."
        ),
        "how_it_works": (
            "- Send **attack** from the Fleet page (PvP rules apply).\n"
            "- Pick targets via quick target, coordinates, or galaxy link — server computes flight and fuel.\n"
            "- On arrival: simulation → losses on fleet, hangar, defense.\n"
            "- **Attacker wins:** plunder up to return cargo; credited on return (not at target).\n"
            "- **Debris field** at target — visible in galaxy system view; recycle mission harvests.\n"
            "- Both players get **combat reports** in messages (rounds, losses, outcome).\n"
            "- **Stationary defense** and **hangar ships** fight together — hangar alone is not enough.\n"
            "- Combat techs modify values empire-wide.\n"
            "- Formulas: ship/defense detail and Technical Data — not Codex."
        ),
        "commander_tips": [
            "Combat techs before first attack — they affect fleet and defense.",
            "Stationary defense counts with hangar ships.",
            "Plunder is capped by return cargo.",
        ],
        "faq": [
            {
                "q": "When do I see the combat guide?",
                "a": "After your first fleet is sent — or when attack becomes relevant.",
            },
            {
                "q": "Instant win with no rounds?",
                "a": "When one side has no combat units.",
            },
        ],
        "discord_summary": (
            "**Combat — attack fleet vs. planet**\n\n"
            "Up to 6 rounds. Losses, debris, plunder. Reports to both sides. Research modifiers."
        ),
    },
    "defense": {
        "quick_help": (
            "Planetary **defense** protects the active world: stationary guns and barriers from "
            "the defense factory — not orbiting fleets."
        ),
        "summary": (
            "**Stationary units per colony**: built via defense factory and defense queue. "
            "Live UI at `/defense`. On **attack**, hangar ships and defense fight together. "
            "Empire **defense score** for ranking."
        ),
        "why": (
            "Fleets alone are not enough — colonies need local defense. Defense is **stationary** "
            "(planet) vs. **mobile** (fleet), and feeds combat and spy intel."
        ),
        "how_it_works": (
            "- Build **defense factory** on the world to protect.\n"
            "- Open **Defense** — queue units (requirements from buildings and account research).\n"
            "- Turrets and barriers unlock with factory level and techs.\n"
            "- Stock is **planet-bound** like hangar ships.\n"
            "- Header switcher changes defense view.\n"
            "- Combat values in defense detail / Technical Data — not Codex."
        ),
        "commander_tips": [
            "Don't leave outposts undefended in PvP space.",
            "Shield and weapon tech strengthen defense in combat.",
            "Plan defense queue alongside shipyard on the same world.",
        ],
        "faq": [
            {
                "q": "Defense vs. ships at the planet?",
                "a": "Defense = stationary. Hangar ships are mobile — both fight on attack.",
            },
            {
                "q": "Why can't I build?",
                "a": "Missing factory level, research, or resources on the active world.",
            },
        ],
        "discord_summary": (
            "**Defense — stationary per world**\n\n"
            "Defense factory + queue per colony. Fights with hangar on attack. Defense score in ranking."
        ),
    },
}


def en_locale_keys() -> dict[str, str]:
    """Flatten CODEX_EN_SECTIONS to i18n keys matching DE generator output."""
    from game.knowledge_parser import locale_keys_for_article

    keys: dict[str, str] = {}
    for codex_id, sections in CODEX_EN_SECTIONS.items():
        normalized: dict[str, object] = {}
        for k, v in sections.items():
            if k == "faq" and isinstance(v, list):
                normalized["faq"] = v
            elif k == "commander_tips" and isinstance(v, list):
                normalized["commander_tips"] = v
            else:
                normalized[k] = v
        keys.update(locale_keys_for_article(codex_id, normalized))
    return keys
