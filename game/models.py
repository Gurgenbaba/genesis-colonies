import sqlite3
import time
import hashlib
import math
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List

from werkzeug.security import check_password_hash, generate_password_hash

from .db import (
    DB_PATH,
    db,
    begin_write_transaction,
    commit,
    rollback,
    with_transaction,
    TxAbort,
    lock_planet_for_update,
    lock_player_for_update,
    table_exists,
    column_exists,
)


def _now_ts() -> int:
    return int(time.time())


# ======================================================================
# DEFAULT GAME SETTINGS
# ======================================================================

DEFAULT_GAME_SETTINGS: Dict[str, str] = {
    "universe_name": "Genesis Colonies",
    "production_speed": "1.0",
    "build_speed": "1.1",
    "research_speed": "0.85",
    "fleet_speed_war": "1.0",
    "fleet_speed_holding": "1.0",
    "fleet_speed_peaceful": "1.0",
    "galaxy_count": "5",
    "queue_limit": "5",
    "research_queue_limit": "2",
    "shipyard_speed": "1.0",
    "shipyard_queue_limit": "3",
    "start_metal": "3000",
    "start_crystal": "1500",

    # Instant resource exchange (Trader Hub)
    "exchange_enabled": "1",
    "exchange_rate_metal_to_crystal": "0.8",
    "exchange_rate_crystal_to_metal": "0.8",
    "exchange_daily_limit": "500000000",
    "exchange_min_amount": "100",

    # historischer Alias (build_speed)
    "speed": "1.1",

    # --- Score Defaults (Ranking) — Preset B: building 1.0, research 0.7 ---
    "score_weight_buildings": "1.0",
    "score_weight_research": "0.7",
    "score_cost_exponent": "1.0",  # 1.0 = linear, >1 = stärker
    "score_softcap": "0.0",        # 0 = aus, z.B. 250000
}


# ======================================================================
# INIT DATABASE
# ======================================================================

def harden_planets_schema(conn: sqlite3.Connection) -> None:
    """
    Upgrade legacy planets tables that predate player_id / is_homeworld columns.
    Safe to call repeatedly (idempotent).
    """
    if not table_exists(conn, "planets"):
        return

    cur = conn.cursor()

    if not column_exists(conn, "planets", "player_id"):
        try:
            cur.execute("ALTER TABLE planets ADD COLUMN player_id INTEGER;")
        except sqlite3.OperationalError:
            pass

    if not column_exists(conn, "planets", "is_homeworld"):
        try:
            cur.execute("ALTER TABLE planets ADD COLUMN is_homeworld INTEGER NOT NULL DEFAULT 0;")
        except sqlite3.OperationalError:
            pass

    if column_exists(conn, "planets", "player_id"):
        cur.execute("UPDATE planets SET player_id = 1 WHERE player_id IS NULL;")

    if column_exists(conn, "planets", "player_id") and column_exists(conn, "planets", "is_homeworld"):
        cur.execute(
            """
            UPDATE planets
            SET is_homeworld = 1
            WHERE id IN (
                SELECT p1.id
                FROM planets p1
                INNER JOIN (
                    SELECT player_id, MIN(id) AS min_id
                    FROM planets
                    GROUP BY player_id
                ) t ON t.min_id = p1.id
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM planets p2
                    WHERE p2.player_id = p1.player_id
                      AND p2.is_homeworld = 1
                )
            );
            """
        )

    for idx_sql in (
        "CREATE INDEX IF NOT EXISTS idx_planets_player_id ON planets(player_id);",
        "CREATE INDEX IF NOT EXISTS idx_planets_player_homeworld ON planets(player_id, is_homeworld);",
        "CREATE INDEX IF NOT EXISTS idx_planets_player ON planets(player_id, is_homeworld);",
    ):
        try:
            cur.execute(idx_sql)
        except sqlite3.OperationalError:
            pass


def init_db() -> None:
    conn = db()
    cur = conn.cursor()

    # ------------------------------------------------------------
    # USERS (Login-System)
    # ------------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            email TEXT
        );
    """)

    try:
        cur.execute("ALTER TABLE users ADD COLUMN email TEXT;")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_lower
                ON users (LOWER(email))
                WHERE email IS NOT NULL AND email != '';
            """
        )
    except sqlite3.OperationalError:
        pass

    for col, typedef in (
        ("email_verified", "INTEGER NOT NULL DEFAULT 0"),
        ("email_verification_token", "TEXT"),
        ("password_reset_token", "TEXT"),
        ("password_reset_expires_at", "INTEGER"),
    ):
        try:
            cur.execute(f"ALTER TABLE users ADD COLUMN {col} {typedef};")
        except sqlite3.OperationalError:
            pass

    # ------------------------------------------------------------
    # PLAYERS (Game-Objekt, id == users.id)
    # ------------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            is_admin INTEGER NOT NULL DEFAULT 0,
            banned_until INTEGER DEFAULT NULL,
            last_seen INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(id) REFERENCES users(id) ON DELETE CASCADE
        );
    """)

    # ------------------------------------------------------------
    # PLANETS
    # ------------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS planets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            is_homeworld INTEGER NOT NULL DEFAULT 0,
            metal REAL NOT NULL DEFAULT 0 CHECK(metal >= 0),
            crystal REAL NOT NULL DEFAULT 0 CHECK(crystal >= 0),
            fuel_cells REAL NOT NULL DEFAULT 500 CHECK(fuel_cells >= 0),
            last_update REAL NOT NULL,
            energy_total INTEGER NOT NULL DEFAULT 0,
            energy_used INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
        );
    """)

    for col, typedef in (
        ("galaxy", "INTEGER NOT NULL DEFAULT 1"),
        ("system", "INTEGER"),
        ("position", "INTEGER"),
        ("fuel_cells", "REAL NOT NULL DEFAULT 500 CHECK(fuel_cells >= 0)"),
    ):
        try:
            cur.execute(f"ALTER TABLE planets ADD COLUMN {col} {typedef};")
        except sqlite3.OperationalError:
            pass

    # ------------------------------------------------------------
    # PLANET BUILDINGS (spaltenbasiert)
    # ------------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS planet_buildings (
            planet_id INTEGER PRIMARY KEY,
            metal_mine INTEGER DEFAULT 0 CHECK(metal_mine >= 0),
            crystal_mine INTEGER DEFAULT 0 CHECK(crystal_mine >= 0),
            solar_plant INTEGER DEFAULT 0 CHECK(solar_plant >= 0),
            research_lab INTEGER DEFAULT 0 CHECK(research_lab >= 0),
            academy INTEGER DEFAULT 0 CHECK(academy >= 0),
            metal_storage INTEGER DEFAULT 0 CHECK(metal_storage >= 0),
            crystal_storage INTEGER DEFAULT 0 CHECK(crystal_storage >= 0),
            command_center INTEGER DEFAULT 0 CHECK(command_center >= 0),
            shipyard INTEGER DEFAULT 0 CHECK(shipyard >= 0),
            fuel_cell_plant INTEGER DEFAULT 0 CHECK(fuel_cell_plant >= 0),
            defense_factory INTEGER DEFAULT 0 CHECK(defense_factory >= 0),
            barracks INTEGER DEFAULT 0 CHECK(barracks >= 0),
            radar_array INTEGER DEFAULT 0 CHECK(radar_array >= 0),
            shield_generator INTEGER DEFAULT 0 CHECK(shield_generator >= 0),
            terraformer INTEGER DEFAULT 0 CHECK(terraformer >= 0),
            nanofactory INTEGER DEFAULT 0 CHECK(nanofactory >= 0),
            geothermal_nexus INTEGER DEFAULT 0 CHECK(geothermal_nexus >= 0),
            planet_core_nexus INTEGER DEFAULT 0 CHECK(planet_core_nexus >= 0),
            FOREIGN KEY(planet_id) REFERENCES planets(id) ON DELETE CASCADE
        );
    """)

    # Migration: fehlende Spalten hinzufügen (robust)
    new_building_cols = [
        ("terraformer",       "INTEGER DEFAULT 0 CHECK(terraformer >= 0)"),
        ("nanofactory",       "INTEGER DEFAULT 0 CHECK(nanofactory >= 0)"),
        ("geothermal_nexus",  "INTEGER DEFAULT 0 CHECK(geothermal_nexus >= 0)"),
        ("planet_core_nexus", "INTEGER DEFAULT 0 CHECK(planet_core_nexus >= 0)"),
        ("fuel_cell_plant",   "INTEGER DEFAULT 0 CHECK(fuel_cell_plant >= 0)"),
        ("orbital_shipyard",  "INTEGER DEFAULT 0 CHECK(orbital_shipyard >= 0)"),
    ]
    for col, ddl in new_building_cols:
        try:
            cur.execute(f"ALTER TABLE planet_buildings ADD COLUMN {col} {ddl};")
        except sqlite3.OperationalError:
            pass

    # ------------------------------------------------------------
    # BUILD QUEUE
    # ------------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS build_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            planet_id INTEGER NOT NULL,
            building_type TEXT NOT NULL,
            start_time REAL NOT NULL,
            finish_time REAL NOT NULL,
            FOREIGN KEY(planet_id) REFERENCES planets(id) ON DELETE CASCADE
        );
    """)

    # ------------------------------------------------------------
    # RESEARCH SYSTEM
    # ------------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS research_levels (
            user_id INTEGER NOT NULL,
            tech_key TEXT NOT NULL,
            level INTEGER NOT NULL CHECK(level >= 0),
            PRIMARY KEY (user_id, tech_key),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS research_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            tech_key TEXT NOT NULL,
            finish_at REAL NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS action_idempotency (
            user_id INTEGER NOT NULL,
            request_id TEXT NOT NULL,
            response_json TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (user_id, request_id),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
    """)

    # ------------------------------------------------------------
    # SETTINGS
    # ------------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS game_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)

    # ------------------------------------------------------------
    # BANS (Admin)
    # ------------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id INTEGER NOT NULL,
            reason TEXT,
            banned_until INTEGER NOT NULL,
            created_at INTEGER NOT NULL,
            FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
        );
    """)

    # ------------------------------------------------------------
    # SCORES / RANKING
    # ------------------------------------------------------------
    cur.execute("""
        CREATE TABLE IF NOT EXISTS player_scores (
            player_id INTEGER PRIMARY KEY,
            score_total INTEGER NOT NULL DEFAULT 0,
            score_buildings INTEGER NOT NULL DEFAULT 0,
            score_research INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
        );
    """)
    for col, ddl in (
        ("score_fleet", "INTEGER NOT NULL DEFAULT 0"),
        ("score_defense", "INTEGER NOT NULL DEFAULT 0"),
        ("rank_total", "INTEGER"),
        ("rank_building", "INTEGER"),
        ("rank_research", "INTEGER"),
    ):
        if not column_exists(conn, "player_scores", col):
            cur.execute(f"ALTER TABLE player_scores ADD COLUMN {col} {ddl};")
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_player_scores_total_desc
        ON player_scores(score_total DESC, score_buildings DESC, score_research DESC, player_id ASC);
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_player_scores_rank_total
        ON player_scores(rank_total ASC);
    """)

    # ------------------------------------------------------------
    # INDIZES
    # ------------------------------------------------------------
    indices = [
        "CREATE INDEX IF NOT EXISTS idx_build_queue_planet ON build_queue(planet_id, finish_time)",
        "CREATE INDEX IF NOT EXISTS idx_build_queue_planet_id ON build_queue(planet_id)",
        "CREATE INDEX IF NOT EXISTS idx_build_queue_planet_finish ON build_queue(planet_id, finish_time)",
        "CREATE INDEX IF NOT EXISTS idx_research_queue_user ON research_queue(user_id, finish_at)",
        "CREATE INDEX IF NOT EXISTS idx_research_queue_user_id ON research_queue(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_research_queue_user_finish ON research_queue(user_id, finish_at)",
        "CREATE INDEX IF NOT EXISTS idx_action_idempotency_created ON action_idempotency(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_action_idempotency_user_created ON action_idempotency(user_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_planets_player ON planets(player_id, is_homeworld)",
        "CREATE INDEX IF NOT EXISTS idx_research_levels_user ON research_levels(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_bans_player ON bans(player_id, banned_until)",
        "CREATE INDEX IF NOT EXISTS idx_players_last_seen ON players(last_seen)",
    ]
    for idx in indices:
        try:
            cur.execute(idx)
        except sqlite3.OperationalError:
            pass

    try:
        cur.execute("ALTER TABLE research_queue ADD COLUMN start_at REAL;")
    except sqlite3.OperationalError:
        pass

    harden_planets_schema(conn)

    from game.admin_audit import ensure_admin_audit_table
    ensure_admin_audit_table(conn)

    from game.playercard import ensure_player_card_tables
    ensure_player_card_tables(conn)

    # ------------------------------------------------------------
    # DEFAULT ADMIN + DEFAULT PLAYER + DEFAULT SETTINGS
    # ------------------------------------------------------------
    create_default_admin(conn)
    create_default_player_and_homeworld(conn)

    from .ranking import backfill_player_score_rows

    backfill_player_score_rows(conn=conn)

    for key, val in DEFAULT_GAME_SETTINGS.items():
        cur.execute(
            """
            INSERT INTO game_settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO NOTHING;
            """,
            (key, str(val)),
        )

    conn.commit()
    conn.close()


# ======================================================================
# USERS / AUTH
# ======================================================================

def hash_password(pwd: str) -> str:
    """PBKDF2-SHA256 (Werkzeug). New passwords always use this format."""
    return generate_password_hash(pwd, method="pbkdf2:sha256")


def verify_password(stored_hash: str, pwd: str) -> bool:
    """Verify password; accepts legacy SHA-256 hex hashes for existing accounts."""
    stored = str(stored_hash or "")
    if not stored or not pwd:
        return False
    if stored.startswith(("pbkdf2:", "scrypt:", "argon2:")):
        return check_password_hash(stored, pwd)
    if len(stored) == 64 and all(c in "0123456789abcdef" for c in stored.lower()):
        return hashlib.sha256(pwd.encode("utf-8")).hexdigest() == stored.lower()
    return False


def create_default_admin(conn: sqlite3.Connection | None = None) -> None:
    own_conn = False
    if conn is None:
        conn = db()
        own_conn = True

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM users;")
    c = cur.fetchone()["c"]

    if c == 0:
        cur.execute(
            """
            INSERT INTO users (username, password_hash, is_admin)
            VALUES ('admin', ?, 1);
            """,
            (hash_password("admin"),),
        )
        admin_id = cur.lastrowid
        cur.execute(
            "INSERT OR IGNORE INTO players (id, name, is_admin) VALUES (?, ?, 1);",
            (admin_id, "Gurkenvater"),
        )

    conn.commit()
    if own_conn:
        conn.close()


def get_user_by_username(username: str):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username = ? LIMIT 1;", (username,))
    user = cur.fetchone()
    conn.close()
    return user


def resolve_login_username(identifier: str) -> Optional[str]:
    """
    Resolve login field to username. Username-only by default.
    Set GC_LOGIN_ALLOW_EMAIL=1 to enable email login later (not active in UI yet).
    """
    import os

    ident = str(identifier or "").strip()
    if not ident:
        return None
    allow_email = os.environ.get("GC_LOGIN_ALLOW_EMAIL", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if allow_email and "@" in ident:
        from .account_email import get_user_by_email

        user = get_user_by_email(ident)
        return str(user["username"]) if user else None
    return ident


def verify_user(username: str, password: str):
    user = get_user_by_username(username)
    if not user:
        return None
    if verify_password(user["password_hash"], password):
        return dict(user)
    return None


def create_user(username: str, password: str, is_admin: int = 0, email: str | None = None):
    conn = db()
    cur = conn.cursor()

    try:
        begin_write_transaction(conn)

        normalized_email = str(email or "").strip().lower() if email else None

        cur.execute(
            """
            INSERT INTO users (username, password_hash, is_admin, email, email_verified)
            VALUES (?, ?, ?, ?, ?);
            """,
            (
                username,
                hash_password(password),
                int(is_admin),
                normalized_email,
                0 if normalized_email else 1,
            ),
        )
        user_id = cur.lastrowid

        ensure_player_and_homeworld(
            player_id=user_id,
            player_name=username,
            is_admin=is_admin,
            conn=conn,
        )

        from .ranking import ensure_player_score_row

        ensure_player_score_row(int(user_id), conn=conn)

        conn.commit()
        return True, None, {"id": user_id, "username": username, "is_admin": bool(is_admin)}

    except sqlite3.IntegrityError:
        conn.rollback()
        return False, "Benutzername ist bereits vergeben.", None
    except Exception as e:
        conn.rollback()
        return False, str(e), None
    finally:
        cur.close()
        conn.close()


# ======================================================================
# PLAYER (Game Objects)
# ======================================================================

def touch_player_online(player_id: int) -> None:
    """Mark player online; throttled to at most once per 30s to reduce write contention."""
    if not player_id:
        return
    now = _now_ts()
    touch_before = now - 30
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE players SET last_seen = ? WHERE id = ? AND (last_seen IS NULL OR last_seen < ?)",
            (now, int(player_id), touch_before),
        )
        conn.commit()
    finally:
        conn.close()


def get_player_stats() -> dict:
    now = _now_ts()
    day_ago = now - 24 * 3600
    week_ago = now - 7 * 24 * 3600
    five_min_ago = now - 5 * 60

    conn = db()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) AS c FROM players")
    total_players = int(cur.fetchone()["c"])

    cur.execute("SELECT COUNT(*) AS c FROM players WHERE last_seen >= ?", (day_ago,))
    active_24h = int(cur.fetchone()["c"])

    cur.execute("SELECT COUNT(*) AS c FROM players WHERE last_seen >= ?", (week_ago,))
    active_7d = int(cur.fetchone()["c"])

    cur.execute("SELECT COUNT(*) AS c FROM players WHERE last_seen >= ?", (five_min_ago,))
    online_now = int(cur.fetchone()["c"])

    conn.close()

    return {
        "total_players": total_players,
        "active_24h": active_24h,
        "active_7d": active_7d,
        "online_now": online_now,
    }


def ensure_player_and_homeworld(
    player_id: int,
    player_name: Optional[str] = None,
    is_admin: int = 0,
    conn: sqlite3.Connection | None = None,
) -> None:
    own_conn = False
    if conn is None:
        conn = db()
        own_conn = True

    cur = conn.cursor()

    try:
        if own_conn:
            begin_write_transaction(conn)

        harden_planets_schema(conn)

        cur.execute("SELECT 1 FROM players WHERE id = ? LIMIT 1;", (int(player_id),))
        row = cur.fetchone()
        if not row:
            cur.execute(
                "INSERT INTO players (id, name, is_admin) VALUES (?, ?, ?);",
                (int(player_id), player_name or f"Player-{player_id}", int(is_admin)),
            )

        if not column_exists(conn, "planets", "player_id") or not column_exists(conn, "planets", "is_homeworld"):
            raise RuntimeError("planets schema is missing player_id or is_homeworld after hardening")

        cur.execute(
            "SELECT COUNT(*) AS c FROM planets WHERE player_id = ? AND is_homeworld = 1;",
            (int(player_id),),
        )
        c = int(cur.fetchone()["c"])

        if c == 0:
            now = time.time()

            start_metal = float(DEFAULT_GAME_SETTINGS["start_metal"])
            start_crystal = float(DEFAULT_GAME_SETTINGS["start_crystal"])
            try:
                settings = get_game_settings()
                start_metal = float(settings.get("start_metal", start_metal))
                start_crystal = float(settings.get("start_crystal", start_crystal))
            except Exception:
                pass

            from game.galaxy import assign_free_coordinates
            from game.planet_evolution.dna import _stable_seed, planet_class_for_coordinates

            galaxy, system, position = assign_free_coordinates(conn)
            planet_class = planet_class_for_coordinates(
                galaxy=int(galaxy),
                system=system,
                position=position,
                is_homeworld=True,
            )
            try:
                settings = get_game_settings()
                salt = settings.get("planet_evolution_server_salt", "genesis_colonies_v1")
            except Exception:
                salt = "genesis_colonies_v1"
            dna_seed = _stable_seed(galaxy, system or 0, position or 0, salt)
            has_class_col = column_exists(conn, "planets", "planet_class")
            has_seed_col = column_exists(conn, "planets", "dna_seed")
            if has_class_col and has_seed_col:
                cur.execute(
                    """
                    INSERT INTO planets (
                        player_id, name, is_homeworld, metal, crystal, fuel_cells, last_update,
                        galaxy, system, position, planet_class, dna_seed
                    )
                    VALUES (?, ?, 1, ?, ?, 500, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        int(player_id),
                        "Aurora Prime",
                        start_metal,
                        start_crystal,
                        now,
                        int(galaxy),
                        int(system),
                        int(position),
                        planet_class,
                        int(dna_seed),
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO planets (
                        player_id, name, is_homeworld, metal, crystal, fuel_cells, last_update,
                        galaxy, system, position
                    )
                    VALUES (?, ?, 1, ?, ?, 500, ?, ?, ?, ?);
                    """,
                    (
                        int(player_id),
                        "Aurora Prime",
                        start_metal,
                        start_crystal,
                        now,
                        int(galaxy),
                        int(system),
                        int(position),
                    ),
                )
            pid = cur.lastrowid

            cur.execute("INSERT INTO planet_buildings (planet_id) VALUES (?);", (int(pid),))

            try:
                from game.planet_evolution.bootstrap import ensure_planet_evolution
                from game.planet_evolution.repository import evolution_schema_ready

                if evolution_schema_ready(conn):
                    ensure_planet_evolution(int(pid), conn)
            except Exception:
                pass

        if own_conn:
            conn.commit()

    except Exception:
        if own_conn:
            conn.rollback()
        raise
    finally:
        if own_conn:
            conn.close()


def create_default_player_and_homeworld(conn: sqlite3.Connection | None = None) -> None:
    own_conn = False
    if conn is None:
        conn = db()
        own_conn = True
    try:
        harden_planets_schema(conn)
        ensure_player_and_homeworld(
            player_id=1,
            player_name="Gurkenvater",
            is_admin=1,
            conn=conn,
        )
    finally:
        if own_conn:
            conn.close()


def load_player(player_id: int, conn: sqlite3.Connection | None = None) -> Optional[Dict[str, Any]]:
    own = False
    if conn is None:
        conn = db()
        own = True
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM players WHERE id = ? LIMIT 1;", (int(player_id),))
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        if own:
            conn.close()



def get_player_by_user_id(user_id: int) -> Optional[Dict[str, Any]]:
    return load_player(int(user_id))


# ======================================================================
# PLANETS
# ======================================================================

def get_planets_by_player(player_id: int, conn: sqlite3.Connection | None = None) -> List[Dict[str, Any]]:
    own_conn = False
    if conn is None:
        conn = db()
        own_conn = True

    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM planets WHERE player_id = ? ORDER BY id ASC;",
        (int(player_id),),
    )
    rows = cur.fetchall()

    if own_conn:
        conn.close()

    return [dict(r) for r in rows]


def get_planet_owner_id(planet_id: int) -> Optional[int]:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT player_id FROM planets WHERE id = ? LIMIT 1;", (int(planet_id),))
    row = cur.fetchone()
    conn.close()
    return int(row["player_id"]) if row else None


def get_homeworld(player_id: int, conn: sqlite3.Connection | None = None) -> Dict[str, Any]:
    own = False
    if conn is None:
        conn = db()
        own = True

    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM planets WHERE player_id = ? AND is_homeworld = 1 LIMIT 1;",
            (int(player_id),),
        )
        row = cur.fetchone()

        if not row:
            # ⚠️ ensure_player_and_homeworld kann conn verwenden – bei dir ja
            ensure_player_and_homeworld(player_id=int(player_id), conn=conn)
            cur.execute(
                "SELECT * FROM planets WHERE player_id = ? AND is_homeworld = 1 LIMIT 1;",
                (int(player_id),),
            )
            row = cur.fetchone()

        return dict(row) if row else {}
    finally:
        if own:
            conn.close()



def save_planet(planet: Dict[str, Any], conn: sqlite3.Connection | None = None) -> None:
    own_conn = False
    if conn is None:
        conn = db()
        own_conn = True

    cur = conn.cursor()
    try:
        if own_conn:
            begin_write_transaction(conn)

        cur.execute(
            """
            UPDATE planets
            SET metal        = MAX(0, ?),
                crystal      = MAX(0, ?),
                fuel_cells   = MAX(0, ?),
                last_update  = ?,
                energy_total = ?,
                energy_used  = ?
            WHERE id = ?;
            """,
            (
                planet["metal"],
                planet["crystal"],
                planet.get("fuel_cells", 0),
                planet.get("last_update", time.time()),
                int(planet.get("energy_total", 0)),
                int(planet.get("energy_used", 0)),
                int(planet["id"]),
            ),
        )

        if own_conn:
            conn.commit()
    except Exception:
        if own_conn:
            conn.rollback()
        raise
    finally:
        if own_conn:
            conn.close()



# ======================================================================
# ATOMIC RESOURCE SPEND
# ======================================================================

def try_spend_resources(planet_id: int, metal_cost: int, crystal_cost: int) -> bool:
    if metal_cost < 0 or crystal_cost < 0:
        raise ValueError("Costs must be >= 0")

    conn = db()
    try:
        begin_write_transaction(conn)
        lock_planet_for_update(conn, int(planet_id))
        ok = try_spend_resources_conn(conn, int(planet_id), int(metal_cost), int(crystal_cost))
        if ok:
            commit(conn)
        else:
            rollback(conn)
        return ok
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def try_spend_resources_conn(
    conn: sqlite3.Connection,
    planet_id: int,
    metal_cost: int,
    crystal_cost: int,
) -> bool:
    """Atomarer Ressourcenabzug innerhalb einer laufenden Transaktion (kein commit)."""
    if metal_cost < 0 or crystal_cost < 0:
        raise ValueError("Costs must be >= 0")
    if metal_cost == 0 and crystal_cost == 0:
        return True

    cur = conn.cursor()
    cur.execute(
        """
        UPDATE planets
        SET metal   = metal   - ?,
            crystal = crystal - ?
        WHERE id = ?
          AND metal   >= ?
          AND crystal >= ?;
        """,
        (int(metal_cost), int(crystal_cost), int(planet_id), int(metal_cost), int(crystal_cost)),
    )
    return cur.rowcount == 1


# ======================================================================
# ACTION IDEMPOTENCY (optional client request_id)
# ======================================================================

_IDEMPOTENCY_TTL_SEC = 120.0


def purge_stale_idempotency(
    conn: sqlite3.Connection,
    *,
    user_id: Optional[int] = None,
    max_age_sec: float = _IDEMPOTENCY_TTL_SEC,
) -> int:
    cutoff = time.time() - float(max_age_sec)
    if user_id is not None:
        cur = conn.execute(
            "DELETE FROM action_idempotency WHERE user_id = ? AND created_at < ?;",
            (int(user_id), float(cutoff)),
        )
    else:
        cur = conn.execute(
            "DELETE FROM action_idempotency WHERE created_at < ?;",
            (float(cutoff),),
        )
    return int(cur.rowcount)


def purge_stale_idempotency_global(max_age_sec: float = _IDEMPOTENCY_TTL_SEC) -> int:
    """TTL cleanup for idempotency rows (call on app startup or periodic maintenance)."""
    conn = db()
    try:
        begin_write_transaction(conn)
        deleted = purge_stale_idempotency(conn, max_age_sec=max_age_sec)
        commit(conn)
        return deleted
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def _purge_stale_idempotency(conn: sqlite3.Connection, user_id: int) -> None:
    purge_stale_idempotency(conn, user_id=user_id)


def get_idempotent_action(user_id: int, request_id: str) -> Optional[Dict[str, Any]]:
    import json

    rid = str(request_id or "").strip()
    if not rid:
        return None

    conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT response_json, created_at FROM action_idempotency
            WHERE user_id = ? AND request_id = ? LIMIT 1;
            """,
            (int(user_id), rid),
        )
        row = cur.fetchone()
        if not row:
            return None
        if float(row["created_at"]) < time.time() - _IDEMPOTENCY_TTL_SEC:
            begin_write_transaction(conn)
            conn.execute(
                "DELETE FROM action_idempotency WHERE user_id = ? AND request_id = ?;",
                (int(user_id), rid),
            )
            commit(conn)
            return None
        return json.loads(str(row["response_json"]))
    finally:
        conn.close()


def save_idempotent_action(user_id: int, request_id: str, response: Dict[str, Any]) -> None:
    import json

    rid = str(request_id or "").strip()
    if not rid:
        return

    conn = db()
    try:
        begin_write_transaction(conn)
        _purge_stale_idempotency(conn, int(user_id))
        conn.execute(
            """
            INSERT INTO action_idempotency (user_id, request_id, response_json, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, request_id) DO UPDATE SET
                response_json = excluded.response_json,
                created_at = excluded.created_at;
            """,
            (int(user_id), rid, json.dumps(response), float(time.time())),
        )
        commit(conn)
    except Exception:
        rollback(conn)
        raise
    finally:
        conn.close()


def adjust_homeworld_resources(
    player_id: Optional[int],
    metal_delta: int = 0,
    crystal_delta: int = 0,
) -> None:
    if not metal_delta and not crystal_delta:
        return

    conn = db()
    cur = conn.cursor()

    try:
        begin_write_transaction(conn)

        if player_id is None:
            cur.execute(
                """
                UPDATE planets
                SET metal   = MAX(0, metal   + ?),
                    crystal = MAX(0, crystal + ?)
                WHERE is_homeworld = 1;
                """,
                (int(metal_delta), int(crystal_delta)),
            )
        else:
            cur.execute(
                """
                UPDATE planets
                SET metal   = MAX(0, metal   + ?),
                    crystal = MAX(0, crystal + ?)
                WHERE player_id = ?
                  AND is_homeworld = 1;
                """,
                (int(metal_delta), int(crystal_delta), int(player_id)),
            )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ======================================================================
# BUILDINGS
# ======================================================================

BUILDING_KEYS = [
    "metal_mine", "crystal_mine", "solar_plant",
    "research_lab", "academy",
    "metal_storage", "crystal_storage",
    "command_center", "shipyard", "orbital_shipyard", "fuel_cell_plant", "defense_factory",
    "barracks", "radar_array", "shield_generator",
    "terraformer", "nanofactory", "geothermal_nexus",
    "planet_core_nexus",
]


def get_planet_buildings(planet_id: int, conn: sqlite3.Connection | None = None) -> Dict[str, int]:
    own_conn = False
    if conn is None:
        conn = db()
        own_conn = True

    cur = conn.cursor()
    cur.execute("SELECT * FROM planet_buildings WHERE planet_id = ?;", (int(planet_id),))
    row = cur.fetchone()

    if not row:
        cur.execute("INSERT INTO planet_buildings (planet_id) VALUES (?);", (int(planet_id),))
        if own_conn:
            conn.commit()
        cur.execute("SELECT * FROM planet_buildings WHERE planet_id = ?;", (int(planet_id),))
        row = cur.fetchone()

    data = dict(row)
    data.pop("planet_id", None)

    if own_conn:
        conn.close()

    return {k: int(v) for k, v in data.items()}


def save_planet_buildings(planet_id: int, buildings: Dict[str, int]) -> None:
    conn = db()
    cur = conn.cursor()

    keys = list(BUILDING_KEYS)

    try:
        begin_write_transaction(conn)
        cur.execute(
            f"""
            UPDATE planet_buildings SET
            {", ".join(f"{k}=?" for k in keys)}
            WHERE planet_id = ?;
            """,
            [int(buildings.get(k, 0)) for k in keys] + [int(planet_id)],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ======================================================================
# BUILD QUEUE
# ======================================================================

def get_build_queue_rows(planet_id: int, conn: sqlite3.Connection | None = None):
    own_conn = False
    if conn is None:
        conn = db()
        own_conn = True

    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM build_queue
        WHERE planet_id = ?
        ORDER BY finish_time ASC;
        """,
        (int(planet_id),),
    )
    rows = cur.fetchall()

    if own_conn:
        conn.close()

    return rows


def add_build_job(
    planet_id: int,
    btype: str,
    start: float,
    finish: float,
    conn: sqlite3.Connection | None = None,
) -> int:
    own_conn = False
    if conn is None:
        conn = db()
        own_conn = True

    cur = conn.cursor()
    try:
        if own_conn:
            begin_write_transaction(conn)

        cur.execute(
            """
            INSERT INTO build_queue (planet_id, building_type, start_time, finish_time)
            VALUES (?, ?, ?, ?);
            """,
            (int(planet_id), str(btype), float(start), float(finish)),
        )
        job_id = cur.lastrowid

        if own_conn:
            conn.commit()

        return int(job_id)
    except Exception:
        if own_conn:
            conn.rollback()
        raise
    finally:
        if own_conn:
            conn.close()


def delete_build_job(job_id: int, conn: sqlite3.Connection | None = None) -> None:
    own_conn = False
    if conn is None:
        conn = db()
        own_conn = True

    cur = conn.cursor()
    try:
        if own_conn:
            begin_write_transaction(conn)
        cur.execute("DELETE FROM build_queue WHERE id = ?;", (int(job_id),))
        if own_conn:
            conn.commit()
    except Exception:
        if own_conn:
            conn.rollback()
        raise
    finally:
        if own_conn:
            conn.close()


# ======================================================================
# SETTINGS
# ======================================================================

def _ensure_game_settings(cur: sqlite3.Cursor) -> Dict[str, str]:
    cur.execute("SELECT key, value FROM game_settings;")
    rows = cur.fetchall()

    if rows:
        settings = {r["key"]: r["value"] for r in rows}
    else:
        settings = dict(DEFAULT_GAME_SETTINGS)
        for key, value in settings.items():
            cur.execute(
                """
                INSERT INTO game_settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value;
                """,
                (key, str(value)),
            )
        cur.connection.commit()

        cur.execute("SELECT key, value FROM game_settings;")
        rows = cur.fetchall()
        settings = {r["key"]: r["value"] for r in rows}

    if "build_speed" not in settings and "speed" in settings:
        settings["build_speed"] = settings["speed"]
    if "speed" not in settings and "build_speed" in settings:
        settings["speed"] = settings["build_speed"]

    return settings


def get_game_settings(conn: sqlite3.Connection | None = None) -> Dict[str, Any]:
    own_conn = False
    if conn is None:
        conn = db()
        own_conn = True

    try:
        cur = conn.cursor()
        settings = _ensure_game_settings(cur)
        return settings
    finally:
        if own_conn:
            conn.close()


def save_game_settings(
    settings: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> None:
    updates: Dict[str, Any] = {}
    if settings:
        updates.update(settings)
    for key, val in kwargs.items():
        if val is None:
            continue
        updates[key] = val

    if not updates:
        return

    if "speed" in updates and "build_speed" not in updates:
        updates["build_speed"] = updates["speed"]
    if "build_speed" in updates and "speed" not in updates:
        updates["speed"] = updates["build_speed"]

    safe_updates: Dict[str, str] = {}
    for key, value in updates.items():
        if isinstance(value, (dict, list, tuple, set)):
            continue

        if isinstance(value, bool):
            v_str = "1" if value else "0"
        elif isinstance(value, int):
            v_str = str(value)
        elif isinstance(value, float):
            if value.is_integer():
                v_str = str(int(value))
            else:
                v_str = f"{value:.6f}".rstrip("0").rstrip(".")
        else:
            v_str = str(value)

        safe_updates[str(key)] = v_str

    if not safe_updates:
        return

    conn = db()
    cur = conn.cursor()
    try:
        begin_write_transaction(conn)
        for key, value_str in safe_updates.items():
            cur.execute(
                """
                INSERT INTO game_settings (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value;
                """,
                (key, value_str),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ======================================================================
# RESEARCH
# ======================================================================

def get_research_levels(user_id: int, conn: sqlite3.Connection | None = None) -> Dict[str, int]:
    own_conn = False
    if conn is None:
        conn = db()
        own_conn = True

    cur = conn.cursor()
    cur.execute(
        "SELECT tech_key, level FROM research_levels WHERE user_id = ?;",
        (int(user_id),),
    )
    rows = cur.fetchall()

    if own_conn:
        conn.close()

    return {r["tech_key"]: int(r["level"]) for r in rows}


def save_research_level(tech_key: str, level: int, user_id: int) -> None:
    conn = db()
    cur = conn.cursor()
    try:
        begin_write_transaction(conn)
        cur.execute(
            """
            INSERT INTO research_levels (user_id, tech_key, level)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;
            """,
            (int(user_id), str(tech_key), int(level)),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_research_queue_rows(user_id: int, conn: sqlite3.Connection | None = None):
    own_conn = False
    if conn is None:
        conn = db()
        own_conn = True

    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM research_queue WHERE user_id = ? ORDER BY finish_at ASC;",
        (int(user_id),),
    )
    rows = cur.fetchall()

    if own_conn:
        conn.close()

    return rows


def add_research_job(
    user_id: int,
    tech_key: str,
    start_at: float,
    finish_at: float,
    conn: sqlite3.Connection | None = None,
) -> int:
    own_conn = False
    if conn is None:
        conn = db()
        own_conn = True

    cur = conn.cursor()
    try:
        if own_conn:
            begin_write_transaction(conn)

        cur.execute(
            """
            INSERT INTO research_queue (user_id, tech_key, start_at, finish_at)
            VALUES (?, ?, ?, ?);
            """,
            (int(user_id), str(tech_key), float(start_at), float(finish_at)),
        )
        job_id = int(cur.lastrowid)

        if own_conn:
            conn.commit()

        return job_id
    except Exception:
        if own_conn:
            conn.rollback()
        raise
    finally:
        if own_conn:
            conn.close()


def delete_research_job(job_id: int, conn: sqlite3.Connection | None = None) -> None:
    own_conn = False
    if conn is None:
        conn = db()
        own_conn = True

    cur = conn.cursor()
    try:
        if own_conn:
            begin_write_transaction(conn)
        cur.execute("DELETE FROM research_queue WHERE id = ?;", (int(job_id),))
        if own_conn:
            conn.commit()
    except Exception:
        if own_conn:
            conn.rollback()
        raise
    finally:
        if own_conn:
            conn.close()


# ======================================================================
# SCORE / RANKING (delegates to game.ranking – single source of truth)
# ======================================================================


def compute_player_score(
    player_id: int,
    conn: sqlite3.Connection | None = None,
) -> Tuple[int, int, int]:
    from .ranking import compute_player_scores

    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True
    try:
        s = compute_player_scores(int(player_id), conn=conn)
        return s["total_score"], s["building_score"], s["research_score"]
    finally:
        if owns_conn:
            conn.close()


def upsert_player_score(
    player_id: int,
    total: int,
    buildings: int,
    research: int,
    conn: sqlite3.Connection | None = None,
) -> None:
    from .ranking import upsert_player_scores

    upsert_player_scores(
        int(player_id),
        {
            "total_score": int(total),
            "building_score": int(buildings),
            "research_score": int(research),
            "fleet_score": 0,
            "defense_score": 0,
        },
        conn=conn,
    )


def recompute_and_upsert_score(
    player_id: int,
    conn: sqlite3.Connection | None = None,
) -> Dict[str, int]:
    from .ranking import recompute_and_upsert_score as _ranking_recompute

    return _ranking_recompute(int(player_id), conn=conn)


def get_player_score_row(player_id: int) -> Optional[Dict[str, Any]]:
    from .ranking import get_player_score_row as _ranking_row

    return _ranking_row(int(player_id))


def get_ranking_rows(limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    from .ranking import get_ranking_rows as _ranking_rows

    return _ranking_rows(limit=limit, offset=offset)


def get_player_rank(player_id: int) -> Tuple[Optional[int], int]:
    from .ranking import get_player_rank as _ranking_rank

    return _ranking_rank(int(player_id))


# ----------------------------------------------------------------------
# QUEUE FINISH TRIGGERS (Score nur bei Finish) - ATOMAR
# ----------------------------------------------------------------------

def finish_due_build_jobs(
    planet_id: int,
    player_id: int,
    now: float | None = None,
    conn: sqlite3.Connection | None = None,
    *,
    update_score: bool = True,
) -> bool:
    """
    Schließt fällige Build-Jobs für einen Planeten ab.
    Delegiert an queue_engine; optional Score (legacy single-planet path).
    """
    from .queue_engine import finish_planet_build_jobs

    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True

    if now is None:
        now = time.time()

    try:
        if owns_conn:
            begin_write_transaction(conn)

        count = finish_planet_build_jobs(conn, int(planet_id), int(player_id), float(now))

        if count > 0 and update_score:
            from .ranking import recompute_and_upsert_score

            recompute_and_upsert_score(int(player_id), conn=conn)

        if owns_conn:
            conn.commit()

        return count > 0

    except Exception:
        if owns_conn:
            conn.rollback()
        raise
    finally:
        if owns_conn:
            conn.close()


def finish_due_research_jobs(
    user_id: int,
    now: float | None = None,
    conn: sqlite3.Connection | None = None,
    *,
    update_score: bool = True,
) -> bool:
    """
    Schließt fällige Research-Jobs ab.
    Delegiert an queue_engine; optional Score (legacy single-player path).
    """
    from .queue_engine import finish_player_research_jobs

    owns_conn = False
    if conn is None:
        conn = db()
        owns_conn = True

    if now is None:
        now = time.time()

    try:
        if owns_conn:
            begin_write_transaction(conn)

        count = finish_player_research_jobs(conn, int(user_id), float(now))

        if count > 0 and update_score:
            from .ranking import recompute_and_upsert_score

            recompute_and_upsert_score(int(user_id), conn=conn)

        if owns_conn:
            conn.commit()

        return count > 0

    except Exception:
        if owns_conn:
            conn.rollback()
        raise
    finally:
        if owns_conn:
            conn.close()
