"""World-map colonization persistence (GC-582A). Claims only — fleet/planet bind in 582B+."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, Optional, Tuple

from ..db import table_exists
from .sector_grid import sector_coords
from .strategic_worlds import strategic_world_type_for_coords

WORLD_KEY_PREFIX = "field"
CLAIM_STATUS_RESERVED = "reserved"
CLAIM_STATUS_CLAIMED = "claimed"

COLONIZABLE_WORLD_TYPES: Tuple[str, ...] = (
    "mining_world",
    "industrial_world",
    "research_world",
    "fortress_world",
    "trade_world",
)

EXPEDITION_WORLD_TYPES: Tuple[str, ...] = (
    "expedition_zone",
    "anomaly_zone",
    "ruins_world",
)

# Reserved for future map targets not yet playable.
PREPARED_EXPEDITION_WORLD_TYPES: Tuple[str, ...] = ()

SALVAGE_WORLD_TYPES: Tuple[str, ...] = (
    "wreckage_field",
)


class WorldKeyError(ValueError):
    """Invalid strategic world key format."""


class WorldColonizationError(ValueError):
    """World colonization validation failed."""


def world_colonization_schema_ready(*, conn: sqlite3.Connection) -> bool:
    if not table_exists(conn, "world_claims"):
        return False
    cols = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(planets);").fetchall()
    }
    required = {
        "world_key",
        "world_x",
        "world_y",
        "sector_x",
        "sector_y",
        "planet_role",
        "origin_world_key",
    }
    return required.issubset(cols)


def build_world_key(
    world_x: float,
    world_y: float,
    *,
    world_type: Optional[str] = None,
) -> str:
    """Canonical strategic world key — matches Command Map `node_key`."""
    wx = float(world_x)
    wy = float(world_y)
    wt = str(world_type or strategic_world_type_for_coords(wx, wy))
    return f"{WORLD_KEY_PREFIX}:{wt}:{int(wx)}:{int(wy)}"


def parse_world_key(world_key: str) -> Dict[str, Any]:
    """Parse `field:{world_type}:{int_x}:{int_y}`."""
    raw = str(world_key or "").strip()
    parts = raw.split(":")
    if len(parts) != 4 or parts[0] != WORLD_KEY_PREFIX:
        raise WorldKeyError("invalid_world_key")
    try:
        world_x = float(parts[2])
        world_y = float(parts[3])
    except (TypeError, ValueError) as exc:
        raise WorldKeyError("invalid_world_key_coords") from exc
    world_type = str(parts[1] or "").strip()
    if not world_type:
        raise WorldKeyError("invalid_world_key_type")
    sector_x, sector_y = sector_coords(world_x, world_y)
    return {
        "world_key": raw,
        "world_type": world_type,
        "planet_role": world_type,
        "world_x": world_x,
        "world_y": world_y,
        "sector_x": int(sector_x),
        "sector_y": int(sector_y),
    }


def is_colonizable_world_type(world_type: str) -> bool:
    return str(world_type or "") in COLONIZABLE_WORLD_TYPES


def is_expedition_world_type(world_type: str) -> bool:
    return str(world_type or "") in EXPEDITION_WORLD_TYPES


def is_prepared_expedition_world_type(world_type: str) -> bool:
    return str(world_type or "") in PREPARED_EXPEDITION_WORLD_TYPES


def is_salvage_world_type(world_type: str) -> bool:
    return str(world_type or "") in SALVAGE_WORLD_TYPES


def get_claim_by_world_key(
    world_key: str,
    *,
    conn: sqlite3.Connection,
) -> Optional[Dict[str, Any]]:
    if not world_colonization_schema_ready(conn=conn):
        return None
    row = conn.execute(
        """
        SELECT world_key, player_id, planet_id, world_x, world_y,
               sector_x, sector_y, planet_role, status, reserved_at, claimed_at
        FROM world_claims
        WHERE world_key = ?;
        """,
        (str(world_key),),
    ).fetchone()
    return dict(row) if row else None


def is_world_claimed(
    world_key: str,
    *,
    conn: sqlite3.Connection,
) -> bool:
    return get_claim_by_world_key(world_key, conn=conn) is not None


def check_colony_limit_available(
    player_id: int,
    *,
    conn: sqlite3.Connection,
) -> Tuple[bool, str]:
    """Return whether the player may found another colony."""
    if not evolution_schema_ready(conn):
        return False, "schema_missing"
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) AS c FROM planets WHERE player_id = ? AND is_homeworld = 0;",
        (int(player_id),),
    )
    colonies = int(cur.fetchone()["c"])
    try:
        from ..models import get_game_settings

        settings = get_game_settings(conn=conn)
        max_col = int(settings.get("max_colonies_per_player", 9))
    except Exception:
        max_col = 9
    if colonies >= max_col:
        return False, "colony_limit_reached"
    return True, ""


def evolution_schema_ready(conn: sqlite3.Connection) -> bool:
    from .repository import evolution_schema_ready as _ready

    return _ready(conn)


def validate_world_colonize_target(
    world_key: str,
    *,
    conn: sqlite3.Connection,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Validate strategic world colonize target before fleet send/arrival."""
    if not world_colonization_schema_ready(conn=conn):
        return False, "schema_missing", {}
    try:
        parsed = parse_world_key(world_key)
    except WorldKeyError:
        return False, "invalid_world_key", {}
    expected_type = strategic_world_type_for_coords(parsed["world_x"], parsed["world_y"])
    if parsed["world_type"] != expected_type:
        return False, "invalid_world_key", {}
    if not is_colonizable_world_type(parsed["world_type"]):
        return False, "world_not_colonizable", {}
    if is_world_claimed(parsed["world_key"], conn=conn):
        return False, "world_already_claimed", {}
    from .strategic_worlds import build_strategic_world_presentation

    presentation = build_strategic_world_presentation(
        parsed["world_x"],
        parsed["world_y"],
        world_type=parsed["world_type"],
    )
    return True, "", {
        "target_type": "strategic_world",
        "target_planet_id": None,
        "target_player_id": None,
        "target_owner_name": None,
        "world_key": parsed["world_key"],
        "world_x": parsed["world_x"],
        "world_y": parsed["world_y"],
        "sector_x": parsed["sector_x"],
        "sector_y": parsed["sector_y"],
        "planet_role": parsed["planet_role"],
        "coords": parsed["world_key"],
        "allowed_missions": ["colonize"],
        "reason_if_blocked": None,
        "strategic_world": presentation,
    }


def build_world_colonize_preview(
    player_id: int,
    world_key: str,
    *,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    """Presentation-only colonize preview for Command Map → Fleet (GC-582C)."""
    from .strategic_worlds import build_strategic_world_presentation

    wk = str(world_key or "").strip()
    presentation: Dict[str, Any] = {}
    target_info: Dict[str, Any] = {}
    ok_target, reason, target_info = validate_world_colonize_target(wk, conn=conn)
    try:
        parsed = parse_world_key(wk)
        presentation = build_strategic_world_presentation(
            parsed["world_x"],
            parsed["world_y"],
            world_type=parsed["world_type"],
        )
    except WorldKeyError:
        ok_target = False
        reason = reason or "invalid_world_key"

    ok_limit, limit_reason = check_colony_limit_available(int(player_id), conn=conn)
    block_reason = ""
    if not ok_target:
        block_reason = reason or "invalid_world_key"
    elif not ok_limit:
        block_reason = limit_reason or "colony_limit_reached"

    return {
        "world_key": wk,
        "can_colonize": bool(ok_target and ok_limit),
        "block_reason": block_reason or None,
        "target": target_info,
        "presentation": presentation,
    }


def validate_world_expedition_target(
    world_key: str,
    *,
    conn: sqlite3.Connection,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Validate strategic world expedition target before fleet send/arrival (GC-583A)."""
    if not world_colonization_schema_ready(conn=conn):
        return False, "schema_missing", {}
    try:
        parsed = parse_world_key(world_key)
    except WorldKeyError:
        return False, "invalid_world_key", {}
    expected_type = strategic_world_type_for_coords(parsed["world_x"], parsed["world_y"])
    if parsed["world_type"] != expected_type:
        return False, "invalid_world_key", {}
    if is_prepared_expedition_world_type(parsed["world_type"]):
        return False, "world_expedition_not_available", {}
    if not is_expedition_world_type(parsed["world_type"]):
        return False, "world_not_expedition", {}
    from .strategic_worlds import build_strategic_world_presentation

    presentation = build_strategic_world_presentation(
        parsed["world_x"],
        parsed["world_y"],
        world_type=parsed["world_type"],
    )
    return True, "", {
        "target_type": "strategic_world",
        "target_planet_id": None,
        "target_player_id": None,
        "target_owner_name": None,
        "world_key": parsed["world_key"],
        "world_x": parsed["world_x"],
        "world_y": parsed["world_y"],
        "sector_x": parsed["sector_x"],
        "sector_y": parsed["sector_y"],
        "planet_role": parsed["planet_role"],
        "coords": parsed["world_key"],
        "allowed_missions": ["expedition"],
        "reason_if_blocked": None,
        "strategic_world": presentation,
    }


def build_world_expedition_preview(
    player_id: int,
    world_key: str,
    *,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    """Presentation-only expedition preview for Command Map → Fleet (GC-583A)."""
    from .strategic_worlds import build_strategic_world_presentation

    wk = str(world_key or "").strip()
    presentation: Dict[str, Any] = {}
    target_info: Dict[str, Any] = {}
    ok_target, reason, target_info = validate_world_expedition_target(wk, conn=conn)
    try:
        parsed = parse_world_key(wk)
        presentation = build_strategic_world_presentation(
            parsed["world_x"],
            parsed["world_y"],
            world_type=parsed["world_type"],
        )
    except WorldKeyError:
        ok_target = False
        reason = reason or "invalid_world_key"

    block_reason = ""
    if not ok_target:
        block_reason = reason or "invalid_world_key"

    return {
        "world_key": wk,
        "can_expedition": bool(ok_target),
        "block_reason": block_reason or None,
        "target": target_info,
        "presentation": presentation,
    }


def _count_player_expedition_ships(player_id: int, *, conn: sqlite3.Connection) -> int:
    from ..expedition_events import count_expedition_ships
    from ..fleet import get_planet_ships
    from .repository import get_context_planet

    planet = get_context_planet(int(player_id), conn=conn)
    if not planet:
        return 0
    ships = get_planet_ships(int(planet["id"]), conn=conn) or {}
    return int(count_expedition_ships(ships))


def validate_world_salvage_target(
    world_key: str,
    *,
    conn: sqlite3.Connection,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Validate strategic wreckage/salvage target before fleet send/arrival (GC-584)."""
    if not world_colonization_schema_ready(conn=conn):
        return False, "schema_missing", {}
    try:
        parsed = parse_world_key(world_key)
    except WorldKeyError:
        return False, "invalid_world_key", {}
    expected_type = strategic_world_type_for_coords(parsed["world_x"], parsed["world_y"])
    if parsed["world_type"] != expected_type:
        return False, "invalid_world_key", {}
    if not is_salvage_world_type(parsed["world_type"]):
        return False, "world_not_salvage", {}
    from .strategic_worlds import build_strategic_world_presentation

    presentation = build_strategic_world_presentation(
        parsed["world_x"],
        parsed["world_y"],
        world_type=parsed["world_type"],
    )
    return True, "", {
        "target_type": "strategic_world",
        "target_planet_id": None,
        "target_player_id": None,
        "target_owner_name": None,
        "world_key": parsed["world_key"],
        "world_x": parsed["world_x"],
        "world_y": parsed["world_y"],
        "sector_x": parsed["sector_x"],
        "sector_y": parsed["sector_y"],
        "planet_role": parsed["planet_role"],
        "coords": parsed["world_key"],
        "allowed_missions": ["expedition"],
        "reason_if_blocked": None,
        "strategic_world": presentation,
    }


def build_world_salvage_preview(
    player_id: int,
    world_key: str,
    *,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    """Presentation-only salvage preview for Command Map → Fleet (GC-584)."""
    from .strategic_worlds import build_strategic_world_presentation

    wk = str(world_key or "").strip()
    presentation: Dict[str, Any] = {}
    target_info: Dict[str, Any] = {}
    ok_target, reason, target_info = validate_world_salvage_target(wk, conn=conn)
    try:
        parsed = parse_world_key(wk)
        presentation = build_strategic_world_presentation(
            parsed["world_x"],
            parsed["world_y"],
            world_type=parsed["world_type"],
        )
    except WorldKeyError:
        ok_target = False
        reason = reason or "invalid_world_key"

    ship_count = _count_player_expedition_ships(int(player_id), conn=conn) if ok_target else 0
    has_ships = ship_count > 0
    block_reason = ""
    if not ok_target:
        block_reason = reason or "invalid_world_key"
    elif not has_ships:
        block_reason = "no_expedition_ships"

    return {
        "world_key": wk,
        "can_salvage": bool(ok_target),
        "can_start_salvage": bool(ok_target and has_ships),
        "has_salvage_ships": has_ships,
        "expedition_ship_count": ship_count,
        "block_reason": block_reason or None,
        "target": target_info,
        "presentation": presentation,
    }


def complete_world_claim(
    world_key: str,
    player_id: int,
    planet_id: int,
    *,
    conn: sqlite3.Connection,
) -> Tuple[bool, str]:
    """Attach a newly founded planet to a reserved world claim."""
    if not world_colonization_schema_ready(conn=conn):
        return False, "schema_missing"
    now = time.time()
    cur = conn.execute(
        """
        UPDATE world_claims
        SET planet_id = ?, status = ?, claimed_at = ?
        WHERE world_key = ? AND player_id = ? AND status = ?;
        """,
        (
            int(planet_id),
            CLAIM_STATUS_CLAIMED,
            now,
            str(world_key),
            int(player_id),
            CLAIM_STATUS_RESERVED,
        ),
    )
    if int(cur.rowcount or 0) != 1:
        return False, "world_claim_not_found"
    conn.execute(
        """
        UPDATE planets
        SET world_key = ?, origin_world_key = ?
        WHERE id = ? AND player_id = ?;
        """,
        (str(world_key), str(world_key), int(planet_id), int(player_id)),
    )
    return True, "ok"


def release_world_claim(
    world_key: str,
    *,
    conn: sqlite3.Connection,
    player_id: Optional[int] = None,
) -> None:
    """Drop a reserved claim after failed colonization."""
    if player_id is not None:
        conn.execute(
            """
            DELETE FROM world_claims
            WHERE world_key = ? AND player_id = ? AND status = ?;
            """,
            (str(world_key), int(player_id), CLAIM_STATUS_RESERVED),
        )
    else:
        conn.execute(
            """
            DELETE FROM world_claims
            WHERE world_key = ? AND status = ?;
            """,
            (str(world_key), CLAIM_STATUS_RESERVED),
        )


def reserve_world_claim(
    player_id: int,
    world_x: float,
    world_y: float,
    *,
    conn: sqlite3.Connection,
    world_type: Optional[str] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Reserve a colonizable strategic world for a player (582A — no planet yet)."""
    if not world_colonization_schema_ready(conn=conn):
        return False, "schema_missing", None

    wx = float(world_x)
    wy = float(world_y)
    wt = str(world_type or strategic_world_type_for_coords(wx, wy))
    if not is_colonizable_world_type(wt):
        return False, "world_not_colonizable", None

    world_key = build_world_key(wx, wy, world_type=wt)
    if is_world_claimed(world_key, conn=conn):
        return False, "world_already_claimed", None

    sector_x, sector_y = sector_coords(wx, wy)
    now = time.time()
    try:
        conn.execute(
            """
            INSERT INTO world_claims (
                world_key, player_id, planet_id,
                world_x, world_y, sector_x, sector_y, planet_role,
                status, reserved_at, claimed_at
            ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, NULL);
            """,
            (
                world_key,
                int(player_id),
                wx,
                wy,
                int(sector_x),
                int(sector_y),
                wt,
                CLAIM_STATUS_RESERVED,
                now,
            ),
        )
    except sqlite3.IntegrityError:
        return False, "world_already_claimed", None

    payload = {
        "world_key": world_key,
        "player_id": int(player_id),
        "world_x": wx,
        "world_y": wy,
        "sector_x": int(sector_x),
        "sector_y": int(sector_y),
        "planet_role": wt,
        "status": CLAIM_STATUS_RESERVED,
        "reserved_at": now,
    }
    return True, "ok", payload


NEWLY_COLONIZED_SECONDS = 7 * 86400


def is_newly_colonized_world(claimed_at: Any, *, now: Optional[float] = None) -> bool:
    """True when a world claim was completed within the polish window (GC-582F)."""
    ts = float(claimed_at or 0)
    if ts <= 0:
        return False
    ref = float(now if now is not None else time.time())
    return (ref - ts) <= NEWLY_COLONIZED_SECONDS


def colonize_fail_reason_label(reason: str, *, locale: str | None = None) -> str:
    """Localized colonization failure reason (never raw error codes in inbox)."""
    from ..i18n import tr

    key = str(reason or "generic").strip().lower()
    return tr(
        f"fleet_colonize_fail_{key}",
        tr(
            "fleet_colonize_fail_generic",
            "The colony could not be established.",
            locale=locale,
        ),
        locale=locale,
    )


def format_world_key_display(world_key: str, *, locale: str | None = None) -> str:
    """Human-readable world label for inbox reports, e.g. Mining World [1520:2480]."""
    from ..i18n import tr
    from .strategic_worlds import build_strategic_world_presentation_from_key

    wk = str(world_key or "").strip()
    try:
        parsed = parse_world_key(wk)
        world = build_strategic_world_presentation_from_key(wk)
        name = tr(str(world["name_key"]), str(world["name_key"]), locale=locale)
        coords = f"{int(parsed['world_x'])}:{int(parsed['world_y'])}"
        return tr(
            "messages_world_display",
            "%(name)s [%(coords)s]",
            locale=locale,
            name=name,
            coords=coords,
        )
    except WorldKeyError:
        return wk


def build_world_colonize_report(
    world_key: str,
    colony_name: str,
    *,
    locale: str | None = None,
    success: bool = True,
    fail_reason: str | None = None,
) -> Tuple[str, str, Dict[str, Any]]:
    """Structured colonization report for world_key targets (GC-582F)."""
    from ..i18n import tr
    from .strategic_worlds import build_strategic_world_presentation_from_key

    wk = str(world_key or "").strip()
    world = build_strategic_world_presentation_from_key(wk)
    world_name = tr(str(world["name_key"]), str(world["name_key"]), locale=locale)
    type_label = tr(str(world["type_key"]), str(world["type_key"]), locale=locale)
    name = str(colony_name or "").strip() or world_name

    metadata: Dict[str, Any] = {
        "report_kind": "world_colonize",
        "mission_type": "colonize",
        "world_key": wk,
        "world_name_key": str(world["name_key"]),
        "world_type_key": str(world["type_key"]),
        "world_role_icon": str(world.get("role_icon") or ""),
        "colony_name": name,
    }

    if success:
        subject = tr(
            "fleet_report_colonize_success_subject_world",
            "New colony founded — %(world)s",
            locale=locale,
            world=world_name,
        )
        body = "\n".join(
            [
                tr("fleet_world_colonize_report_headline", "New colony founded", locale=locale),
                tr(
                    "fleet_world_colonize_report_location",
                    "Location: %(world)s",
                    locale=locale,
                    world=world_name,
                ),
                tr(
                    "fleet_world_colonize_report_type",
                    "Type: %(type)s",
                    locale=locale,
                    type=type_label,
                ),
                tr(
                    "fleet_world_colonize_report_colony",
                    "Colony: %(name)s",
                    locale=locale,
                    name=name,
                ),
                tr(
                    "fleet_world_colonize_report_world_key",
                    "World: %(world)s",
                    locale=locale,
                    world=format_world_key_display(wk, locale=locale),
                ),
            ]
        )
        metadata["success"] = True
        return subject, body, metadata

    reason = str(fail_reason or "generic")
    reason_text = colonize_fail_reason_label(reason, locale=locale)
    world_display = format_world_key_display(wk, locale=locale)
    subject = tr(
        "fleet_report_colonize_failed_subject_world",
        "Colonization failed — %(world)s",
        locale=locale,
        world=world_name,
    )
    body = "\n".join(
        [
            tr(
                "fleet_world_colonize_report_failed_headline",
                "Colony could not be founded.",
                locale=locale,
            ),
            "",
            reason_text,
            "",
            tr("fleet_world_colonize_report_world_label", "World:", locale=locale),
            world_display,
        ]
    )
    metadata["success"] = False
    metadata["reason"] = reason
    return subject, body, metadata
