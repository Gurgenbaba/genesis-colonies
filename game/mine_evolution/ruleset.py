"""Mine Ascension ruleset identity used by release/config guards."""

ASCENSION_RULESET = "nodebuster-v1"


def is_nodebuster_ruleset() -> bool:
    return ASCENSION_RULESET == "nodebuster-v1"
