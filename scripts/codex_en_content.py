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
            "- **Effective stats:** displayed combat values may also include bonuses from Commander class, tech tree, and Titans — UI shows server total bonus; no client formula.\n"
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
    "command_map": {
        "quick_help": (
            "The **Command Map** (world map) shows your empire spatially: Genesis Ark as hub, "
            "colonies, Expansion Sites, and strategic places — under `/galaxy` as the world-map tab "
            "(`view=command_map`)."
        ),
        "summary": (
            "The **Command Map** is Genesis Colonies' visual empire map. Instead of a plain colony "
            "list you see hub-and-spoke: the **Genesis Ark** at the center, linked worlds, trade "
            "routes, and places with type and promise. It lives under **`/galaxy`** (world map) — "
            "**`/empire` is not a map**, it is the economy/production matrix."
        ),
        "why": (
            "A star empire should be **seen**, not only scrolled. The Command Map makes expansion, "
            "roles, and goals spatially readable and ties Planet Evolution, Expansion Sites, and "
            "fleet targets into one world view."
        ),
        "how_it_works": (
            "- Open **`/galaxy`** and the **World Map** tab (`view=command_map` / alias `imperium`).\n"
            "- **Hub:** Genesis Ark (homeworld) central; colonies as satellites with role icons.\n"
            "- **Edges:** active trade routes and hub links connect worlds.\n"
            "- Clicking your own worlds switches the **active planet** (like the header switcher).\n"
            "- Expansion Sites, Strategic Worlds, landmarks, and chokepoints appear with Ark "
            "development progress — actions depend on gates and missions.\n"
            "- Classic **system view** (`view=system`) stays in parallel for slots and fleet prefill.\n"
            "- Do not confuse **`/empire`** with the Command Map."
        ),
        "commander_tips": [
            "Plan expansion and places on the **world map** first, not only in the slot list.",
            "Genesis Ark stays the hub — read colonies around it.",
            "`/empire` = production/matrix; world map = `/galaxy` world-map tab.",
        ],
        "faq": [
            {
                "q": "Where do I find the Command Map?",
                "a": "Under `/galaxy` → **World Map** tab (`view=command_map`). Not under `/empire`.",
            },
            {
                "q": "Difference from `/empire`?",
                "a": "Command Map = spatial empire/world view. `/empire` = economy and production matrix.",
            },
            {
                "q": "Do I still need system view?",
                "a": "Yes — classic slots, the expedition slot, and many fleet prefills still use system view.",
            },
        ],
        "discord_summary": (
            "**Command Map — empire on the world map**\n\n"
            "`/galaxy` world map: Genesis Ark as hub, colonies, Expansion Sites, Strategic Worlds. "
            "`/empire` is economy, not a map. Unlocks at Ark development stage 5."
        ),
    },
    "expeditions": {
        "quick_help": (
            "**Expeditions** are exploration missions: classic galaxy expedition slot or Strategic "
            "Worlds (expedition zones, anomalies, ruins) — send a fleet, event on arrival, report "
            "in messages."
        ),
        "summary": (
            "Expeditions use the **canonical Fleet expedition mission** and the event engine. "
            "Targets: **position 16** (synthetic expedition slot) in system view and **Expedition "
            "Worlds** on the world map (`expedition_zone`, `anomaly_zone`, `ruins_world`). No "
            "parallel loot system — outcome and report come from the existing expedition pipeline."
        ),
        "why": (
            "Not every world should become a colony immediately. Expeditions reward exploration "
            "with finds, risks, and reports — and open places you **expedition** instead of colonize."
        ),
        "how_it_works": (
            "- **Classic:** Galaxy system view → expedition slot (position 16) → Fleet with mission "
            "Expedition.\n"
            "- **World map:** Strategic World of expedition type → Inspector \"Start expedition\" → "
            "Fleet prefill with `world_key`.\n"
            "- On arrival the server rolls events (finds, hazards, pirates, rare encounters) — UI "
            "shows server data only.\n"
            "- **Expo hulls** carry the loot role; **freighters** raise salvage capacity; combat/"
            "escort roles protect against pirates and do not count as expo value.\n"
            "- Reports land in the **inbox** (event card); pirate fights may open a combat report too.\n"
            "- Mass expedition and daily rhythm: the server limits efficiency after many expeditions "
            "on the same UTC day — details only in UI/preview, never Codex math.\n"
            "- Ancient Relay and higher Expansion Sites open more expedition/world options with Ark "
            "stage — Codex unlock from development stage **10**."
        ),
        "commander_tips": [
            "Bring expo ships for finds; freighters for salvage; escorts against pirates.",
            "Start world expeditions from the Inspector — the target stays bound to the place.",
            "Always read inbox reports; trust only server preview.",
        ],
        "faq": [
            {
                "q": "Expedition vs. colonization?",
                "a": "Colonization founds a world with a Seed Ark. Expedition explores and returns "
                "report/loot — no new colony.",
            },
            {
                "q": "Where do I start?",
                "a": "Fleet mission Expedition: classic slot pos. 16 or an Expedition World on the "
                "world map.",
            },
            {
                "q": "Why little loot?",
                "a": "Cargo cap of expo/freight hulls and server-side event/daily logic — no client "
                "formula.",
            },
        ],
        "discord_summary": (
            "**Expeditions — explore instead of colonize**\n\n"
            "Mission Expedition: galaxy slot 16 or Expedition Worlds (zones, anomalies, ruins). "
            "Event engine, inbox report. Expo hulls + freighters. Codex from Ark stage 10."
        ),
    },
    "logistics": {
        "quick_help": (
            "**Logistics** moves Ferronite, Crytite, and Fuel Cells between **your** colonies: "
            "**Collect** (sources → hub) and **Distribute** (hub → targets) under `/logistics`."
        ),
        "summary": (
            "Fleet Logistics is multi-colony resource movement through the existing fleet pipeline — "
            "not a second movement system. On **`/logistics`** you plan Collect or Distribute around "
            "a **hub** (usually the active context planet). The server picks freighters "
            "(`auto_cargo`); preview and launch only with a server plan."
        ),
        "why": (
            "With several worlds, single transport is not enough. Logistics batches pickup and "
            "delivery so production worlds feed the hub and the hub restocks colonies — with the "
            "same fleet rules and slots."
        ),
        "how_it_works": (
            "- Open **`/logistics`** (link from the Fleet page).\n"
            "- **Collect:** mark source colonies → freighters start **from sources** and deliver to "
            "the **hub**; ships return empty to the source.\n"
            "- **Distribute:** enter amounts at the hub → delivery to chosen own targets; ships "
            "return empty to the hub.\n"
            "- Only **your** planets; only **cargo ships**; UI uses **auto_cargo** (no manual "
            "freighter pick needed).\n"
            "- Each started leg consumes **one fleet slot**; preview shows whether launch is possible.\n"
            "- Messages: arrival and return as logistics reports in the inbox.\n"
            "- Flight time, cargo, and fuel cells: server preview only — do not calculate yourself."
        ),
        "commander_tips": [
            "Before Collect: station freighters on the **sources**; before Distribute: freighters at "
            "the **hub**.",
            "Check hub = active planet before you launch.",
            "Check free fleet slots — many targets need many slots.",
        ],
        "faq": [
            {
                "q": "Difference from transport?",
                "a": "Single transport = one mission. Logistics = planned Collect/Distribute across "
                "several of your worlds with batch and preview.",
            },
            {
                "q": "Can I supply foreign planets?",
                "a": "No — only worlds you own.",
            },
            {
                "q": "Why won't it start?",
                "a": "No freighters in the right place, no resources, no free slots, or preview "
                "`can_launch` is false — read the UI message.",
            },
        ],
        "discord_summary": (
            "**Logistics — Collect and Distribute**\n\n"
            "`/logistics`: resources between your colonies. Collect = sources → hub; Distribute = "
            "hub → targets. Cargo-only, auto_cargo, one slot per leg. Orbital shipyard unlock like "
            "Fleet."
        ),
    },
    "strategic_worlds": {
        "quick_help": (
            "**Strategic Worlds** are named places on the world map with type, risk, and promise — "
            "and also the maturity stage of a colony after finished Planet Evolution and "
            "specialization."
        ),
        "summary": (
            "On the Command Map free fields become **Strategic Worlds**: Mining, Research, "
            "Industrial, Fortress, Expedition Zone, Ruins, Anomaly, Wreckage — each with name, "
            "risk, and flavor. Some types you colonize (Expansion), others you **expedition**. In "
            "the Expansion Protocol, **Strategic World** is also the phase after a full colony + "
            "Evolution/specialization."
        ),
        "why": (
            "The map should answer \"**where do I want to go**\", not only \"where is a free slot\". "
            "Type and promise set expectation: Ferronite potential, research, yard, fortress, or "
            "expedition — identity before pure slot filling."
        ),
        "how_it_works": (
            "- On the **world map** click a Strategic World node → Inspector: type, status, risk, "
            "promise, planned action.\n"
            "- **Colonizable** types: claim via Expansion/Fleet with Seed Ark (see Expansion).\n"
            "- **Expedition types** (`expedition_zone`, `anomaly_zone`, `ruins_world`): mission "
            "Expedition, no claim as colony.\n"
            "- Your own colony can mature into a **Strategic World** when Planet Evolution and "
            "specialization are done — character world, not a second Genesis Ark.\n"
            "- Codex entry opens at Ark development stage **15** (higher expansion/world gates)."
        ),
        "commander_tips": [
            "Read the Inspector before binding a fleet — type decides colony vs. expedition.",
            "Specialization on your worlds is permanent; think before choosing.",
            "Strategic World ≠ replacement capital — the Genesis Ark stays the center.",
        ],
        "faq": [
            {
                "q": "Is every Strategic World a colony?",
                "a": "No. Some are unclaimed places; expedition types stay exploration targets. "
                "Colonies can later reach Strategic World status.",
            },
        ],
        "discord_summary": (
            "**Strategic Worlds — places with character**\n\n"
            "World map: named types (Mining, Research, Expedition, Ruins …). Colonize or expedition "
            "by type. Mature colonies after Evolution. Codex from Ark stage 15."
        ),
    },
    "diplomacy": {
        "quick_help": (
            "**Galactic Diplomacy** shapes your galaxy's character: alliance blocs, resolutions, "
            "crises, and long-term personality — surface under `/galactic-politics`."
        ),
        "summary": (
            "Diplomacy is the **macro politics layer** above Galactic Directives. Directives steer "
            "*what* the galaxy emphasizes in a cycle; Diplomacy steers *who* shapes it: Scientific, "
            "Military, Industrial, Frontier, or Neutral blocs, votes, emergency sessions, and lasting "
            "traits. Player surface: **`/galactic-politics`**."
        ),
        "why": (
            "Galaxies should be politically tellable — not just a buff. Bloc stance and traits "
            "affect where research, war, expansion, or logistics stay strong long-term. That is "
            "community scale, not a 1:1 war system between single Commanders."
        ),
        "how_it_works": (
            "- Page **`/galactic-politics`**: bloc landscape, open resolutions, active personality, "
            "emergency banner.\n"
            "- **Alliance Blocs** per galaxy (officer sets bloc): Scientific, Military, Industrial, "
            "Frontier, Neutral.\n"
            "- **Directive vote** and **resolutions** (YES/NO, officer proposals) beside the monthly "
            "directive cycle.\n"
            "- **Galaxy Personality** grows from history and bloc dominance — slow, lasting alignment.\n"
            "- **Emergency Directives** are time-limited crisis overlays.\n"
            "- Mechanical bonuses run through the **EffectResolver** — UI shows server state, no "
            "client math.\n"
            "- Do not confuse with **Imperial Directives** (personal High Command orders) or "
            "alliance chat."
        ),
        "commander_tips": [
            "Check galaxy bloc and trait before large investment decisions.",
            "Imperial Directives ≠ Galactic Diplomacy — personal vs. galaxy politics.",
            "Bloc swap has a cooldown; often locked during open resolutions.",
        ],
        "faq": [
            {
                "q": "Difference from Imperial Directives?",
                "a": "Imperial = your personal Daily/Weekly orders. Diplomacy/Directives = "
                "galaxy-wide politics and community alignment.",
            },
            {
                "q": "Must I be in an alliance?",
                "a": "Bloc assignment runs through the alliance. Unassigned counts as Neutral — "
                "resolutions and directives stay galaxy-visible.",
            },
        ],
        "discord_summary": (
            "**Diplomacy — blocs, resolutions, galaxy character**\n\n"
            "`/galactic-politics`: alliance blocs, votes, resolutions, personality, emergencies. "
            "Complements Galactic Directives. ≠ Imperial Directives. Unlocks after first visit."
        ),
    },
    "imperial_directives": {
        "quick_help": (
            "**Imperial Directives** are personal High Command orders: **3 Daily** and **1 Weekly**. "
            "Progress from normal play; claim rewards manually under `/imperial-directives`."
        ),
        "summary": (
            "Imperial Directives reward Economy, Science, Fleet, Military, and Exploration — without "
            "a separate quest accept. Goals scale server-side with your empire score. Completed "
            "directives grant containers/boosters into **Inventory** after claim. Incomplete ones "
            "expire on reset."
        ),
        "why": (
            "High Command should reward operational play, not force a second progress bar. No "
            "Accept/Track — directives are always active and vanish on period change if unfinished."
        ),
        "how_it_works": (
            "- Page **`/imperial-directives`**: cards with category, rarity, progress, remaining "
            "time, reward preview.\n"
            "- **Daily:** 3 orders, reset every 24 h (UTC). **Weekly:** 1 order, weekly reset.\n"
            "- Progress comes from gameplay events (building done, research, fleet, expeditions, "
            "defense, …) — no separate polling.\n"
            "- Status: active → completed → **Claim** → claimed until reset.\n"
            "- Rewards: inventory containers and boosters — no parallel loot system.\n"
            "- **Not** Galactic Directives / Diplomacy: those are galaxy politics; these are "
            "account-personal.\n"
            "- Goals and scaling are server-only — Codex has no formulas."
        ),
        "commander_tips": [
            "Don't forget to claim — completed ≠ auto-collected.",
            "Daily/Weekly complement normal building and flying; force nothing.",
            "Nav badge shows claimable directives.",
        ],
        "faq": [
            {
                "q": "Imperial vs. Galactic Directives?",
                "a": "Imperial = your personal orders. Galactic = galaxy vote and macro buffs/politics.",
            },
            {
                "q": "Must I accept directives?",
                "a": "No — they are active immediately. Not finished → replaced on next reset.",
            },
            {
                "q": "Where do rewards land?",
                "a": "After claim in **Inventory** (containers/boosters).",
            },
        ],
        "discord_summary": (
            "**Imperial Directives — High Command orders**\n\n"
            "3 Daily + 1 Weekly, progress from gameplay, claim manually. `/imperial-directives`. "
            "≠ Galactic Diplomacy. Unlocks after first visit."
        ),
    },
    "world_boss": {'quick_help': '**World Boss** events are server-wide PvE encounters: Commanders share one boss, '
               'strike it in the Encounter Stage, and earn contribution toward meta rewards.',
 'summary': 'Under `/world-boss` the **Encounter Stage** shows a shared HP bar, hangar-powered '
            'instant strikes, and personal/alliance contribution boards. Bosses appear in the '
            'galaxy for a LiveOps window. After defeat or expiry, claim meta containers/items — '
            'never ships or resource stacks.',
 'why': 'World Boss ties LiveOps, community DPS, and meta progression together. Contribution feeds '
        'ranks, alliance XP, and claim tiers. Catch/Titans are the retention loop afterward.',
 'how_it_works': '- Open **World Boss** or follow a galaxy deep-link when a boss slot is visible.\n'
                 '- **Attack:** instant strike — ships stay in hangar (no losses on this path). '
                 'Cooldown/wave limits are server-side.\n'
                 '- **Auto-attack:** optional server follow-ups when cooldown allows.\n'
                 '- **Contribution:** damage and ranks are server-only; alliance members '
                 'aggregate.\n'
                 '- **Phases:** critical phase enables **taming** (see Titans).\n'
                 '- **Rewards:** claim after defeated/expired with contribution — or auto-claim on '
                 'successful tame for damage participants.\n'
                 '- Idle state shows next-spawn countdown; help modal explains the stage.',
 'commander_tips': ['Strike early — contribution and ranks build across the window.',
                    'Coordinate waves if you want alliance-top tiers.',
                    'Discoverer bonus needs expedition find **and** your own damage.'],
 'faq': [{'q': 'Do I lose ships on a World Boss attack?',
          'a': 'No — the instant path reads hangar power only; no hangar losses.'},
         {'q': 'Where do I find the boss?',
          'a': 'Active events show in the galaxy and on `/world-boss`. Deep-links open the '
               'Encounter Stage.'},
         {'q': 'When can I claim?',
          'a': 'After defeat or expiry with contribution — or automatically after a successful '
               'tame for all damage participants.'}],
 'discord_summary': '**World Boss — server-wide Encounter Stage**\n'
                    '\n'
                    '`/world-boss`: shared boss, instant strikes without hangar loss, boards, '
                    'claim tiers. Galaxy shows active slots. Catch/Titans = separate codex.'},
    "titans": {'quick_help': '**Titans** (boss companions) come from taming in the World Boss stage. Owned '
               'titans live on Overview — missions earn **Ark Tokens** for the Free Shop.',
 'summary': 'In the critical boss phase you may attempt a **catch** (Timekeeper cost, chance, and '
            'cooldown are server-authored). Success binds a flavor companion with no combat/fleet '
            'buffs. On **Overview**, hotspots and click SFX apply only to **your owned** titans; '
            'locked silhouettes mark untamed bosses. Missions grant Ark Tokens '
            '(`story_scrap_token`) on success — same currency as Story Free Shop.',
 'why': 'Titans extend the World Boss loop: fight → catch → Overview presence → mission → meta '
        'currency. Prestige and side content — not a second combat system.',
 'how_it_works': '- **Catch:** active event in critical phase, free companion capacity, not '
                 'already owned for that boss key.\n'
                 '- **Capacity:** starts low; shop SKU can add slots (server cap).\n'
                 '- **Overview:** landscape hotspots + mission popover — interaction/SFX only for '
                 '**owned** titans.\n'
                 '- **Missions:** start/claim from Overview; one mission per companion; success → '
                 'Ark Token.\n'
                 '- No combat/fleet stat buffs from companions.',
 'commander_tips': ['Plan catch only when Timekeeper and capacity allow — fails start catch '
                    'cooldown.',
                    'Mission variants trade duration for risk; claim on time.',
                    'Overview hotspots are companion missions, not galaxy combat.'],
 'faq': [{'q': 'Do titans give combat buffs?',
          'a': 'No. Flavor, Overview presence, and Ark Token missions only.'},
         {'q': 'Why no click SFX on a hotspot?',
          'a': 'SFX and mission popovers are for **owned** titans. Untamed silhouettes stay '
               'locked.'},
         {'q': 'Where do Ark Tokens go?',
          'a': 'Free Shop tab on `/shop` (Story owner) — not the EUR payment catalog.'}],
 'discord_summary': '**Titans — companions, Overview, Ark Tokens**\n'
                    '\n'
                    'World Boss catch → owned titan. Overview hotspots/SFX only when owned. '
                    'Missions → Ark Tokens. No combat buffs.'},
    "pirates": {'quick_help': '**Pirates** are a living galaxy threat: bases, faction AI, and Heat. Spy, attack, '
               'and salvage through the same fleet and combat pipeline as players.',
 'summary': 'The pirate ecosystem fills denser galaxies with temporary **pirate bases**, faction '
            'commanders in ranking, and raids that escalate with **galaxy Heat**. Pirates use spy '
            '→ intel → attack with canonical flight times. Destroy bases, watch bounty/threat, and '
            'face `pirate_war` crises when Heat peaks. Expeditions may add ambush and '
            'infiltration.',
 'why': 'Empty systems become contested space: farm targets, colony risk, and fairness (no cheat '
        'hangars, visible ETAs). Pirates keep the galaxy awake without chat bots.',
 'how_it_works': '- **Galaxy:** bases and AI worlds with status chips; inspector shows faction and '
                 'your bounty.\n'
                 '- **Heat:** combat, expo, asteroids, world boss, colonize heat systems — '
                 'thresholds unlock patrols, raids, crises.\n'
                 '- **Player actions:** spy/attack/recycle via `/fleet` and galaxy quick actions.\n'
                 "- **Destroy:** base gone → slot free; that base's outbound raids recall.\n"
                 '- **AI commanders:** real accounts in ranking/PlayerCard (AI badge); homeworlds '
                 'protected.\n'
                 '- **Threat/Bounty:** hard hitters become preferred revenge targets.',
 'commander_tips': ['Spy before raiding — intel cuts both ways.',
                    'Hot Heat systems are rich and dangerous; harden colonies there.',
                    "Don't mix recycler and raid fleets without a plan."],
 'faq': [{'q': 'Are pirates real players?',
          'a': 'Faction bots are AI accounts with hangars and planets — visible fleets, no chat. '
               'Temporary bases are map instances.'},
         {'q': 'Can my Genesis Ark be destroyed?',
          'a': 'No. Homeworlds are protected; only non-home colonies can fall under planet-breaker '
               'rules.'},
         {'q': 'Why am I being raided?',
          'a': 'High threat/bounty or a hot galaxy — AI prefers lucrative targets with visible '
               'flight time.'}],
 'discord_summary': '**Pirates — living galaxy threat**\n'
                    '\n'
                    'Bases + faction AI, Heat escalation, spy/attack via canonical fleets. Ranking '
                    'shows AI commanders. Homeworld safe; colonies at risk.'},
    "commander_classes": {'quick_help': 'On `/skilltree` pick a **Commander class** and unlock a linear skill trunk — '
               'account-wide via EffectResolver, not a second research tree.',
 'summary': 'Five classes shape playstyle: **Vanguard** (combat), **Forge Lord** (economy), '
            '**Archivist** (research), **Void Admiral** (fleet), **Envoy** (intel/support). Skill '
            'points come from score milestones. The trunk is strictly linear; capstones cost heavy '
            'Ferronite/Crytite/Fuel Cells from the context planet. Class swap costs Timekeeper, '
            'clears skills, refunds SP, and lets you re-pick. No in-class respec.',
 'why': 'Class is long-term Commander identity: soft mods on the existing effect stack — not '
        'parallel research and not Planet Evolution specialization. Story may use your Living '
        'Commander as narrator.',
 'how_it_works': '- Open **Skilltree** — cinematic pick, then trunk + inspector.\n'
                 '- **Claim SP** from due score milestones, then unlock ranks in order.\n'
                 '- **Capstones** cost steep resources from the active planet.\n'
                 '- **Swap:** debit Timekeeper → clear skills → refund SP → re-pick; cost rises '
                 'per swap.\n'
                 '- Bonuses merge through the same EffectResolver as alliance and boosters.',
 'commander_tips': ['Pick for your main loop — eco vs fleet vs PvP — not a bit of everything.',
                    'Claim SP first; only push capstones with full depots on the context planet.',
                    'Swap sparingly: Timekeeper is scarce and the trunk restarts.'],
 'faq': [{'q': 'Does class replace account research?',
          'a': 'No. Soft mods only — research, buildings, and Planet Evolution remain required.'},
         {'q': 'Can I respec single skills?', 'a': 'No — only a full class swap for Timekeeper.'},
         {'q': 'Is class planet-bound?',
          'a': 'No — account-wide. Capstone costs still pull from the context planet.'}],
 'discord_summary': '**Commander classes — Skilltree**\n'
                    '\n'
                    '`/skilltree`: one class, linear trunk, score SP, expensive capstones, '
                    'Timekeeper swap. EffectResolver bonuses — not a second research tree.'},
    "alliance": {'quick_help': 'The **Alliance** at `/alliance` is your social and cooperative hub: found, join, '
               'donate, run projects, and manage diplomacy.',
 'summary': 'Alliances have tag, logo, ranks (leader/officer/member), member limits, and '
            'recruitment modes. The **donation pool** takes Ferronite, Crytite, and Fuel Cells '
            'from the **active planet**. Officers start **alliance projects** (buildings/techs) '
            'from the pool — separate timing, not the planet build queue. Bonuses use '
            'EffectResolver; diplomacy covers NAP, pact, and war with fleet hooks.',
 'why': 'Together you scale LiveOps (World Boss), expo coordination, and defense. Alliance is '
        'shared progress and rules between Commanders — not a second empire screen.',
 'how_it_works': '- **Hub `/alliance`:** own cockpit or onboarding + directory; public '
                 '`/alliance/<id>`.\n'
                 '- **Join:** tag join or application by recruitment mode.\n'
                 '- **Donate:** resources from context planet into the pool — caps are '
                 'server-side.\n'
                 '- **Projects:** one active project; finish applies levels server-side.\n'
                 '- **Roles:** leader transfers/kicks/disbands; officers manage profile, logo, '
                 'apps, diplomacy.\n'
                 '- **Diplomacy:** NAP blocks attack; pact enables ally transport/hold; war opens '
                 'attack with flag.',
 'commander_tips': ['Donate from the planet with surplus — check context planet.',
                    'Officers: fill the pool before starting the next project.',
                    'Clarify NAP with neighbors before fleet misunderstandings.'],
 'faq': [{'q': 'Is alliance XP the same as ranking points?',
          'a': "No. Alliance XP/level drives projects; ranking's Alliance tab sums member scores "
               'separately.'},
         {'q': 'Can the leader leave?',
          'a': 'Only after transfer, or as the last member (then disband).'},
         {'q': 'Do alliance bonuses apply on every planet?',
          'a': 'Yes via EffectResolver; donations remain planet-scoped.'}],
 'discord_summary': '**Alliance — hub, pool, projects, diplomacy**\n'
                    '\n'
                    '`/alliance`: ranks, donations from the active planet, one project, '
                    'EffectResolver bonuses, NAP/pact/war with fleet hooks.'},
    "story_ops": {'quick_help': '**Genesis Story Ops** at `/story` are authorized transmissions and side ops — lore '
               'that reacts to real gameplay, not a daily quest reset.',
 'summary': 'You receive transmissions, make choices, and complete objectives in normal play '
            '(build, fleet, combat). Progress is persistent across chapters and arcs. Rewards are '
            'meta: containers, boosters, flags, inbox — never ships or resource stacks. **Ark '
            'Tokens** drip on chapter clears for the Free Shop; Titans can earn the same currency '
            'via missions.',
 'why': 'Story makes the empire narratable without a second daily-ops island beside Imperial '
        'Directives. They share the event bus — different owners and cadence.',
 'how_it_works': '- Open **Story**: hero orb, arc carousel, audio controls, mission/reward hints.\n'
                 '- **Advance / Choice:** server-authored; UI patches state without reload.\n'
                 '- Objectives listen to gameplay events while you keep playing.\n'
                 '- Optional neural TTS for transmissions.\n'
                 '- Living Commander (class) may appear as narrator portrait.\n'
                 '- Sidebar badge when a transmission or choice waits.',
 'commander_tips': ['Read Story and Imperial Directives as parallel rhythms on shared gameplay.',
                    'Treat choices seriously — flags unlock later beats and codex fragments.',
                    'Ark Tokens ≠ EUR shop — use the Free Shop tab.'],
 'faq': [{'q': 'Do Story Ops reset daily?',
          'a': 'No. Story is persistent; daily/weekly ops belong to Directives / Battle Pass.'},
         {'q': 'Do I claim like Directives?',
          'a': 'Narrative rewards typically auto-grant; the UI shows the notice.'},
         {'q': 'Do I need a Commander class?',
          'a': 'Recommended for immersion, but arcs can start without one.'}],
 'discord_summary': '**Story Ops — transmissions & side ops**\n'
                    '\n'
                    '`/story`: persistent arcs, choices, gameplay objectives, meta rewards, Ark '
                    'Tokens/Free Shop. No daily reset — Directives stay separate.'},
    "liveops_retention": {'quick_help': '**Login calendar** (`/login-rewards`) and **Battle Pass** (`/premium`) are the F2P '
               'LiveOps rail: daily attendance and season ops for meta rewards.',
 'summary': 'The login calendar is a rolling attendance track: one claim per UTC day, strictly '
            'sequential; gaps reset the streak. Milestone days grant stronger containers and '
            'Timekeeper-adjacent rewards. The **Battle Pass** has free and premium tracks, season '
            'ops, and a soft activity drip. Premium uses the same entitlement path as the shop. '
            'Rewards stay meta — never ships or Ferronite stacks.',
 'why': 'Retention without pay-to-win: High Command greets you daily; the season rewards active '
        'play. Paid is convenience and FOMO; free stays valuable.',
 'how_it_works': '- **`/login-rewards`:** claimed / claimable / locked calendar; server events may '
                 'overlay (read-only).\n'
                 '- Claim only the next due day — no makeup for missed days.\n'
                 '- **`/premium`:** horizontal free/premium trackboard, season ops cards, level/op '
                 'claims.\n'
                 '- XP from ops and capped activity drip — server authored.\n'
                 '- Mid-season premium unlock makes already-reached premium tiers claimable.\n'
                 '- Nav badges flag claimable ops/rewards.',
 'commander_tips': ['Protect the login streak — a missed UTC night resets you.',
                    'Claim daily ops before going offline; keep weekly progress rolling.',
                    'Buy premium only if you still play the season — mid-season catches up reached '
                    'tiers.'],
 'faq': [{'q': 'Is Battle Pass pay-to-win?',
          'a': 'No. Tracks grant meta/QoL/cosmetics — not ships, defense, or resource stacks as '
               'paid power.'},
         {'q': 'Difference from Imperial Directives?',
          'a': 'Directives = rotating command ops with their own loot. Login/BP = attendance + '
               'season track.'},
         {'q': 'Where do I unlock premium?',
          'a': 'Shop Season Pass SKU (or LiveOps grant) — same entitlement flag.'}],
 'discord_summary': '**LiveOps — login calendar & Battle Pass**\n'
                    '\n'
                    '`/login-rewards` + `/premium`: daily streak, free/premium tracks, season ops. '
                    'Meta rewards only. Premium = shop entitlement.'},
    "shop_identity": {'quick_help': 'The **Shop** at `/shop` sells convenience and **identity**: Season Pass, '
               'Timekeeper packs, booster/container bundles — plus name styles. Theme and aura '
               'shape your UI shell.',
 'summary': 'Payment fulfills allowed SKUs only: premium entitlement, Timekeeper, meta containers, '
            'booster bundles, titan slot, cosmetics. **No** resource, ship, or defense shop. The '
            '**identity shell** separates signals: equipped PlayerCard **theme** colors chrome; '
            '**aura** adds prestige glow; **name style** styles only the visible name in galaxy, '
            'chat, ranking, and more. Free Shop (Ark Tokens) is a separate tab — Story owner, not '
            'the EUR catalog.',
 'why': 'Paid accelerates patience and expression, not combat victory. Identity makes Commanders '
        'recognizable in multiplayer surfaces without a second cosmetics engine.',
 'how_it_works': '- Browse `/shop` → checkout → provider → webhook/return fulfillment '
                 '(idempotent).\n'
                 '- Season Pass writes the same premium flag as LiveOps.\n'
                 '- Unlock cosmetics and equip them on the PlayerCard.\n'
                 '- Theme/aura affect your shell; name style affects name links everywhere.\n'
                 '- Legal ack before purchase; virtual goods credit after fulfillment.',
 'commander_tips': ['Exhaust free baseline (login, directives, BP free) first — paid is impulse.',
                    'Name style is socially visible; theme/aura are mostly your chrome.',
                    "Ark Token tab ≠ EUR tab — don't mix currencies."],
 'faq': [{'q': 'Can I buy Ferronite?',
          'a': 'No. Shop and loot stay meta-only for paid/convenience.'},
         {'q': "Why doesn't name style change UI color?",
          'a': 'By design: name style ≠ theme. Color comes from the equipped theme.'},
         {'q': 'What is the Free Shop?',
          'a': 'Ark Token redemption (Story/Titans) on the shop tab — no real money.'}],
 'discord_summary': '**Shop & identity**\n'
                    '\n'
                    '`/shop`: Season Pass, TK, meta packs, cosmetics. Theme/aura = shell; name '
                    'style = name only. No resource/ship shop. Free Shop = Ark Tokens.'},
    "inventory": {'quick_help': '**Inventory** at `/inventory` is your meta vault: open containers, use items, top '
               'up Timekeeper, and trigger craft/exchange.',
 'summary': 'Lootboxes, boosters, fragments, and utilities from login, Battle Pass, shop, story, '
            'expeditions, and events land here. Containers roll **meta only** (items/boosters — no '
            'Ferronite/ship drops). **Timekeeper** is the empire-wide time balance: credit from '
            'items/rewards, apply manually with ⚡ on running queues. Tabs cover containers, items, '
            'and the Relic Arena (Case Battles).',
 'why': 'Meta progression needs a home that is not an economy printer. Inventory bundles '
        'consumption and craft so buildings, research, and combat stay server-authoritative.',
 'how_it_works': '- **`/inventory`:** load state, open containers, use/craft items.\n'
                 '- Loot pools are meta-only; collectibles may later redeem at Collector '
                 'Exchange.\n'
                 '- **Timekeeper:** deposit legacy time items, then ⚡ on '
                 'build/research/shipyard/defense/PE queues.\n'
                 '- Boosters activate server-side and appear in state.\n'
                 '- Nav badge flags Case Battle or other inventory attention.',
 'commander_tips': ['Save Timekeeper for long offline jobs; let short fillers run without TK.',
                    'Open containers when you need boosters now — otherwise inventory fills with '
                    '“later”.',
                    'Fragments feed lifetime stats and Collector Exchange — collecting matters.'],
 'faq': [{'q': 'Why no Ferronite from boxes?',
          'a': 'By design (meta-only). Resources come from mines, trade, debris, and missions.'},
         {'q': 'Is Timekeeper automatic?',
          'a': 'Not for human sessions — you apply ⚡ deliberately. (Autoplay/AI is an ops '
               'exception.)'},
         {'q': 'Where is the Relic Arena?',
          'a': 'Inventory tab — Case Battles with sealed containers.'}],
 'discord_summary': '**Inventory — containers, items, Timekeeper**\n'
                    '\n'
                    '`/inventory`: open/use meta loot, deposit TK, apply to queues. No '
                    'resource/ship boxes. Case Battles as a tab.'},
    "collector_exchange": {'quick_help': 'The **Collector Exchange** in the Trader Hub trades fragments and collectibles for '
               'boosters, utility, and curated offers — not Ferronite exchange rates.',
 'summary': 'Four specialists (Xenobiologist, Scrapmaster, Energy Engineer, Hypertech) take '
            'inventory collectibles and return fixed offers. Every grant raises your **lifetime '
            'stats** permanently — redeeming lowers inventory only, never lifetime. Prestige '
            'badges/titles track lifetime milestones. Wreck reconstruction and DNA paths are '
            'curated offers, not lootbox inflation.',
 'why': 'After meta-only loot, fragments must not die as badges: every drop is progress — redeem '
        'now or save toward milestones.',
 'how_it_works': '- Open Trader Hub → Collector Exchange / pick a specialist.\n'
                 '- Choose an offer, check inputs, redeem (idempotent) — rewards to inventory or '
                 'context planet when planet-bound.\n'
                 '- Inventory craft and exchange may share sinks (e.g. DNA) — UI shows both '
                 'paths.\n'
                 '- Not the Unified Resource Trader rates.',
 'commander_tips': ['Watch lifetime goals before burning everything for instant boosters.',
                    'Scrapmaster for shipyard-adjacent boosts; Xenobiologist for research/PE.',
                    "Redeem only with enough input — partial stacks won't clear an offer."],
 'faq': [{'q': 'Do redeemed fragments leave my statistics?',
          'a': 'No. Lifetime only rises — redeem lowers inventory balance only.'},
         {'q': 'Same trader as Ferronite/Crytite?',
          'a': 'No. Resource trader and scrapyard stay separate; Collector is collectible ↔ '
               'progress.'},
         {'q': 'Can Exchange grant ships?',
          'a': 'Only via curated reconstruction offers — never as random lootbox rolls.'}],
 'discord_summary': '**Collector Exchange — fragments with purpose**\n'
                    '\n'
                    'Trader Hub specialists: fragments → boosters/utility/curated offers. Lifetime '
                    'stats never drop. Prestige through collecting.'},
    "asteroids": {'quick_help': '**Asteroid fields** appear for a limited time in dense galaxy systems. Harvest '
               'them with the **reclaimer** using the **recycle** mission.',
 'summary': 'Waves spawn belts of Ferronite rock, Crytite shards, fuel ice, or mixed belts on free '
            'classic slots. Multiple fleets may launch — **first arrival** claims the pool. '
            'Expired fields do not fall back to debris. The galaxy board shows en-route status and '
            'next-wave countdown.',
 'why': 'Short-lived contested resource prizes without a new miner class: existing recycle '
        'pipeline, visible competition, LiveOps tempo in full systems.',
 'how_it_works': '- Open a galaxy system with an active asteroid board; read type and timers.\n'
                 '- Send reclaimers on recycle targeting the asteroid — prefill/quick action '
                 'helps.\n'
                 '- Arrival: claimed, missed, or expired — report explains the outcome.\n'
                 '- Your own outbound disables harvest until return or field gone.\n'
                 '- Loot is Ferronite / Crytite / Fuel Cells into cargo only; remainder is lost if '
                 'cargo is short.',
 'commander_tips': ['Watch dense systems — belts spawn there first.',
                    'Check cargo and reclaimer count before send; first arrival wins.',
                    "Don't confuse with debris recycle: asteroid flights never fall through to "
                    'debris.'],
 'faq': [{'q': 'Which ship?',
          'a': 'Reclaimer with recycle role — mixed fleets OK; mission stays recycle.'},
         {'q': 'Can the field expire mid-flight?',
          'a': 'Yes — then an expired report, no automatic debris.'},
         {'q': 'World Boss on the slot?',
          'a': 'Boss wins priority; asteroids need a free classic slot.'}],
 'discord_summary': '**Asteroids — timed harvest**\n'
                    '\n'
                    'Galaxy belts, recycle mission, first-arrival claim. Resource loot only. Board '
                    'shows en-route and wave timer.'},
    "case_battles": {'quick_help': 'The **Relic Arena** (Case Battles) in inventory lets Commanders stake sealed '
               'containers — simultaneous opens; the best find claims the pool.',
 'summary': 'Create or join a battle (public/private), escrow containers, and pick a mode '
            '(Standard, Crazy, Terminal, Share, Team). All seals break in parallel. Winner logic '
            'and reward values are server-only; then seed reveal and verify. Meta-only drops — '
            'same loot engine as normal containers.',
 'why': 'A social spike for inventory overflow: fair, auditable container wagers without cashout '
        'and without client-side loot math.',
 'how_it_works': '- Inventory → **Relic Arena** tab.\n'
                 '- Create/Join consumes containers atomically; cancel while open refunds.\n'
                 '- open → running → finished (or cancelled); auto-settle catches stuck runs.\n'
                 '- Modes change distribution (Share proportional, Team splits foe loot, Terminal '
                 'per round).\n'
                 '- After finish: verify seed via API.\n'
                 '- Nav badge on inventory when you are in open/running battles.',
 'commander_tips': ['Only stake containers you can afford to lose — escrow is real until '
                    'cancel/finish.',
                    'Read the mode before joining (Share ≠ winner-takes-all).',
                    'Use private lobbies with friends to avoid randoms.'],
 'faq': [{'q': 'Can I cash out real money?', 'a': 'No. Inventory meta items only — no cashout.'},
         {'q': 'Are rolls manipulable?',
          'a': 'Commit-reveal: hash before the battle, seed after finish — verify checks the '
               'chain.'},
         {'q': 'Is this pay-to-win?', 'a': 'You stake owned containers; wins stay meta-only.'}],
 'discord_summary': '**Relic Arena — Case Battles**\n'
                    '\n'
                    'Inventory tab: container escrow, simultaneous opens, server winner, seed '
                    'verify. Modes include Share/Team. Meta-only.'},
    "galactic_directives": {'quick_help': '**Galactic Directives** at `/galactic-politics` are per-galaxy macro politics: the '
               'community votes; Primary and Secondary shape bonuses for all worlds in that '
               'galaxy.',
 'summary': 'Unlike Planet Policies (you choose locally), Galactic Directives run in monthly '
            'cycles: vote on candidate directives, then a mandate with **Primary** (full effect) '
            'and **Secondary** (weaker or dedicated secondary set). Effects flow through '
            'EffectResolver into production, research, fleet, defense, and more — with tradeoffs. '
            'Multiple galaxies mean multiple political landscapes.',
 'why': 'Spatial strategy: a mining colony in G1 and a research hub in G2 should feel different '
        'mandates. Politics becomes an endgame lever above the empire without replacing Planet '
        'Policies.',
 'how_it_works': '- Open **Galactic Politics**; pick a galaxy where you hold colonies.\n'
                 '- While voting is open: one vote per cycle for a Primary candidate — changeable '
                 'until the window ends.\n'
                 '- Resolution sets Primary/Secondary; the following month is the active mandate.\n'
                 '- Repeated Primary wins may trigger cooldowns (server rule).\n'
                 '- Results messages announce outcomes; LiveOps may force when needed.\n'
                 '- Planet Policies still stack — micro + macro via Effects.',
 'commander_tips': ['Vote in every galaxy you seriously produce in.',
                    'Read tradeoffs — strong Primary buffs rarely come free.',
                    'Align local policies with the galactic mandate.'],
 'faq': [{'q': 'Does this replace Planet Policies?',
          'a': 'No. Policies = per colony. Directives = per galaxy for everyone there.'},
         {'q': 'Is alliance diplomacy involved?',
          'a': 'No — alliance NAP/war is separate. Politics is galaxy community vote.'},
         {'q': 'Where are the exact bonus magnitudes?',
          'a': 'Politics UI / Technical Data — the Codex explains the principle only.'}],
 'discord_summary': '**Galactic Directives — macro politics**\n'
                    '\n'
                    '`/galactic-politics`: monthly vote per galaxy, Primary+Secondary mandates, '
                    'EffectResolver. Complementary to Planet Policies.'},
    "salvage": {'quick_help': '**Salvage** opens **wreckage fields** on the Command Map: an expedition mission to '
               'the world, with a salvage report instead of a classic slot-16 expo substitute.',
 'summary': '`wreckage_field` worlds are playable map targets. Start salvage from the inspector; '
            'the fleet flies mission **expedition** with `world_key`. Outcomes use salvage-capable '
            'event keys. Classic **recycle** remains for combat debris and asteroids — different '
            'target type, same reclaimer ships possible.',
 'why': 'Wrecks tell loss and opportunity on the empire map without forcing combat on the salvage '
        'world. Salvage extends the expedition pipeline instead of a second fleet engine.',
 'how_it_works': '- Find a wreckage field on Command Map / Empire with a salvage badge.\n'
                 '- Preview checks ships and startability; inspector → prepare/start salvage.\n'
                 '- Fleet prefill: expedition + world key; activity like other world missions.\n'
                 '- Return: salvage report with world name.\n'
                 "- PvP debris: separate recycle mission on galaxy slots — don't confuse with "
                 'wreckage fields.',
 'commander_tips': ['Check salvage ships in preview before launch.',
                    'Wreckage ≠ asteroid ≠ debris: read mission and target type in the UI.',
                    'Keep reports for follow-up flight context.'],
 'faq': [{'q': 'Is salvage a fight?',
          'a': 'Phase-1 wreckage fields use the expedition outcome pipeline without a combat focus '
               'on the salvage world.'},
         {'q': 'Difference from asteroids?',
          'a': 'Asteroids: classic slots, recycle, first arrival. Salvage: Command Map world, '
               'expedition + world key.'},
         {'q': 'Do I need a special recycler building?',
          'a': 'No — canonical fleet missions and existing reclaimer/expedition ships.'}],
 'discord_summary': '**Salvage — wreckage fields on the map**\n'
                    '\n'
                    'Command Map → expedition with world key → salvage report. Debris/asteroids '
                    'stay recycle. No second fleet engine.'},
    "ranking": {
        "quick_help": (
            "**Ranking** compares Commanders by empire score and related boards under `/ranking` — "
            "wealth components, combat prestige, World Boss damage, and alliances."
        ),
        "summary": (
            "The ranking page shows how empires compare. Core score is the **normalized total "
            "resource wealth** of an account (buildings, research, fleet, defense, Planet Evolution, "
            "stockpiles) — not a separate vanity formula. Tabs break down components; World Boss and "
            "destruction are separate prestige signals."
        ),
        "why": (
            "Commanders need a fair, readable ladder: who invested where, who fights, who hits the "
            "World Boss. Ranking makes progress visible without inventing a second economy."
        ),
        "how_it_works": (
            "- Open **`/ranking`** for boards and your placement.\n"
            "- **Total score** = conserved wealth (resources invested + stockpiles) via the score "
            "owner — trading at score-neutral rates does not create points.\n"
            "- Tabs: buildings, research, evolution, fleet, defense, World Boss damage, alliance "
            "sums — UI shows server snapshots.\n"
            "- Combat destruction prestige is separate from wealth total.\n"
            "- Scores refresh on a server schedule; do not reverse-engineer points in the Codex."
        ),
        "commander_tips": [
            "Spend resources into buildings/fleet — wealth moves between score buckets, total stays "
            "when nothing is burned.",
            "World Boss tab is lifetime damage, not wealth.",
            "Inactive accounts may drop from live boards — keep playing.",
        ],
        "faq": [
            {
                "q": "Does trading raise my score?",
                "a": "Score-neutral trader rates only move wealth between metal/crystal/fuel — they "
                "do not mint points.",
            },
            {
                "q": "Why did my score drop after a fight?",
                "a": "Destroyed own units remove wealth. Destruction prestige is a separate signal.",
            },
        ],
        "discord_summary": (
            "**Ranking — empire score boards**\n\n"
            "`/ranking`: wealth score + component tabs, World Boss damage, alliances. Server "
            "snapshots. Unlocks after first visit."
        ),
    },
    "auction": {
        "quick_help": (
            "The **Auction House** under `/auction-house` lists rotating lootbox containers. Bid "
            "with resources from your **active planet** — winners receive inventory containers."
        ),
        "summary": (
            "Auctions offer a live rotation of meta containers (no event boxes). You bid Ferronite, "
            "Crytite, or Fuel Cells from the context planet. Listings expire; the highest valid bid "
            "wins and the box lands in **Inventory**. No ships or raw resource stacks as auction "
            "loot."
        ),
        "why": (
            "Auctions add a timed market for meta loot without a second economy. Resource bids "
            "sink wealth into containers you open later — same inventory pipeline as other rewards."
        ),
        "how_it_works": (
            "- Open **`/auction-house`** — active listings, your bids, and rotation countdown.\n"
            "- Place bids from the **active planet** wallet; minimum raise and bid limits are "
            "server-side.\n"
            "- When a listing ends, the winner gets the container in Inventory; losers keep their "
            "resources (except what was outbid).\n"
            "- Event boxes never appear in rotation.\n"
            "- Nav badge can mark new listings after your last visit."
        ),
        "commander_tips": [
            "Switch to a planet with enough resources before bidding.",
            "Watch remaining time — last-second raises are common.",
            "Won boxes go to Inventory — open them there, not on the auction page.",
        ],
        "faq": [
            {
                "q": "Can I buy ships here?",
                "a": "No — only meta containers into Inventory.",
            },
            {
                "q": "Where do resources come from?",
                "a": "From the active (context) planet — check the header switcher.",
            },
        ],
        "discord_summary": (
            "**Auction House — timed container bids**\n\n"
            "`/auction-house`: rotate listings, bid with active-planet resources, win → Inventory. "
            "No event boxes. Unlocks after first visit."
        ),
    },
    "messages": {
        "quick_help": (
            "**Messages** (`/messages`) is your inbox: combat reports, expedition results, "
            "logistics, system notices, and more — keep it open beside Chat."
        ),
        "summary": (
            "The inbox collects server-authored reports and notices for your Commander. Combat "
            "opens the full report modal; expeditions and logistics land as event cards; system "
            "mail covers alliance, directives, and ops. Archive and mark-read are client actions "
            "on server state."
        ),
        "why": (
            "Fleets and events resolve while you are elsewhere. Messages are the durable log so "
            "you never miss a fight outcome, expo find, or logistics arrival."
        ),
        "how_it_works": (
            "- Open **`/messages`** from the nav (always available).\n"
            "- Filter by category; open a row for full detail or combat theater.\n"
            "- Mark read / read-all / archive without inventing local report copies.\n"
            "- Chat is separate live social — Messages is the report archive."
        ),
        "commander_tips": [
            "Check after fleet arrivals — combat and expo reports land here first.",
            "Unread badge in the nav means something waiting.",
            "Archive clutter; keep important combat reports until you reviewed losses.",
        ],
        "faq": [
            {
                "q": "Messages vs. Chat?",
                "a": "Chat is live conversation. Messages is the inbox for reports and system mail.",
            },
            {
                "q": "Where are combat details?",
                "a": "Open the combat message — full report / theater from the inbox entry.",
            },
        ],
        "discord_summary": (
            "**Messages — inbox for reports**\n\n"
            "`/messages`: combat, expo, logistics, system. Always unlocked. Chat stays separate."
        ),
    },
    "referrals": {
        "quick_help": (
            "**Referrals** under `/referrals`: share your code, link new Commanders, and claim "
            "tier rewards as referred players become active."
        ),
        "summary": (
            "Each Commander has a unique referral code and link. New players can apply a code once "
            "(at register or in-game). When referred accounts meet activity milestones, the referrer "
            "unlocks tier rewards — meta containers into **Inventory**. Same-IP referrals are "
            "recorded but do not count toward tiers."
        ),
        "why": (
            "Grow the community with fair invites: rewards for real activity, not empty alts. "
            "Rewards stay in the inventory meta loop — no resource dump."
        ),
        "how_it_works": (
            "- Open **`/referrals`** for your code, link, progress, and claimable tiers.\n"
            "- Share the link/code; the referred player applies it once.\n"
            "- Activity gates (account age / planet progress) decide when a referral counts.\n"
            "- Claim tier boxes into Inventory when required counts are met.\n"
            "- Server rejects abuse patterns (e.g. same IP) for tier credit."
        ),
        "commander_tips": [
            "Share the link early — codes apply only once per account.",
            "Claim tiers when the counter fills; boxes wait in Inventory.",
            "Don't farm same-IP alts — they won't count.",
        ],
        "faq": [
            {
                "q": "Can I change my referrer later?",
                "a": "No — a code links once per account.",
            },
            {
                "q": "What do I get?",
                "a": "Tiered meta containers in Inventory after referred players qualify.",
            },
        ],
        "discord_summary": (
            "**Referrals — invite code and tiers**\n\n"
            "`/referrals`: unique code, activity-gated tiers, Inventory rewards. Unlocks after "
            "first visit."
        ),
    },
    "influence": {
        "quick_help": (
            "**Influence** is the visible teal territory around your Genesis Ark and colonies on "
            "the Command Map — your empire's footprint, not a combat buff."
        ),
        "summary": (
            "Influence paints your own realm on the world map: a soft teal area around the Ark hub "
            "and linked colonies. Locked Expansion Sites stay outside. It is derived from your "
            "colony positions — no separate DB economy and no enemy territory in the MVP layer."
        ),
        "why": (
            "You should see \"this is mine\" at a glance. Influence makes hub-and-spoke ownership "
            "readable before presence of other Commanders arrives."
        ),
        "how_it_works": (
            "- Open the **Command Map** (`/galaxy` world-map tab).\n"
            "- Teal influence surrounds the Genesis Ark and your colonies.\n"
            "- Expansion Sites do not gain influence until unlocked/claimed as appropriate.\n"
            "- Pan/zoom keeps the layer under fog and above the background.\n"
            "- No production or combat modifiers from influence in this layer — display first.\n"
            "- Codex unlock from Ark development stage **10**."
        ),
        "commander_tips": [
            "Read influence as your footprint while planning expansion.",
            "Empty gaps between colonies are normal until you settle more worlds.",
            "Don't expect PvP buffs from the teal glow — it is territory visualization.",
        ],
        "faq": [
            {
                "q": "Does influence give bonuses?",
                "a": "Not in the base influence layer — it visualizes your empire territory.",
            },
            {
                "q": "Do I see other players' influence?",
                "a": "MVP focuses on your own realm; foreign presence is a later layer.",
            },
        ],
        "discord_summary": (
            "**Influence — your empire glow on the map**\n\n"
            "Command Map teal footprint around Ark + colonies. Display layer, not combat math. "
            "Codex from Ark stage 10."
        ),
    },
    "faq_general": {
        "quick_help": (
            "**General FAQ** — short answers for new Commanders: where to start, how the Codex "
            "works, and which surfaces matter in the first hour."
        ),
        "summary": (
            "A cross-cutting FAQ for Genesis Colonies: Genesis Ark first, active world vs. empire, "
            "queues, Codex unlocks, and where to ask for help. It does not replace system articles — "
            "it points you to them."
        ),
        "why": (
            "New Commanders hit the same questions before specialized Codex entries unlock. A "
            "always-on FAQ reduces confusion without spoiling later systems."
        ),
        "how_it_works": (
            "- Always unlocked in the Codex (Band I).\n"
            "- Use it when you are unsure which page or article to open next.\n"
            "- Deeper mechanics live in buildings, research, Planet Evolution, fleet, and related "
            "articles.\n"
            "- Game rules / options may link related community policies separately."
        ),
        "commander_tips": [
            "Start on Overview and stabilize Ark production before expanding.",
            "Check the header planet switcher before spending resources.",
            "Locked Codex entries show a teaser — visit the related page or grow the Ark.",
        ],
        "faq": [
            {
                "q": "What should I do first?",
                "a": "Build production on the Genesis Ark, keep build/research queues running, and "
                "learn Planet Evolution as long-term progress.",
            },
            {
                "q": "Why is a Codex topic locked?",
                "a": "Many entries unlock by Ark stage, a building, or visiting the related page — "
                "read the teaser.",
            },
            {
                "q": "Where is help in-game?",
                "a": "Codex panel, Quick Help on pages, and this FAQ. Combat/expo details also land "
                "in Messages.",
            },
        ],
        "discord_summary": (
            "**General FAQ — first-hour answers**\n\n"
            "Always-on Codex entry: start on the Ark, planet scope, unlock teasers, where to dig "
            "deeper."
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
