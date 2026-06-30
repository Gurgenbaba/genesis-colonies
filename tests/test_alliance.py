"""EPIC-09 Alliance Hub tests (GC-AL-001 … GC-AL-006)."""

from __future__ import annotations

import time
import uuid

import pytest

from game.alliance import (
    alliance_hub_schema_ready,
    apply_to_alliance,
    create_alliance,
    donate_to_alliance,
    finish_due_alliance_projects,
    get_alliance_effect_modifiers,
    get_alliance_public_profile,
    get_alliance_state,
    get_player_alliance,
    join_alliance_by_tag,
    leave_alliance,
    respond_application,
    start_alliance_project,
    update_alliance_description,
    withdraw_application,
)
from game.alliance_catalog import BASE_MEMBER_LIMIT, member_limit_from_buildings
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

        proj_id = int(state["active_project"]["id"])
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
    body = resp.get_data(as_text=True)
    assert "alliance-hub-module" in body
    assert "alliance-hub-command" in body
    assert "alliance-hub-pool-tile" in body
    assert "data-pool-val=\"metal\"" in body
    assert "alliance-hub-tab" in body
    assert "gc-btn-danger" in body


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
