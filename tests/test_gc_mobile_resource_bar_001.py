from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_mobile_resource_bar_uses_true_two_by_two_grid_without_shell_scroll():
    css = _read("static/css/empire_resource_relay.css")
    block = css.split("GC-MOBILE-RESBAR-001", 1)[1]

    assert "@media (max-width: 760px)" in block
    assert "grid-template-columns: repeat(2, minmax(0, 1fr)) !important;" in block
    assert "overflow-x: hidden !important;" in block
    assert "grid-auto-flow: row !important;" in block

    for selector in (
        ".resource-bar-cmd .hud-res-metal",
        ".resource-bar-cmd .hud-res-crystal",
        ".resource-bar-cmd .hud-res-fuel-cells",
        ".resource-bar-cmd .hud-res-energy",
    ):
        assert selector in block

    assert "min-inline-size: 0 !important;" in block
    assert "min-width: 0 !important;" in block


def test_mobile_resource_values_stay_exact_without_ellipsis_or_scientific_notation():
    css = _read("static/css/empire_resource_relay.css")
    block = css.split("GC-MOBILE-RESBAR-001", 1)[1]
    value_block = block.split(".resource-bar-cmd .res-value {", 1)[1].split("}", 1)[0]

    assert "white-space: nowrap !important;" in value_block
    assert "text-overflow: clip !important;" in value_block
    assert "overflow-x: auto !important;" in value_block
    assert "ellipsis" not in value_block


def test_mobile_hotfix_overrides_legacy_mando_rule_by_load_order():
    base = _read("templates/base.html")
    mando = _read("static/css/mando_exact_numbers.css")
    hotfix = _read("static/css/empire_resource_relay.css")

    # The legacy mobile rule is the regression source; the last-loaded shell CSS must win.
    assert "repeat(3, minmax(16rem, 1fr)) minmax(10rem, 0.62fr)" in mando
    assert base.index("css/mando_exact_numbers.css") < base.index("css/empire_resource_relay.css")
    assert "repeat(2, minmax(0, 1fr)) !important" in hotfix
    assert "GC-MOBILE-RESBAR-001" in hotfix
