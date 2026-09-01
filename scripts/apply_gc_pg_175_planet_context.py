#!/usr/bin/env python3
from pathlib import Path

path = Path('game/planet_evolution/repository.py')
src = path.read_text(encoding='utf-8')
src = src.replace(
    'from ..db import column_exists, table_exists',
    'from ..db import column_exists, get_db_backend, table_exists',
    1,
)
start = src.index('def get_active_planet_id(')
end = src.index('\ndef get_planet_dna(', start)
replacement = '''def get_active_planet_id(player_id: int, conn: Optional[sqlite3.Connection] = None) -> int:
    from ..models import get_homeworld

    own = conn is None
    if own:
        conn = db()
    try:
        cur = conn.cursor()
        pid = int(player_id)
        # PostgreSQL canonical owner: keep context writes off the hot players row.
        # A missing context row falls through to the legacy column for rolling deploys
        # and newly-created accounts; the first explicit switch creates the canonical row.
        if get_db_backend() == "postgres" and table_exists(conn, "player_context"):
            cur.execute(
                "SELECT active_planet_id FROM player_context WHERE player_id = ? LIMIT 1;",
                (pid,),
            )
            row = cur.fetchone()
            ap = row["active_planet_id"] if row else None
            if ap:
                cur.execute(
                    "SELECT id FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
                    (int(ap), pid),
                )
                if cur.fetchone():
                    return int(ap)

        if column_exists(conn, "players", "active_planet_id"):
            cur.execute(
                "SELECT active_planet_id FROM players WHERE id = ? LIMIT 1;",
                (pid,),
            )
            row = cur.fetchone()
            ap = row["active_planet_id"] if row else None
            if ap:
                cur.execute(
                    "SELECT id FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
                    (int(ap), pid),
                )
                if cur.fetchone():
                    return int(ap)
        planet = get_homeworld(player_id=pid, conn=conn)
        return int(planet["id"])
    finally:
        if own:
            conn.close()


def set_active_planet_id(player_id: int, planet_id: int, conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    pid = int(player_id)
    plid = int(planet_id)
    cur.execute(
        "SELECT id FROM planets WHERE id = ? AND player_id = ? LIMIT 1;",
        (plid, pid),
    )
    if not cur.fetchone():
        raise ValueError("planet_not_owned")

    if get_db_backend() == "postgres" and table_exists(conn, "player_context"):
        cur.execute(
            """
            INSERT INTO player_context (player_id, active_planet_id, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT (player_id) DO UPDATE SET
                active_planet_id = excluded.active_planet_id,
                updated_at = excluded.updated_at;
            """,
            (pid, plid, int(time.time())),
        )
        return

    # SQLite compatibility owner remains players.active_planet_id.
    if column_exists(conn, "players", "active_planet_id"):
        cur.execute(
            "UPDATE players SET active_planet_id = ? WHERE id = ?;",
            (plid, pid),
        )

'''
src = src[:start] + replacement + src[end:]
path.write_text(src, encoding='utf-8')
