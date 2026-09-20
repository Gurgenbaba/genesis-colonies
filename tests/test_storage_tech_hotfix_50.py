from game.effects.effect_resolver import EffectResolver, STORAGE_TECH_PER_LEVEL


def test_storage_tech_balance_is_ten_percent_per_level():
    assert STORAGE_TECH_PER_LEVEL == 0.10
    assert EffectResolver.storage_bonus_pct(1) == 10
    assert EffectResolver.storage_bonus_pct(10) == 100


def test_storage_tech_balance_is_additive_in_canonical_modifier():
    resolver = EffectResolver({}, {'storage_tech': 2}, settings={})
    assert resolver.get_modifiers()['storage_factor'] == 1.2
