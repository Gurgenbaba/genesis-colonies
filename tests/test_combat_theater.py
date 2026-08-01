"""Combat Encounter Theater — cutout assets + path helpers (GC-CT)."""

from __future__ import annotations

from pathlib import Path

from game.defense_defs import ACTIVE_DEFENSE_KEYS, defense_battle_icon_path, defense_icon_static_path
from game.fleet_defs import SHIPS, ship_battle_icon_path, ship_icon_static_path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static" / "img"


def _static_fs_path(url_path: str) -> Path:
    assert url_path.startswith("/static/")
    return ROOT / "static" / url_path[len("/static/") :]


def test_ship_battle_icon_paths_use_cutout_dir():
    for key in sorted(SHIPS):
        battle = ship_battle_icon_path(key)
        normal = ship_icon_static_path(key)
        assert battle == f"/static/img/ships/cutout/{key}.png"
        assert normal == f"/static/img/ships/{key}.png"
        assert battle != normal


def test_defense_battle_icon_paths_use_cutout_dir():
    for key in sorted(ACTIVE_DEFENSE_KEYS):
        battle = defense_battle_icon_path(key)
        normal = defense_icon_static_path(key)
        assert battle == f"/static/img/defense/cutout/{key}.png"
        assert normal == f"/static/img/defense/{key}.png"
        assert battle != normal


def test_ship_cutout_assets_exist():
    for key in sorted(SHIPS):
        png = STATIC / "ships" / "cutout" / f"{key}.png"
        webp = STATIC / "ships" / "cutout" / f"{key}.webp"
        assert png.is_file(), f"missing {png}"
        assert webp.is_file(), f"missing {webp}"
        # RGBA cutout — corner should be transparent-ish
        from PIL import Image

        im = Image.open(png)
        assert im.mode == "RGBA"
        assert im.getpixel((0, 0))[3] < 40


def test_defense_cutout_assets_exist():
    for key in sorted(ACTIVE_DEFENSE_KEYS):
        png = STATIC / "defense" / "cutout" / f"{key}.png"
        webp = STATIC / "defense" / "cutout" / f"{key}.webp"
        assert png.is_file(), f"missing {png}"
        assert webp.is_file(), f"missing {webp}"
        from PIL import Image

        im = Image.open(png)
        assert im.mode == "RGBA"


def test_combat_theater_js_and_css_markers():
    js = (ROOT / "static" / "js" / "combat_theater.js").read_text(encoding="utf-8")
    assert "GC.combatTheater" in js
    assert "buildTimeline" in js
    assert "salvo" in js
    assert "projectileSignature" in js
    assert "gc-ct-bolt--" in js
    assert "flak_array" in js
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    assert ".gc-combat-theater" in css
    assert ".gc-ct-projectile" in css
    assert "gc-ct-bolt--falcon_interceptor" in css
    assert "gc-ct-bolt--flak_array" in css
    assert "gc-ct-bolt--planet_breaker" in css
    assert ".gc-ct-nebula" in css
    assert ".gc-ct-rift" in css
    assert "is-flagship" in css
    assert "gc-ct-backdrop" in js
    assert "fmtCompact" in js
    assert "is-flagship" in js
    assert "is-firing" in js
    base = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    assert "js/combat_theater.js" in base
    messages = (ROOT / "static" / "js" / "messages.js").read_text(encoding="utf-8")
    assert "data-ct-wrap" in messages
    assert "combatTheater.mountAndPlay" in messages
    assert "expedition_pirate" in messages


def test_projectile_signatures_cover_all_units():
    from game.combat_theater import (
        DEFENSE_SIGNATURES,
        SHIP_SIGNATURES,
        bolt_burst_range,
        projectile_signature,
    )
    from game.defense_defs import ACTIVE_DEFENSE_KEYS
    from game.fleet_defs import SHIPS

    for key in SHIPS:
        sig = projectile_signature(key, "ship")
        assert sig == SHIP_SIGNATURES[key]
        lo, hi = bolt_burst_range(key)
        assert 1 <= lo <= hi <= 8
    for key in ACTIVE_DEFENSE_KEYS:
        sig = projectile_signature(key, "defense")
        assert sig == DEFENSE_SIGNATURES[key]
    assert projectile_signature("unknown_hull", "ship") == "laser_mid"
    assert len({projectile_signature(k, "ship") for k in SHIPS}) == len(SHIPS)
    assert len({projectile_signature(k, "defense") for k in ACTIVE_DEFENSE_KEYS}) == len(
        ACTIVE_DEFENSE_KEYS
    )

def test_locale_theater_keys_present():
    import json

    required = [
        "combat_theater_attacker",
        "combat_theater_defender",
        "combat_theater_empty_side",
        "combat_theater_engaging",
        "combat_theater_heavy",
        "combat_theater_open_report",
        "combat_theater_replay",
        "combat_theater_round",
        "combat_theater_skip",
        "combat_report_kind_expedition_pirate",
        "combat_report_expedition_pirate_name",
    ]
    for loc in ("de", "en", "es", "fr", "pl", "pt", "ru", "tr"):
        data = json.loads((ROOT / "locales" / f"{loc}.json").read_text(encoding="utf-8"))
        for key in required:
            assert key in data, f"{loc} missing {key}"


def test_theater_timeline_has_multi_salvos_per_side():
    from game.combat_theater import build_theater_timeline, profile_for_defense, profile_for_ship

    meta = {
        "fleet_id": 42,
        "winner": "attacker",
        "rounds": [
            {
                "number": 1,
                "attacker_losses": {"falcon_interceptor": 2},
                "defender_losses": {"spark_drone": 5, "flak_array": 1},
            },
            {
                "number": 2,
                "attacker_losses": {"falcon_interceptor": 50},
                "defender_losses": {"ironclad_frigate": 20},
            },
        ],
    }
    events = build_theater_timeline(meta)
    types = [e["type"] for e in events]
    assert types[0] == "intro"
    assert types[-1] == "finale"
    atk_salvos = [e for e in events if e["type"] == "salvo" and e["side"] == "attacker"]
    def_salvos = [e for e in events if e["type"] == "salvo" and e["side"] == "defender"]
    assert len(atk_salvos) >= 4  # at least 2+2 across rounds
    assert len(def_salvos) >= 4
    # round 2 has spike losses → 3 salvos each
    r2_atk = [e for e in atk_salvos if e["round"] == 2]
    assert len(r2_atk) == 3
    assert profile_for_ship("planet_breaker") == "plasma_heavy"
    assert profile_for_defense("flak_array") == "flak"
    assert profile_for_defense("orbital_shield") == "missile"


def test_theater_js_requires_click_for_report():
    js = (ROOT / "static" / "js" / "combat_theater.js").read_text(encoding="utf-8")
    assert "Stay on theater until the player opens the report" in js
    assert 'later(() => finish("reveal"), 900)' not in js
    assert "salvoGap: 820" in js
    assert "sideSwitch: 420" in js


def test_theater_round_duration_is_deliberate():
    from game.combat_theater import BEAT, build_theater_timeline

    meta = {
        "fleet_id": 7,
        "rounds": [
            {"number": 1, "attacker_losses": {"falcon_interceptor": 1}, "defender_losses": {"spark_drone": 2}},
        ],
    }
    events = build_theater_timeline(meta)
    finale = events[-1]
    # One round with 2–3 salvos each side should land well above the old ~3s flash.
    min_expected = (
        BEAT["intro"]
        + BEAT["round_announce"]
        + 2 * BEAT["salvo_gap"]  # atk min
        + BEAT["side_switch"]
        + 2 * BEAT["salvo_gap"]  # def min
        + BEAT["resolve_hold"]
        + BEAT["round_gap"]
    )
    assert finale["at"] >= min_expected
    assert finale["at"] >= 5000
