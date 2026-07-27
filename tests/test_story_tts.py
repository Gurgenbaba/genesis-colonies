"""Story TTS narration shaping — no Otto-monotone flattening."""

from __future__ import annotations

from game.story.tts import prepare_contact_script, resolve_voice


def test_prepare_keeps_paragraph_pauses():
    text = "Erste Zeile des Signals.\n\nZweite Passage nach dem Bruch."
    out = prepare_contact_script(text, locale="de")
    assert "…" in out or "..." in out
    assert "Erste Zeile" in out
    assert "Zweite Passage" in out
    assert "\n" not in out  # paragraphs become spoken pauses, not raw newlines


def test_prepare_lattice_pronunciation_de():
    out = prepare_contact_script("Die Lattice atmet.", locale="de")
    assert "Lättis" in out


def test_resolve_voice_de_is_killian():
    assert resolve_voice("de") == "de-DE-KillianNeural"
    assert resolve_voice("en") == "en-US-ChristopherNeural"
