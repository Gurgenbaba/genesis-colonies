"""Story TTS narration shaping — plain edge-tts, no SSML mangling."""

from __future__ import annotations

from game.story.tts import prepare_contact_script, resolve_voice


def test_prepare_keeps_paragraph_pauses():
    text = "Erste Zeile des Signals.\n\nZweite Passage nach dem Bruch."
    out = prepare_contact_script(text, locale="de")
    assert "…" in out or "..." in out
    assert "Erste Zeile" in out
    assert "Zweite Passage" in out
    assert "\n" not in out


def test_prepare_lattice_pronunciation_de():
    out = prepare_contact_script("Die Lattice atmet. Genesis Ark wartet.", locale="de")
    assert "Lättis" in out
    assert "Genesis-Ark" in out


def test_prepare_dash_becomes_comma_pause():
    out = prepare_contact_script("Kein Slot — sie ist der Sitz.", locale="de")
    assert "—" not in out
    assert "Slot" in out
    assert "Sitz" in out


def test_resolve_voice_de_is_killian():
    assert resolve_voice("de") == "de-DE-KillianNeural"
    assert resolve_voice("en") == "en-US-ChristopherNeural"


def test_no_ssml_in_prepared_script():
    out = prepare_contact_script("Eins.\n\nZwei.", locale="de")
    assert "<speak" not in out
    assert "<break" not in out


def test_prepare_gsp_coords_not_read_as_smileys():
    """Edge TTS treats :P / :S: as emoticons — expand to spoken position labels."""
    out = prepare_contact_script(
        "Raum ist adressierbar: Galaxie, System, Position — [G:S:P].",
        locale="de",
    )
    assert "[G:S:P]" not in out
    assert "G:S:P" not in out
    assert ":P" not in out
    assert "Galaxie System Position" in out

    out_num = prepare_contact_script("Treffpunkt [1:42:8].", locale="de")
    assert "[1:42:8]" not in out_num
    assert "1 zu 42 zu 8" in out_num

    out_en = prepare_contact_script("Format [G:S:P]", locale="en")
    assert "galaxy system position" in out_en


def test_prepare_numeric_range_not_comma_split():
    out = prepare_contact_script("Positionen 1–15 tragen Welten.", locale="de")
    assert "1 bis 15" in out
    assert "1, 15" not in out
