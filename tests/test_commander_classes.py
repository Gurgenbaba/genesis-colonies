"""
EPIC-27 — Commander Classes & Skill Trees.

Run: python -m pytest tests/test_commander_classes.py -v
"""

from __future__ import annotations

import uuid

import pytest

from game.commander_class_catalog import (
    CLASS_KEYS,
    SKILLS,
    class_preview_mods,
    skills_for_class,
    swap_cost_sec,
)
from game.commander_classes import (
    claim_skill_points,
    get_commander_effect_modifiers,
    pick_class,
    schema_ready,
    serialize_for_client,
    swap_class,
    unlock_skill,
)
from game.db import begin_write_transaction, commit, db
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.timekeeper import credit, get_balance


@pytest.fixture
def commander_db(tmp_path, monkeypatch):
    db_path = tmp_path / "commander.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    import game.db as gdb

    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player(conn=None):
    own = conn is None
    if own:
        conn = db()
    ok, err, user = create_user(f"cc_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="ClassTester", conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid


def test_catalog_five_classes_linear_trunks():
    assert len(CLASS_KEYS) == 5
    for ck in CLASS_KEYS:
        trunk = skills_for_class(ck)
        assert len(trunk) >= 5
        assert trunk[0].get("prereq_skill") in (None, "")
        for i in range(1, len(trunk)):
            assert trunk[i]["prereq_skill"] == trunk[i - 1]["key"]
        assert any(s.get("is_capstone") for s in trunk)
        preview = class_preview_mods(ck)
        assert preview
    assert swap_cost_sec(0) == 24 * 3600
    assert swap_cost_sec(99) == swap_cost_sec(4)
    assert "vanguard_strike_doctrine" in SKILLS


def test_schema_ready(commander_db):
    conn = db()
    try:
        assert schema_ready(conn) is True
    finally:
        conn.close()


def test_pick_once_and_second_fails(commander_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        begin_write_transaction(conn)
        ok, reason, payload = pick_class(uid, "vanguard", conn=conn)
        assert ok and reason == "ok"
        assert payload["class_key"] == "vanguard"
        ok2, reason2, _ = pick_class(uid, "forge_lord", conn=conn)
        assert not ok2
        assert reason2 == "class_already_set"
        commit(conn)
    finally:
        conn.close()


def test_linear_gate_and_sp_unlock(commander_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        begin_write_transaction(conn)
        pick_class(uid, "vanguard", conn=conn)
        # Grant SP directly
        conn.execute(
            """
            UPDATE player_commander
            SET skill_points_unspent = 20, skill_points_earned = 20
            WHERE player_id = ?;
            """,
            (uid,),
        )
        ok_bad, reason_bad, _ = unlock_skill(uid, "vanguard_hull_focus", conn=conn)
        assert not ok_bad and reason_bad == "prereq_missing"
        ok1, _, p1 = unlock_skill(uid, "vanguard_strike_doctrine", conn=conn)
        assert ok1
        assert p1["ranks"].get("vanguard_strike_doctrine") == 1
        # max rank 3 — unlock twice more
        unlock_skill(uid, "vanguard_strike_doctrine", conn=conn)
        unlock_skill(uid, "vanguard_strike_doctrine", conn=conn)
        ok2, _, p2 = unlock_skill(uid, "vanguard_hull_focus", conn=conn)
        assert ok2
        assert p2["ranks"].get("vanguard_hull_focus") == 1
        mods = get_commander_effect_modifiers(uid, conn=conn)
        assert float(mods.get("weapon_bonus") or 0) > 0
        assert float(mods.get("armor_bonus") or 0) > 0
        commit(conn)
    finally:
        conn.close()


def test_sp_milestone_idempotent(commander_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        begin_write_transaction(conn)
        conn.execute(
            """
            INSERT INTO player_scores (player_id, score_total, score_buildings, score_research, updated_at)
            VALUES (?, 10000, 0, 0, 0)
            ON CONFLICT(player_id) DO UPDATE SET score_total = 10000;
            """,
            (uid,),
        )
        ok1, _, p1 = claim_skill_points(uid, conn=conn)
        assert ok1
        first = int(p1.get("claimed_points") or 0)
        assert first >= 3  # 1k + 5k + 10k
        ok2, _, p2 = claim_skill_points(uid, conn=conn)
        assert ok2
        assert int(p2.get("claimed_points") or 0) == 0
        row = serialize_for_client(uid, conn=conn)
        assert int(row["skill_points_unspent"]) == first
        commit(conn)
    finally:
        conn.close()


def test_capstone_resource_debit(commander_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        begin_write_transaction(conn)
        pick_class(uid, "vanguard", conn=conn)
        for sk in (
            "vanguard_strike_doctrine",
            "vanguard_hull_focus",
            "vanguard_barrier",
            "vanguard_assault_protocol",
        ):
            cfg = SKILLS[sk]
            conn.execute(
                """
                INSERT INTO player_commander_skills (player_id, skill_key, rank, unlocked_at)
                VALUES (?, ?, ?, 0);
                """,
                (uid, sk, int(cfg["max_rank"])),
            )
        planet = conn.execute(
            "SELECT id FROM planets WHERE player_id = ? LIMIT 1;",
            (uid,),
        ).fetchone()
        pid = int(planet["id"])
        # Too poor for capstone A
        conn.execute(
            "UPDATE planets SET metal = 1000, crystal = 1000, fuel_cells = 1000 WHERE id = ?;",
            (pid,),
        )
        ok_poor, reason_poor, _ = unlock_skill(
            uid, "vanguard_apex_raider", planet_id=pid, conn=conn
        )
        assert not ok_poor
        assert reason_poor == "insufficient_resources"
        # Fund capstone A
        conn.execute(
            "UPDATE planets SET metal = ?, crystal = ?, fuel_cells = ? WHERE id = ?;",
            (30_000_000, 15_000_000, 6_000_000, pid),
        )
        ok, reason, payload = unlock_skill(
            uid, "vanguard_apex_raider", planet_id=pid, conn=conn
        )
        assert ok, reason
        assert payload["ranks"].get("vanguard_apex_raider") == 1
        after = conn.execute(
            "SELECT metal, crystal, fuel_cells FROM planets WHERE id = ?;",
            (pid,),
        ).fetchone()
        assert float(after["metal"]) == pytest.approx(5_000_000)
        assert float(after["crystal"]) == pytest.approx(2_500_000)
        assert float(after["fuel_cells"]) == pytest.approx(1_000_000)
        # Ultimate still too expensive
        ok2, reason2, _ = unlock_skill(
            uid, "vanguard_war_sovereign", planet_id=pid, conn=conn
        )
        assert not ok2
        assert reason2 == "insufficient_resources"
        commit(conn)
    finally:
        conn.close()


def test_effect_resolver_includes_class_mods(commander_db):
    from game.effects import get_effect_resolver

    conn = db()
    try:
        uid = _player(conn=conn)
        begin_write_transaction(conn)
        pick_class(uid, "vanguard", conn=conn)
        conn.execute(
            """
            INSERT INTO player_commander_skills (player_id, skill_key, rank, unlocked_at)
            VALUES (?, 'vanguard_strike_doctrine', 3, 0);
            """,
            (uid,),
        )
        commit(conn)
        resolver = get_effect_resolver(uid, conn=conn, force_refresh=True)
        mods = resolver.get_combat_modifiers()
        assert float(mods.get("weapon_bonus") or 0) >= 0.06
    finally:
        conn.close()


def test_class_swap_refunds_sp_and_debits_tk(commander_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        begin_write_transaction(conn)
        pick_class(uid, "forge_lord", conn=conn)
        conn.execute(
            """
            UPDATE player_commander
            SET skill_points_unspent = 2, skill_points_earned = 5
            WHERE player_id = ?;
            """,
            (uid,),
        )
        conn.execute(
            """
            INSERT INTO player_commander_skills (player_id, skill_key, rank, unlocked_at)
            VALUES (?, 'forge_extraction', 2, 0);
            """,
            (uid,),
        )
        credit(uid, 24 * 3600, "test", conn=conn)
        ok, reason, payload = swap_class(uid, conn=conn)
        assert ok, reason
        assert payload["class_key"] is None
        assert int(payload["skill_points_unspent"]) == 5
        assert payload["ranks"] == {}
        assert get_balance(uid, conn=conn) == 0
        assert int(payload["swap_count"]) == 1
        # Re-pick allowed
        ok2, _, p2 = pick_class(uid, "envoy", conn=conn)
        assert ok2
        assert p2["class_key"] == "envoy"
        commit(conn)
    finally:
        conn.close()


def test_catalog_portraits_exist():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "static"
    from game.commander_class_catalog import CLASSES, ROLE_ICON_KEYS, role_icon_path

    for ck, meta in CLASSES.items():
        portrait = meta.get("portrait")
        assert portrait, ck
        assert str(portrait).endswith(".webp"), portrait
        assert (root / portrait).is_file(), f"missing {portrait}"
        assert meta.get("officer_key")
        assert meta.get("title_key")
        assert meta.get("epithet_key")
        assert meta.get("theme")
    for ik in ROLE_ICON_KEYS:
        path = role_icon_path(ik)
        assert path.endswith(".webp"), path
        assert (root / path).is_file(), ik
        assert (root / path).stat().st_size > 500, ik


def test_skilltree_cinematic_markup(commander_db):
    import importlib

    import app as app_mod

    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    importlib.reload(app_mod)
    client = app_mod.app.test_client()
    uid = _player()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    res = client.get("/skilltree")
    body = res.get_data(as_text=True)
    assert res.status_code == 200
    assert "data-cc-card" in body
    assert "data-cc-focus-root" in body
    assert "img/classes/Vanguard.webp" in body
    assert "img/classes/icons/" in body
    assert "cc-chip" in body
    assert "gc-placeholder-page" not in body


def _assert_skill_map_contract(body: str, *, expect_unlock: bool = True):
    assert "skilltree-map" in body
    assert "skilltree-map-node" in body
    assert "skilltree-map-edge" in body
    assert "skilltree-map-dock" in body
    assert "skilltree-path-node" not in body
    assert "skilltree-path-step" not in body
    assert "skilltree-path-edge" not in body
    assert "skilltree-trunk-list" not in body
    assert "skilltree-node-main" not in body
    for slot in range(1, 7):
        assert f"skilltree-map-node--slot-{slot}" in body
    assert body.count("data-skilltree-edge=") == 5
    assert "skilltree-map-node--capstone" in body
    assert 'data-skilltree-select="' in body
    if expect_unlock:
        assert 'data-skilltree-unlock="' in body
        assert "data-skilltree-dock-unlock" in body
    # Unlock only on dock — map nodes must not carry unlock attrs
    import re

    assert not re.search(
        r"skilltree-map-node[^>]*data-skilltree-unlock=",
        body,
    )
    assert "is-locked" in body or "is-maxed" in body or "is-available" in body


def test_skilltree_visual_path_after_pick(commander_db):
    import importlib
    import re

    import app as app_mod

    from game.bootstrap import bootstrap_application
    from game.commander_class_catalog import CLASS_KEYS
    from game.db import begin_write_transaction, commit, db

    bootstrap_application(skip_migration_check=True)
    importlib.reload(app_mod)

    for class_key in CLASS_KEYS:
        client = app_mod.app.test_client()
        uid = _player()
        with client.session_transaction() as sess:
            sess["user_id"] = uid
        pick = client.post(
            "/api/commander/class/pick",
            json={"class_key": class_key},
            headers={"Accept": "application/json"},
        )
        assert pick.status_code == 200, class_key
        assert pick.get_json()["ok"] is True, class_key

        # Fresh picks start at 0 SP → first node would be locked; grant SP so
        # available/unlock contract is visible (presentation-only test).
        conn = db()
        try:
            begin_write_transaction(conn)
            conn.execute(
                "UPDATE player_commander SET skill_points_unspent = 5 WHERE player_id = ?",
                (uid,),
            )
            commit(conn)
        finally:
            conn.close()

        res = client.get("/skilltree")
        body = res.get_data(as_text=True)
        assert res.status_code == 200, class_key
        _assert_skill_map_contract(body, expect_unlock=True)

        unlock_keys = [
            k
            for k in re.findall(r'data-skilltree-unlock="([^"]+)"', body)
            if k
        ]
        assert unlock_keys, class_key
        assert "skilltree-map-node--capstone" in body
        assert body.count('aria-current="step"') == 1, class_key
        assert "is-locked" in body


def test_skilltree_path_partial_rank_still_unlockable(commander_db):
    import importlib
    import re

    import app as app_mod

    from game.bootstrap import bootstrap_application
    from game.commander_classes import unlock_skill
    from game.db import begin_write_transaction, commit, db
    from game.ranking import invalidate_player_score_cache

    bootstrap_application(skip_migration_check=True)
    importlib.reload(app_mod)
    client = app_mod.app.test_client()
    uid = _player()

    conn = db()
    try:
        begin_write_transaction(conn)
        ok, reason, _ = pick_class(uid, "archivist", conn=conn)
        assert ok, reason
        from game.commander_classes import get_commander_row

        conn.execute(
            "UPDATE player_commander SET skill_points_unspent = 10 WHERE player_id = ?",
            (uid,),
        )
        ok_u, reason_u, _ = unlock_skill(uid, "archivist_codex", conn=conn)
        assert ok_u, reason_u
        commit(conn)
        invalidate_player_score_cache(uid)
        row = get_commander_row(uid, conn=conn)
        assert int(row.get("skill_points_unspent") or 0) >= 0
    finally:
        conn.close()

    with client.session_transaction() as sess:
        sess["user_id"] = uid
    res = client.get("/skilltree")
    body = res.get_data(as_text=True)
    assert res.status_code == 200
    _assert_skill_map_contract(body, expect_unlock=True)
    assert 'data-skilltree-unlock="archivist_codex"' in body
    assert "commander_rank_up" in body or "Rang erhöhen" in body or "Increase rank" in body
    # Edge after first maxed? first skill rank 1/3 still available → not maxed → next edge dim
    assert re.search(r"skilltree-map-edge is-dim", body)
    assert 'data-skill-key="archivist_codex"' in body
    assert 'data-skill-status="available"' in body


def test_api_commander_class_pick_keeps_session(commander_db):
    """POST pick must return JSON 200 with state — not an HTML login redirect."""
    import importlib

    import app as app_mod

    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    importlib.reload(app_mod)
    client = app_mod.app.test_client()
    uid = _player()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    # Wrong method must not look like a logged-in JSON success
    bad = client.get("/api/commander/class/pick")
    assert bad.status_code == 405

    res = client.post(
        "/api/commander/class/pick",
        json={"class_key": "vanguard"},
        headers={"Accept": "application/json"},
    )
    assert res.status_code == 200
    assert res.is_json
    payload = res.get_json()
    assert payload["ok"] is True
    assert payload["reason"] == "ok"
    assert (payload.get("commander") or {}).get("class_key") == "vanguard"
    assert isinstance(payload.get("state"), dict)

    # Unauthenticated API returns JSON 401, not HTML redirect
    client2 = app_mod.app.test_client()
    unauth = client2.post(
        "/api/commander/class/pick",
        json={"class_key": "envoy"},
        headers={"Accept": "application/json"},
    )
    assert unauth.status_code == 401
    assert unauth.is_json
    assert unauth.get_json().get("error") == "not_logged_in"


def test_skilltree_path_dead_css_selectors_gone():
    from pathlib import Path

    css = (Path(__file__).resolve().parent.parent / "static" / "style.css").read_text(
        encoding="utf-8"
    )
    assert ".skilltree-trunk-list" not in css
    assert ".skilltree-node-main" not in css
    assert ".skilltree-path-node" not in css
    assert "--skilltree-path-shift" not in css
    assert ".skilltree-map-node" in css
    assert "skilltree-map-node--slot-1" in css
    assert ".skilltree-map-dock" in css
    assert "min-width: 540px" in css


def test_role_icon_webps_and_skill_icon_keys(commander_db):
    from pathlib import Path

    from game.commander_class_catalog import (
        ROLE_ICON_KEYS,
        SKILLS,
        role_icon_path,
        skill_image_path,
    )

    root = Path(__file__).resolve().parent.parent / "static"
    icons_dir = root / "img" / "classes" / "icons"
    for ik in ROLE_ICON_KEYS:
        path = root / role_icon_path(ik)
        assert path.is_file(), ik
        assert path.suffix == ".webp"
        assert path.stat().st_size > 500
        assert not (icons_dir / f"{ik}.jpg").exists()
    assert len(SKILLS) == 30
    for sk, skill in SKILLS.items():
        ik = skill.get("icon_key")
        assert ik in ROLE_ICON_KEYS, sk
        art = root / skill_image_path(sk)
        assert art.is_file(), sk
        assert art.suffix == ".webp"
        assert art.stat().st_size > 500


def test_skilltree_path_art_in_markup(commander_db):
    import importlib

    import app as app_mod

    from game.bootstrap import bootstrap_application
    from game.db import begin_write_transaction, commit, db

    bootstrap_application(skip_migration_check=True)
    importlib.reload(app_mod)
    client = app_mod.app.test_client()
    uid = _player()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    assert client.post(
        "/api/commander/class/pick",
        json={"class_key": "archivist"},
        headers={"Accept": "application/json"},
    ).status_code == 200
    conn = db()
    try:
        begin_write_transaction(conn)
        conn.execute(
            "UPDATE player_commander SET skill_points_unspent = 5 WHERE player_id = ?",
            (uid,),
        )
        commit(conn)
    finally:
        conn.close()
    body = client.get("/skilltree").get_data(as_text=True)
    assert "skilltree-map-node__art" in body
    assert "img/classes/skills/archivist_codex.webp" in body
    assert "img/classes/skills/" in body
    assert "skilltree-map-dock" in body
    assert "data-skilltree-dock-unlock" in body


def test_void_admiral_fuel_and_cargo_apply(commander_db):
    """Fuel efficiency factor < 1 reduces cost; cargo_multiplier enlarges holds."""
    from game.commander_class_catalog import format_mod_chip, preview_chips_for_class
    from game.fleet import _fleet_galactic_modifiers
    from game.fleet_calc import calculate_fuel_cost, calculate_total_cargo

    uid = _player()
    conn = db()
    try:
        begin_write_transaction(conn)
        assert pick_class(uid, "void_admiral", conn=conn)[0]
        conn.execute(
            "UPDATE player_commander SET skill_points_unspent = 20 WHERE player_id = ?",
            (uid,),
        )
        for key in ("admiral_warp_lanes", "admiral_hold_capacity", "admiral_fuel_thrift"):
            skill = next(s for s in skills_for_class("void_admiral") if s["key"] == key)
            for _ in range(int(skill["max_rank"])):
                ok, reason, _ = unlock_skill(uid, key, planet_id=None, conn=conn)
                assert ok, (key, reason)
        mods = get_commander_effect_modifiers(uid, conn=conn)
        assert float(mods.get("cargo_multiplier", 1.0)) > 1.0
        assert float(mods.get("fuel_efficiency_factor", 1.0)) < 1.0
        fuel_chip = format_mod_chip("fuel_efficiency_factor", mods["fuel_efficiency_factor"])
        assert fuel_chip and fuel_chip["display"].startswith("+")
        chips = preview_chips_for_class("void_admiral", limit=4)
        assert any(c["key"] == "fleet_speed_multiplier" for c in chips)
        assert any(c["key"] == "cargo_multiplier" for c in chips)
        er_mods = _fleet_galactic_modifiers(uid, conn)
        base_cargo = calculate_total_cargo({"mule_courier": 10})
        boosted = calculate_total_cargo(
            {"mule_courier": 10}, cargo_multiplier=er_mods["cargo_multiplier"]
        )
        assert boosted > base_cargo
        base_fuel = calculate_fuel_cost({"mule_courier": 500}, distance=1000, speed_percent=100)
        cheap = calculate_fuel_cost(
            {"mule_courier": 500},
            distance=1000,
            speed_percent=100,
            fuel_efficiency_factor_override=er_mods["fuel_efficiency_factor"],
        )
        assert base_fuel > 10
        assert cheap < base_fuel
        ser = serialize_for_client(uid, conn=conn)
        hold = next(s for s in ser["skills"] if s["key"] == "admiral_hold_capacity")
        assert hold["effect_chips"]
        assert hold["effect_chips_per_rank"]
        commit(conn)
    finally:
        conn.close()


def test_envoy_scan_chip_marked_prepared(commander_db):
    from game.commander_class_catalog import preview_chips_for_class

    chips = preview_chips_for_class("envoy", limit=4)
    scan = next((c for c in chips if c["key"] == "scan_range"), None)
    assert scan is not None
    assert scan.get("prepared") is True
