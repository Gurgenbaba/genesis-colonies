"""Production regression: mine Ascension gates must never surface as generic errors."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_build_action_maps_ascension_required_to_existing_localized_copy():
    src = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    block = src.split("function mapActionError(reason, payload)", 1)[1].split("\n  function ", 1)[0]
    assert 'reason === "ascension_required"' in block
    assert 't("buildings_mine_evo_progress"' in block
    assert 't("buildings_mine_evo_action"' in block
    assert "return `${progress}: ${action}`" in block


def test_existing_ascension_copy_is_present_in_every_locale():
    for locale in ("de", "en", "fr", "es", "pl", "tr", "ru", "pt"):
        text = (ROOT / "locales" / f"{locale}.json").read_text(encoding="utf-8")
        assert '"buildings_mine_evo_progress"' in text, locale
        assert '"buildings_mine_evo_action"' in text, locale


def test_backend_keeps_semantic_ascension_reason():
    src = (ROOT / "game" / "buildings.py").read_text(encoding="utf-8")
    assert 'last_reason = "ascension_required" if is_evolution_mine else "invalid"' in src


def test_level_385_has_headroom_after_rank_viii_catchup():
    import game.buildings as buildings
    from game.mine_evolution import UNCAPPED_BUILDING_LEVEL

    rank_vii_cap = buildings._effective_building_queue_cap(
        "metal_mine",
        UNCAPPED_BUILDING_LEVEL,
        planet_id=1,
        evolution_rank=7,
    )
    rank_viii_cap = buildings._effective_building_queue_cap(
        "metal_mine",
        UNCAPPED_BUILDING_LEVEL,
        planet_id=1,
        evolution_rank=8,
    )

    assert rank_vii_cap == 375
    assert rank_viii_cap == 400
    assert 385 > rank_vii_cap
    assert 386 <= rank_viii_cap
