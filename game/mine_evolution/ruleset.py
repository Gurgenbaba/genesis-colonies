"""Mine Ascension ruleset identity used by release/config guards."""

ASCENSION_RULESET = "skill-tree-v1"


def is_skill_tree_ruleset() -> bool:
    return ASCENSION_RULESET == "skill-tree-v1"
