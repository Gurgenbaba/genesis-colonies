from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, got {count}")
    write(path, text.replace(old, new, 1))


def append_once(path: str, marker: str, block: str) -> None:
    text = read(path)
    if marker in text:
        return
    write(path, text.rstrip() + "\n\n" + block.strip() + "\n")


MIGRATION = r'''-- 155_alliance_war_meta.sql
-- GC-AL-WAR-02: derived combat meta for active alliance wars.
-- Diplomacy lifecycle remains authoritative in alliance_diplomacy.

CREATE TABLE IF NOT EXISTS alliance_war_stats (
    alliance_id_low       INTEGER NOT NULL,
    alliance_id_high      INTEGER NOT NULL,
    war_started_at        INTEGER NOT NULL,
    low_score_raw         TEXT NOT NULL DEFAULT '0',
    high_score_raw        TEXT NOT NULL DEFAULT '0',
    low_units_destroyed   TEXT NOT NULL DEFAULT '0',
    high_units_destroyed  TEXT NOT NULL DEFAULT '0',
    low_wins              INTEGER NOT NULL DEFAULT 0,
    high_wins             INTEGER NOT NULL DEFAULT 0,
    draws                 INTEGER NOT NULL DEFAULT 0,
    battle_count          INTEGER NOT NULL DEFAULT 0,
    last_battle_at        INTEGER,
    updated_at            INTEGER NOT NULL,
    PRIMARY KEY (alliance_id_low, alliance_id_high),
    FOREIGN KEY(alliance_id_low) REFERENCES alliances(id) ON DELETE CASCADE,
    FOREIGN KEY(alliance_id_high) REFERENCES alliances(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS alliance_war_events (
    fleet_id                 INTEGER PRIMARY KEY,
    alliance_id_low          INTEGER NOT NULL,
    alliance_id_high         INTEGER NOT NULL,
    war_started_at           INTEGER NOT NULL,
    attacker_alliance_id     INTEGER NOT NULL,
    defender_alliance_id     INTEGER NOT NULL,
    attacker_score_raw       TEXT NOT NULL DEFAULT '0',
    defender_score_raw       TEXT NOT NULL DEFAULT '0',
    attacker_units_destroyed TEXT NOT NULL DEFAULT '0',
    defender_units_destroyed TEXT NOT NULL DEFAULT '0',
    result                   TEXT NOT NULL,
    created_at               INTEGER NOT NULL,
    FOREIGN KEY(alliance_id_low) REFERENCES alliances(id) ON DELETE CASCADE,
    FOREIGN KEY(alliance_id_high) REFERENCES alliances(id) ON DELETE CASCADE,
    FOREIGN KEY(attacker_alliance_id) REFERENCES alliances(id) ON DELETE CASCADE,
    FOREIGN KEY(defender_alliance_id) REFERENCES alliances(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_alliance_war_events_campaign
    ON alliance_war_events(alliance_id_low, alliance_id_high, war_started_at, created_at);
'''

WAR_MODULE = r'''"""Alliance war meta — derived combat statistics for active diplomacy wars (GC-AL-WAR-02).

The canonical war lifecycle remains in ``game.alliance`` / ``alliance_diplomacy``.
This module only records combat-derived metadata and deliberately reuses the
canonical combat destruction score helper from ``game.scoring``.
"""

from __future__ import annotations

import time
from typing import Any, Mapping

from .db import table_exists
from .scoring import compute_destroyed_raw_from_losses


def _now() -> int:
    return int(time.time())


def war_meta_schema_ready(conn) -> bool:
    return table_exists(conn, "alliance_war_stats") and table_exists(
        conn, "alliance_war_events"
    )


def _pair(alliance_a: int, alliance_b: int) -> tuple[int, int]:
    a = int(alliance_a)
    b = int(alliance_b)
    return (a, b) if a < b else (b, a)


def _as_bigint(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _loss_count(losses: Mapping[str, int] | None) -> int:
    return sum(_as_bigint(qty) for qty in (losses or {}).values())


def _player_alliance(player_id: int, conn) -> dict[str, Any] | None:
    if not table_exists(conn, "alliance_members") or not table_exists(conn, "alliances"):
        return None
    row = conn.execute(
        """
        SELECT a.id AS alliance_id, a.name, a.tag
        FROM alliance_members am
        JOIN alliances a ON a.id = am.alliance_id
        WHERE am.player_id = ?
        LIMIT 1;
        """,
        (int(player_id),),
    ).fetchone()
    return dict(row) if row else None


def _active_war_relation(alliance_a: int, alliance_b: int, conn) -> dict[str, Any] | None:
    if not table_exists(conn, "alliance_diplomacy"):
        return None
    low, high = _pair(alliance_a, alliance_b)
    if low <= 0 or high <= 0 or low == high:
        return None
    row = conn.execute(
        """
        SELECT alliance_id_low, alliance_id_high, relation, updated_at
        FROM alliance_diplomacy
        WHERE alliance_id_low = ? AND alliance_id_high = ? AND relation = 'war'
        LIMIT 1;
        """,
        (low, high),
    ).fetchone()
    return dict(row) if row else None


def _zero_stats(low: int, high: int, war_started_at: int) -> dict[str, Any]:
    return {
        "alliance_id_low": int(low),
        "alliance_id_high": int(high),
        "war_started_at": int(war_started_at),
        "low_score_raw": "0",
        "high_score_raw": "0",
        "low_units_destroyed": "0",
        "high_units_destroyed": "0",
        "low_wins": 0,
        "high_wins": 0,
        "draws": 0,
        "battle_count": 0,
        "last_battle_at": None,
        "updated_at": int(war_started_at),
    }


def _load_campaign_stats(low: int, high: int, war_started_at: int, conn) -> dict[str, Any]:
    if not war_meta_schema_ready(conn):
        return _zero_stats(low, high, war_started_at)
    row = conn.execute(
        """
        SELECT * FROM alliance_war_stats
        WHERE alliance_id_low = ? AND alliance_id_high = ?
        LIMIT 1;
        """,
        (int(low), int(high)),
    ).fetchone()
    if not row or int(row["war_started_at"] or 0) != int(war_started_at):
        return _zero_stats(low, high, war_started_at)
    return dict(row)


def _ensure_campaign_stats(low: int, high: int, war_started_at: int, conn) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT * FROM alliance_war_stats
        WHERE alliance_id_low = ? AND alliance_id_high = ?
        LIMIT 1;
        """,
        (int(low), int(high)),
    ).fetchone()
    now = _now()
    if not row:
        conn.execute(
            """
            INSERT INTO alliance_war_stats (
                alliance_id_low, alliance_id_high, war_started_at,
                low_score_raw, high_score_raw,
                low_units_destroyed, high_units_destroyed,
                low_wins, high_wins, draws, battle_count,
                last_battle_at, updated_at
            ) VALUES (?, ?, ?, '0', '0', '0', '0', 0, 0, 0, 0, NULL, ?);
            """,
            (int(low), int(high), int(war_started_at), now),
        )
        return _zero_stats(low, high, war_started_at)
    current = dict(row)
    if int(current.get("war_started_at") or 0) != int(war_started_at):
        conn.execute(
            """
            UPDATE alliance_war_stats
            SET war_started_at = ?,
                low_score_raw = '0', high_score_raw = '0',
                low_units_destroyed = '0', high_units_destroyed = '0',
                low_wins = 0, high_wins = 0, draws = 0, battle_count = 0,
                last_battle_at = NULL, updated_at = ?
            WHERE alliance_id_low = ? AND alliance_id_high = ?;
            """,
            (int(war_started_at), now, int(low), int(high)),
        )
        return _zero_stats(low, high, war_started_at)
    return current


def _side_payload(stats: Mapping[str, Any], alliance_id: int, low: int) -> dict[str, Any]:
    is_low = int(alliance_id) == int(low)
    prefix = "low" if is_low else "high"
    return {
        "alliance_id": int(alliance_id),
        "score_raw": str(_as_bigint(stats.get(f"{prefix}_score_raw"))),
        "units_destroyed": str(_as_bigint(stats.get(f"{prefix}_units_destroyed"))),
        "wins": _as_bigint(stats.get(f"{prefix}_wins")),
    }


def get_active_war_stats_for_alliance_pair(
    alliance_id: int,
    other_alliance_id: int,
    *,
    conn,
) -> dict[str, Any] | None:
    """Read-only current-war scoreboard oriented as self/other."""
    relation = _active_war_relation(alliance_id, other_alliance_id, conn)
    if not relation:
        return None
    low, high = _pair(alliance_id, other_alliance_id)
    started = int(relation.get("updated_at") or 0)
    stats = _load_campaign_stats(low, high, started, conn)
    own = _side_payload(stats, int(alliance_id), low)
    other = _side_payload(stats, int(other_alliance_id), low)
    return {
        "active": True,
        "war_started_at": started,
        "battle_count": _as_bigint(stats.get("battle_count")),
        "draws": _as_bigint(stats.get("draws")),
        "last_battle_at": int(stats.get("last_battle_at") or 0) or None,
        "self": own,
        "other": other,
        "lead": "self"
        if _as_bigint(own["score_raw"]) > _as_bigint(other["score_raw"])
        else "other"
        if _as_bigint(other["score_raw"]) > _as_bigint(own["score_raw"])
        else "draw",
    }


def _combat_context(
    *,
    stats: Mapping[str, Any],
    low: int,
    attacker: Mapping[str, Any],
    defender: Mapping[str, Any],
    attacker_delta: int,
    defender_delta: int,
    attacker_units_delta: int,
    defender_units_delta: int,
) -> dict[str, Any]:
    attacker_id = int(attacker["alliance_id"])
    defender_id = int(defender["alliance_id"])
    atk = _side_payload(stats, attacker_id, low)
    deff = _side_payload(stats, defender_id, low)
    atk.update(
        {
            "name": str(attacker.get("name") or ""),
            "tag": str(attacker.get("tag") or ""),
            "score_delta_raw": str(_as_bigint(attacker_delta)),
            "units_delta": str(_as_bigint(attacker_units_delta)),
        }
    )
    deff.update(
        {
            "name": str(defender.get("name") or ""),
            "tag": str(defender.get("tag") or ""),
            "score_delta_raw": str(_as_bigint(defender_delta)),
            "units_delta": str(_as_bigint(defender_units_delta)),
        }
    )
    atk_score = _as_bigint(atk["score_raw"])
    def_score = _as_bigint(deff["score_raw"])
    return {
        "active": True,
        "war_started_at": int(stats.get("war_started_at") or 0),
        "battle_count": _as_bigint(stats.get("battle_count")),
        "draws": _as_bigint(stats.get("draws")),
        "last_battle_at": int(stats.get("last_battle_at") or 0) or None,
        "attacker": atk,
        "defender": deff,
        "lead": "attacker" if atk_score > def_score else "defender" if def_score > atk_score else "draw",
    }


def record_war_combat_report(
    *,
    attacker_player_id: int,
    defender_player_id: int,
    attacker_losses: Mapping[str, int] | None,
    defender_losses: Mapping[str, int] | None,
    result: str,
    fleet_id: Any,
    conn,
) -> dict[str, Any] | None:
    """Record one PvP fleet battle against the currently active alliance war.

    ``fleet_id`` is the idempotency key. Missing ids produce read-only context
    and never mutate statistics. All score deltas come from the canonical
    combat destruction helper; this module owns no parallel scoring formula.
    """
    if not war_meta_schema_ready(conn):
        return None
    attacker = _player_alliance(int(attacker_player_id), conn)
    defender = _player_alliance(int(defender_player_id), conn)
    if not attacker or not defender:
        return None
    attacker_aid = int(attacker["alliance_id"])
    defender_aid = int(defender["alliance_id"])
    if attacker_aid == defender_aid:
        return None
    relation = _active_war_relation(attacker_aid, defender_aid, conn)
    if not relation:
        return None

    low, high = _pair(attacker_aid, defender_aid)
    war_started_at = int(relation.get("updated_at") or 0)
    attacker_delta = compute_destroyed_raw_from_losses(defender_losses or {})
    defender_delta = compute_destroyed_raw_from_losses(attacker_losses or {})
    attacker_units = _loss_count(defender_losses)
    defender_units = _loss_count(attacker_losses)

    try:
        fid = int(fleet_id)
    except (TypeError, ValueError):
        fid = 0
    if fid <= 0:
        stats = _load_campaign_stats(low, high, war_started_at, conn)
        return _combat_context(
            stats=stats,
            low=low,
            attacker=attacker,
            defender=defender,
            attacker_delta=0,
            defender_delta=0,
            attacker_units_delta=0,
            defender_units_delta=0,
        )

    savepoint = "gc_alliance_war_meta"
    conn.execute(f"SAVEPOINT {savepoint};")
    try:
        stats = _ensure_campaign_stats(low, high, war_started_at, conn)
        now = _now()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO alliance_war_events (
                fleet_id, alliance_id_low, alliance_id_high, war_started_at,
                attacker_alliance_id, defender_alliance_id,
                attacker_score_raw, defender_score_raw,
                attacker_units_destroyed, defender_units_destroyed,
                result, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fleet_id) DO NOTHING;
            """,
            (
                fid,
                low,
                high,
                war_started_at,
                attacker_aid,
                defender_aid,
                str(attacker_delta),
                str(defender_delta),
                str(attacker_units),
                str(defender_units),
                str(result or "undecided"),
                now,
            ),
        )
        inserted = int(cur.rowcount or 0) > 0
        if inserted:
            low_score = _as_bigint(stats.get("low_score_raw"))
            high_score = _as_bigint(stats.get("high_score_raw"))
            low_units = _as_bigint(stats.get("low_units_destroyed"))
            high_units = _as_bigint(stats.get("high_units_destroyed"))
            low_wins = _as_bigint(stats.get("low_wins"))
            high_wins = _as_bigint(stats.get("high_wins"))
            draws = _as_bigint(stats.get("draws"))
            battles = _as_bigint(stats.get("battle_count")) + 1

            if attacker_aid == low:
                low_score += attacker_delta
                low_units += attacker_units
                high_score += defender_delta
                high_units += defender_units
            else:
                high_score += attacker_delta
                high_units += attacker_units
                low_score += defender_delta
                low_units += defender_units

            outcome = str(result or "undecided").strip().lower()
            if outcome == "attacker":
                if attacker_aid == low:
                    low_wins += 1
                else:
                    high_wins += 1
            elif outcome == "defender":
                if defender_aid == low:
                    low_wins += 1
                else:
                    high_wins += 1
            elif outcome == "draw":
                draws += 1

            conn.execute(
                """
                UPDATE alliance_war_stats
                SET low_score_raw = ?, high_score_raw = ?,
                    low_units_destroyed = ?, high_units_destroyed = ?,
                    low_wins = ?, high_wins = ?, draws = ?, battle_count = ?,
                    last_battle_at = ?, updated_at = ?
                WHERE alliance_id_low = ? AND alliance_id_high = ?
                  AND war_started_at = ?;
                """,
                (
                    str(low_score),
                    str(high_score),
                    str(low_units),
                    str(high_units),
                    low_wins,
                    high_wins,
                    draws,
                    battles,
                    now,
                    now,
                    low,
                    high,
                    war_started_at,
                ),
            )
        stats = _load_campaign_stats(low, high, war_started_at, conn)
        conn.execute(f"RELEASE SAVEPOINT {savepoint};")
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint};")
        conn.execute(f"RELEASE SAVEPOINT {savepoint};")
        raise

    return _combat_context(
        stats=stats,
        low=low,
        attacker=attacker,
        defender=defender,
        attacker_delta=attacker_delta if inserted else 0,
        defender_delta=defender_delta if inserted else 0,
        attacker_units_delta=attacker_units if inserted else 0,
        defender_units_delta=defender_units if inserted else 0,
    )
'''

TESTS = r'''from __future__ import annotations

import sqlite3
from pathlib import Path

from game.alliance_war import (
    get_active_war_stats_for_alliance_pair,
    record_war_combat_report,
)
from game.scoring import compute_destroyed_raw_from_losses


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE alliances (
            id INTEGER PRIMARY KEY,
            tag TEXT NOT NULL,
            name TEXT NOT NULL
        );
        CREATE TABLE alliance_members (
            alliance_id INTEGER NOT NULL,
            player_id INTEGER NOT NULL,
            role TEXT NOT NULL DEFAULT 'member',
            PRIMARY KEY (alliance_id, player_id)
        );
        CREATE TABLE alliance_diplomacy (
            alliance_id_low INTEGER NOT NULL,
            alliance_id_high INTEGER NOT NULL,
            relation TEXT NOT NULL,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY (alliance_id_low, alliance_id_high)
        );
        CREATE TABLE alliance_war_stats (
            alliance_id_low INTEGER NOT NULL,
            alliance_id_high INTEGER NOT NULL,
            war_started_at INTEGER NOT NULL,
            low_score_raw TEXT NOT NULL DEFAULT '0',
            high_score_raw TEXT NOT NULL DEFAULT '0',
            low_units_destroyed TEXT NOT NULL DEFAULT '0',
            high_units_destroyed TEXT NOT NULL DEFAULT '0',
            low_wins INTEGER NOT NULL DEFAULT 0,
            high_wins INTEGER NOT NULL DEFAULT 0,
            draws INTEGER NOT NULL DEFAULT 0,
            battle_count INTEGER NOT NULL DEFAULT 0,
            last_battle_at INTEGER,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY (alliance_id_low, alliance_id_high)
        );
        CREATE TABLE alliance_war_events (
            fleet_id INTEGER PRIMARY KEY,
            alliance_id_low INTEGER NOT NULL,
            alliance_id_high INTEGER NOT NULL,
            war_started_at INTEGER NOT NULL,
            attacker_alliance_id INTEGER NOT NULL,
            defender_alliance_id INTEGER NOT NULL,
            attacker_score_raw TEXT NOT NULL DEFAULT '0',
            defender_score_raw TEXT NOT NULL DEFAULT '0',
            attacker_units_destroyed TEXT NOT NULL DEFAULT '0',
            defender_units_destroyed TEXT NOT NULL DEFAULT '0',
            result TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        INSERT INTO alliances(id, tag, name) VALUES
            (10, 'RED', 'Red Fleet'),
            (20, 'BLU', 'Blue Guard');
        INSERT INTO alliance_members(alliance_id, player_id, role) VALUES
            (10, 1, 'leader'),
            (20, 2, 'leader');
        INSERT INTO alliance_diplomacy(alliance_id_low, alliance_id_high, relation, updated_at)
            VALUES (10, 20, 'war', 1000);
        """
    )
    return conn


def _record(conn: sqlite3.Connection, fleet_id: int, *, qty: int = 5):
    return record_war_combat_report(
        attacker_player_id=1,
        defender_player_id=2,
        attacker_losses={"sentinel_turret": 2},
        defender_losses={"sentinel_turret": qty},
        result="attacker",
        fleet_id=fleet_id,
        conn=conn,
    )


def test_war_combat_records_canonical_score_and_stats() -> None:
    conn = _conn()
    meta = _record(conn, 9001)
    assert meta and meta["active"] is True
    expected = compute_destroyed_raw_from_losses({"sentinel_turret": 5})
    assert int(meta["attacker"]["score_raw"]) == expected
    assert int(meta["attacker"]["units_destroyed"]) == 5
    assert meta["attacker"]["wins"] == 1
    assert meta["battle_count"] == 1
    state = get_active_war_stats_for_alliance_pair(10, 20, conn=conn)
    assert state and int(state["self"]["score_raw"]) == expected


def test_same_fleet_id_is_idempotent() -> None:
    conn = _conn()
    first = _record(conn, 9001)
    second = _record(conn, 9001)
    assert first and second
    assert second["battle_count"] == 1
    assert second["attacker"]["score_raw"] == first["attacker"]["score_raw"]
    assert second["attacker"]["score_delta_raw"] == "0"
    assert conn.execute("SELECT COUNT(*) AS c FROM alliance_war_events").fetchone()["c"] == 1


def test_peace_stops_stats_and_rewar_starts_fresh_campaign() -> None:
    conn = _conn()
    _record(conn, 9001)
    conn.execute(
        "UPDATE alliance_diplomacy SET relation = 'neutral', updated_at = 1500 "
        "WHERE alliance_id_low = 10 AND alliance_id_high = 20"
    )
    assert _record(conn, 9002) is None
    conn.execute(
        "UPDATE alliance_diplomacy SET relation = 'war', updated_at = 2000 "
        "WHERE alliance_id_low = 10 AND alliance_id_high = 20"
    )
    zero = get_active_war_stats_for_alliance_pair(10, 20, conn=conn)
    assert zero and zero["war_started_at"] == 2000
    assert zero["battle_count"] == 0
    fresh = _record(conn, 9003, qty=1)
    assert fresh and fresh["war_started_at"] == 2000
    assert fresh["battle_count"] == 1
    expected = compute_destroyed_raw_from_losses({"sentinel_turret": 1})
    assert int(fresh["attacker"]["score_raw"]) == expected


def test_big_war_score_is_not_limited_to_sqlite_int64() -> None:
    conn = _conn()
    qty = 10**20
    meta = _record(conn, 9900, qty=qty)
    assert meta
    expected = compute_destroyed_raw_from_losses({"sentinel_turret": qty})
    assert expected > 2**63
    assert int(meta["attacker"]["score_raw"]) == expected
    stored = conn.execute(
        "SELECT low_score_raw FROM alliance_war_stats WHERE alliance_id_low = 10 AND alliance_id_high = 20"
    ).fetchone()["low_score_raw"]
    assert isinstance(stored, str)
    assert int(stored) == expected


def test_missing_fleet_id_never_mutates_stats() -> None:
    conn = _conn()
    meta = record_war_combat_report(
        attacker_player_id=1,
        defender_player_id=2,
        attacker_losses={},
        defender_losses={"sentinel_turret": 5},
        result="attacker",
        fleet_id=None,
        conn=conn,
    )
    assert meta and meta["battle_count"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM alliance_war_events").fetchone()["c"] == 0


def test_combat_report_dispatch_and_renderer_are_war_aware() -> None:
    messages_py = Path("game/messages.py").read_text(encoding="utf-8")
    messages_js = Path("static/js/messages.js").read_text(encoding="utf-8")
    assert "record_war_combat_report" in messages_py
    assert 'raw_meta["alliance_war"] = war_meta' in messages_py
    assert "renderAllianceWarPanel" in messages_js
    assert 't("alliance_relation_war", "War")' in messages_js
'''

DOC = r'''# GC-AL-WAR-02 — Alliance War Meta

**Status:** ✅ Implemented on feature branch · Owner: `game/alliance.py` (lifecycle) + `game/alliance_war.py` (derived combat meta)

WAR-02 extends the WAR-01 peace lifecycle with a real campaign scoreboard. It does **not** introduce a second diplomacy or combat engine.

## Rules

- The active war remains authoritative in `alliance_diplomacy`.
- `alliance_diplomacy.updated_at` is the identity/start timestamp of the current war campaign.
- Only battles where both players belong to different alliances whose current relation is `war` count.
- War Score reuses `scoring.compute_destroyed_raw_from_losses()` exactly; there is no second score formula.
- `fleet_id` is the combat-event idempotency key. A retried fleet tick can never add the same battle twice.
- Peace immediately stops new war statistics because the relation is no longer `war`.
- A later declaration between the same alliances gets a new `updated_at`, therefore a fresh 0:0 campaign.
- Score and destroyed-unit totals are persisted as decimal `TEXT`, so values above SQLite signed 64-bit remain exact.

## Schema — migration 155

`alliance_war_stats` stores the current campaign aggregate per normalized alliance pair. `alliance_war_events` stores one immutable combat contribution per `fleet_id` for retry protection and auditability.

Historical event rows keep their `war_started_at`; the hub only reads the campaign matching the currently active relation.

## Combat integration

`messages.dispatch_combat_reports()` enriches the already-authoritative combat report metadata with `alliance_war` before creating attacker/defender inbox rows. The recorder receives the existing combat losses/result/fleet id and never resolves a battle itself.

Combat report UI shows:

- localized WAR badge,
- current War Score for both alliances,
- victories,
- destroyed units,
- total battles and draws.

The Alliance diplomacy tab exposes the same server scoreboard next to each active war.

## Tests

```bash
python -m pytest tests/test_alliance_war_meta.py tests/test_alliance.py tests/test_combat.py -q
```

Critical regressions: canonical score parity, fleet-id idempotency, peace stop, re-war reset, >64-bit scores, report renderer integration.
'''

write("migrations/155_alliance_war_meta.sql", MIGRATION)
write("game/alliance_war.py", WAR_MODULE)
write("tests/test_alliance_war_meta.py", TESTS)
write("docs/GC-AL-WAR-02.md", DOC)

# Alliance hub: enrich only active war rows with the derived scoreboard.
replace_once(
    "game/alliance.py",
    '''    return [dict(r) for r in cur.fetchall()]\n\n\ndef _diplomacy_requests''',
    '''    rows: List[Dict[str, Any]] = []\n    for raw in cur.fetchall():\n        item = dict(raw)\n        if str(item.get("relation") or "") == "war":\n            try:\n                from .alliance_war import get_active_war_stats_for_alliance_pair\n\n                item["war_stats"] = get_active_war_stats_for_alliance_pair(\n                    int(alliance_id), int(item["other_id"]), conn=conn\n                )\n            except Exception:\n                item["war_stats"] = None\n        rows.append(item)\n    return rows\n\n\ndef _diplomacy_requests''',
)

# Combat reports are the canonical integration point: one server result, one fleet id.
replace_once(
    "game/messages.py",
    '''    meta = normalize_combat_metadata(metadata)\n    out: dict[str, Any] = {"attacker": None, "defender": None}\n''',
    '''    raw_meta = dict(metadata or {})\n    if conn is not None:\n        try:\n            from .alliance_war import record_war_combat_report\n\n            war_meta = record_war_combat_report(\n                attacker_player_id=int(attacker_id),\n                defender_player_id=int(defender_id),\n                attacker_losses=raw_meta.get("attacker_losses") or {},\n                defender_losses=raw_meta.get("defender_losses") or {},\n                result=str(raw_meta.get("result") or raw_meta.get("winner") or "undecided"),\n                fleet_id=raw_meta.get("fleet_id"),\n                conn=conn,\n            )\n            if war_meta:\n                raw_meta["alliance_war"] = war_meta\n        except Exception:\n            logger.exception(\n                "alliance war meta persist failed attacker_id=%s defender_id=%s fleet_id=%s",\n                int(attacker_id),\n                int(defender_id),\n                raw_meta.get("fleet_id"),\n            )\n    meta = normalize_combat_metadata(raw_meta)\n    out: dict[str, Any] = {"attacker": None, "defender": None}\n''',
)

# Messages UI: WAR is an additional badge, not a replacement for PvE combat-kind badges.
replace_once(
    "static/js/messages.js",
    '''  function combatKindBadgeHtml(meta) {\n    const kind = String(meta?.combat_kind || "").trim().toLowerCase();\n    if (kind === "world_boss") {\n      return `<span class="gc-combat-kind-badge gc-combat-kind-badge--world-boss">${esc(\n        t("combat_report_kind_world_boss", "World Boss")\n      )}</span>`;\n    }\n    if (kind === "pirate_base") {\n      return `<span class="gc-combat-kind-badge gc-combat-kind-badge--pirate">${esc(\n        t("combat_report_kind_pirate_base", "Pirate base")\n      )}</span>`;\n    }\n    if (kind === "expedition_pirate") {\n      return `<span class="gc-combat-kind-badge gc-combat-kind-badge--pirate">${esc(\n        t("combat_report_kind_expedition_pirate", "Expedition pirates")\n      )}</span>`;\n    }\n    return "";\n  }\n''',
    '''  function combatKindBadgeHtml(meta) {\n    const badges = [];\n    const war = meta?.alliance_war;\n    if (war && war.active) {\n      badges.push(\n        `<span class="gc-combat-kind-badge gc-combat-kind-badge--war">${esc(\n          t("alliance_relation_war", "War")\n        )}</span>`\n      );\n    }\n    const kind = String(meta?.combat_kind || "").trim().toLowerCase();\n    if (kind === "world_boss") {\n      badges.push(`<span class="gc-combat-kind-badge gc-combat-kind-badge--world-boss">${esc(\n        t("combat_report_kind_world_boss", "World Boss")\n      )}</span>`);\n    }\n    if (kind === "pirate_base") {\n      badges.push(`<span class="gc-combat-kind-badge gc-combat-kind-badge--pirate">${esc(\n        t("combat_report_kind_pirate_base", "Pirate base")\n      )}</span>`);\n    }\n    if (kind === "expedition_pirate") {\n      badges.push(`<span class="gc-combat-kind-badge gc-combat-kind-badge--pirate">${esc(\n        t("combat_report_kind_expedition_pirate", "Expedition pirates")\n      )}</span>`);\n    }\n    return badges.join("");\n  }\n''',
)

replace_once(
    "static/js/messages.js",
    '''  function combatCoordsHtml(meta) {''',
    '''  function renderAllianceWarPanel(meta) {\n    const war = meta?.alliance_war;\n    if (!war || !war.active) return "";\n    const attacker = war.attacker || {};\n    const defender = war.defender || {};\n    const side = (entry) => {\n      const tag = String(entry.tag || "").trim();\n      const name = String(entry.name || "").trim();\n      const identity = `${tag ? `[${tag}] ` : ""}${name || "—"}`;\n      return (\n        `<div class="gc-combat-war-side">` +\n          `<span class="gc-combat-war-name">${esc(identity)}</span>` +\n          `<strong class="gc-combat-war-score gc-mono">${esc(formatInt(entry.score_raw || 0))}</strong>` +\n          `<span class="gc-combat-war-meta gc-mono">${esc(t("alliance_war_wins", "Victories"))}: ${esc(\n            formatInt(entry.wins || 0)\n          )} · ${esc(t("alliance_war_destroyed_units", "Destroyed units"))}: ${esc(\n            formatInt(entry.units_destroyed || 0)\n          )}</span>` +\n        `</div>`\n      );\n    };\n    return renderCombatPanel(\n      t("alliance_war_score", "War Score"),\n      `<div class="gc-combat-war-duel">${side(attacker)}<span class="gc-combat-war-vs">VS</span>${side(defender)}</div>` +\n        `<div class="gc-combat-war-summary gc-mono">` +\n          `${esc(t("alliance_war_battles", "Battles"))}: ${esc(formatInt(war.battle_count || 0))} · ` +\n          `${esc(t("alliance_war_draws", "Draws"))}: ${esc(formatInt(war.draws || 0))}` +\n        `</div>`,\n      "gc-combat-report-panel--war"\n    );\n  }\n\n  function combatCoordsHtml(meta) {''',
)

replace_once(
    "static/js/messages.js",
    '''    const expoBattlePanel = renderExpeditionPirateBattlePanel(safeMeta);\n    if (expoBattlePanel) sections.push(expoBattlePanel);\n''',
    '''    const warPanel = renderAllianceWarPanel(safeMeta);\n    if (warPanel) sections.push(warPanel);\n\n    const expoBattlePanel = renderExpeditionPirateBattlePanel(safeMeta);\n    if (expoBattlePanel) sections.push(expoBattlePanel);\n''',
)

# Alliance diplomacy list: compact campaign scoreboard before the peace action.
replace_once(
    "templates/alliance.html",
    '''            {{ alliance_dip_relation(d.relation) }}\n            {% if d.relation == 'war' and st.can_manage %}\n''',
    '''            {{ alliance_dip_relation(d.relation) }}\n            {% if d.relation == 'war' and d.war_stats %}\n            {% set ws = d.war_stats %}\n            <div class="alliance-hub-war-meta">\n              <div class="alliance-hub-war-scoreline gc-mono">\n                <span>{{ T("alliance_war_score", "War Score") }}</span>\n                <strong>{{ ws.self.score_raw|fmt_int }}</strong>\n                <span>:</span>\n                <strong>{{ ws.other.score_raw|fmt_int }}</strong>\n              </div>\n              <div class="alliance-hub-war-detail gc-mono">\n                <span>{{ T("alliance_war_battles", "Gefechte") }}: {{ ws.battle_count|fmt_int }}</span>\n                <span>{{ T("alliance_war_wins", "Siege") }}: {{ ws.self.wins|fmt_int }} : {{ ws.other.wins|fmt_int }}</span>\n                <span>{{ T("alliance_war_destroyed_units", "Zerstörte Einheiten") }}: {{ ws.self.units_destroyed|fmt_int }} : {{ ws.other.units_destroyed|fmt_int }}</span>\n                {% if ws.draws %}<span>{{ T("alliance_war_draws", "Unentschieden") }}: {{ ws.draws|fmt_int }}</span>{% endif %}\n              </div>\n            </div>\n            {% endif %}\n            {% if d.relation == 'war' and st.can_manage %}\n''',
)

CSS = r'''
/* GC-AL-WAR-02 — alliance campaign score + combat report marker */
.alliance-hub-war-meta {
  flex: 1 1 100%;
  min-width: min(100%, 28rem);
  padding: .55rem .7rem;
  border: 1px solid color-mix(in srgb, var(--gc-danger, #ff5a6f) 35%, transparent);
  border-radius: .55rem;
  background: color-mix(in srgb, var(--gc-danger, #ff5a6f) 8%, transparent);
}
.alliance-hub-war-scoreline,
.alliance-hub-war-detail {
  display: flex;
  flex-wrap: wrap;
  gap: .35rem .65rem;
  align-items: center;
}
.alliance-hub-war-scoreline strong { font-size: 1.05rem; }
.alliance-hub-war-detail { margin-top: .3rem; opacity: .78; font-size: .78rem; }
.gc-combat-kind-badge--war {
  border-color: color-mix(in srgb, var(--gc-danger, #ff5a6f) 62%, transparent);
  background: color-mix(in srgb, var(--gc-danger, #ff5a6f) 14%, transparent);
}
.gc-combat-war-duel {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  gap: .75rem;
  align-items: center;
}
.gc-combat-war-side { display: grid; gap: .25rem; min-width: 0; }
.gc-combat-war-side:last-child { text-align: right; }
.gc-combat-war-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.gc-combat-war-score { font-size: 1.2rem; }
.gc-combat-war-meta, .gc-combat-war-summary { font-size: .78rem; opacity: .78; }
.gc-combat-war-vs { opacity: .55; font-weight: 800; }
.gc-combat-war-summary { margin-top: .75rem; text-align: center; }
@media (max-width: 620px) {
  .gc-combat-war-duel { grid-template-columns: 1fr; }
  .gc-combat-war-vs { text-align: center; }
  .gc-combat-war-side:last-child { text-align: left; }
}
'''
append_once("static/style.css", "GC-AL-WAR-02 — alliance campaign score", CSS)

# Locale parity without reformatting the existing JSON files.
translations = {
    "de": {
        "alliance_war_score": "Kriegs-Score",
        "alliance_war_battles": "Gefechte",
        "alliance_war_destroyed_units": "Zerstörte Einheiten",
        "alliance_war_wins": "Siege",
        "alliance_war_draws": "Unentschieden",
        "alliance_war_since": "Krieg seit",
    },
    "en": {
        "alliance_war_score": "War Score",
        "alliance_war_battles": "Battles",
        "alliance_war_destroyed_units": "Destroyed units",
        "alliance_war_wins": "Victories",
        "alliance_war_draws": "Draws",
        "alliance_war_since": "War since",
    },
    "fr": {
        "alliance_war_score": "Score de guerre",
        "alliance_war_battles": "Batailles",
        "alliance_war_destroyed_units": "Unités détruites",
        "alliance_war_wins": "Victoires",
        "alliance_war_draws": "Matchs nuls",
        "alliance_war_since": "Guerre depuis",
    },
    "es": {
        "alliance_war_score": "Puntuación de guerra",
        "alliance_war_battles": "Batallas",
        "alliance_war_destroyed_units": "Unidades destruidas",
        "alliance_war_wins": "Victorias",
        "alliance_war_draws": "Empates",
        "alliance_war_since": "Guerra desde",
    },
    "pl": {
        "alliance_war_score": "Wynik wojenny",
        "alliance_war_battles": "Bitwy",
        "alliance_war_destroyed_units": "Zniszczone jednostki",
        "alliance_war_wins": "Zwycięstwa",
        "alliance_war_draws": "Remisy",
        "alliance_war_since": "Wojna od",
    },
    "tr": {
        "alliance_war_score": "Savaş Skoru",
        "alliance_war_battles": "Muharebeler",
        "alliance_war_destroyed_units": "Yok edilen birimler",
        "alliance_war_wins": "Zaferler",
        "alliance_war_draws": "Beraberlikler",
        "alliance_war_since": "Savaş başlangıcı",
    },
    "ru": {
        "alliance_war_score": "Военный счёт",
        "alliance_war_battles": "Бои",
        "alliance_war_destroyed_units": "Уничтоженные юниты",
        "alliance_war_wins": "Победы",
        "alliance_war_draws": "Ничьи",
        "alliance_war_since": "Война с",
    },
    "pt": {
        "alliance_war_score": "Pontuação de guerra",
        "alliance_war_battles": "Batalhas",
        "alliance_war_destroyed_units": "Unidades destruídas",
        "alliance_war_wins": "Vitórias",
        "alliance_war_draws": "Empates",
        "alliance_war_since": "Guerra desde",
    },
}
for locale, additions in translations.items():
    path = f"locales/{locale}.json"
    text = read(path)
    current = json.loads(text)
    if all(key in current for key in additions):
        continue
    missing = {key: value for key, value in additions.items() if key not in current}
    closing = text.rfind("\n}")
    if closing < 0:
        raise RuntimeError(f"{path}: closing object marker not found")
    payload = ",\n" + ",\n".join(
        f"  {json.dumps(key, ensure_ascii=False)}: {json.dumps(value, ensure_ascii=False)}"
        for key, value in missing.items()
    )
    updated = text[:closing] + payload + text[closing:]
    json.loads(updated)
    write(path, updated)

# Master docs reality-sync.
replace_once(
    "docs/ALLIANCE_SYSTEM.md",
    "**Status:** ✅ **MVP complete** (GC-AL-MVP-01 … GC-AL-MVP-09) + **UX-Pass** (GC-AL-UX-01…03) + **GC-AL-DIP-01** (Fleet Mission Hooks) + **GC-AL-WAR-01** (Peace Workflow). Kriegs-Score / Report-Meta folgt separat.",
    "**Status:** ✅ **MVP complete** (GC-AL-MVP-01 … GC-AL-MVP-09) + **UX-Pass** (GC-AL-UX-01…03) + **GC-AL-DIP-01** (Fleet Mission Hooks) + **GC-AL-WAR-01** (Peace Workflow) + **GC-AL-WAR-02** (War Score / Combat Meta).",
)
replace_once(
    "docs/ALLIANCE_SYSTEM.md",
    "- **Follow-up:** Combat Kriegs-Meta (Reports/Score/Badges) als GC-AL-WAR-02.",
    "- **GC-AL-WAR-02:** aktive Kriege führen eine serverseitige Kampagnenstatistik (War Score aus kanonischem Destroyed-Raw, zerstörte Einheiten, Siege/Gefechte/Unentschieden). `fleet_id` dedupliziert Combat-Retries; Frieden stoppt sofort, Re-War startet bei 0. Combat Reports tragen sichtbare WAR-Meta/Badges.",
)
replace_once(
    "docs/ALLIANCE_SYSTEM.md",
    "## Schema (Migration 088–092)",
    "## Schema (Migration 088–092, 155)",
)
replace_once(
    "docs/ALLIANCE_SYSTEM.md",
    "- **092:** Partial unique indexes (active project, pending diplomacy, pending application per player)",
    "- **092:** Partial unique indexes (active project, pending diplomacy, pending application per player)\n- **155:** `alliance_war_stats` + `alliance_war_events` (Big-Score-safe TEXT aggregates, `fleet_id` idempotency)",
)
replace_once(
    "docs/ALLIANCE_SYSTEM.md",
    "python -m pytest tests/test_alliance.py -q",
    "python -m pytest tests/test_alliance.py tests/test_alliance_war_meta.py -q",
)

append_once(
    "docs/COMBAT_SYSTEM.md",
    "GC-AL-WAR-02 — Alliance war meta",
    '''### GC-AL-WAR-02 — Alliance war meta\n\nPvP-Attack reports call the derived `game/alliance_war.py` recorder through `messages.dispatch_combat_reports()`. Only an active `alliance_diplomacy.relation = 'war'` counts. War Score reuses `compute_destroyed_raw_from_losses()`; `fleet_id` is the idempotency key. The returned `alliance_war` metadata powers the localized WAR badge and campaign score panel in `static/js/messages.js`. Combat resolution itself remains unchanged.''',
)

print("WAR-02 patch applied")
