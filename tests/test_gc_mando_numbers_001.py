"""GC-MANDO-NUMBERS-001 — huge exact numbers stay usable on Mando's three surfaces."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_exact_number_styles_are_shell_loaded():
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "mando_exact_numbers.css").read_text(encoding="utf-8")
    assert "css/mando_exact_numbers.css" in base
    assert ".resource-bar-cmd .res-value" in css
    assert ".gc-records-row-value" in css
    assert ".gc-hof-table .gc-hof-col-num" in css
    assert "font-variant-numeric: tabular-nums" in css


def test_records_and_hof_keep_exact_values_not_scientific_notation():
    records = (ROOT / "templates" / "records.html").read_text(encoding="utf-8")
    hof = (ROOT / "templates" / "hall_of_fame.html").read_text(encoding="utf-8")
    assert "record.value_fmt" in records
    assert "total_destroyed_score_fmt" in hof
    assert "debris_total_fmt" in hof
    assert "loot_total_fmt" in hof
    combined = records + hof
    assert "toExponential" not in combined
    assert "toPrecision" not in combined


def test_huge_number_layout_does_not_ellipsis_record_or_hof_values():
    css = (ROOT / "static" / "css" / "mando_exact_numbers.css").read_text(encoding="utf-8")
    record_block = css.split(".gc-records-row-value", 1)[1].split("}", 1)[0]
    hof_block = css.split(".gc-hof-table .gc-hof-col-num", 1)[1].split("}", 1)[0]
    assert "overflow-x: auto" in record_block
    assert "text-overflow: ellipsis" not in record_block
    assert "white-space: nowrap" in record_block
    assert "white-space: nowrap" in hof_block


def test_hud_prioritizes_three_main_resources_and_compacts_energy_without_ellipsis():
    css = (ROOT / "static" / "css" / "mando_exact_numbers.css").read_text(encoding="utf-8")
    bar_block = css.split(".resource-bar.resource-bar-cmd {", 1)[1].split("}", 1)[0]
    value_block = css.split(".resource-bar-cmd .res-value {", 1)[1].split("}", 1)[0]
    tk_block = css.split(".resource-bar-cmd .hud-res-timekeeper {", 1)[1].split("}", 1)[0]
    assert "grid-template-columns: repeat(3, minmax(0, 1fr)) minmax(9.5rem, 0.52fr) !important" in bar_block
    assert "width: 100% !important" in bar_block
    assert "max-width: none !important" in bar_block
    assert "overflow-x: auto" in bar_block
    assert "scrollbar-gutter: stable" in bar_block
    assert "display: none !important" in tk_block
    assert "min-height: 4.35rem" in css
    assert ".resource-bar-cmd .hud-res-energy .res-icon--hud" in css
    assert "min-inline-size: 10rem" in css
    assert "min-inline-size: 18rem" not in css
    assert "overflow-x: auto" in value_block
    assert "text-overflow: ellipsis" not in value_block
    assert "text-align: right" in value_block


def test_timekeeper_is_presented_in_header_and_mirrors_live_resource_balance():
    partial = (ROOT / "templates" / "partials" / "header_language_switcher.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "mando_exact_numbers.css").read_text(encoding="utf-8")
    assert partial.index('class="gc-language-switcher"') < partial.index('class="gc-hud-panel gc-header-timekeeper"')
    assert "img/res/timekeeper.webp" in partial
    assert "data-timekeeper-header-balance" in partial
    assert 'document.querySelector("#resource-bar [data-timekeeper-balance]")' in partial
    assert "MutationObserver(sync)" in partial
    assert ".gc-header-timekeeper" in css
    assert ".gc-hslot-lang" in css


def test_desktop_command_header_is_one_outer_surface_not_detached_cards():
    css = (ROOT / "static" / "css" / "mando_exact_numbers.css").read_text(encoding="utf-8")
    assert "GC-HUD-SHELL-002" in css
    hardened = css.split("GC-HUD-SHELL-002", 1)[1]
    row_block = hardened.split(".gc-header-row-top {", 1)[1].split("}", 1)[0]
    assert "overflow: hidden !important" in row_block
    assert "background:" in row_block
    assert "border:" in row_block
    assert "border-radius: 0 !important" in row_block
    assert "background: transparent !important" in hardened
    assert "background-image: none !important" in hardened
    assert "border-inline-start: 0 !important" in hardened
    assert ".gc-score-pill > #hud-score-total" in css
    assert "display: none !important" in css
