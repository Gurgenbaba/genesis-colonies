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
