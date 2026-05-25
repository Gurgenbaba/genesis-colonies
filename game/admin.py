# game/admin.py
"""
Admin-Logik für Genesis Colonies.

Bündelt alles, was das Admin Control Center braucht:
- Universums-/Server-Settings (Speed, Queue-Limit, Startressourcen, Name, MOTD)
- Ressourcen-Tools (Overflow, optional für alle Spieler)
- Universe-Wipe (Planeten/Forschung/Queues zurücksetzen, Accounts bleiben)
- Ban / Unban von Spielern + Übersicht der aktiven Banns

WICHTIG:
- Nutzt zentrale DB-Helper aus game.models
- Multi-User safe
- Best-Effort bei optionalen Tabellen (bans/messages/logs/etc.)
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Optional

from .models import (
    db,
    get_game_settings,
    save_game_settings,
    adjust_homeworld_resources,
    ensure_player_and_homeworld,
)


# =============================================================================
# Helpers
# =============================================================================

def _ensure_admin_defaults(settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    Gibt ein Dict zurück, das alle Felder enthält, die admin_panel.html erwartet.
    """
    defaults: Dict[str, Any] = {
        "universe_name": "Genesis Colonies",
        "galaxy_count": 1,
        "queue_limit": 3,
        "research_queue_limit": 3,

        "production_speed": 1.0,
        "build_speed": 1.0,
        "research_speed": 1.0,

        "fleet_speed_war": 1.0,
        "fleet_speed_holding": 1.0,
        "fleet_speed_peaceful": 1.0,

        "start_metal": 0,
        "start_crystal": 0,

        "motd_text": "",
        "motd_enabled": 0,
    }

    merged = dict(defaults)
    for k, v in (settings or {}).items():
        merged[k] = v
    return merged


def _parse_int(raw: Any, default: Optional[int] = None) -> Optional[int]:
    if raw is None:
        return default
    s = str(raw).strip()
    if not s:
        return default
    try:
        return int(s.replace(" ", ""))
    except ValueError:
        return default


def _parse_float(raw: Any, default: Optional[float] = None) -> Optional[float]:
    if raw is None:
        return default
    s = str(raw).strip()
    if not s:
        return default
    try:
        return float(s.replace(" ", "").replace(",", "."))
    except ValueError:
        return default


def _table_exists(cur: sqlite3.Cursor, name: str) -> bool:
    try:
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=? LIMIT 1;",
            (name,),
        )
        return cur.fetchone() is not None
    except Exception:
        return False


def _fmt_ts(ts: Optional[int]) -> str:
    if not ts:
        return "-"
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ts)))
    except (OverflowError, OSError, ValueError, TypeError):
        return "-"


# =============================================================================
# 1) Settings laden / speichern
# =============================================================================

def get_admin_settings() -> Dict[str, Any]:
    """
    Wird vom admin_panel aufgerufen.
    Liefert ein vollständiges Settings-Dict mit allen erwarteten Feldern.
    """
    current = get_game_settings() or {}
    if not isinstance(current, dict):
        current = dict(current)

    s = _ensure_admin_defaults(current)

    # motd_enabled zu 0/1 normalisieren (Checkbox-Handling)
    try:
        s["motd_enabled"] = 1 if int(s.get("motd_enabled", 0) or 0) != 0 else 0
    except (TypeError, ValueError):
        s["motd_enabled"] = 0

    return s


def update_admin_settings(form: Dict[str, Any]) -> None:
    """
    Universums-Einstellungen aus dem Admin-Formular übernehmen und speichern.

    Zusätzlich:
    - MOTD-Text & Enable-Flag
    - Optional: Startressourcen als Mindestwert auf alle Homeworlds anwenden
    """
    current = get_game_settings() or {}
    if not isinstance(current, dict):
        current = dict(current)

    new_settings = dict(current)

    # ------------------- Strings -------------------
    universe_name = str(form.get("universe_name") or "").strip() or "Genesis Colonies"
    new_settings["universe_name"] = universe_name

    # ------------------- Integers -------------------
    gal_count = _parse_int(form.get("galaxy_count"))
    if gal_count is not None and gal_count > 0:
        new_settings["galaxy_count"] = gal_count

    queue_limit = _parse_int(form.get("queue_limit"))
    if queue_limit is not None and queue_limit > 0:
        new_settings["queue_limit"] = queue_limit

    research_queue_limit = _parse_int(form.get("research_queue_limit"))
    if research_queue_limit is not None and research_queue_limit > 0:
        new_settings["research_queue_limit"] = research_queue_limit

    start_metal = _parse_int(form.get("start_metal"))
    if start_metal is not None and start_metal >= 0:
        new_settings["start_metal"] = start_metal

    start_crystal = _parse_int(form.get("start_crystal"))
    if start_crystal is not None and start_crystal >= 0:
        new_settings["start_crystal"] = start_crystal

    # ------------------- Floats -------------------
    prod_speed = _parse_float(form.get("production_speed"))
    if prod_speed is not None and prod_speed > 0:
        new_settings["production_speed"] = prod_speed

    build_speed = _parse_float(form.get("build_speed"))
    if build_speed is not None and build_speed > 0:
        new_settings["build_speed"] = build_speed

    research_speed = _parse_float(form.get("research_speed"))
    if research_speed is not None and research_speed > 0:
        new_settings["research_speed"] = research_speed

    fleet_war = _parse_float(form.get("fleet_speed_war"))
    if fleet_war is not None and fleet_war > 0:
        new_settings["fleet_speed_war"] = fleet_war

    fleet_hold = _parse_float(form.get("fleet_speed_holding"))
    if fleet_hold is not None and fleet_hold > 0:
        new_settings["fleet_speed_holding"] = fleet_hold

    fleet_peace = _parse_float(form.get("fleet_speed_peaceful"))
    if fleet_peace is not None and fleet_peace > 0:
        new_settings["fleet_speed_peaceful"] = fleet_peace

    # ------------------- MOTD -------------------
    motd_text = str(form.get("motd_text") or "").strip()
    motd_enabled = (form.get("motd_enabled") == "1") and bool(motd_text)

    new_settings["motd_text"] = motd_text  # auch leer speichern -> löscht korrekt
    new_settings["motd_enabled"] = 1 if motd_enabled else 0

    # ------------------- Apply start resources to existing (minimum) -------------------
    apply_start_flag = form.get("apply_start_to_existing") == "1"
    if apply_start_flag:
        sm = int(new_settings.get("start_metal", 0) or 0)
        sc = int(new_settings.get("start_crystal", 0) or 0)

        if sm > 0 or sc > 0:
            conn = db()
            try:
                cur = conn.cursor()
                if sm > 0:
                    cur.execute(
                        """
                        UPDATE planets
                           SET metal = CASE
                               WHEN metal < ? THEN ?
                               ELSE metal
                           END
                         WHERE is_homeworld = 1;
                        """,
                        (sm, sm),
                    )
                if sc > 0:
                    cur.execute(
                        """
                        UPDATE planets
                           SET crystal = CASE
                               WHEN crystal < ? THEN ?
                               ELSE crystal
                           END
                         WHERE is_homeworld = 1;
                        """,
                        (sc, sc),
                    )
                conn.commit()
            finally:
                conn.close()

    save_game_settings(new_settings)


# =============================================================================
# 2) Ressourcen-Tools (Overflow)
# =============================================================================

def handle_resource_tools(form: Dict[str, Any], current_user_id: Optional[int]) -> None:
    """
    Verteilt Metall / Crytite auf Homeworlds.

    Felder:
      - metal_delta: "100000" oder "-50000"
      - crystal_delta
      - resource_player_id (optional)
      - resource_apply_all = "1" -> alle Homeworlds

    Nutzt adjust_homeworld_resources:
      - player_id=None  -> alle Homeworlds
      - player_id=int   -> Homeworld dieses Spielers
    """
    raw_m = str(form.get("metal_delta") or "").replace(" ", "").strip()
    raw_c = str(form.get("crystal_delta") or "").replace(" ", "").strip()

    try:
        metal_delta = int(raw_m) if raw_m else 0
    except ValueError:
        metal_delta = 0

    try:
        crystal_delta = int(raw_c) if raw_c else 0
    except ValueError:
        crystal_delta = 0

    if metal_delta == 0 and crystal_delta == 0:
        return

    apply_all = form.get("resource_apply_all") == "1"
    player_id_raw = form.get("resource_player_id")

    if apply_all:
        adjust_homeworld_resources(
            player_id=None,
            metal_delta=metal_delta,
            crystal_delta=crystal_delta,
        )
        return

    target_player_id: Optional[int] = None
    if player_id_raw:
        try:
            target_player_id = int(str(player_id_raw).strip())
        except ValueError:
            target_player_id = None

    if target_player_id is None:
        target_player_id = current_user_id

    if target_player_id is None:
        return

    adjust_homeworld_resources(
        player_id=int(target_player_id),
        metal_delta=metal_delta,
        crystal_delta=crystal_delta,
    )


# =============================================================================
# 3) Universe-Wipe (Soft-Reset + Homeworld-Rebuild)
# =============================================================================

def wipe_universe(form: Dict[str, Any]) -> None:
    """
    Universum „wipen“, ohne Accounts zu löschen.

    Checkboxes:
      - wipe_confirm = "1" (Pflicht)
      - wipe_reset_research = "1"
      - wipe_reset_resources = "1" (aktuell implizit durch neue Homeworlds)
      - wipe_delete_messages = "1"

    Schritte:
      - build_queue & research_queue leeren
      - optional research_levels leeren
      - planet_buildings & planets leeren
      - optional Nachrichten/Logs leeren (wenn Tabellen existieren)
      - Scores resetten (player_scores)
      - für alle Spieler neue Homeworlds erzeugen (ensure_player_and_homeworld)
      - bans optional löschen? -> NICHT automatisch (Fairplay). Wenn du willst: extra Checkbox.
    """
    if form.get("wipe_confirm") != "1":
        return

    reset_research = form.get("wipe_reset_research") == "1"
    delete_messages = form.get("wipe_delete_messages") == "1"
    _ = form.get("wipe_reset_resources")  # Placeholder

    conn = db()
    cur = conn.cursor()

    try:
        conn.execute("BEGIN")

        # --- Queues wipen ---
        for table in ("build_queue", "research_queue"):
            if _table_exists(cur, table):
                cur.execute(f"DELETE FROM {table};")

        # --- Research reset (optional) ---
        if reset_research and _table_exists(cur, "research_levels"):
            cur.execute("DELETE FROM research_levels;")

        # --- Planeten & Buildings löschen ---
        if _table_exists(cur, "planet_buildings"):
            cur.execute("DELETE FROM planet_buildings;")

        if _table_exists(cur, "planets"):
            cur.execute("DELETE FROM planets;")

        # --- Ranking/Score zurücksetzen (wichtig, sonst UI stale) ---
        if _table_exists(cur, "player_scores"):
            cur.execute("DELETE FROM player_scores;")

        # --- Nachrichten/Logs löschen (Best-Effort) ---
        if delete_messages:
            for table in ("messages", "combat_reports", "logs", "battle_logs"):
                if _table_exists(cur, table):
                    cur.execute(f"DELETE FROM {table};")

        # --- Homeworlds für alle Spieler neu aufbauen ---
        player_rows: List[Any] = []
        if _table_exists(cur, "players"):
            cur.execute("SELECT id, name, is_admin FROM players;")
            player_rows = cur.fetchall()

        for row in player_rows:
            pid = row["id"]
            pname = row["name"] if "name" in row.keys() else f"Commander {pid}"
            is_admin = row["is_admin"] if "is_admin" in row.keys() else 0

            ensure_player_and_homeworld(
                player_id=int(pid),
                player_name=pname,
                is_admin=is_admin,
                conn=conn,
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# =============================================================================
# 4) Ban / Unban + Bannliste
# =============================================================================

def ban_player(form: Dict[str, Any]) -> None:
    """
    Spieler bannen (zeitlich oder permanent).

    Felder:
      - ban_player_id: int
      - ban_hours: int (0 oder leer => permanent)
      - ban_reason: optional

    Schema:
      - players.banned_until (INTEGER Unix TS; NULL = kein Bann)
      - bans (id, player_id, reason, banned_until, created_at) optional
    """
    player_id = _parse_int(form.get("ban_player_id"))
    if not player_id:
        return

    hours = _parse_int(form.get("ban_hours"), default=0) or 0
    reason = str(form.get("ban_reason") or "").strip()

    now = int(time.time())
    banned_until = now + (hours * 3600) if hours > 0 else now + 50 * 365 * 24 * 3600  # ~50 Jahre

    conn = db()
    cur = conn.cursor()
    try:
        conn.execute("BEGIN")

        cur.execute(
            "UPDATE players SET banned_until = ? WHERE id = ?;",
            (banned_until, int(player_id)),
        )

        # Ban-Log nur wenn Tabelle existiert
        if _table_exists(cur, "bans"):
            cur.execute(
                """
                INSERT INTO bans (player_id, reason, banned_until, created_at)
                VALUES (?, ?, ?, ?);
                """,
                (int(player_id), reason, int(banned_until), int(now)),
            )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def unban_player(form: Dict[str, Any]) -> None:
    """
    Bann eines Spielers aufheben.

    Feld:
      - unban_player_id
    """
    player_id = _parse_int(form.get("unban_player_id"))
    if not player_id:
        return

    now = int(time.time())

    conn = db()
    cur = conn.cursor()
    try:
        conn.execute("BEGIN")

        cur.execute(
            "UPDATE players SET banned_until = NULL WHERE id = ?;",
            (int(player_id),),
        )

        # bans optional markieren, aber NICHT überschreiben/zerstören
        if _table_exists(cur, "bans"):
            try:
                cur.execute(
                    """
                    UPDATE bans
                       SET reason = CASE
                           WHEN reason IS NULL OR reason = '' THEN '[UNBANNED]'
                           WHEN instr(reason, '[UNBANNED]') > 0 THEN reason
                           ELSE reason || ' [UNBANNED]'
                       END
                     WHERE id = (
                         SELECT id
                           FROM bans
                          WHERE player_id = ?
                          ORDER BY created_at DESC
                          LIMIT 1
                     );
                    """,
                    (int(player_id),),
                )
            except Exception:
                pass

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_ban_list() -> List[Dict[str, Any]]:
    """
    Liefert alle aktuell gebannten Spieler (players.banned_until > now).

    Nutzt joined users.username + letzte bans-Zeile (Reason, created_at).
    Wenn bans-Tabelle nicht existiert, liefert reason/created_at leer.
    """
    now = int(time.time())
    conn = db()
    try:
        cur = conn.cursor()

        has_bans = _table_exists(cur, "bans")
        has_users = _table_exists(cur, "users")

        if not _table_exists(cur, "players"):
            return []

        if has_bans and has_users:
            cur.execute(
                """
                SELECT
                    p.id AS player_id,
                    p.name AS player_name,
                    p.banned_until AS banned_until,
                    u.username AS username,
                    b.reason AS reason,
                    b.created_at AS created_at
                FROM players p
                LEFT JOIN users u ON u.id = p.id
                LEFT JOIN bans b
                       ON b.id = (
                           SELECT id
                             FROM bans
                            WHERE player_id = p.id
                            ORDER BY created_at DESC
                            LIMIT 1
                       )
                WHERE p.banned_until IS NOT NULL
                  AND p.banned_until > ?
                ORDER BY p.id ASC;
                """,
                (now,),
            )
            rows = cur.fetchall()

        elif has_users:
            cur.execute(
                """
                SELECT
                    p.id AS player_id,
                    p.name AS player_name,
                    p.banned_until AS banned_until,
                    u.username AS username
                FROM players p
                LEFT JOIN users u ON u.id = p.id
                WHERE p.banned_until IS NOT NULL
                  AND p.banned_until > ?
                ORDER BY p.id ASC;
                """,
                (now,),
            )
            rows = cur.fetchall()

        else:
            cur.execute(
                """
                SELECT
                    p.id AS player_id,
                    p.name AS player_name,
                    p.banned_until AS banned_until
                FROM players p
                WHERE p.banned_until IS NOT NULL
                  AND p.banned_until > ?
                ORDER BY p.id ASC;
                """,
                (now,),
            )
            rows = cur.fetchall()

    finally:
        conn.close()

    result: List[Dict[str, Any]] = []

    for r in rows:
        d = dict(r)

        banned_until = d.get("banned_until")
        created_at = d.get("created_at")
        reason = d.get("reason") or ""

        expires_text = _fmt_ts(banned_until)
        created_text = _fmt_ts(created_at)

        is_permanent = False
        if banned_until and int(banned_until) - now > 10 * 365 * 24 * 3600:
            is_permanent = True
            expires_text = "permanent"

        d["reason"] = reason
        d["created_text"] = created_text
        d["expires_text"] = expires_text
        d["is_permanent"] = is_permanent

        result.append(d)

    return result
