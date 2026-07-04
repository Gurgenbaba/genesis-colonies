"""EPIC-09 Alliance Hub tests (GC-AL-001 … GC-AL-MVP-09)."""

from __future__ import annotations

import re
import time
import uuid
from pathlib import Path

import pytest

from game.alliance import (
    alliance_hub_schema_ready,
    apply_to_alliance,
    are_players_allied,
    create_alliance,
    demote_member,
    disband_alliance,
    donate_to_alliance,
    donation_limits_for_pool,
    finish_due_alliance_projects,
    get_alliance_effect_modifiers,
    get_alliance_expedition_loot_multiplier,
    get_alliance_members,
    get_alliance_public_profile,
    get_alliance_state,
    get_player_alliance,
    join_alliance_by_tag,
    kick_member,
    leave_alliance,
    promote_member,
    respond_application,
    send_alliance_broadcast,
    send_diplomacy_request,
    set_member_role,
    start_alliance_project,
    transfer_leadership,
    update_alliance_description,
    update_alliance_profile,
    update_recruitment_mode,
    withdraw_application,
)
from game.alliance_catalog import BASE_MEMBER_LIMIT, DONATION_XP_DAILY_CAP, member_limit_from_buildings, project_effect_preview
from game.db import db
from game.effects import get_effect_resolver
from game.models import create_user, ensure_player_and_homeworld, init_db
from game.planet_evolution.repository import get_context_planet


@pytest.fixture
def alliance_db(tmp_path, monkeypatch):
    db_path = tmp_path / "alliance_test.db"
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


def _player(conn=None, *, name: str | None = None):
    own = conn is None
    if own:
        conn = db()
    ok, err, user = create_user(f"ally_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name=name or f"P{uid}", conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid


def _fund_planet(uid: int, conn, *, metal=500_000, crystal=500_000, fuel=100_000) -> int:
    planet = get_context_planet(player_id=uid, conn=conn)
    pid = int(planet["id"])
    conn.execute(
        "UPDATE planets SET metal = ?, crystal = ?, fuel_cells = ? WHERE id = ?;",
        (float(metal), float(crystal), float(fuel), pid),
    )
    return pid


ALLIANCE_INTERNAL_KEYS = (
    "research_archive",
    "alliance_headquarters",
    "expedition_office",
    "logistics_depot",
    "diplomacy_center",
    "research_network",
    "expedition_coordination",
    "industrial_logistics",
    "defensive_protocols",
    "trade_coordination",
)


def _alliance_member_hub_html(alliance_db, uid=None):
    if uid is None:
        uid = _player()
        conn = db()
        try:
            create_alliance("HUB", "Hub UI", uid, conn=conn)
            conn.commit()
        finally:
            conn.close()
    client = _app_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    resp = client.get("/alliance", headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


def _alliance_visible_text(html: str) -> str:
    cleaned = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S | re.I)
    cleaned = re.sub(r"\sdata-[a-z0-9_-]+=\"[^\"]*\"", "", cleaned, flags=re.I)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    return cleaned


def test_schema_ready(alliance_db):
    conn = db()
    try:
        assert alliance_hub_schema_ready(conn)
    finally:
        conn.close()


def test_create_join_leave(alliance_db):
    founder = _player(name="Founder")
    member = _player(name="Member")
    conn = db()
    try:
        create_alliance("TST", "Test Alliance", founder, description="Hello", conn=conn)
        conn.commit()

        ally = get_player_alliance(founder, conn=conn)
        assert ally is not None
        assert ally["role"] == "leader"
        assert ally["tag"] == "TST"

        join_alliance_by_tag(member, "TST", conn=conn)
        conn.commit()
        assert get_player_alliance(member, conn=conn) is not None

        leave_alliance(member, conn=conn)
        conn.commit()
        assert get_player_alliance(member, conn=conn) is None
    finally:
        conn.close()


def test_officer_can_update_description(alliance_db):
    conn = db()
    try:
        founder = _player(conn=conn)
        create_alliance("OFF", "Officers", founder, conn=conn)
        conn.commit()
        update_alliance_description(founder, "Updated lore", conn=conn)
        conn.commit()
        state = get_alliance_state(founder, conn=conn)
        assert state["description"] == "Updated lore"
    finally:
        conn.close()


def test_member_limit_from_hq(alliance_db):
    assert member_limit_from_buildings({}) == BASE_MEMBER_LIMIT
    assert member_limit_from_buildings({"alliance_headquarters": 2}) == BASE_MEMBER_LIMIT + 4


def test_donation_and_pool_cap(alliance_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        create_alliance("DON", "Donors", uid, conn=conn)
        conn.commit()
        _fund_planet(uid, conn)

        donate_to_alliance(uid, "metal", 5_000, conn=conn)
        conn.commit()
        state = get_alliance_state(uid, conn=conn)
        assert state["pool"]["metal"] == 5_000

        cap = state["pool_cap"]["metal"]
        with pytest.raises(ValueError, match="pool_cap_exceeded"):
            donate_to_alliance(uid, "metal", cap + 1, conn=conn)
    finally:
        conn.close()


def test_donation_spends_context_planet(alliance_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        create_alliance("PLN", "Planet", uid, conn=conn)
        conn.commit()
        pid = _fund_planet(uid, conn, metal=50_000)
        before = conn.execute("SELECT metal FROM planets WHERE id = ?;", (pid,)).fetchone()["metal"]

        donate_to_alliance(uid, "metal", 1_000, conn=conn)
        conn.commit()
        after = conn.execute("SELECT metal FROM planets WHERE id = ?;", (pid,)).fetchone()["metal"]
        assert float(after) == float(before) - 1000
    finally:
        conn.close()


def test_project_start_and_finish(alliance_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        create_alliance("PRJ", "Projects", uid, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(uid, conn=conn)["alliance_id"])
        _fund_planet(uid, conn)
        conn.execute(
            "UPDATE alliances SET pool_metal = 500000, pool_crystal = 500000, pool_fuel_cells = 200000 WHERE id = ?;",
            (aid,),
        )
        conn.commit()

        start_alliance_project(uid, "building", "alliance_headquarters", conn=conn)
        conn.commit()
        state = get_alliance_state(uid, conn=conn)
        assert state["active_project"] is not None
        ap = state["active_project"]
        assert int(ap["started_at"]) > 0
        assert int(ap["finish_at"]) > int(ap["started_at"])
        assert int(ap["duration_seconds"]) == int(ap["finish_at"]) - int(ap["started_at"])
        assert 0 <= float(ap["progress_pct"]) <= 100

        proj_id = int(ap["id"])
        conn.execute(
            "UPDATE alliance_projects SET finish_at = ? WHERE id = ?;",
            (int(time.time()) - 1, proj_id),
        )
        conn.commit()
        finish_due_alliance_projects(conn=conn, alliance_id=aid)
        conn.commit()

        state = get_alliance_state(uid, conn=conn)
        assert state["buildings"].get("alliance_headquarters") == 1
        assert state["member_limit"] == BASE_MEMBER_LIMIT + 2
    finally:
        conn.close()


def test_project_requires_pool(alliance_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        create_alliance("POO", "Poor", uid, conn=conn)
        conn.commit()
        with pytest.raises(ValueError, match="insufficient_pool"):
            start_alliance_project(uid, "building", "alliance_headquarters", conn=conn)
    finally:
        conn.close()


def test_effect_resolver_alliance_bonuses(alliance_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        create_alliance("FX", "Effects", uid, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(uid, conn=conn)["alliance_id"])
        conn.execute(
            """
            INSERT INTO alliance_technologies (alliance_id, tech_key, level)
            VALUES (?, 'research_network', 4);
            """,
            (aid,),
        )
        conn.commit()

        mods_member = get_alliance_effect_modifiers(uid, conn=conn)
        assert mods_member["research_time_speed"] > 1.0

        outsider = _player(conn=conn)
        conn.commit()
        mods_out = get_alliance_effect_modifiers(outsider, conn=conn)
        assert mods_out["research_time_speed"] == 1.0

        planet = get_context_planet(player_id=uid, conn=conn)
        resolver = get_effect_resolver(uid, conn=conn, planet=planet)
        rmods = resolver.get_modifiers()
        assert rmods["research_time_speed"] > 1.0
    finally:
        conn.close()


def _set_recruitment_mode(conn, alliance_id: int, mode: str) -> None:
    conn.execute(
        "UPDATE alliances SET recruitment_mode = ? WHERE id = ?;",
        (mode, int(alliance_id)),
    )


def test_application_flow(alliance_db):
    leader = _player()
    applicant = _player()
    conn = db()
    try:
        create_alliance("APP", "Apply", leader, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(leader, conn=conn)["alliance_id"])

        apply_to_alliance(applicant, aid, message="Hi", conn=conn)
        conn.commit()
        state = get_alliance_state(leader, conn=conn)
        assert len(state["applications"]) == 1
        app_id = int(state["applications"][0]["id"])

        respond_application(leader, app_id, accept=True, conn=conn)
        conn.commit()
        assert get_player_alliance(applicant, conn=conn) is not None
    finally:
        conn.close()


def test_application_requires_message(alliance_db):
    leader = _player()
    applicant = _player()
    conn = db()
    try:
        create_alliance("MSG", "MessageReq", leader, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(leader, conn=conn)["alliance_id"])
        with pytest.raises(ValueError, match="application_message_required"):
            apply_to_alliance(applicant, aid, message="", conn=conn)
    finally:
        conn.close()


def test_pending_application_guest_state(alliance_db):
    leader = _player()
    applicant = _player()
    conn = db()
    try:
        create_alliance("PND", "Pending", leader, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(leader, conn=conn)["alliance_id"])
        apply_to_alliance(applicant, aid, message="Please let me in", conn=conn)
        state = get_alliance_state(applicant, conn=conn)
        assert state["has_pending_application"] is True
        assert state["pending_application"]["tag"] == "PND"
        assert state["pending_application"]["message"] == "Please let me in"
        assert state["in_alliance"] is False
    finally:
        conn.close()


def test_withdraw_application(alliance_db):
    leader = _player()
    applicant = _player()
    conn = db()
    try:
        create_alliance("WDR", "Withdraw", leader, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(leader, conn=conn)["alliance_id"])
        apply_to_alliance(applicant, aid, message="Hi", conn=conn)
        assert get_alliance_state(applicant, conn=conn)["has_pending_application"] is True
        withdraw_application(applicant, conn=conn)
        state = get_alliance_state(applicant, conn=conn)
        assert state.get("has_pending_application") is not True
        assert state.get("pending_application") is None
    finally:
        conn.close()


def test_recruitment_application_only_blocks_direct_join(alliance_db):
    leader = _player()
    joiner = _player()
    conn = db()
    try:
        create_alliance("APPONLY", "App Only", leader, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(leader, conn=conn)["alliance_id"])
        _set_recruitment_mode(conn, aid, "application_only")
        conn.commit()
        with pytest.raises(ValueError, match="recruitment_application_only"):
            join_alliance_by_tag(joiner, "APPONLY", conn=conn)
        apply_to_alliance(joiner, aid, message="Application please", conn=conn)
        assert get_alliance_state(leader, conn=conn)["applications"]
    finally:
        conn.close()


def test_recruitment_closed_blocks_join_and_apply(alliance_db):
    leader = _player()
    outsider = _player()
    conn = db()
    try:
        create_alliance("CLSD", "Closed", leader, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(leader, conn=conn)["alliance_id"])
        _set_recruitment_mode(conn, aid, "closed")
        conn.commit()
        with pytest.raises(ValueError, match="recruitment_closed"):
            join_alliance_by_tag(outsider, "CLSD", conn=conn)
        with pytest.raises(ValueError, match="recruitment_closed"):
            apply_to_alliance(outsider, aid, message="Let me in", conn=conn)
    finally:
        conn.close()


def test_decline_application(alliance_db):
    leader = _player()
    applicant = _player()
    conn = db()
    try:
        create_alliance("DCL", "Decline", leader, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(leader, conn=conn)["alliance_id"])
        apply_to_alliance(applicant, aid, message="Hi", conn=conn)
        app_id = int(get_alliance_state(leader, conn=conn)["applications"][0]["id"])
        respond_application(leader, app_id, accept=False, conn=conn)
        assert get_player_alliance(applicant, conn=conn) is None
        assert get_alliance_state(leader, conn=conn)["applications"] == []
    finally:
        conn.close()


def test_apply_api_returns_alliance_state(alliance_db):
    leader = _player()
    applicant = _player()
    conn = db()
    try:
        create_alliance("API", "ApiApply", leader, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(leader, conn=conn)["alliance_id"])
    finally:
        conn.close()

    client = _app_client()
    with client.session_transaction() as sess:
        sess["user_id"] = applicant
    resp = client.post(
        "/api/alliance/apply",
        json={"alliance_id": aid, "message": "Hello officers"},
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert "state" in data
    assert data["alliance"]["has_pending_application"] is True


def test_withdraw_api(alliance_db):
    leader = _player()
    applicant = _player()
    conn = db()
    try:
        create_alliance("WAPI", "WithdrawApi", leader, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(leader, conn=conn)["alliance_id"])
        apply_to_alliance(applicant, aid, message="Hi", conn=conn)
    finally:
        conn.close()

    client = _app_client()
    with client.session_transaction() as sess:
        sess["user_id"] = applicant
    resp = client.post(
        "/api/alliance/application/withdraw",
        json={},
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["alliance"].get("has_pending_application") is not True


def _app_client():
    import importlib
    import app as app_mod

    importlib.reload(app_mod)
    app_mod.app.config["TESTING"] = True
    return app_mod.app.test_client()


def test_alliance_page_route(alliance_db):
    uid = _player()
    client = _app_client()

    with client.session_transaction() as sess:
        sess["user_id"] = uid

    resp = client.get("/alliance", headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "alliance-hub-page" in body


def test_donation_commits_when_external_conn(alliance_db):
    """Regression: API path passes conn — donate must commit spend + pool without caller commit."""
    conn = db()
    try:
        uid = _player(conn=conn)
        create_alliance("DON", "Donate API", uid, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(uid, conn=conn)["alliance_id"])
        pid = _fund_planet(uid, conn, metal=50_000)
        before = float(conn.execute("SELECT metal FROM planets WHERE id = ?;", (pid,)).fetchone()["metal"])

        donate_to_alliance(uid, "metal", 1500, conn=conn)

        pool = float(
            conn.execute("SELECT pool_metal FROM alliances WHERE id = ?;", (aid,)).fetchone()["pool_metal"]
        )
        after = float(conn.execute("SELECT metal FROM planets WHERE id = ?;", (pid,)).fetchone()["metal"])
        assert pool == 1500.0
        assert after == before - 1500.0
    finally:
        conn.close()


def test_alliance_logo_upload_officer(alliance_db):
    from io import BytesIO

    from PIL import Image

    conn = db()
    try:
        uid = _player(conn=conn)
        create_alliance("LOG", "Logo", uid, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(uid, conn=conn)["alliance_id"])
    finally:
        conn.close()

    buf = BytesIO()
    Image.new("RGB", (128, 128), color=(40, 80, 120)).save(buf, format="PNG")
    buf.seek(0)

    client = _app_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    resp = client.post(
        "/api/alliance/logo",
        data={"logo": (buf, "logo.png")},
        content_type="multipart/form-data",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["alliance"]["show_logo"] is True
    assert f"/api/alliance-logo/{aid}" in (data["alliance"].get("logo_url_client") or "")

    logo_resp = client.get(f"/api/alliance-logo/{aid}")
    assert logo_resp.status_code == 200
    assert logo_resp.mimetype in ("image/webp", "image/png", "image/jpeg")


def test_alliance_page_no_wip_banner(alliance_db):
    uid = _player()
    client = _app_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    resp = client.get("/alliance", headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'class="gc-wip-banner"' not in body
    assert "gc-wip-banner-icon" not in body


def test_alliance_member_hub_module(alliance_db):
    body = _alliance_member_hub_html(alliance_db)
    assert "alliance-hub-module" in body
    assert "alliance-hub-hero" in body
    assert "alliance-hub-hero-top" in body
    assert "alliance-hub-logo-frame--hero" in body
    assert "alliance-hub-stats" in body
    assert "alliance-hub-xp-card" in body
    assert "alliance-hub-hero-desc" in body
    assert "data-alliance-manage-modal" in body
    assert 'id="alliance-manage-modal" hidden' not in body
    assert "data-alliance-manage-open" in body
    assert "data-alliance-logo-upload" in body
    assert "data-alliance-profile-form" in body
    assert 'data-alliance-submit="profile"' in body
    assert "alliance-hub-project-effect-grid" in body
    assert "alliance-hub-member-table--roster" in body
    assert "alliance-hub-member-grid--roster" not in body
    assert "alliance-hub-hero-logo-row" in body
    assert '<ul class="alliance-hub-project-grid"' not in body
    assert "alliance-hub-project-card" in body
    assert "<article class=\"alliance-hub-project-card" in body or "alliance-hub-project-card alliance-hub-project-card--locked" in body
    assert "data-alliance-chat-open" in body
    assert "data-alliance-broadcast-open" in body
    assert "alliance-broadcast-modal" in body
    assert "alliance-hub-project-card--locked" in body
    assert "alliance-hub-unlock-card--diplomacy" in body
    assert "alliance-hub-project-affects" in body
    assert "gc-prog-info" in body
    assert "alliance-hub-pool-tile" in body
    assert "data-pool-val=\"metal\"" in body
    assert "alliance-hub-tab" in body
    assert "data-alliance-disband" in body
    assert "data-alliance-leave" in body
    assert "alliance-hub-management" not in body
    assert "gc-btn-danger" in body
    assert body.count("alliance-hub-hero-actions") == 1
    assert "alliance-hub-hero-actions--chat" not in body


def test_alliance_active_project_renders_localized_label(alliance_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        create_alliance("PRJ", "Project UI", uid, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(uid, conn=conn)["alliance_id"])
        _fund_planet(uid, conn)
        conn.execute(
            "UPDATE alliances SET pool_metal = 500000, pool_crystal = 500000, pool_fuel_cells = 200000 WHERE id = ?;",
            (aid,),
        )
        conn.commit()
        start_alliance_project(uid, "building", "alliance_headquarters", conn=conn)
        conn.commit()
    finally:
        conn.close()

    client = _app_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    resp = client.get("/alliance", headers={"X-Requested-With": "XMLHttpRequest"})
    body = resp.get_data(as_text=True)
    assert "data-alliance-active-project" in body
    assert "data-project-eta" in body

    sub_match = re.search(
        r'data-alliance-active-project[\s\S]*?alliance-hub-section-sub">([^<]+)',
        body,
    )
    assert sub_match, "active project subtitle missing"
    subtitle = sub_match.group(1)
    assert "alliance_headquarters" not in subtitle
    assert "Headquarters" in subtitle or "Hauptquartier" in subtitle
    assert "→ L1" in subtitle


def test_alliance_member_roster_includes_contribution_fields(alliance_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        create_alliance("ROST", "Roster", uid, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(uid, conn=conn)["alliance_id"])
        _fund_planet(uid, conn)
        donate_to_alliance(uid, "metal", 5000, conn=conn)
        conn.commit()
        members = get_alliance_members(aid, conn=conn)
    finally:
        conn.close()
    assert len(members) == 1
    row = members[0]
    assert row["donation_points"] >= 5000
    assert row["xp_contribution"] >= 0
    assert "joined_label" in row
    assert "last_seen_label" in row


def test_project_effect_preview_headquarters_members(alliance_db):
    from game.alliance_catalog import project_effect_preview

    fx = project_effect_preview(
        "building",
        "alliance_headquarters",
        current_level=0,
        target_level=1,
        buildings={"alliance_headquarters": 0},
    )
    assert fx["current_value"] == 5
    assert fx["next_value"] == 7


def test_available_projects_include_effect_preview(alliance_db):
    uid = _player()
    conn = db()
    try:
        create_alliance("FX", "Effects", uid, conn=conn)
        conn.commit()
        state = get_alliance_state(uid, conn=conn)
    finally:
        conn.close()
    projects = [p for p in state["available_projects"] if p["key"] == "alliance_headquarters"]
    assert projects
    assert "effect" in projects[0]
    assert projects[0]["effect"]["next_value"] == 7


def test_alliance_create_api_pjax(alliance_db):
    uid = _player()
    client = _app_client()

    with client.session_transaction() as sess:
        sess["user_id"] = uid

    resp = client.post(
        "/api/alliance/create",
        json={"tag": "API", "name": "Api Alliance", "description": "x"},
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert "state" in data
    assert data["alliance"]["in_alliance"] is True
    assert data["alliance"]["role"] == "leader"
    assert data["alliance"]["tag"] == "API"


def test_alliance_page_no_get_create_form(alliance_db):
    uid = _player()
    client = _app_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    resp = client.get("/alliance", headers={"X-PJAX": "true", "X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'data-alliance-create-form' in body
    assert 'method="get"' not in body.lower()
    assert 'data-alliance-submit="create"' in body
    assert 'type="button"' in body


def test_create_then_member_hub_pjax(alliance_db):
    uid = _player()
    client = _app_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    create = client.post(
        "/api/alliance/create",
        json={"tag": "HUB", "name": "Hub Alliance", "description": ""},
        headers={"Content-Type": "application/json"},
    )
    assert create.status_code == 200
    assert create.get_json()["alliance"]["in_alliance"] is True

    page = client.get("/alliance", headers={"X-PJAX": "true", "X-Requested-With": "XMLHttpRequest"})
    body = page.get_data(as_text=True)
    assert "data-alliance-member" in body
    assert "data-alliance-guest" not in body
    assert "[HUB]" in body or "HUB" in body


def test_join_already_in_alliance_returns_error_payload(alliance_db):
    founder = _player()
    client = _app_client()
    with client.session_transaction() as sess:
        sess["user_id"] = founder

    resp = client.post(
        "/api/alliance/create",
        json={"tag": "DUP", "name": "Dup", "description": ""},
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200

    join = client.post(
        "/api/alliance/join",
        json={"tag": "OTHER"},
        headers={"Content-Type": "application/json"},
    )
    assert join.status_code == 400
    data = join.get_json()
    assert data["ok"] is False
    assert data["error"] == "already_in_alliance"
    assert "state" in data
    assert data["alliance"]["in_alliance"] is True


def test_create_membership_visible_immediately(alliance_db):
    uid = _player()
    conn = db()
    try:
        create_alliance("IMM", "Immediate", uid, conn=conn)
        ally = get_player_alliance(uid, conn=conn)
        assert ally is not None
        assert ally["role"] == "leader"
        state = get_alliance_state(uid, conn=conn)
        assert state["in_alliance"] is True
        assert state["role"] == "leader"
    finally:
        conn.close()


def test_alliance_public_profile_members_and_points(alliance_db):
    leader = _player(name="Leader")
    member = _player(name="Member")
    guest = _player(name="Guest")
    conn = db()
    try:
        create_alliance("PUB", "Public Alliance", leader, description="Welcome", conn=conn)
        conn.commit()
        join_alliance_by_tag(member, "PUB", conn=conn)
        conn.commit()
        aid = int(get_player_alliance(leader, conn=conn)["alliance_id"])
        _fund_planet(leader, conn, metal=20_000)
        _fund_planet(member, conn, metal=10_000)
        donate_to_alliance(leader, "metal", 1200, conn=conn)
        donate_to_alliance(member, "metal", 800, conn=conn)
        conn.commit()

        profile = get_alliance_public_profile(aid, conn=conn)
        assert profile["tag"] == "PUB"
        assert profile["name"] == "Public Alliance"
        assert profile["description"] == "Welcome"
        assert profile["member_count"] == 2
        assert profile["allows_direct_join"] is True
        assert len(profile["members"]) == 2
        points = sorted(m["donation_points"] for m in profile["members"])
        assert points == [800, 1200]

        guest_state = get_alliance_state(guest, conn=conn)
        assert guest_state["in_alliance"] is False
        assert any(b["id"] == aid for b in guest_state["browse"])
    finally:
        conn.close()


def test_alliance_profile_api(alliance_db):
    leader = _player()
    guest = _player()
    conn = db()
    try:
        create_alliance("APIP", "Profile API", leader, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(leader, conn=conn)["alliance_id"])
    finally:
        conn.close()

    client = _app_client()
    with client.session_transaction() as sess:
        sess["user_id"] = guest
    resp = client.get(f"/api/alliance/profile/{aid}", headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["profile"]["id"] == aid
    assert data["profile"]["tag"] == "APIP"
    assert data["alliance"]["in_alliance"] is False
    assert len(data["profile"]["members"]) == 1


def test_alliance_guest_directory_markup(alliance_db):
    leader = _player()
    guest = _player()
    conn = db()
    try:
        create_alliance("DIR", "Directory", leader, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(leader, conn=conn)["alliance_id"])
    finally:
        conn.close()

    client = _app_client()
    with client.session_transaction() as sess:
        sess["user_id"] = guest
    resp = client.get("/alliance", headers={"X-Requested-With": "XMLHttpRequest"})
    body = resp.get_data(as_text=True)
    assert "alliance-hub-directory" in body
    assert "alliance-hub-browse-grid" in body
    assert f'data-alliance-browse-open="{aid}"' in body
    assert "data-alliance-detail" in body
    assert "data-alliance-apply-toggle" not in body


def test_leader_must_transfer(alliance_db):
    leader = _player(name="Leader")
    officer = _player(name="Officer")
    conn = db()
    try:
        create_alliance("LMT", "Transfer Test", leader, conn=conn)
        conn.commit()
        join_alliance_by_tag(officer, "LMT", conn=conn)
        conn.commit()
        with pytest.raises(ValueError, match="leader_must_transfer"):
            leave_alliance(leader, conn=conn)
    finally:
        conn.close()


def test_solo_leader_leave_disbands(alliance_db):
    leader = _player()
    conn = db()
    try:
        create_alliance("SOLO", "Solo", leader, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(leader, conn=conn)["alliance_id"])
        leave_alliance(leader, conn=conn)
        conn.commit()
        assert get_player_alliance(leader, conn=conn) is None
        row = conn.execute("SELECT id FROM alliances WHERE id = ?;", (aid,)).fetchone()
        assert row is None
    finally:
        conn.close()


def test_role_management_flow(alliance_db):
    leader = _player(name="Leader")
    officer = _player(name="Officer")
    member = _player(name="Member")
    conn = db()
    try:
        create_alliance("ROL", "Roles", leader, conn=conn)
        conn.commit()
        join_alliance_by_tag(officer, "ROL", conn=conn)
        join_alliance_by_tag(member, "ROL", conn=conn)
        conn.commit()
        promote_member(leader, officer, conn=conn)
        conn.commit()
        assert get_player_alliance(officer, conn=conn)["role"] == "officer"
        demote_member(leader, officer, conn=conn)
        conn.commit()
        assert get_player_alliance(officer, conn=conn)["role"] == "member"
        aid = int(get_player_alliance(leader, conn=conn)["alliance_id"])
        transfer_leadership(aid, leader, officer, conn=conn)
        conn.commit()
        assert get_player_alliance(officer, conn=conn)["role"] == "leader"
        assert get_player_alliance(leader, conn=conn)["role"] == "officer"
        kick_member(aid, officer, member, conn=conn)
        conn.commit()
        assert get_player_alliance(member, conn=conn) is None
    finally:
        conn.close()


def test_disband_alliance(alliance_db):
    leader = _player()
    member = _player()
    conn = db()
    try:
        create_alliance("DSB", "Disband", leader, conn=conn)
        conn.commit()
        join_alliance_by_tag(member, "DSB", conn=conn)
        conn.commit()
        aid = int(get_player_alliance(leader, conn=conn)["alliance_id"])
        disband_alliance(aid, leader, conn=conn)
        conn.commit()
        assert get_player_alliance(leader, conn=conn) is None
        assert get_player_alliance(member, conn=conn) is None
        assert conn.execute("SELECT id FROM alliances WHERE id = ?;", (aid,)).fetchone() is None
    finally:
        conn.close()


def test_recruitment_mode_api(alliance_db):
    leader = _player()
    member = _player()
    conn = db()
    try:
        create_alliance("REC", "Recruit", leader, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(leader, conn=conn)["alliance_id"])
        update_recruitment_mode(aid, leader, "application_only", conn=conn)
        conn.commit()
        state = get_alliance_state(leader, conn=conn)
        assert state["recruitment_mode"] == "application_only"
        with pytest.raises(ValueError, match="recruitment_application_only"):
            join_alliance_by_tag(member, "REC", conn=conn)
        update_recruitment_mode(aid, leader, "closed", conn=conn)
        conn.commit()
        with pytest.raises(ValueError, match="recruitment_closed"):
            apply_to_alliance(member, aid, message="Please let me in", conn=conn)
    finally:
        conn.close()


def test_donation_xp_daily_cap(alliance_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        create_alliance("XPC", "XP Cap", uid, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(uid, conn=conn)["alliance_id"])
        now = int(time.time())
        conn.executemany(
            """
            INSERT INTO alliance_donations (alliance_id, player_id, resource, amount, xp_granted, created_at)
            VALUES (?, ?, 'metal', 1, 1, ?);
            """,
            [(aid, uid, now) for _ in range(DONATION_XP_DAILY_CAP - 1)],
        )
        conn.commit()
        _fund_planet(uid, conn, metal=50_000)
        before_xp = int(conn.execute("SELECT alliance_xp FROM alliances WHERE id = ?;", (aid,)).fetchone()["alliance_xp"])
        donate_to_alliance(uid, "metal", 10_000, conn=conn)
        conn.commit()
        xp_today = int(
            conn.execute(
                "SELECT COALESCE(SUM(xp_granted), 0) AS xp FROM alliance_donations WHERE player_id = ?;",
                (uid,),
            ).fetchone()["xp"]
        )
        assert xp_today == DONATION_XP_DAILY_CAP
        after_first = int(conn.execute("SELECT alliance_xp FROM alliances WHERE id = ?;", (aid,)).fetchone()["alliance_xp"])
        assert after_first == before_xp + 1
        donate_to_alliance(uid, "metal", 10_000, conn=conn)
        conn.commit()
        after_second = int(conn.execute("SELECT alliance_xp FROM alliances WHERE id = ?;", (aid,)).fetchone()["alliance_xp"])
        assert after_second == after_first
    finally:
        conn.close()


def test_project_completion_grants_xp(alliance_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        create_alliance("PRX", "Project XP", uid, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(uid, conn=conn)["alliance_id"])
        conn.execute(
            "UPDATE alliances SET pool_metal = 500000, pool_crystal = 500000, pool_fuel_cells = 500000 WHERE id = ?;",
            (aid,),
        )
        conn.commit()
        start_alliance_project(uid, "building", "alliance_headquarters", conn=conn)
        conn.commit()
        before = int(conn.execute("SELECT alliance_xp FROM alliances WHERE id = ?;", (aid,)).fetchone()["alliance_xp"])
        conn.execute(
            "UPDATE alliance_projects SET finish_at = ? WHERE alliance_id = ? AND status = 'active';",
            (int(time.time()) - 1, aid),
        )
        finish_due_alliance_projects(conn=conn, alliance_id=aid)
        conn.commit()
        after = int(conn.execute("SELECT alliance_xp FROM alliances WHERE id = ?;", (aid,)).fetchone()["alliance_xp"])
        assert after > before
    finally:
        conn.close()


def test_diplomacy_war_and_duplicate_request(alliance_db):
    from game.alliance import get_alliance_relation

    leader_a = _player(name="A")
    leader_b = _player(name="B")
    conn = db()
    try:
        create_alliance("WAR", "Warriors", leader_a, conn=conn)
        create_alliance("PEA", "Peace", leader_b, conn=conn)
        conn.commit()
        aid_a = int(get_player_alliance(leader_a, conn=conn)["alliance_id"])
        aid_b = int(get_player_alliance(leader_b, conn=conn)["alliance_id"])
        conn.execute(
            "INSERT INTO alliance_buildings (alliance_id, building_key, level) VALUES (?, 'diplomacy_center', 1);",
            (aid_a,),
        )
        conn.commit()
        send_diplomacy_request(leader_a, "PEA", "war", conn=conn)
        conn.commit()
        assert get_alliance_relation(aid_a, aid_b, conn=conn) == "war"
        send_diplomacy_request(leader_a, "PEA", "nap", conn=conn)
        conn.commit()
        with pytest.raises(ValueError, match="duplicate_diplomacy_request"):
            send_diplomacy_request(leader_a, "PEA", "nap", conn=conn)
    finally:
        conn.close()


def test_application_accept_notifies_applicant(alliance_db):
    leader = _player(name="Leader")
    applicant = _player(name="Applicant")
    conn = db()
    try:
        create_alliance("NTF", "Notify", leader, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(leader, conn=conn)["alliance_id"])
        _set_recruitment_mode(conn, aid, "application_only")
        conn.commit()
        apply_to_alliance(applicant, aid, message="Ready to serve", conn=conn)
        conn.commit()
        app_id = int(
            conn.execute(
                "SELECT id FROM alliance_applications WHERE player_id = ? AND status = 'pending';",
                (applicant,),
            ).fetchone()["id"]
        )
        respond_application(leader, app_id, accept=True, conn=conn)
        conn.commit()
        msg = conn.execute(
            "SELECT subject FROM player_messages WHERE recipient_player_id = ? ORDER BY id DESC LIMIT 1;",
            (applicant,),
        ).fetchone()
        assert msg is not None
        assert "NTF" in str(msg["subject"])
    finally:
        conn.close()


def test_member_cannot_update_description(alliance_db):
    leader = _player()
    member = _player()
    conn = db()
    try:
        create_alliance("FOR", "Forbidden", leader, conn=conn)
        conn.commit()
        join_alliance_by_tag(member, "FOR", conn=conn)
        conn.commit()
        with pytest.raises(ValueError, match="forbidden"):
            update_alliance_description(member, "Nope", conn=conn)
    finally:
        conn.close()


def test_api_alliance_state(alliance_db):
    uid = _player()
    client = _app_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    resp = client.get("/api/alliance/state", headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert "alliance" in data


def test_api_leave_description_donate_project(alliance_db):
    leader = _player()
    member = _player()
    conn = db()
    try:
        create_alliance("API", "Api Flow", leader, conn=conn)
        conn.commit()
        join_alliance_by_tag(member, "API", conn=conn)
        conn.commit()
        _fund_planet(leader, conn, metal=100_000)
        conn.commit()
    finally:
        conn.close()

    client = _app_client()
    with client.session_transaction() as sess:
        sess["user_id"] = leader

    desc = client.post(
        "/api/alliance/description",
        json={"description": "Updated via API"},
        headers={"Content-Type": "application/json"},
    )
    assert desc.status_code == 200
    assert desc.get_json()["ok"] is True
    assert desc.get_json()["alliance"]["description"] == "Updated via API"

    donate = client.post(
        "/api/alliance/donate",
        json={"resource": "metal", "amount": 100},
        headers={"Content-Type": "application/json"},
    )
    assert donate.status_code == 200, donate.get_json()
    assert donate.get_json()["ok"] is True

    conn = db()
    try:
        aid = int(get_player_alliance(leader, conn=conn)["alliance_id"])
        conn.execute(
            "UPDATE alliances SET pool_metal = 500000, pool_crystal = 500000, pool_fuel_cells = 500000 WHERE id = ?;",
            (aid,),
        )
        conn.commit()
    finally:
        conn.close()

    project = client.post(
        "/api/alliance/project/start",
        json={"kind": "building", "key": "alliance_headquarters"},
        headers={"Content-Type": "application/json"},
    )
    assert project.status_code == 200
    assert project.get_json()["ok"] is True

    with client.session_transaction() as sess:
        sess["user_id"] = member
    leave = client.post("/api/alliance/leave", json={}, headers={"Content-Type": "application/json"})
    assert leave.status_code == 200
    assert leave.get_json()["ok"] is True
    assert leave.get_json()["alliance"]["in_alliance"] is False


def test_api_leave_leader_error_payload(alliance_db):
    leader = _player()
    member = _player()
    conn = db()
    try:
        create_alliance("LER", "Leader Err", leader, conn=conn)
        conn.commit()
        join_alliance_by_tag(member, "LER", conn=conn)
        conn.commit()
    finally:
        conn.close()

    client = _app_client()
    with client.session_transaction() as sess:
        sess["user_id"] = leader
    resp = client.post("/api/alliance/leave", json={}, headers={"Content-Type": "application/json"})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["ok"] is False
    assert data["error"] == "leader_must_transfer"
    assert "state" in data
    assert "alliance" in data


def test_api_recruitment_and_member_actions(alliance_db):
    leader = _player()
    member = _player()
    conn = db()
    try:
        create_alliance("MGT", "Manage", leader, conn=conn)
        conn.commit()
        join_alliance_by_tag(member, "MGT", conn=conn)
        conn.commit()
    finally:
        conn.close()

    client = _app_client()
    with client.session_transaction() as sess:
        sess["user_id"] = leader

    rec = client.post(
        "/api/alliance/recruitment",
        json={"mode": "application_only"},
        headers={"Content-Type": "application/json"},
    )
    assert rec.status_code == 200
    assert rec.get_json()["alliance"]["recruitment_mode"] == "application_only"

    promote = client.post(
        "/api/alliance/member/role",
        json={"player_id": member, "role": "officer"},
        headers={"Content-Type": "application/json"},
    )
    assert promote.status_code == 200
    data = promote.get_json()
    assert data["ok"] is True
    assert "state" in data
    assert "alliance" in data
    roles = {m["player_id"]: m["role"] for m in data["alliance"]["members"]}
    assert roles[member] == "officer"


def test_set_member_role_leader_only(alliance_db):
    leader = _player()
    officer = _player()
    member = _player()
    conn = db()
    try:
        create_alliance("RLS", "Roles Only", leader, conn=conn)
        conn.commit()
        join_alliance_by_tag(officer, "RLS", conn=conn)
        join_alliance_by_tag(member, "RLS", conn=conn)
        conn.commit()
        aid = int(get_player_alliance(leader, conn=conn)["alliance_id"])
        set_member_role(aid, leader, officer, "officer", conn=conn)
        conn.commit()
        with pytest.raises(ValueError, match="forbidden"):
            set_member_role(aid, officer, member, "officer", conn=conn)
    finally:
        conn.close()


def test_officer_kick_permissions(alliance_db):
    leader = _player()
    officer = _player()
    member = _player()
    other_officer = _player()
    conn = db()
    try:
        create_alliance("KCK", "Kick Perms", leader, conn=conn)
        conn.commit()
        join_alliance_by_tag(officer, "KCK", conn=conn)
        join_alliance_by_tag(member, "KCK", conn=conn)
        join_alliance_by_tag(other_officer, "KCK", conn=conn)
        conn.commit()
        aid = int(get_player_alliance(leader, conn=conn)["alliance_id"])
        set_member_role(aid, leader, officer, "officer", conn=conn)
        set_member_role(aid, leader, other_officer, "officer", conn=conn)
        conn.commit()
        kick_member(aid, officer, member, conn=conn)
        conn.commit()
        assert get_player_alliance(member, conn=conn) is None
        with pytest.raises(ValueError, match="forbidden"):
            kick_member(aid, officer, other_officer, conn=conn)
        with pytest.raises(ValueError, match="forbidden"):
            kick_member(aid, officer, leader, conn=conn)
    finally:
        conn.close()


def test_transfer_leadership_to_member(alliance_db):
    leader = _player()
    member = _player()
    conn = db()
    try:
        create_alliance("TRN", "Transfer", leader, conn=conn)
        conn.commit()
        join_alliance_by_tag(member, "TRN", conn=conn)
        conn.commit()
        aid = int(get_player_alliance(leader, conn=conn)["alliance_id"])
        transfer_leadership(aid, leader, member, conn=conn)
        conn.commit()
        assert get_player_alliance(member, conn=conn)["role"] == "leader"
        assert get_player_alliance(leader, conn=conn)["role"] == "officer"
    finally:
        conn.close()


def test_disband_forbidden_for_officer(alliance_db):
    leader = _player()
    officer = _player()
    conn = db()
    try:
        create_alliance("DSF", "Disband Forbidden", leader, conn=conn)
        conn.commit()
        join_alliance_by_tag(officer, "DSF", conn=conn)
        conn.commit()
        aid = int(get_player_alliance(leader, conn=conn)["alliance_id"])
        set_member_role(aid, leader, officer, "officer", conn=conn)
        conn.commit()
        with pytest.raises(ValueError, match="forbidden"):
            disband_alliance(aid, officer, conn=conn)
    finally:
        conn.close()


def test_update_alliance_profile(alliance_db):
    leader = _player()
    conn = db()
    try:
        create_alliance("PRF", "Profile Old", leader, description="Old", conn=conn)
        conn.commit()
        aid = int(get_player_alliance(leader, conn=conn)["alliance_id"])
        update_alliance_profile(
            aid,
            leader,
            tag="NEW",
            name="Profile New",
            description="New lore",
            conn=conn,
        )
        conn.commit()
        state = get_alliance_state(leader, conn=conn)
        assert state["tag"] == "NEW"
        assert state["name"] == "Profile New"
        assert state["description"] == "New lore"
    finally:
        conn.close()


def test_duplicate_tag_and_name_rejected(alliance_db):
    leader_a = _player()
    leader_b = _player()
    conn = db()
    try:
        create_alliance("DUP", "First Alliance", leader_a, conn=conn)
        create_alliance("OTH", "Second Alliance", leader_b, conn=conn)
        conn.commit()
        aid_b = int(get_player_alliance(leader_b, conn=conn)["alliance_id"])
        with pytest.raises(ValueError, match="duplicate_tag"):
            update_alliance_profile(aid_b, leader_b, tag="DUP", conn=conn)
        with pytest.raises(ValueError, match="duplicate_name"):
            update_alliance_profile(aid_b, leader_b, name="First Alliance", conn=conn)
    finally:
        conn.close()


def test_api_profile_update(alliance_db):
    leader = _player()
    conn = db()
    try:
        create_alliance("APIP2", "Api Profile", leader, conn=conn)
        conn.commit()
    finally:
        conn.close()

    client = _app_client()
    with client.session_transaction() as sess:
        sess["user_id"] = leader
    resp = client.post(
        "/api/alliance/profile",
        json={"tag": "AP2", "name": "Updated Name", "description": "Updated desc"},
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert "state" in data
    assert data["alliance"]["tag"] == "AP2"
    assert data["alliance"]["name"] == "Updated Name"

    conn = db()
    try:
        aid = int(
            conn.execute(
                "SELECT alliance_id FROM alliance_members WHERE player_id = ? LIMIT 1;",
                (leader,),
            ).fetchone()["alliance_id"]
        )
        row = conn.execute(
            "SELECT tag, name, description FROM alliances WHERE id = ?;",
            (aid,),
        ).fetchone()
        assert row["tag"] == "AP2"
        assert row["name"] == "Updated Name"
        assert row["description"] == "Updated desc"
    finally:
        conn.close()


def test_api_profile_update_error_envelope(alliance_db):
    leader = _player()
    conn = db()
    try:
        create_alliance("ERR1", "Error One", leader, conn=conn)
        conn.commit()
    finally:
        conn.close()

    client = _app_client()
    with client.session_transaction() as sess:
        sess["user_id"] = leader
    resp = client.post(
        "/api/alliance/profile",
        json={"tag": "", "name": ""},
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["ok"] is False
    assert data["error"] in ("invalid_alliance", "invalid_tag")
    assert data.get("message")


def test_api_disband_persists(alliance_db):
    leader = _player()
    conn = db()
    try:
        create_alliance("DSB2", "Disband API", leader, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(leader, conn=conn)["alliance_id"])
    finally:
        conn.close()

    client = _app_client()
    with client.session_transaction() as sess:
        sess["user_id"] = leader
    resp = client.post("/api/alliance/disband", json={}, headers={"Content-Type": "application/json"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["alliance"]["in_alliance"] is False

    conn = db()
    try:
        assert conn.execute("SELECT id FROM alliances WHERE id = ?;", (aid,)).fetchone() is None
        assert get_player_alliance(leader, conn=conn) is None
    finally:
        conn.close()

    conn = db()
    try:
        uid = _player(conn=conn)
        create_alliance("INS", "Insufficient", uid, conn=conn)
        conn.commit()
        _fund_planet(uid, conn, metal=50, crystal=50, fuel=50)
        with pytest.raises(ValueError, match="insufficient_resources"):
            donate_to_alliance(uid, "metal", 500, conn=conn)
    finally:
        conn.close()


def test_donation_rejects_invalid_amount(alliance_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        create_alliance("INV", "Invalid", uid, conn=conn)
        conn.commit()
        _fund_planet(uid, conn)
        with pytest.raises(ValueError, match="invalid_donation"):
            donate_to_alliance(uid, "metal", 0, conn=conn)
        with pytest.raises(ValueError, match="invalid_donation"):
            donate_to_alliance(uid, "metal", -100, conn=conn)
    finally:
        conn.close()


def test_donation_notifies_officers(alliance_db):
    leader = _player(name="Leader")
    member = _player(name="Donor")
    conn = db()
    try:
        create_alliance("DNT", "DonateMsg", leader, conn=conn)
        conn.commit()
        join_alliance_by_tag(member, "DNT", conn=conn)
        conn.commit()
        _fund_planet(member, conn, metal=10_000)
        donate_to_alliance(member, "metal", 500, conn=conn)
        conn.commit()
        msg = conn.execute(
            """
            SELECT subject, metadata_json FROM player_messages
            WHERE recipient_player_id = ? ORDER BY id DESC LIMIT 1;
            """,
            (leader,),
        ).fetchone()
        assert msg is not None
        assert "DNT" in str(msg["subject"])
    finally:
        conn.close()


def test_project_start_requires_officer(alliance_db):
    leader = _player()
    member = _player()
    conn = db()
    try:
        create_alliance("OFFP", "OfficerProj", leader, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(leader, conn=conn)["alliance_id"])
        join_alliance_by_tag(member, "OFFP", conn=conn)
        conn.commit()
        conn.execute(
            "UPDATE alliances SET pool_metal = 500000, pool_crystal = 500000, pool_fuel_cells = 200000 WHERE id = ?;",
            (aid,),
        )
        conn.commit()
        with pytest.raises(ValueError, match="forbidden"):
            start_alliance_project(member, "building", "alliance_headquarters", conn=conn)
    finally:
        conn.close()


def test_project_start_consumes_alliance_pool(alliance_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        create_alliance("CNS", "Consume", uid, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(uid, conn=conn)["alliance_id"])
        conn.execute(
            "UPDATE alliances SET pool_metal = 500000, pool_crystal = 500000, pool_fuel_cells = 200000 WHERE id = ?;",
            (aid,),
        )
        conn.commit()
        before = get_alliance_state(uid, conn=conn)["pool"]
        start_alliance_project(uid, "building", "alliance_headquarters", conn=conn)
        conn.commit()
        after = get_alliance_state(uid, conn=conn)["pool"]
        assert after["metal"] < before["metal"]
        assert after["crystal"] < before["crystal"]
        assert after["fuel_cells"] < before["fuel_cells"]
    finally:
        conn.close()


def test_cannot_start_second_active_project(alliance_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        create_alliance("ONE", "SingleProj", uid, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(uid, conn=conn)["alliance_id"])
        conn.execute(
            "UPDATE alliances SET pool_metal = 900000, pool_crystal = 900000, pool_fuel_cells = 400000 WHERE id = ?;",
            (aid,),
        )
        conn.commit()
        start_alliance_project(uid, "building", "alliance_headquarters", conn=conn)
        conn.commit()
        with pytest.raises(ValueError, match="project_active"):
            start_alliance_project(uid, "building", "research_archive", conn=conn)
    finally:
        conn.close()


def test_project_start_and_finish_notify_members(alliance_db):
    leader = _player()
    member = _player()
    conn = db()
    try:
        create_alliance("PRM", "ProjMsg", leader, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(leader, conn=conn)["alliance_id"])
        join_alliance_by_tag(member, "PRM", conn=conn)
        conn.commit()
        conn.execute(
            "UPDATE alliances SET pool_metal = 500000, pool_crystal = 500000, pool_fuel_cells = 200000 WHERE id = ?;",
            (aid,),
        )
        conn.commit()
        start_alliance_project(leader, "building", "alliance_headquarters", conn=conn)
        conn.commit()
        start_msg = conn.execute(
            "SELECT subject FROM player_messages WHERE recipient_player_id = ? ORDER BY id DESC LIMIT 1;",
            (member,),
        ).fetchone()
        assert start_msg is not None
        assert "PRM" in str(start_msg["subject"])

        proj_id = int(
            conn.execute(
                "SELECT id FROM alliance_projects WHERE alliance_id = ? AND status = 'active';",
                (aid,),
            ).fetchone()["id"]
        )
        conn.execute(
            "UPDATE alliance_projects SET finish_at = ? WHERE id = ?;",
            (int(time.time()) - 1, proj_id),
        )
        conn.commit()
        finish_due_alliance_projects(conn=conn, alliance_id=aid)
        conn.commit()
        finish_msg = conn.execute(
            "SELECT subject FROM player_messages WHERE recipient_player_id = ? ORDER BY id DESC LIMIT 1;",
            (member,),
        ).fetchone()
        assert finish_msg is not None
        assert "PRM" in str(finish_msg["subject"])
    finally:
        conn.close()


def test_alliance_production_combat_bonuses_via_effect_resolver(alliance_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        create_alliance("BNS", "Bonuses", uid, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(uid, conn=conn)["alliance_id"])
        conn.execute(
            """
            INSERT INTO alliance_technologies (alliance_id, tech_key, level)
            VALUES (?, 'industrial_logistics', 3),
                   (?, 'defensive_protocols', 2);
            """,
            (aid, aid),
        )
        conn.commit()

        mods = get_alliance_effect_modifiers(uid, conn=conn)
        assert mods["metal_prod_factor"] > 1.0
        assert mods["crystal_prod_factor"] > 1.0
        assert mods["armor_bonus"] > 0.0
        assert mods["shield_bonus"] > 0.0

        planet = get_context_planet(player_id=uid, conn=conn)
        resolver = get_effect_resolver(uid, conn=conn, planet=planet)
        rmods = resolver.get_modifiers()
        assert rmods["metal_prod_factor"] > 1.0
        assert rmods["armor_bonus"] > 0.0
    finally:
        conn.close()


def test_expedition_loot_multiplier_hook(alliance_db):
    conn = db()
    try:
        uid = _player(conn=conn)
        create_alliance("EXP", "Expedition", uid, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(uid, conn=conn)["alliance_id"])
        conn.execute(
            """
            INSERT INTO alliance_technologies (alliance_id, tech_key, level)
            VALUES (?, 'expedition_coordination', 2);
            """,
            (aid,),
        )
        conn.commit()
        mult = get_alliance_expedition_loot_multiplier(uid, conn=conn)
        assert mult > 1.0
        outsider = _player(conn=conn)
        conn.commit()
        assert get_alliance_expedition_loot_multiplier(outsider, conn=conn) == 1.0
    finally:
        conn.close()


def test_same_alliance_hold_permission(alliance_db):
    leader = _player()
    member = _player()
    outsider = _player()
    conn = db()
    try:
        create_alliance("HLD", "Hold", leader, conn=conn)
        conn.commit()
        join_alliance_by_tag(member, "HLD", conn=conn)
        conn.commit()
        assert are_players_allied(leader, member, conn=conn) is True
        assert are_players_allied(leader, outsider, conn=conn) is False

        from game.fleet import allowed_missions_for_target_type

        ally_allowed = allowed_missions_for_target_type("ally_planet", hold_enabled=True)
        foreign_allowed = allowed_missions_for_target_type("foreign_planet", hold_enabled=True)
        assert "hold" in ally_allowed
        assert "hold" not in foreign_allowed
    finally:
        conn.close()


def test_api_donate_error_includes_state_and_alliance(alliance_db):
    uid = _player()
    conn = db()
    try:
        create_alliance("APIE", "ApiErr", uid, conn=conn)
        conn.commit()
    finally:
        conn.close()

    client = _app_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    resp = client.post(
        "/api/alliance/donate",
        json={"resource": "metal", "amount": -1},
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["ok"] is False
    assert "state" in data
    assert "alliance" in data
    assert data["reason"] == "invalid_donation"


def _alliance_js_block() -> str:
    src = Path("static/main.js").read_text(encoding="utf-8")
    start = src.find("function parseAlliancePageState")
    init_start = src.find("  function initAlliance()")
    end = src.find("\n  function debugDirectiveDomMutation", init_start)
    assert start >= 0 and init_start > start and end > init_start
    return src[start:end]


def test_alliance_js_no_full_reload():
    """GC-AL-MVP-08: Alliance module must not use full page reload navigation."""
    block = _alliance_js_block()
    assert "location.reload" not in block
    assert "location.href =" not in block
    assert "location.assign" not in block
    assert "GC.fetchGameAction" in block
    assert "applyActionState" in block
    assert "allianceReloadHub" in block
    assert "GC.navigateTo" in block or "GC.reloadCurrentPage" in block


def test_alliance_template_project_server_timing_attributes(alliance_db):
    uid = _player()
    conn = db()
    try:
        create_alliance("TIM", "Timing", uid, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(uid, conn=conn)["alliance_id"])
        conn.execute(
            "UPDATE alliances SET pool_metal = 500000, pool_crystal = 500000, pool_fuel_cells = 200000 WHERE id = ?;",
            (aid,),
        )
        conn.commit()
        start_alliance_project(uid, "building", "alliance_headquarters", conn=conn)
        conn.commit()
    finally:
        conn.close()

    client = _app_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    resp = client.get("/alliance", headers={"X-Requested-With": "XMLHttpRequest"})
    body = resp.get_data(as_text=True)
    assert "data-alliance-active-project" in body
    assert "data-duration-seconds=" in body
    assert "data-progress-pct=" in body
    assert "data-started-at=" in body
    assert "data-finish-at=" in body


def test_api_project_start_forbidden_includes_envelope(alliance_db):
    leader = _player()
    member = _player()
    conn = db()
    try:
        create_alliance("PRF", "Perm", leader, conn=conn)
        conn.commit()
        join_alliance_by_tag(member, "PRF", conn=conn)
        conn.commit()
    finally:
        conn.close()

    client = _app_client()
    with client.session_transaction() as sess:
        sess["user_id"] = member
    resp = client.post(
        "/api/alliance/project/start",
        json={"kind": "building", "key": "alliance_headquarters"},
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["ok"] is False
    assert data["reason"] == "forbidden"
    assert "state" in data
    assert "alliance" in data


def test_donation_limits_cap_by_cheapest_project(alliance_db):
    uid = _player()
    conn = db()
    try:
        create_alliance("LIM", "Limits", uid, conn=conn)
        conn.commit()
        state = get_alliance_state(uid, conn=conn)
        cheapest = state["available_projects"][0]
        need_metal = int(cheapest["cost"]["metal"])
        aid = int(state["alliance_id"])
        pool_metal = 10_000
        conn.execute("UPDATE alliances SET pool_metal = ? WHERE id = ?;", (pool_metal, aid))
        conn.commit()
        state = get_alliance_state(uid, conn=conn)
        cap_room = max(0, int(state["pool_cap"]["metal"]) - pool_metal)
        expected = min(max(0, need_metal - pool_metal), cap_room)
        assert state["donation_limits"]["metal"] == expected
        assert expected > 0
    finally:
        conn.close()


def test_donation_rejects_exceeds_project_need(alliance_db):
    uid = _player()
    conn = db()
    try:
        create_alliance("OVR", "Overspend", uid, conn=conn)
        conn.commit()
        _fund_planet(uid, conn)
        state = get_alliance_state(uid, conn=conn)
        max_metal = int(state["donation_limits"]["metal"])
        assert max_metal > 0
        with pytest.raises(ValueError, match="donation_exceeds_need"):
            donate_to_alliance(uid, "metal", max_metal + 1, conn=conn)
    finally:
        conn.close()

    client = _app_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    resp = client.post(
        "/api/alliance/donate",
        json={"resource": "metal", "amount": max_metal + 1},
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["ok"] is False
    assert data["reason"] == "donation_exceeds_need"
    assert "state" in data
    assert "alliance" in data


def test_donation_limit_zero_when_pool_full(alliance_db):
    uid = _player()
    conn = db()
    try:
        create_alliance("FUL", "FullPool", uid, conn=conn)
        conn.commit()
        state = get_alliance_state(uid, conn=conn)
        aid = int(state["alliance_id"])
        conn.execute(
            """
            UPDATE alliances
            SET pool_metal = ?, pool_crystal = ?, pool_fuel_cells = ?
            WHERE id = ?;
            """,
            (
                int(state["pool_cap"]["metal"]),
                int(state["pool_cap"]["crystal"]),
                int(state["pool_cap"]["fuel_cells"]),
                aid,
            ),
        )
        conn.commit()
        state = get_alliance_state(uid, conn=conn)
        assert state["donation_limits"]["metal"] == 0
        assert state["donation_limits"]["crystal"] == 0
        assert state["donation_limits"]["fuel_cells"] == 0
    finally:
        conn.close()


def test_donation_limits_allow_pool_stockpile_when_project_need_met(alliance_db):
    uid = _player()
    conn = db()
    try:
        create_alliance("STK", "Stockpile", uid, conn=conn)
        conn.commit()
        state = get_alliance_state(uid, conn=conn)
        cheapest = state["available_projects"][0]
        need_metal = int(cheapest["cost"]["metal"])
        aid = int(state["alliance_id"])
        conn.execute("UPDATE alliances SET pool_metal = ? WHERE id = ?;", (need_metal, aid))
        conn.commit()
        state = get_alliance_state(uid, conn=conn)
        cap_room = max(0, int(state["pool_cap"]["metal"]) - need_metal)
        assert state["donation_limits"]["metal"] == cap_room
        assert cap_room > 0
    finally:
        conn.close()


def test_donation_limits_active_project_uses_pool_cap_only(alliance_db):
    uid = _player()
    conn = db()
    try:
        create_alliance("ACT", "Active", uid, conn=conn)
        conn.commit()
        _fund_planet(uid, conn, metal=500_000, crystal=500_000, fuel=200_000)
        state = get_alliance_state(uid, conn=conn)
        aid = int(state["alliance_id"])
        cheapest = state["available_projects"][0]
        cost = cheapest["cost"]
        conn.execute(
            """
            UPDATE alliances
            SET pool_metal = ?, pool_crystal = ?, pool_fuel_cells = ?
            WHERE id = ?;
            """,
            (int(cost["metal"]), int(cost["crystal"]), int(cost["fuel_cells"]), aid),
        )
        conn.commit()
        start_alliance_project(uid, cheapest["kind"], cheapest["key"], conn=conn)
        conn.commit()
        state = get_alliance_state(uid, conn=conn)
        assert state["active_project"] is not None
        pool_metal = int(state["pool"]["metal"])
        cap_metal = int(state["pool_cap"]["metal"])
        assert state["donation_limits"]["metal"] == max(0, cap_metal - pool_metal)
    finally:
        conn.close()


def test_donation_notify_uses_localized_resource(alliance_db):
    uid = _player()
    conn = db()
    try:
        create_alliance("MSG", "Messages", uid, conn=conn)
        conn.commit()
        _fund_planet(uid, conn)
        donate_to_alliance(uid, "metal", 100, conn=conn)
        conn.commit()
        row = conn.execute(
            """
            SELECT body FROM player_messages
            WHERE recipient_player_id = ?
            ORDER BY id DESC LIMIT 1;
            """,
            (uid,),
        ).fetchone()
        assert row is not None
        body = str(row["body"])
        assert "Ferronit" in body
    finally:
        conn.close()

def test_alliance_donate_template_caps_input(alliance_db):
    uid = _player()
    conn = db()
    try:
        create_alliance("TPL", "Template", uid, conn=conn)
        conn.commit()
    finally:
        conn.close()

    client = _app_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    resp = client.get("/alliance", headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'class="gc-input gc-num-input alliance-hub-donate-input"' in html
    assert "data-input-max=" in html
    assert "alliance_donate_max_hint" in html or "Max." in html


def test_alliance_js_donate_uses_read_number_input():
    block = _alliance_js_block()
    assert "readNumberInput(input)" in block
    assert "parseInt(input?.value" not in block


def test_donation_limits_helper_matches_state(alliance_db):
    uid = _player()
    conn = db()
    try:
        create_alliance("HLR", "Helper", uid, conn=conn)
        conn.commit()
        state = get_alliance_state(uid, conn=conn)
        limits = donation_limits_for_pool(
            state["pool"],
            state["pool_cap"],
            state["available_projects"],
            active_project=state.get("active_project"),
        )
        assert limits == state["donation_limits"]
    finally:
        conn.close()


def test_locked_projects_include_tech_when_archive_missing(alliance_db):
    uid = _player()
    conn = db()
    try:
        create_alliance("LCK", "Locked", uid, conn=conn)
        conn.commit()
        state = get_alliance_state(uid, conn=conn)
        locked = state.get("locked_projects") or []
        tech_locked = [p for p in locked if p.get("kind") == "tech"]
        assert tech_locked
        assert all(p.get("missing_requirements") for p in tech_locked)
        assert any(
            req.get("key") == "research_archive"
            for p in tech_locked
            for req in (p.get("missing_requirements") or [])
        )
    finally:
        conn.close()


def test_diplomacy_unlock_project_in_state(alliance_db):
    uid = _player()
    conn = db()
    try:
        create_alliance("DIP", "Diplo", uid, conn=conn)
        conn.commit()
        state = get_alliance_state(uid, conn=conn)
        assert state["diplomacy_unlocked"] is False
        proj = state.get("diplomacy_unlock_project")
        assert proj is not None
        assert proj.get("key") == "diplomacy_center"
    finally:
        conn.close()


def test_alliance_broadcast_officers_only(alliance_db):
    leader = _player()
    member = _player()
    conn = db()
    try:
        create_alliance("BC", "Broadcast", leader, conn=conn)
        conn.commit()
        join_alliance_by_tag(member, "BC", conn=conn)
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(ValueError, match="forbidden"):
        send_alliance_broadcast(member, "Hello", "Alliance news")

    conn = db()
    try:
        count = send_alliance_broadcast(leader, "Orders", "All hands on deck.", conn=conn)
        conn.commit()
        assert count == 1
        row = conn.execute(
            "SELECT subject, body FROM player_messages WHERE recipient_player_id = ? ORDER BY id DESC LIMIT 1;",
            (member,),
        ).fetchone()
        assert row is not None
        assert "Orders" in str(row["subject"])
        assert "All hands on deck." in str(row["body"])
        leader_mail = conn.execute(
            "SELECT COUNT(*) AS c FROM player_messages WHERE recipient_player_id = ?;",
            (leader,),
        ).fetchone()
        assert int(leader_mail["c"]) == 0
    finally:
        conn.close()


def test_api_alliance_broadcast(alliance_db):
    leader = _player()
    member = _player()
    conn = db()
    try:
        create_alliance("APIB", "ApiBroadcast", leader, conn=conn)
        conn.commit()
        join_alliance_by_tag(member, "APIB", conn=conn)
        conn.commit()
    finally:
        conn.close()

    client = _app_client()
    with client.session_transaction() as sess:
        sess["user_id"] = leader
    resp = client.post(
        "/api/alliance/broadcast",
        json={"subject": "Rally", "body": "Meeting tonight at 20:00."},
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data.get("broadcast_count") == 1
    assert "alliance" in data


def test_tech_projects_available_after_research_archive(alliance_db):
    uid = _player()
    conn = db()
    try:
        create_alliance("TEC", "Tech", uid, conn=conn)
        conn.commit()
        aid = int(get_player_alliance(uid, conn=conn)["alliance_id"])
        conn.execute(
            "INSERT INTO alliance_buildings (alliance_id, building_key, level) VALUES (?, 'research_archive', 1) ON CONFLICT(alliance_id, building_key) DO UPDATE SET level = 1;",
            (aid,),
        )
        conn.commit()
        state = get_alliance_state(uid, conn=conn)
        tech_avail = [p for p in state["available_projects"] if p.get("kind") == "tech"]
        assert tech_avail
    finally:
        conn.close()


def test_alliance_layout_uses_card_grids_not_lists(alliance_db):
    body = _alliance_member_hub_html(alliance_db)
    assert '<ul class="alliance-hub-project-grid"' not in body
    assert '<ul class="alliance-hub-member-grid' not in body
    assert 'class="alliance-hub-pool-grid"' in body
    assert 'class="alliance-hub-tab-bar"' in body
    assert 'class="alliance-hub-tab is-active"' in body
    assert "alliance-hub-grid-section" in body
    assert "alliance-hub-hero-logo-row" in body


def test_alliance_no_internal_keys_visible(alliance_db):
    body = _alliance_member_hub_html(alliance_db)
    visible = _alliance_visible_text(body).lower()
    for key in ALLIANCE_INTERNAL_KEYS:
        assert key not in visible, f"internal key leaked into visible HTML: {key}"


def test_alliance_hero_actions_single_group(alliance_db):
    body = _alliance_member_hub_html(alliance_db)
    assert body.count('class="alliance-hub-hero-actions"') == 1
    assert "data-alliance-manage-open" in body
    assert "data-alliance-chat-open" in body


def test_alliance_member_roster_uses_cards_not_table(alliance_db):
    body = _alliance_member_hub_html(alliance_db)
    assert "alliance-hub-member-table--roster" in body
    assert "alliance-hub-member-grid--roster" not in body


def test_alliance_project_cards_show_localized_building_names(alliance_db):
    body = _alliance_member_hub_html(alliance_db)
    visible = _alliance_visible_text(body)
    assert "Hauptquartier" in visible or "Headquarters" in visible
    assert "research_archive" not in visible.lower()


def test_alliance_diplomacy_jump_highlights_project(alliance_db):
    body = _alliance_member_hub_html(alliance_db)
    assert 'data-alliance-highlight-project="diplomacy_center"' in body
    assert 'data-project-key="diplomacy_center"' in body


def test_project_effect_preview_includes_affects_and_desc(alliance_db):
    fx = project_effect_preview(
        "tech",
        "research_network",
        current_level=0,
        target_level=1,
    )
    assert fx["desc_key"] == "alliance_tech_research_network_desc"
    assert fx["affects_keys"] == ["alliance_affects_research"]
    hq = project_effect_preview(
        "building",
        "alliance_headquarters",
        current_level=0,
        target_level=1,
        buildings={"alliance_headquarters": 0},
    )
    assert hq["desc_key"] == "alliance_building_hq_desc"
    assert hq["affects_keys"] == ["alliance_affects_members"]
    assert hq["next_value"] == member_limit_from_buildings({"alliance_headquarters": 1})
