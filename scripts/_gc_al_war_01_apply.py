from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:120]!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def insert_locale_keys(path: Path, mapping: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    existing = [key for key in mapping if key in data]
    if existing:
        raise SystemExit(f"{path}: keys already exist: {existing}")
    stripped = text.rstrip()
    if not stripped.endswith("}"):
        raise SystemExit(f"{path}: expected JSON object")
    body = stripped[:-1].rstrip()
    if data:
        body += ","
    lines = [
        "  " + json.dumps(k, ensure_ascii=False) + ": " + json.dumps(v, ensure_ascii=False)
        for k, v in mapping.items()
    ]
    body += "\n" + ",\n".join(lines) + "\n}\n"
    json.loads(body)
    path.write_text(body, encoding="utf-8")


LOCALES = {
    "de": {
        "alliance_relation_peace": "Friedensangebot",
        "alliance_dip_offer_peace": "Frieden anbieten",
        "peace_requires_war": "Ein Friedensangebot ist nur während eines aktiven Krieges möglich.",
        "war_active": "Der Krieg ist aktiv. Beendet ihn zuerst durch ein Friedensangebot.",
        "already_at_war": "Diese Allianzen befinden sich bereits im Krieg.",
    },
    "en": {
        "alliance_relation_peace": "Peace offer",
        "alliance_dip_offer_peace": "Offer peace",
        "peace_requires_war": "A peace offer is only possible during an active war.",
        "war_active": "The war is active. End it through a peace offer first.",
        "already_at_war": "These alliances are already at war.",
    },
    "fr": {
        "alliance_relation_peace": "Offre de paix",
        "alliance_dip_offer_peace": "Proposer la paix",
        "peace_requires_war": "Une offre de paix n’est possible que pendant une guerre active.",
        "war_active": "La guerre est active. Mettez-y fin avec une offre de paix avant tout autre pacte.",
        "already_at_war": "Ces alliances sont déjà en guerre.",
    },
    "es": {
        "alliance_relation_peace": "Oferta de paz",
        "alliance_dip_offer_peace": "Ofrecer la paz",
        "peace_requires_war": "Solo se puede ofrecer la paz durante una guerra activa.",
        "war_active": "La guerra está activa. Termínala primero mediante una oferta de paz.",
        "already_at_war": "Estas alianzas ya están en guerra.",
    },
    "pl": {
        "alliance_relation_peace": "Oferta pokoju",
        "alliance_dip_offer_peace": "Zaproponuj pokój",
        "peace_requires_war": "Ofertę pokoju można złożyć tylko podczas aktywnej wojny.",
        "war_active": "Wojna trwa. Najpierw zakończ ją poprzez ofertę pokoju.",
        "already_at_war": "Te sojusze są już w stanie wojny.",
    },
    "tr": {
        "alliance_relation_peace": "Barış teklifi",
        "alliance_dip_offer_peace": "Barış teklif et",
        "peace_requires_war": "Barış teklifi yalnızca aktif bir savaş sırasında yapılabilir.",
        "war_active": "Savaş devam ediyor. Önce bir barış teklifiyle savaşı sona erdirin.",
        "already_at_war": "Bu ittifaklar zaten savaş halinde.",
    },
    "ru": {
        "alliance_relation_peace": "Предложение мира",
        "alliance_dip_offer_peace": "Предложить мир",
        "peace_requires_war": "Предложить мир можно только во время активной войны.",
        "war_active": "Война продолжается. Сначала завершите её через предложение мира.",
        "already_at_war": "Эти альянсы уже находятся в состоянии войны.",
    },
    "pt": {
        "alliance_relation_peace": "Oferta de paz",
        "alliance_dip_offer_peace": "Oferecer paz",
        "peace_requires_war": "Uma oferta de paz só pode ser feita durante uma guerra ativa.",
        "war_active": "A guerra está ativa. Encerre-a primeiro por meio de uma oferta de paz.",
        "already_at_war": "Essas alianças já estão em guerra.",
    },
}

for locale, mapping in LOCALES.items():
    insert_locale_keys(ROOT / "locales" / f"{locale}.json", mapping)

catalog = ROOT / "game" / "alliance_catalog.py"
replace_once(
    catalog,
    'DIPLOMACY_REQUEST_TYPES = frozenset({"nap", "alliance", "war"})\n',
    'DIPLOMACY_REQUEST_TYPES = frozenset({"nap", "alliance", "war", "peace"})\n',
)

alliance = ROOT / "game" / "alliance.py"
replace_once(
    alliance,
    '''def _diplomacy_pair(a: int, b: int) -> Tuple[int, int]:\n    x, y = int(a), int(b)\n    if x > y:\n        x, y = y, x\n    return x, y\n\n\ndef get_alliance_relation''',
    '''def _diplomacy_pair(a: int, b: int) -> Tuple[int, int]:\n    x, y = int(a), int(b)\n    if x > y:\n        x, y = y, x\n    return x, y\n\n\ndef _invalidate_pending_diplomacy_requests_between(\n    alliance_id_a: int,\n    alliance_id_b: int,\n    *,\n    conn,\n    now: Optional[int] = None,\n    except_request_id: Optional[int] = None,\n) -> int:\n    \"\"\"Close stale bilateral offers whenever a newer relation transition wins.\"\"\"\n    a, b = int(alliance_id_a), int(alliance_id_b)\n    ts = int(now or _now())\n    params: List[Any] = [ts, a, b, b, a]\n    extra = \"\"\n    if except_request_id is not None:\n        extra = \" AND id != ?\"\n        params.append(int(except_request_id))\n    cur = conn.cursor()\n    cur.execute(\n        f\"\"\"\n        UPDATE alliance_diplomacy_requests\n        SET status = 'declined', responded_at = COALESCE(responded_at, ?)\n        WHERE status = 'pending'\n          AND ((from_alliance_id = ? AND to_alliance_id = ?)\n            OR (from_alliance_id = ? AND to_alliance_id = ?))\n          {extra};\n        \"\"\",\n        tuple(params),\n    )\n    return int(cur.rowcount or 0)\n\n\ndef get_alliance_relation''',
)
replace_once(
    alliance,
    '''        to_aid = int(target["id"])\n        if to_aid == from_aid:\n            raise ValueError("invalid_target")\n        now = _now()\n        if own:\n            begin_write_transaction(conn)\n        if rtype == "war":\n            lo, hi = _diplomacy_pair(from_aid, to_aid)\n            conn.execute(''',
    '''        to_aid = int(target["id"])\n        if to_aid == from_aid:\n            raise ValueError("invalid_target")\n        current_relation = get_alliance_relation(from_aid, to_aid, conn=conn)\n        if rtype == "peace" and current_relation != "war":\n            raise ValueError("peace_requires_war")\n        if current_relation == "war" and rtype in ("nap", "alliance"):\n            raise ValueError("war_active")\n        if current_relation == "war" and rtype == "war":\n            raise ValueError("already_at_war")\n        now = _now()\n        if own:\n            begin_write_transaction(conn)\n        if rtype == "war":\n            _invalidate_pending_diplomacy_requests_between(from_aid, to_aid, conn=conn, now=now)\n            lo, hi = _diplomacy_pair(from_aid, to_aid)\n            conn.execute(''',
)
replace_once(
    alliance,
    '''        else:\n            cur.execute(\n                \"\"\"\n                SELECT id FROM alliance_diplomacy_requests\n                WHERE from_alliance_id = ? AND to_alliance_id = ? AND request_type = ?\n                  AND status = 'pending'\n                LIMIT 1;\n                \"\"\",\n                (from_aid, to_aid, rtype),\n            )\n            if cur.fetchone():\n                raise ValueError("duplicate_diplomacy_request")\n            conn.execute(''',
    '''        else:\n            if rtype == "peace":\n                cur.execute(\n                    \"\"\"\n                    SELECT id FROM alliance_diplomacy_requests\n                    WHERE request_type = 'peace' AND status = 'pending'\n                      AND ((from_alliance_id = ? AND to_alliance_id = ?)\n                        OR (from_alliance_id = ? AND to_alliance_id = ?))\n                    LIMIT 1;\n                    \"\"\",\n                    (from_aid, to_aid, to_aid, from_aid),\n                )\n            else:\n                cur.execute(\n                    \"\"\"\n                    SELECT id FROM alliance_diplomacy_requests\n                    WHERE from_alliance_id = ? AND to_alliance_id = ? AND request_type = ?\n                      AND status = 'pending'\n                    LIMIT 1;\n                    \"\"\",\n                    (from_aid, to_aid, rtype),\n                )\n            if cur.fetchone():\n                raise ValueError("duplicate_diplomacy_request")\n            conn.execute(''',
)
replace_once(
    alliance,
    '''        if accept:\n            relation = "alliance" if str(req["request_type"]) == "alliance" else "nap"\n            if relation not in DIPLOMACY_RELATIONS:\n                relation = "nap"\n            lo, hi = _diplomacy_pair(int(req["from_alliance_id"]), to_aid)\n            conn.execute(\n                \"\"\"\n                INSERT INTO alliance_diplomacy (alliance_id_low, alliance_id_high, relation, updated_at)\n                VALUES (?, ?, ?, ?)\n                ON CONFLICT(alliance_id_low, alliance_id_high) DO UPDATE SET\n                    relation = excluded.relation, updated_at = excluded.updated_at;\n                \"\"\",\n                (lo, hi, relation, now),\n            )\n            conn.execute(''',
    '''        if accept:\n            request_type = str(req["request_type"] or "").strip().lower()\n            from_aid = int(req["from_alliance_id"])\n            lo, hi = _diplomacy_pair(from_aid, to_aid)\n            if request_type == "peace":\n                if get_alliance_relation(from_aid, to_aid, conn=conn) != "war":\n                    raise ValueError("peace_requires_war")\n                conn.execute(\n                    \"DELETE FROM alliance_diplomacy WHERE alliance_id_low = ? AND alliance_id_high = ?;\",\n                    (lo, hi),\n                )\n                _invalidate_pending_diplomacy_requests_between(\n                    from_aid,\n                    to_aid,\n                    conn=conn,\n                    now=now,\n                    except_request_id=int(request_id),\n                )\n            else:\n                if get_alliance_relation(from_aid, to_aid, conn=conn) == "war":\n                    raise ValueError("war_active")\n                relation = "alliance" if request_type == "alliance" else "nap"\n                if relation not in DIPLOMACY_RELATIONS:\n                    relation = "nap"\n                conn.execute(\n                    \"\"\"\n                    INSERT INTO alliance_diplomacy (alliance_id_low, alliance_id_high, relation, updated_at)\n                    VALUES (?, ?, ?, ?)\n                    ON CONFLICT(alliance_id_low, alliance_id_high) DO UPDATE SET\n                        relation = excluded.relation, updated_at = excluded.updated_at;\n                    \"\"\",\n                    (lo, hi, relation, now),\n                )\n            conn.execute(''',
)

template = ROOT / "templates" / "alliance.html"
replace_once(
    template,
    '''          <li class="alliance-hub-diplomacy-row">\n            <span class="alliance-hub-tag">[{{ d.other_tag }}]</span>\n            <span class="alliance-hub-dip-name">{{ d.other_name }}</span>\n            {{ alliance_dip_relation(d.relation) }}\n          </li>''',
    '''          <li class="alliance-hub-diplomacy-row">\n            <span class="alliance-hub-tag">[{{ d.other_tag }}]</span>\n            <span class="alliance-hub-dip-name">{{ d.other_name }}</span>\n            {{ alliance_dip_relation(d.relation) }}\n            {% if d.relation == 'war' and st.can_manage %}\n            <form class="alliance-hub-dip-peace-form" data-alliance-action="diplomacy" method="post" action="#" novalidate>\n              <input type="hidden" name="tag" value="{{ d.other_tag }}">\n              <input type="hidden" name="request_type" value="peace">\n              <button type="button" class="gc-btn gc-btn-sm gc-btn-ghost" data-alliance-submit="diplomacy">{{ T("alliance_dip_offer_peace", "Frieden anbieten") }}</button>\n            </form>\n            {% endif %}\n          </li>''',
)

tests = ROOT / "tests" / "test_alliance.py"
replace_once(
    tests,
    '''    respond_application,\n    send_alliance_broadcast,\n    send_diplomacy_request,\n''',
    '''    respond_application,\n    respond_diplomacy_request,\n    send_alliance_broadcast,\n    send_diplomacy_request,\n''',
)
marker = '\n\ndef test_gc_al_dip_01_fleet_mission_hooks(alliance_db):\n'
text = tests.read_text(encoding="utf-8")
if text.count(marker) != 1:
    raise SystemExit("tests/test_alliance.py: diplomacy insertion marker mismatch")
new_tests = r'''


def _setup_war_pair(conn, *, tag_a="WRA", tag_b="WRB"):
    from game.alliance import get_alliance_relation

    leader_a = _player(conn=conn, name=f"{tag_a} Leader")
    leader_b = _player(conn=conn, name=f"{tag_b} Leader")
    create_alliance(tag_a, f"{tag_a} Alliance", leader_a, conn=conn)
    create_alliance(tag_b, f"{tag_b} Alliance", leader_b, conn=conn)
    conn.commit()
    aid_a = int(get_player_alliance(leader_a, conn=conn)["alliance_id"])
    aid_b = int(get_player_alliance(leader_b, conn=conn)["alliance_id"])
    conn.executemany(
        "INSERT INTO alliance_buildings (alliance_id, building_key, level) VALUES (?, 'diplomacy_center', 1);",
        [(aid_a,), (aid_b,)],
    )
    conn.commit()
    send_diplomacy_request(leader_a, tag_b, "war", conn=conn)
    conn.commit()
    assert get_alliance_relation(aid_a, aid_b, conn=conn) == "war"
    return leader_a, leader_b, aid_a, aid_b


def test_gc_al_war_01_peace_accept_returns_to_neutral(alliance_db):
    from game.alliance import get_alliance_relation

    conn = db()
    try:
        leader_a, leader_b, aid_a, aid_b = _setup_war_pair(conn, tag_a="PAA", tag_b="PBB")
        send_diplomacy_request(leader_a, "PBB", "peace", conn=conn)
        conn.commit()
        req = conn.execute(
            "SELECT id FROM alliance_diplomacy_requests WHERE request_type='peace' AND status='pending' LIMIT 1;"
        ).fetchone()
        assert req is not None
        respond_diplomacy_request(leader_b, int(req["id"]), accept=True, conn=conn)
        conn.commit()
        assert get_alliance_relation(aid_a, aid_b, conn=conn) == "neutral"
        row = conn.execute("SELECT status FROM alliance_diplomacy_requests WHERE id = ?;", (int(req["id"]),)).fetchone()
        assert row["status"] == "accepted"
    finally:
        conn.close()


def test_gc_al_war_01_declined_peace_keeps_war(alliance_db):
    from game.alliance import get_alliance_relation

    conn = db()
    try:
        leader_a, leader_b, aid_a, aid_b = _setup_war_pair(conn, tag_a="PCA", tag_b="PCB")
        send_diplomacy_request(leader_a, "PCB", "peace", conn=conn)
        conn.commit()
        req_id = int(conn.execute(
            "SELECT id FROM alliance_diplomacy_requests WHERE request_type='peace' AND status='pending' LIMIT 1;"
        ).fetchone()["id"])
        respond_diplomacy_request(leader_b, req_id, accept=False, conn=conn)
        conn.commit()
        assert get_alliance_relation(aid_a, aid_b, conn=conn) == "war"
    finally:
        conn.close()


def test_gc_al_war_01_transition_guards_and_stale_requests(alliance_db):
    conn = db()
    try:
        leader_a = _player(conn=conn, name="Transition A")
        leader_b = _player(conn=conn, name="Transition B")
        create_alliance("TRA", "Transition A", leader_a, conn=conn)
        create_alliance("TRB", "Transition B", leader_b, conn=conn)
        conn.commit()
        aid_a = int(get_player_alliance(leader_a, conn=conn)["alliance_id"])
        aid_b = int(get_player_alliance(leader_b, conn=conn)["alliance_id"])
        conn.execute(
            "INSERT INTO alliance_buildings (alliance_id, building_key, level) VALUES (?, 'diplomacy_center', 1);",
            (aid_a,),
        )
        conn.commit()

        with pytest.raises(ValueError, match="peace_requires_war"):
            send_diplomacy_request(leader_a, "TRB", "peace", conn=conn)

        send_diplomacy_request(leader_a, "TRB", "nap", conn=conn)
        conn.commit()
        nap_id = int(conn.execute(
            "SELECT id FROM alliance_diplomacy_requests WHERE request_type='nap' AND status='pending' LIMIT 1;"
        ).fetchone()["id"])

        send_diplomacy_request(leader_a, "TRB", "war", conn=conn)
        conn.commit()
        stale = conn.execute("SELECT status FROM alliance_diplomacy_requests WHERE id = ?;", (nap_id,)).fetchone()
        assert stale["status"] == "declined"

        with pytest.raises(ValueError, match="war_active"):
            send_diplomacy_request(leader_a, "TRB", "nap", conn=conn)
        with pytest.raises(ValueError, match="war_active"):
            send_diplomacy_request(leader_a, "TRB", "alliance", conn=conn)
        with pytest.raises(ValueError, match="already_at_war"):
            send_diplomacy_request(leader_a, "TRB", "war", conn=conn)

        assert aid_a != aid_b
    finally:
        conn.close()


def test_gc_al_war_01_member_cannot_offer_peace(alliance_db):
    conn = db()
    try:
        leader_a, _leader_b, _aid_a, _aid_b = _setup_war_pair(conn, tag_a="MRA", tag_b="MRB")
        member = _player(conn=conn, name="Member")
        join_alliance_by_tag(member, "MRA", conn=conn)
        conn.commit()
        with pytest.raises(ValueError, match="forbidden"):
            send_diplomacy_request(member, "MRB", "peace", conn=conn)
        assert get_player_alliance(leader_a, conn=conn) is not None
    finally:
        conn.close()


def test_gc_al_war_01_hub_renders_peace_action_for_active_war(alliance_db):
    conn = db()
    try:
        leader_a, _leader_b, _aid_a, _aid_b = _setup_war_pair(conn, tag_a="UIA", tag_b="UIB")
    finally:
        conn.close()
    body = _alliance_member_hub_html(alliance_db, uid=leader_a)
    assert 'name="request_type" value="peace"' in body
    assert 'name="tag" value="UIB"' in body
    assert 'data-alliance-submit="diplomacy"' in body
'''
tests.write_text(text.replace(marker, new_tests + marker), encoding="utf-8")

# Extend existing fleet-hook test: accepted peace must immediately return target to neutral behavior.
replace_once(
    tests,
    '''        assert mission_allowed_for_target("attack", war_target)[0] is True\n        assert mission_allowed_for_target("transport", war_target)[0] is False\n    finally:\n        conn.close()\n''',
    '''        assert mission_allowed_for_target("attack", war_target)[0] is True\n        assert mission_allowed_for_target("transport", war_target)[0] is False\n\n        # Accepted peace -> neutral immediately; canonical fleet hook follows relation state.\n        send_diplomacy_request(leader_a, "DBB", "peace", conn=conn)\n        conn.commit()\n        peace_req = int(\n            conn.execute(\n                \"\"\"\n                SELECT id FROM alliance_diplomacy_requests\n                WHERE from_alliance_id = ? AND request_type = 'peace' AND status = 'pending'\n                LIMIT 1;\n                \"\"\",\n                (aid_a,),\n            ).fetchone()[\"id\"]\n        )\n        respond_diplomacy_request(leader_b, peace_req, accept=True, conn=conn)\n        conn.commit()\n        assert get_players_diplomacy_relation(leader_a, leader_b, conn=conn) == "neutral"\n        peace_target = resolve_fleet_target(leader_a, g, s, p, conn=conn)\n        assert peace_target.get("diplomacy_relation") == "neutral"\n        assert "attack" in peace_target["allowed_missions"]\n    finally:\n        conn.close()\n''',
)

alliance_doc = ROOT / "docs" / "ALLIANCE_SYSTEM.md"
replace_once(
    alliance_doc,
    '**Status:** ✅ **MVP complete** (GC-AL-MVP-01 … GC-AL-MVP-09) + **UX-Pass** (GC-AL-UX-01…03) + **GC-AL-DIP-01** (Fleet Mission Hooks). Kriegs-Meta / End-War UI bewusst später.\n',
    '**Status:** ✅ **MVP complete** (GC-AL-MVP-01 … GC-AL-MVP-09) + **UX-Pass** (GC-AL-UX-01…03) + **GC-AL-DIP-01** (Fleet Mission Hooks) + **GC-AL-WAR-01** (Peace Workflow). Kriegs-Score / Report-Meta folgt separat.\n',
)
replace_once(
    alliance_doc,
    '- **Follow-up:** Combat Kriegs-Meta (Reports/Score), End-War / Peace-UI\n',
    '- **GC-AL-WAR-01:** aktiver Krieg → gegenseitig bestätigtes Friedensangebot → `neutral`; Krieg invalidiert ältere Pact-Requests, damit keine stale Anfrage den neueren Kriegszustand überschreibt.\n- **Follow-up:** Combat Kriegs-Meta (Reports/Score/Badges) als GC-AL-WAR-02.\n',
)

capability = ROOT / "docs" / "CAPABILITY_STATUS.md"
replace_once(
    capability,
    '   - 📋 Kriegs-Meta (Reports/Score), End-War UI\n',
    '   - ✅ **GC-AL-WAR-01** — Peace Workflow / sichere Diplomatie-Transitions\n   - 📋 **GC-AL-WAR-02** — Kriegs-Meta (Reports/Score/Badges)\n',
)

print("GC-AL-WAR-01 patch applied")
