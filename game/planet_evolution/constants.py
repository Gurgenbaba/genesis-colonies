"""Planet Evolution System — constants and caps."""

from __future__ import annotations

AFFINITY_KEYS = (
    "industry",
    "science",
    "energy",
    "military",
    "trade",
    "ecology",
    "governance",
    "experimental",
    "ancient",
)

PLANET_CLASSES = (
    "terrestrial",
    "volcanic",
    "ice",
    "barren",
    "oceanic",
    "ruin",
    "gas_giant_moon",
)

CULTURE_ARCHETYPES = (
    "frontier_settlers",
    "militarized_society",
    "scientific_collective",
    "corporate_syndicate",
    "ai_governance",
    "criminal_underworld",
    "industrial_union_state",
    "isolationists",
)

MAX_PLANET_LEVEL = 30
SPECIALIZATION_UNLOCK_LEVEL = 8
IDENTITY_TEASER_MIN_LEVEL = 3
MAX_SPECIALIZATION_TIER = 3
MAX_ASCENSION_RANK = 3
EVENT_COOLDOWN_HOURS = 48
POLICY_COOLDOWN_HOURS = 72
MAX_ACTIVE_EVENTS = 1
MECHANICS_COMPILE_VERSION = 1

LEVEL_UNLOCKS = {
    3: ("dna_reveal", 1),
    5: ("policy_slot", 1),
    8: ("specialization",),
    12: ("export_slot", 2),
    15: ("dna_reveal", 2),
    18: ("policy_slot", 2),
    22: ("experimental_gate",),
    25: ("ascension",),
    30: ("policy_slot", 3),
}

RARITY_TIER_ORDER = ("common", "uncommon", "rare", "epic", "legendary")

RARITY_XP_MULT = {
    "common": 1.0,
    "uncommon": 1.2,
    "rare": 1.5,
    "epic": 2.0,
    "legendary": 3.0,
}

DISCOVERY_RARITY_MULT = {
    "common": 1,
    "uncommon": 2,
    "rare": 5,
    "epic": 15,
    "legendary": 50,
}
