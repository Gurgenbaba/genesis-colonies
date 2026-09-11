from game.effects.effect_resolver import EffectResolver, STORAGE_TECH_PER_LEVEL


def test_storage_tech_hotfix_is_fifty_percent_per_level():
    assert STORAGE_TECH_PER_LEVEL == 0.50
    assert EffectResolver.storage_bonus_pct(1) == 50
    assert EffectResolver.storage_bonus_pct(10) == 500


def test_storage_tech_hotfix_is_additive_in_canonical_modifier():
    resolver = EffectResolver({}, {'storage_tech': 2}, settings={})
    assert resolver.get_modifiers()['storage_factor'] == 2.0
