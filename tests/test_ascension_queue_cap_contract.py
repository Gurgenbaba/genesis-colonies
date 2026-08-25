from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_build_enqueue_caps_max_by_slots_and_ascension_headroom():
    source = (ROOT / "game" / "buildings.py").read_text(encoding="utf-8")
    assert "def _effective_building_queue_cap(" in source
    assert "required_level_for_evolution(rank + 1)" in source
    assert "queue_free_slots = max(0, int(queue_limit) - len(rows_db))" in source
    assert "level_headroom = max(" in source
    assert "max_attempts = min(64, queue_free_slots, level_headroom)" in source
    assert 'last_reason = "ascension_required" if is_evolution_mine else "invalid"' in source


def test_building_ui_treats_ascension_gate_as_max_state():
    template = (ROOT / "templates" / "buildings.html").read_text(encoding="utf-8")
    assert "(not _uncapped_action) and" not in template
    assert "(not _uncapped) and" not in template
