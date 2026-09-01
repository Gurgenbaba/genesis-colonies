#!/usr/bin/env python3
"""PostgreSQL sandbox runtime for Genesis browser QA.

Starts Genesis against an already-provisioned disposable PostgreSQL instance
(e.g. a GitHub Actions service container), applies migrations, creates a QA
player, performs a real PostgreSQL planet-switch preflight, and launches the
Flask process. The database URL is never printed.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import IO
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SECRET = "sentinel-postgres-test-secret-key-32chars"


@dataclass
class PostgresSandboxRuntime:
    base_url: str
    username: str
    password: str
    process: subprocess.Popen
    log_handle: IO[str]

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        try:
            self.log_handle.close()
        except Exception:
            pass


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _server_env(port: int | None = None) -> dict[str, str]:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("Postgres Sentinel requires DATABASE_URL")
    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": "development",
            "FLASK_ENV": "development",
            "FLASK_DEBUG": "0",
            "GC_DB_BACKEND": "postgres",
            "DATABASE_URL": database_url,
            "GC_SKIP_MIGRATION_CHECK": "1",
            "GC_EMBEDDED_CRON": "0",
            "GC_FLASK_THREADED": "1",
            "GC_MAINTENANCE_WORKER": "0",
            "GC_NAV_PERF_DEBUG": "1",
            "SECRET_KEY": DEFAULT_SECRET,
            "HOST": "127.0.0.1",
        }
    )
    if port is not None:
        env["PORT"] = str(port)
    return env


def _wait_server(base_url: str, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urlopen(f"{base_url}/login", timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError(f"Postgres Sentinel Flask subprocess not ready: {base_url}")


def _migrate() -> None:
    migration = subprocess.run(
        [sys.executable, str(ROOT / "migrate.py")],
        cwd=str(ROOT),
        env=_server_env(),
        capture_output=True,
        text=True,
        timeout=180,
    )
    if migration.returncode != 0:
        details = (migration.stderr or migration.stdout or "").strip()
        raise RuntimeError(f"Postgres Sentinel migration failed: {details[-4000:]}")


def _create_test_player_and_preflight_switch(username: str, password: str) -> None:
    """Seed a second colony and prove the production switch service on real PG.

    GC-PG-175 regression: an explicit switch must persist in player_context and
    must not rewrite players.active_planet_id. This runs before Chromium so a
    recurrence of the production 409/lock-busy path fails the PG gate directly.
    """
    code = r'''
import json
from game.db import db
from game.models import create_user, get_homeworld
from game.planet_evolution.expansion_protocol import INTERSTELLAR_EXPANSION_TECH
from game.planet_evolution.service import colonize_planet, set_active_planet

ok, error, user = create_user(USERNAME, PASSWORD)
if not ok or not user:
    raise SystemExit(error or "create_user failed")
player_id = int(user["id"])

conn = db()
try:
    homeworld = get_homeworld(player_id, conn=conn)
    if not homeworld:
        raise SystemExit("homeworld missing")
    homeworld_id = int(homeworld["id"])
    conn.execute("UPDATE planets SET planet_level = ? WHERE id = ?;", (25, homeworld_id))
    conn.execute(
        "INSERT INTO research_levels (user_id, tech_key, level) VALUES (?, ?, ?) "
        "ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;",
        (player_id, INTERSTELLAR_EXPANSION_TECH, 6),
    )
    conn.commit()
    ok_colony, reason_colony, extra = colonize_planet(
        player_id,
        name="Sentinel PG Colony",
        galaxy=1,
        system=220,
        position=3,
        conn=conn,
    )
    if not ok_colony or not extra or not extra.get("planet_id"):
        raise SystemExit(f"colonize failed: {reason_colony}")
    colony_id = int(extra["planet_id"])
    conn.commit()
finally:
    conn.close()

ok_switch, reason_switch = set_active_planet(player_id, colony_id)
if not ok_switch:
    raise SystemExit(f"planet switch to colony failed: {reason_switch}")

conn = db()
try:
    context = conn.execute(
        "SELECT active_planet_id FROM player_context WHERE player_id = ? LIMIT 1;",
        (player_id,),
    ).fetchone()
    legacy = conn.execute(
        "SELECT active_planet_id FROM players WHERE id = ? LIMIT 1;",
        (player_id,),
    ).fetchone()
    if not context or int(context["active_planet_id"] or 0) != colony_id:
        raise SystemExit("player_context did not persist colony switch")
    if not legacy or int(legacy["active_planet_id"] or 0) != homeworld_id:
        raise SystemExit("PostgreSQL switch unexpectedly rewrote players.active_planet_id")
finally:
    conn.close()

ok_home, reason_home = set_active_planet(player_id, homeworld_id)
if not ok_home:
    raise SystemExit(f"planet switch back home failed: {reason_home}")

conn = db()
try:
    context = conn.execute(
        "SELECT active_planet_id FROM player_context WHERE player_id = ? LIMIT 1;",
        (player_id,),
    ).fetchone()
    if not context or int(context["active_planet_id"] or 0) != homeworld_id:
        raise SystemExit("player_context did not persist homeworld switch")
finally:
    conn.close()

print(json.dumps({
    "ok": True,
    "id": player_id,
    "homeworld_id": homeworld_id,
    "colony_id": colony_id,
    "planet_switch_preflight": True,
}))
'''
    bootstrap = f"USERNAME={username!r}\nPASSWORD={password!r}\n" + code
    created = subprocess.run(
        [sys.executable, "-c", bootstrap],
        cwd=str(ROOT),
        env=_server_env(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if created.returncode != 0:
        details = (created.stderr or created.stdout or "").strip()
        raise RuntimeError(f"Postgres Sentinel player/switch bootstrap failed: {details[-4000:]}")
    try:
        payload = json.loads((created.stdout or "").strip().splitlines()[-1])
    except Exception as exc:
        raise RuntimeError("Postgres Sentinel player bootstrap returned invalid output") from exc
    if not payload.get("ok") or not payload.get("planet_switch_preflight"):
        raise RuntimeError("Postgres Sentinel planet-switch preflight did not succeed")


def start_postgres_sandbox(artifact_root: Path) -> PostgresSandboxRuntime:
    artifact_root.mkdir(parents=True, exist_ok=True)
    _migrate()

    username = f"SentinelPG{uuid.uuid4().hex[:8]}"
    password = "S-" + secrets.token_urlsafe(18)
    _create_test_player_and_preflight_switch(username, password)

    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    log_handle = (artifact_root / "server.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "app.py")],
        cwd=str(ROOT),
        env=_server_env(port),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_server(base_url)
    except Exception:
        process.terminate()
        try:
            process.wait(timeout=5)
        except Exception:
            process.kill()
        log_handle.close()
        raise

    return PostgresSandboxRuntime(
        base_url=base_url,
        username=username,
        password=password,
        process=process,
        log_handle=log_handle,
    )
