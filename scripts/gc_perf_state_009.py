from pathlib import Path

ALLIANCE_PATH = Path("game/alliance.py")
TEST_PATH = Path("tests/test_gc_perf_state_009.py")

OLD = '''def count_alliance_nav_attention(player_id: int, *, conn=None) -> int:
    """Nav badge count: outbound pending app (1) or inbound apps for officers."""
    own = conn is None
    if own:
        conn = db()
    try:
        if not alliance_hub_schema_ready(conn):
            return 0
        pid = int(player_id)
        membership = get_player_alliance(pid, conn=conn)
        if not membership:
            return 1 if _player_pending_application(pid, conn) else 0
        if not can_manage_applications(membership.get("role")):
            return 0
        aid = int(membership["alliance_id"])
        return len(_pending_applications(aid, conn))
    finally:
        if own:
            conn.close()
'''

NEW = '''def count_alliance_nav_attention(player_id: int, *, conn=None) -> int:
    """Return the minimal Alliance attention count used by the nav badge."""
    own = conn is None
    if own:
        conn = db()
    try:
        if not alliance_hub_schema_ready(conn):
            return 0

        pid = int(player_id)
        cur = conn.cursor()
        cur.execute(
            """
            SELECT alliance_id, role
            FROM alliance_members
            WHERE player_id = ?
            LIMIT 1;
            """,
            (pid,),
        )
        membership = cur.fetchone()

        if membership is None:
            cur.execute(
                """
                SELECT 1 AS pending
                FROM alliance_applications
                WHERE player_id = ? AND status = 'pending'
                LIMIT 1;
                """,
                (pid,),
            )
            return 1 if cur.fetchone() is not None else 0

        if not can_manage_applications(membership["role"]):
            return 0

        cur.execute(
            """
            SELECT COUNT(*) AS c
            FROM alliance_applications
            WHERE alliance_id = ? AND status = 'pending';
            """,
            (int(membership["alliance_id"]),),
        )
        row = cur.fetchone()
        return int(row["c"] or 0) if row is not None else 0
    finally:
        if own:
            conn.close()
'''

TEST = r'''import sqlite3

from game import alliance


_REQUIRED_TABLES = (
    "alliances",
    "alliance_members",
    "alliance_donations",
    "alliance_buildings",
    "alliance_technologies",
    "alliance_projects",
    "alliance_applications",
    "alliance_diplomacy",
    "alliance_diplomacy_requests",
)


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE alliances (id INTEGER PRIMARY KEY);")
    conn.execute(
        "CREATE TABLE alliance_members (alliance_id INTEGER, player_id INTEGER, role TEXT);"
    )
    conn.execute("CREATE TABLE alliance_donations (id INTEGER);")
    conn.execute("CREATE TABLE alliance_buildings (id INTEGER);")
    conn.execute("CREATE TABLE alliance_technologies (id INTEGER);")
    conn.execute("CREATE TABLE alliance_projects (id INTEGER);")
    conn.execute(
        "CREATE TABLE alliance_applications ("
        "id INTEGER PRIMARY KEY, alliance_id INTEGER, player_id INTEGER, status TEXT"
        ");"
    )
    conn.execute("CREATE TABLE alliance_diplomacy (id INTEGER);")
    conn.execute("CREATE TABLE alliance_diplomacy_requests (id INTEGER);")
    conn.commit()
    return conn


def _block_broad_helpers(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("broad Alliance serializer/helper must not run on nav attention path")

    monkeypatch.setattr(alliance, "get_player_alliance", fail)
    monkeypatch.setattr(alliance, "_player_pending_application", fail)
    monkeypatch.setattr(alliance, "_pending_applications", fail)


def _selects(trace):
    return [sql for sql in trace if sql.lstrip().upper().startswith("SELECT")]


def _assert_attention_sql_shape(trace, expected_selects):
    selects = _selects(trace)
    assert len(selects) == expected_selects
    assert sum("sqlite_master" in sql.lower() for sql in selects) == 1
    assert not any(" join " in f" {sql.lower()} " for sql in selects)
    assert not any("pragma_table_info" in sql.lower() for sql in selects)
    assert not any("recruitment_mode" in sql.lower() for sql in selects)


def test_alliance_nav_attention_guest_is_minimal_and_read_only(monkeypatch):
    _block_broad_helpers(monkeypatch)
    conn = _conn()
    try:
        trace = []
        conn.set_trace_callback(trace.append)
        assert alliance.count_alliance_nav_attention(7, conn=conn) == 0
        _assert_attention_sql_shape(trace, 3)
        assert not conn.in_transaction

        conn.set_trace_callback(None)
        conn.execute(
            "INSERT INTO alliance_applications (alliance_id, player_id, status) VALUES (1, 7, 'pending');"
        )
        conn.commit()
        trace.clear()
        conn.set_trace_callback(trace.append)
        assert alliance.count_alliance_nav_attention(7, conn=conn) == 1
        _assert_attention_sql_shape(trace, 3)
        assert not conn.in_transaction
    finally:
        conn.close()


def test_alliance_nav_attention_member_stops_after_slim_membership(monkeypatch):
    _block_broad_helpers(monkeypatch)
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO alliance_members (alliance_id, player_id, role) VALUES (1, 8, 'member');"
        )
        conn.commit()
        trace = []
        conn.set_trace_callback(trace.append)
        assert alliance.count_alliance_nav_attention(8, conn=conn) == 0
        _assert_attention_sql_shape(trace, 2)
        selects = _selects(trace)
        assert "alliance_id, role" in selects[-1].lower()
        assert "alliances" not in selects[-1].lower().replace("alliance_members", "")
        assert not conn.in_transaction
    finally:
        conn.close()


def test_alliance_nav_attention_officer_and_leader_use_scalar_count(monkeypatch):
    _block_broad_helpers(monkeypatch)
    for player_id, role in ((9, "officer"), (10, "leader")):
        conn = _conn()
        try:
            conn.execute(
                "INSERT INTO alliance_members (alliance_id, player_id, role) VALUES (1, ?, ?);",
                (player_id, role),
            )
            conn.executemany(
                "INSERT INTO alliance_applications (alliance_id, player_id, status) VALUES (?, ?, ?);",
                [
                    (1, 101, "pending"),
                    (1, 102, "pending"),
                    (1, 103, "rejected"),
                    (2, 104, "pending"),
                ],
            )
            conn.commit()
            trace = []
            conn.set_trace_callback(trace.append)
            assert alliance.count_alliance_nav_attention(player_id, conn=conn) == 2
            _assert_attention_sql_shape(trace, 3)
            selects = _selects(trace)
            assert "count(*)" in selects[-1].lower()
            assert "players" not in selects[-1].lower()
            assert not conn.in_transaction
        finally:
            conn.close()
'''


def main():
    text = ALLIANCE_PATH.read_text(encoding="utf-8")
    if NEW not in text:
        if OLD not in text:
            raise SystemExit("count_alliance_nav_attention source block not found")
        text = text.replace(OLD, NEW, 1)
        ALLIANCE_PATH.write_text(text, encoding="utf-8")

    TEST_PATH.write_text(TEST, encoding="utf-8")


if __name__ == "__main__":
    main()
