#!/usr/bin/env python3
"""Production-scale infinity-load A/B orchestrator (GC-PROD recovery follow-up).

Seeds a temp SQLite DB (no production access), then runs the same journeys against
historical worktrees:

  A = 9027ec0 (stable)
  B = b0fade84 (STATE-012)  — full SHA b0fade8492ead95f0f9b36e7e317b4e692f57c19
  C = 7f3990b (STATE-013)

Scale tiers multiply hot-table rows (baseline / 10x / 100x) so growth curves are
visible — not only player count.

Usage (from repo root on fix branch):
  python scripts/prod_infinity_load_ab.py
  python scripts/prod_infinity_load_ab.py --scales baseline,10x --loops 20 --game-state-loops 40
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "scripts" / "_prod_infinity_load_probe.py"

DEFAULT_WORKTREES = {
    "A_9027ec0": ROOT.parent / "gc-wt-A-9027ec0",
    "B_b0fade84": ROOT.parent / "gc-wt-B-b0fade84",
    "C_7f3990b": ROOT.parent / "gc-wt-C-7f3990b",
}

SCALE_FACTORS = {
    "baseline": 1,
    "10x": 10,
    "100x": 100,
}


def _run(cmd: List[str], *, env: Dict[str, str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True)


def _bootstrap_seed_env(db_path: Path) -> None:
    os.environ["GC_DB_PATH"] = str(db_path)
    os.environ["GC_SKIP_MIGRATION_CHECK"] = "1"
    os.environ["SECRET_KEY"] = "prod-infinity-load-ab-secret-key-32c"
    os.environ["APP_ENV"] = "development"
    os.environ.pop("DATABASE_URL", None)
    os.environ["GC_DB_BACKEND"] = "sqlite"


def _init_migrated_db(db_path: Path) -> None:
    _bootstrap_seed_env(db_path)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    import game.db as gdb

    gdb._DB_PATH = None
    if hasattr(gdb, "DB_PATH"):
        gdb.DB_PATH = db_path

    from game.models import init_db
    import migrate

    init_db()
    migrate.main()


def _create_players(n_players: int) -> List[int]:
    """create_user already opens its own conn + ensure_player_and_homeworld."""
    from game.models import create_user

    uids: List[int] = []
    for i in range(n_players):
        ok, err, user = create_user(f"ab_{i}_{uuid.uuid4().hex[:6]}", "test-pass-123")
        if not ok:
            raise RuntimeError(f"create_user failed: {err}")
        uids.append(int(user["id"]))
    return uids


def _ensure_extra_planets(conn: sqlite3.Connection, uids: List[int], target_planets: int) -> None:
    """Add extra planet rows (synthetic colonies) until planet count >= target."""
    now = int(time.time())
    cur = int(conn.execute("SELECT COUNT(*) AS c FROM planets").fetchone()[0])
    if cur >= target_planets:
        return
    # Pick galaxies 1..9 cycling; avoid unique (galaxy,system,position) collisions.
    next_id_hint = cur
    i = 0
    while cur < target_planets:
        uid = uids[i % len(uids)]
        galaxy = 1 + (i % 9)
        system = 1 + ((i // 9) % 499)
        position = 1 + (i % 15)
        try:
            conn.execute(
                """
                INSERT INTO planets (
                    player_id, name, galaxy, system, position,
                    metal, crystal, fuel_cells, last_update, is_homeworld
                ) VALUES (?, ?, ?, ?, ?, 1000, 1000, 1000, ?, 0);
                """,
                (uid, f"Syn-{next_id_hint}", galaxy, system, position, now),
            )
            cur += 1
            next_id_hint += 1
        except sqlite3.IntegrityError:
            pass
        i += 1
        if i > target_planets * 50:
            break
    conn.commit()


def _seed_directives(conn: sqlite3.Connection, uids: List[int], factor: int) -> None:
    now = int(time.time())
    daily = time.strftime("daily:%Y-%m-%d", time.gmtime(now))
    weekly = time.strftime("weekly:%Y-W%W", time.gmtime(now))
    defs = [
        r["key"]
        for r in conn.execute("SELECT key FROM directive_definitions LIMIT 20").fetchall()
    ]
    if not defs:
        return
    rows = []
    for uid in uids:
        for k in range(4 * factor):
            def_key = defs[k % len(defs)]
            cadence = "daily" if k % 4 else "weekly"
            period = daily if cadence == "daily" else weekly
            status = "completed" if k % 5 == 0 else "active"
            rows.append(
                (
                    uid,
                    def_key,
                    cadence,
                    "common",
                    10,
                    10 if status == "completed" else 1,
                    status,
                    "{}",
                    period,
                    now + 86400,
                    now if status == "completed" else None,
                    None,
                    now,
                )
            )
    conn.executemany(
        """
        INSERT INTO player_directives (
            player_id, definition_key, cadence, rarity, target_value, progress_value,
            status, reward_json, period_key, expires_at, completed_at, claimed_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        rows,
    )
    conn.commit()


def _seed_gd(conn: sqlite3.Connection, factor: int) -> None:
    now = int(time.time())
    # Many historical/closed cycles + open ones across galaxies.
    cycle_ids = []
    for g in range(1, 10):
        for m in range(factor * 3):
            status = "vote_open" if m % 7 == 0 else "closed"
            year = 2020 + (m // 12)
            month = 1 + (m % 12)
            try:
                conn.execute(
                    """
                    INSERT INTO gd_cycles (
                        galaxy, year, month, vote_start_at, vote_end_at,
                        effect_start_at, effect_end_at, status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        g,
                        year,
                        month,
                        now - 7200,
                        now + 7200 if status == "vote_open" else now - 100,
                        now + 8000,
                        now + 86400 * 30,
                        status,
                        now,
                        now,
                    ),
                )
                cycle_ids.append(int(conn.execute("SELECT last_insert_rowid()").fetchone()[0]))
            except sqlite3.IntegrityError:
                continue
    # Votes: factor * many players on older cycles
    player_ids = [int(r[0]) for r in conn.execute("SELECT id FROM players LIMIT 500").fetchall()]
    vote_rows = []
    for i, cid in enumerate(cycle_ids):
        for j in range(min(len(player_ids), 5 * factor)):
            pid = player_ids[(i + j) % len(player_ids)]
            vote_rows.append((cid, 1 + (i % 9), pid, "industrial", now, now))
    conn.executemany(
        """
        INSERT OR IGNORE INTO gd_votes (cycle_id, galaxy, player_id, directive_key, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?);
        """,
        vote_rows,
    )
    conn.commit()


def _seed_votes_auctions(conn: sqlite3.Connection, uids: List[int], factor: int) -> None:
    now = int(time.time())
    # vote_rewards: schema is (provider, user_id, ...) per migrations/048
    providers = []
    try:
        providers = [
            (r["provider_key"] if hasattr(r, "keys") else r[0])
            for r in conn.execute(
                "SELECT provider_key FROM vote_providers LIMIT 20"
            ).fetchall()
        ]
    except sqlite3.Error:
        providers = ["topg"]
    if not providers:
        providers = ["topg"]
    for uid in uids:
        for k in range(max(1, factor)):
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO vote_rewards (
                        provider, user_id, vote_ip, provider_ref, status,
                        reward_key, voted_at, created_at
                    ) VALUES (?, ?, '127.0.0.1', ?, 'pending', 'credits', ?, ?);
                    """,
                    (
                        providers[k % len(providers)],
                        uid,
                        f"ref-{uid}-{k}-{uuid.uuid4().hex[:6]}",
                        now - k,
                        now,
                    ),
                )
            except sqlite3.Error:
                break

    # auction_house_listings / bids — real columns from migrations/047
    planet_ids = [
        int(r[0])
        for r in conn.execute("SELECT id FROM planets LIMIT 500").fetchall()
    ]
    if not planet_ids:
        conn.commit()
        return
    for i in range(20 * factor):
        try:
            conn.execute(
                """
                INSERT INTO auction_house_listings (
                    box_key, currency, start_price, current_bid, starts_at, ends_at,
                    status, created_at
                ) VALUES ('common_crate', 'credits', 10, 0, ?, ?, 'active', ?);
                """,
                (now - 10, now + 86400, now),
            )
        except sqlite3.Error:
            break
    listing_ids = [
        int(r[0])
        for r in conn.execute(
            "SELECT id FROM auction_house_listings ORDER BY id DESC LIMIT ?",
            (20 * factor,),
        ).fetchall()
    ]
    for i, lid in enumerate(listing_ids):
        try:
            conn.execute(
                """
                INSERT INTO auction_house_bids (
                    listing_id, player_id, planet_id, amount, created_at
                ) VALUES (?, ?, ?, ?, ?);
                """,
                (lid, uids[i % len(uids)], planet_ids[i % len(planet_ids)], 10 + i, now),
            )
        except sqlite3.Error:
            break
    conn.commit()


def seed_database(db_path: Path, *, n_players: int, n_planets: int, factor: int) -> int:
    if db_path.exists():
        db_path.unlink()
    for suffix in ("-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        if p.exists():
            p.unlink()

    _init_migrated_db(db_path)
    from game.db import db

    # Create players first without holding a long-lived connection (avoids SQLITE_BUSY
    # against create_user's own BEGIN IMMEDIATE).
    uids = _create_players(n_players)
    conn = db()
    try:
        _ensure_extra_planets(conn, uids, n_planets)
        _seed_directives(conn, uids, factor)
        _seed_gd(conn, factor)
        _seed_votes_auctions(conn, uids, factor)
        primary = uids[0]
        # Ensure primary has open cycle in their galaxy for government badge path
        gal = conn.execute(
            "SELECT galaxy FROM planets WHERE player_id = ? LIMIT 1;",
            (primary,),
        ).fetchone()
        if gal is not None:
            g = int(gal[0] if not hasattr(gal, "keys") else gal["galaxy"])
            now = int(time.time())
            try:
                conn.execute(
                    """
                    INSERT INTO gd_cycles (
                        galaxy, year, month, vote_start_at, vote_end_at,
                        effect_start_at, effect_end_at, status, created_at, updated_at
                    ) VALUES (?, 2099, 1, ?, ?, ?, ?, 'vote_open', ?, ?);
                    """,
                    (g, now - 100, now + 86400, now + 90000, now + 200000, now, now),
                )
                conn.commit()
            except sqlite3.IntegrityError:
                conn.execute(
                    "UPDATE gd_cycles SET status='vote_open', vote_start_at=?, vote_end_at=? "
                    "WHERE galaxy=? AND year=2099 AND month=1;",
                    (now - 100, now + 86400, g),
                )
                conn.commit()
        return primary
    finally:
        conn.close()


def measure_label(
    *,
    label: str,
    code_root: Path,
    seed_db: Path,
    out_dir: Path,
    player_id: int,
    loops: int,
    game_state_loops: int,
    with_writer_hold: bool,
) -> Dict[str, Any]:
    out_dir = out_dir.resolve()
    seed_db = seed_db.resolve()
    code_root = code_root.resolve()
    run_db = (out_dir / f"{label}.db").resolve()
    if run_db.exists():
        run_db.unlink()
    for suffix in ("-wal", "-shm"):
        p = Path(str(run_db) + suffix)
        if p.exists():
            p.unlink()
    shutil.copy2(seed_db, run_db)
    out_json = (out_dir / f"{label}.json").resolve()
    cmd = [
        sys.executable,
        str(PROBE.resolve()),
        "--code-root",
        str(code_root),
        "--db",
        str(run_db),
        "--label",
        label,
        "--player-id",
        str(player_id),
        "--loops",
        str(loops),
        "--game-state-loops",
        str(game_state_loops),
        "--out",
        str(out_json),
    ]
    if with_writer_hold:
        cmd.append("--with-writer-hold")
    env = os.environ.copy()
    env["GC_DB_PATH"] = str(run_db)
    env["GC_SKIP_MIGRATION_CHECK"] = "1"
    env["PYTHONPATH"] = str(code_root)
    # Run with cwd=ROOT so relative imports of the probe stay stable; code comes from PYTHONPATH.
    proc = _run(cmd, env=env, cwd=ROOT)
    payload: Dict[str, Any] = {
        "label": label,
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "")[-2000:],
        "stderr": (proc.stderr or "")[-4000:],
        "report_path": str(out_json),
        "db_path": str(run_db),
    }
    if out_json.exists():
        try:
            payload["report"] = json.loads(out_json.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            payload["report_error"] = str(exc)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scales", default="baseline,10x,100x")
    parser.add_argument("--players", type=int, default=125)
    parser.add_argument("--planets", type=int, default=168)
    parser.add_argument("--loops", type=int, default=30)
    parser.add_argument("--game-state-loops", type=int, default=80)
    parser.add_argument("--with-writer-hold", action="store_true", default=True)
    parser.add_argument("--no-writer-hold", action="store_true")
    parser.add_argument("--out-dir", default=str(ROOT / "artifacts" / "prod_infinity_load_ab"))
    parser.add_argument("--worktree-a", default=str(DEFAULT_WORKTREES["A_9027ec0"]))
    parser.add_argument("--worktree-b", default=str(DEFAULT_WORKTREES["B_b0fade84"]))
    parser.add_argument("--worktree-c", default=str(DEFAULT_WORKTREES["C_7f3990b"]))
    args = parser.parse_args()

    with_writer = bool(args.with_writer_hold) and not bool(args.no_writer_hold)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    worktrees: List[Tuple[str, Path]] = [
        ("A_9027ec0", Path(args.worktree_a)),
        ("B_b0fade84", Path(args.worktree_b)),
        ("C_7f3990b", Path(args.worktree_c)),
    ]
    for label, path in worktrees:
        if not path.exists():
            print(f"ERROR: missing worktree {label}: {path}", file=sys.stderr)
            return 2

    summary: Dict[str, Any] = {
        "created_at": int(time.time()),
        "note": "GitHub main != Railway production deploy; this is local A/B only",
        "worktrees": {k: str(v) for k, v in worktrees},
        "scales": {},
    }

    for scale_name in [s.strip() for s in args.scales.split(",") if s.strip()]:
        factor = SCALE_FACTORS.get(scale_name)
        if factor is None:
            print(f"skip unknown scale {scale_name}", file=sys.stderr)
            continue
        scale_dir = out_dir / scale_name
        scale_dir.mkdir(parents=True, exist_ok=True)
        seed_db = scale_dir / "seed.db"
        print(f"== seeding {scale_name} factor={factor} ==")
        t0 = time.perf_counter()
        primary = seed_database(
            seed_db,
            n_players=args.players,
            n_planets=args.planets,
            factor=factor,
        )
        seed_s = time.perf_counter() - t0
        seed_size = seed_db.stat().st_size if seed_db.exists() else 0
        print(f"seed done in {seed_s:.1f}s size={seed_size} primary={primary}")

        scale_results = {
            "factor": factor,
            "seed_seconds": round(seed_s, 2),
            "seed_bytes": seed_size,
            "primary_player_id": primary,
            "labels": {},
        }
        for label, path in worktrees:
            print(f"-- measure {scale_name}/{label} --")
            result = measure_label(
                label=f"{scale_name}__{label}",
                code_root=path,
                seed_db=seed_db,
                out_dir=scale_dir,
                player_id=primary,
                loops=args.loops,
                game_state_loops=args.game_state_loops,
                with_writer_hold=with_writer,
            )
            scale_results["labels"][label] = result
            rep = result.get("report") or {}
            gs = ((rep.get("api_game_state") or {}).get("timing") or {})
            print(
                f"   game-state p50={gs.get('p50_ms')} p95={gs.get('p95_ms')} "
                f"max={gs.get('max_ms')} err={result.get('returncode')}"
            )
        summary["scales"][scale_name] = scale_results

    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
