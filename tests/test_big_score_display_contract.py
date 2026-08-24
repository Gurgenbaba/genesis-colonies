from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MAIN_JS = ROOT / "static" / "main.js"


def test_huge_score_display_keeps_named_suffixes_before_scientific_notation():
    src = MAIN_JS.read_text(encoding="utf-8")
    assert 'if (abs >= 10n ** 33n)' in src
    assert '[10n ** 30n, "Q"]' in src
    assert '[10n ** 27n, "R"]' in src
    assert '[10n ** 24n, "Y"]' in src
    assert '[10n ** 21n, "Z"]' in src
    assert '[10n ** 18n, "E"]' in src
    assert '[10n ** 15n, "P"]' in src
    assert 'if (abs >= 1_000_000_000_000_000n)' not in src
