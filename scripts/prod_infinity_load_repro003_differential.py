#!/usr/bin/env python3
"""GC-PROD-INFINITY-LOAD-REPRO-003 — differential concurrency (no hotfix / no PR).

1) Control without maintenance (calibrate harness)
2) Staged maintenance attribution
3) Historical A/B/C differential on identical seed copies

Usage examples:
  python scripts/prod_infinity_load_repro003_differential.py --phase control
  python scripts/prod_infinity_load_repro003_differential.py --phase stages
  python scripts/prod_infinity_load_repro003_differential.py --phase differential --reps 3
  python scripts/prod_infinity_load_repro003_differential.py --phase all
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "concurrency_repro",
    ROOT / "scripts" / "prod_infinity_load_concurrency_repro.py",
)
assert _spec and _spec.loader
_cr = importlib.util.module_from_spec(_spec)
sys.modules["concurrency_repro"] = _cr
_spec.loader.exec_module(_cr)

WORKTREES = {
    "A_9027ec0": {
        "sha": "9027ec0934b68be8e6ea9ffce29854422e71dc15",
        "path": ROOT.parent / "gc-wt-A-9027ec0",
    },
    "B_b0fade84": {
        "sha": "b0fade8492ead95f0f9b36e7e317b4e692f57c19",
        "path": ROOT.parent / "gc-wt-B-b0fade84",
    },
    "C_7f3990b": {
        "sha": "7f3990b384b4197ec5c2e03d15d7e8f2ebba419d",
        "path": ROOT.parent / "gc-wt-C-7f3990b",
    },
}

SECRET = "concurrency-repro-secret-key-32charsxx"


def _copy_seed(seed: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    for suffix in ("-wal", "-shm"):
        p = Path(str(dest) + suffix)
        if p.exists():
            p.unlink()
    shutil.copy2(seed, dest)
    return dest


def _normalize_runtime(db_path: Path, code_root: Path) -> Dict[str, Any]:
    db_path = Path(db_path).resolve()
    code_root = Path(code_root).resolve()
    env = os.environ.copy()
    env.update(
        {
            "GC_DB_PATH": str(db_path),
            "GC_SKIP_MIGRATION_CHECK": "1",
            "GC_MAINTENANCE_WORKER": "1",
            "GC_EMBEDDED_CRON": "0",
            "SECRET_KEY": SECRET,
            "APP_ENV": "development",
            "GC_DB_BACKEND": "sqlite",
            "PYTHONPATH": str(code_root),
        }
    )
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "_repro003_staged_maint.py"), "normalize_only"],
        cwd=str(code_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return {
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "").strip()[-2000:],
        "stderr": (proc.stderr or "").strip()[-2000:],
        "db_path": str(db_path),
        "db_bytes": db_path.stat().st_size if db_path.exists() else 0,
    }


def _run_staged_maint(db_path: Path, code_root: Path, mode: str) -> Dict[str, Any]:
    db_path = Path(db_path).resolve()
    code_root = Path(code_root).resolve()
    env = os.environ.copy()
    env.update(
        {
            "GC_DB_PATH": str(db_path),
            "GC_SKIP_MIGRATION_CHECK": "1",
            "GC_MAINTENANCE_WORKER": "1",
            "GC_EMBEDDED_CRON": "0",
            "SECRET_KEY": SECRET,
            "APP_ENV": "development",
            "GC_DB_BACKEND": "sqlite",
            "PYTHONPATH": str(code_root),
        }
    )
    # Staged script lives on current branch; import game from code_root via PYTHONPATH.
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "_repro003_staged_maint.py"), mode],
        cwd=str(code_root),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    payload: Dict[str, Any] = {
        "returncode": proc.returncode,
        "stderr_tail": (proc.stderr or "")[-3000:],
        "db_path": str(db_path),
        "db_bytes": db_path.stat().st_size if db_path.exists() else 0,
    }
    try:
        payload["timed"] = json.loads((proc.stdout or "").strip().splitlines()[-1])
    except Exception as exc:  # noqa: BLE001
        payload["parse_error"] = str(exc)
        payload["stdout_tail"] = (proc.stdout or "")[-3000:]
    return payload


def _route_key_stats(report: Dict[str, Any], route: str) -> Dict[str, float]:
    by = ((report.get("analysis") or {}).get("by_route") or {}).get(route) or {}
    return {
        "p50_ms": float(by.get("p50_ms") or 0),
        "p95_ms": float(by.get("p95_ms") or 0),
        "p99_ms": float(by.get("p99_ms") or 0),
        "max_ms": float(by.get("max_ms") or 0),
        "n": float(by.get("n") or 0),
    }


def _penalty(with_m: Dict[str, float], control: Dict[str, float]) -> Dict[str, float]:
    return {
        "p95_ms": round(with_m["p95_ms"] - control["p95_ms"], 2),
        "p99_ms": round(with_m["p99_ms"] - control["p99_ms"], 2),
        "max_ms": round(with_m["max_ms"] - control["max_ms"], 2),
    }


def run_http_load(
    *,
    label: str,
    seed_db: Path,
    out_dir: Path,
    code_root: Path,
    clients: int,
    duration_sec: float,
    with_maintenance: bool,
    maint_mode: str = "all",
    maint_interval_sec: float = 10.0,
) -> Dict[str, Any]:
    """HTTP load against code_root Flask; optional staged maintenance sidecar."""
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    # Absolute path is mandatory: historical worktrees use cwd=code_root, so a
    # relative GC_DB_PATH would open an empty DB under the worktree (REPRO-003 footgun).
    run_db = (out_dir / f"{label}.db").resolve()
    _copy_seed(Path(seed_db).resolve(), run_db)
    if run_db.stat().st_size < 10_000_000:
        raise RuntimeError(f"seed copy too small ({run_db.stat().st_size} bytes): {run_db}")
    norm = _normalize_runtime(run_db, Path(code_root).resolve())

    meta_path = Path(seed_db).resolve().with_suffix(".meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    player_ids = [int(x) for x in (meta.get("players") or []) if x]
    if not player_ids:
        player_ids = [int(meta.get("primary_player_id") or 2)]

    port = _cr._free_port()
    base_url = f"http://127.0.0.1:{port}"
    os.environ["SECRET_KEY"] = SECRET

    # Start Flask from historical/current code root
    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": "development",
            "FLASK_ENV": "development",
            "FLASK_DEBUG": "0",
            "GC_DB_BACKEND": "sqlite",
            "GC_DB_PATH": str(run_db),  # absolute
            "GC_SKIP_MIGRATION_CHECK": "1",
            "GC_EMBEDDED_CRON": "0",
            "GC_MAINTENANCE_WORKER": "1",
            "GC_FLASK_THREADED": "1",
            "GC_REQUEST_PERF_DEBUG": "1",
            "GC_REQUEST_PERF_SLOW_MS": "500",
            "GC_REQUEST_PERF_SAMPLE": "1.0",
            "SECRET_KEY": SECRET,
            "HOST": "127.0.0.1",
            "PORT": str(port),
            "PYTHONPATH": str(Path(code_root).resolve()),
        }
    )
    log_path = out_dir / f"{label}_server.log"
    log_handle = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, str(code_root / "app.py")],
        cwd=str(code_root),
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    proc._repro_log_handle = log_handle  # type: ignore[attr-defined]

    samples: List[_cr.RequestSample] = []
    maint_samples: List[_cr.MaintSample] = []
    stage_reports: List[Dict[str, Any]] = []
    lock = __import__("threading").Lock()
    stop_at = time.time() + duration_sec
    t_wall0 = time.time()

    try:
        _cr._wait_http(f"{base_url}/login", timeout=120)
        chosen = player_ids[: max(1, min(clients, len(player_ids)))]
        clients_obj = [_cr.AuthedClient(base_url, pid) for pid in chosen]
        threads = []
        import random
        import threading

        for i, client in enumerate(clients_obj):
            rng = random.Random(42_000 + i)  # identical jitter seed pattern across trees
            t = threading.Thread(
                target=_cr._client_loop,
                args=(client, stop_at, samples, lock, rng),
                daemon=True,
            )
            threads.append(t)
            t.start()

        def _maint_loop():
            while time.time() < stop_at:
                if not with_maintenance:
                    time.sleep(0.5)
                    continue
                t0 = time.time()
                timed = _run_staged_maint(run_db, code_root, maint_mode)
                t1 = time.time()
                with lock:
                    stage_reports.append(timed)
                    maint_samples.append(
                        _cr.MaintSample(
                            stage=f"staged_{maint_mode}",
                            start_ts=t0,
                            end_ts=t1,
                            duration_ms=(t1 - t0) * 1000.0,
                            ok=timed.get("returncode", 1) == 0,
                            error=None if timed.get("returncode") == 0 else "staged_failed",
                            detail={
                                "longest": (timed.get("timed") or {}).get("longest_stage"),
                                "total_ms": (timed.get("timed") or {}).get("total_ms"),
                                "stages": (timed.get("timed") or {}).get("stages"),
                            },
                        )
                    )
                    print(
                        f"[STAGED {maint_mode}] {(t1 - t0) * 1000:.0f}ms "
                        f"longest={(timed.get('timed') or {}).get('longest_stage')}"
                    )
                time.sleep(max(1.0, maint_interval_sec))

        mt = __import__("threading").Thread(target=_maint_loop, daemon=True)
        threads.append(mt)
        mt.start()
        for t in threads:
            t.join()

        analysis = _cr.analyze(samples, maint_samples)
        wall = time.time() - t_wall0
        rps = (len(samples) / wall) if wall > 0 else 0.0
        # Auth / DB sanity: forged session must yield mostly 200s on game-state.
        gs_samples = [s for s in samples if s.route == "/api/game-state"]
        gs_ok = sum(1 for s in gs_samples if int(s.status) == 200)
        gs_401 = sum(1 for s in gs_samples if int(s.status) == 401)
        auth_ok_ratio = (gs_ok / len(gs_samples)) if gs_samples else 0.0
        report = {
            "label": label,
            "code_root": str(Path(code_root).resolve()),
            "db_path": str(run_db),
            "db_bytes": run_db.stat().st_size,
            "with_maintenance": with_maintenance,
            "maint_mode": maint_mode if with_maintenance else "none",
            "clients": len(clients_obj),
            "duration_sec": duration_sec,
            "request_count": len(samples),
            "requests_per_sec": round(rps, 2),
            "auth_ok_ratio_game_state": round(auth_ok_ratio, 4),
            "game_state_200": gs_ok,
            "game_state_401": gs_401,
            "runtime_normalize": norm,
            "analysis": analysis,
            "game_state": _route_key_stats({"analysis": analysis}, "/api/game-state"),
            "galaxy": _route_key_stats({"analysis": analysis}, "/galaxy"),
            "stage_reports": stage_reports[:20],
            "worker_model": "flask_threaded_harness",
            "note": "Not a Gunicorn production claim; WSL/Docker for that separately.",
        }
        if auth_ok_ratio < 0.8:
            report["INVALID"] = True
            report["invalid_reason"] = (
                f"auth_ok_ratio={auth_ok_ratio:.3f} "
                f"(200={gs_ok} 401={gs_401}) — likely wrong DB or SECRET_KEY mismatch"
            )
            print(f"INVALID RUN {label}: {report['invalid_reason']}")
        out_json = out_dir / f"{label}_report.json"
        out_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(
            f"{label}: gs_p50={report['game_state']['p50_ms']} "
            f"gs_p95={report['game_state']['p95_ms']} "
            f"slow5={analysis.get('slow_ge_5000_count')} rps={report['requests_per_sec']} "
            f"auth_ok={auth_ok_ratio:.3f} db_mb={run_db.stat().st_size/1024/1024:.1f}"
        )
        return report
    finally:
        _cr.stop_proc(proc)


def phase_control(seed: Path, out_dir: Path, clients: int, duration: float) -> Dict[str, Any]:
    print("== CONTROL (no maintenance) ==")
    # Try calibrated load first
    report = run_http_load(
        label="control_calibrated",
        seed_db=seed,
        out_dir=out_dir,
        code_root=ROOT,
        clients=clients,
        duration_sec=duration,
        with_maintenance=False,
    )
    gs = report["game_state"]
    calibrated = gs["p50_ms"] < 1000.0 and gs["p95_ms"] < 2500.0
    # If still too hot, retry with fewer clients
    if not calibrated and clients > 3:
        print("Control too hot — retrying with clients=3")
        report = run_http_load(
            label="control_calibrated_c3",
            seed_db=seed,
            out_dir=out_dir,
            code_root=ROOT,
            clients=3,
            duration_sec=duration,
            with_maintenance=False,
        )
        gs = report["game_state"]
        calibrated = gs["p50_ms"] < 1000.0 and gs["p95_ms"] < 2500.0
    report["CONTROL_CALIBRATED"] = calibrated
    return report


def phase_stages(seed: Path, out_dir: Path) -> Dict[str, Any]:
    print("== STAGE ATTRIBUTION (no HTTP) ==")
    db = _copy_seed(seed, out_dir / "stages_only.db")
    _normalize_runtime(db, ROOT)
    modes = ["all", "ranking_only", "fleet_only", "no_ranking", "no_fleet"]
    results = {}
    for mode in modes:
        print(f"-- staged mode={mode}")
        results[mode] = _run_staged_maint(db, ROOT, mode)
    out = {"modes": results}
    (out_dir / "stages_attribution.json").write_text(
        json.dumps(out, indent=2, sort_keys=True), encoding="utf-8"
    )
    return out


def phase_differential(
    seed: Path,
    out_dir: Path,
    *,
    clients: int,
    duration: float,
    reps: int,
) -> Dict[str, Any]:
    print("== HISTORICAL DIFFERENTIAL ==")
    summary: Dict[str, Any] = {"reps": reps, "trees": {}}
    for tree_name, info in WORKTREES.items():
        path = Path(info["path"])
        if not path.exists():
            summary["trees"][tree_name] = {"error": f"missing worktree {path}"}
            continue
        tree_out = out_dir / tree_name
        tree_out.mkdir(parents=True, exist_ok=True)
        control_runs = []
        maint_runs = []
        for rep in range(1, reps + 1):
            print(f"-- {tree_name} rep={rep} CONTROL")
            c = run_http_load(
                label=f"{tree_name}_r{rep}_control",
                seed_db=seed,
                out_dir=tree_out,
                code_root=path,
                clients=clients,
                duration_sec=duration,
                with_maintenance=False,
            )
            control_runs.append(c)
            print(f"-- {tree_name} rep={rep} MAINT")
            m = run_http_load(
                label=f"{tree_name}_r{rep}_maint",
                seed_db=seed,
                out_dir=tree_out,
                code_root=path,
                clients=clients,
                duration_sec=duration,
                with_maintenance=True,
                maint_mode="all",
                maint_interval_sec=12.0,
            )
            maint_runs.append(m)

        def _avg_metric(runs: List[Dict[str, Any]], route: str, key: str) -> float:
            vals = [_route_key_stats(r, route)[key] for r in runs]
            return round(statistics.mean(vals), 2) if vals else 0.0

        control_gs = {
            "p95_ms": _avg_metric(control_runs, "/api/game-state", "p95_ms"),
            "p99_ms": _avg_metric(control_runs, "/api/game-state", "p99_ms"),
            "p50_ms": _avg_metric(control_runs, "/api/game-state", "p50_ms"),
            "max_ms": _avg_metric(control_runs, "/api/game-state", "max_ms"),
        }
        maint_gs = {
            "p95_ms": _avg_metric(maint_runs, "/api/game-state", "p95_ms"),
            "p99_ms": _avg_metric(maint_runs, "/api/game-state", "p99_ms"),
            "p50_ms": _avg_metric(maint_runs, "/api/game-state", "p50_ms"),
            "max_ms": _avg_metric(maint_runs, "/api/game-state", "max_ms"),
        }
        # Longest writer stage across maint runs
        longest = []
        for m in maint_runs:
            for sr in m.get("stage_reports") or []:
                timed = sr.get("timed") or {}
                for st in timed.get("stages") or []:
                    longest.append(st)
        longest_stage = None
        if longest:
            longest_stage = max(longest, key=lambda s: float(s.get("duration_ms") or 0))

        summary["trees"][tree_name] = {
            "sha": info["sha"],
            "control_game_state": control_gs,
            "maintenance_game_state": maint_gs,
            "maintenance_penalty": _penalty(maint_gs, control_gs),
            "longest_writer_stage": longest_stage,
            "slow5_control_avg": round(
                statistics.mean(
                    [
                        float((r.get("analysis") or {}).get("slow_ge_5000_count") or 0)
                        for r in control_runs
                    ]
                ),
                2,
            ),
            "slow5_maint_avg": round(
                statistics.mean(
                    [
                        float((r.get("analysis") or {}).get("slow_ge_5000_count") or 0)
                        for r in maint_runs
                    ]
                ),
                2,
            ),
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--seed",
        default=str(ROOT / "artifacts" / "concurrency_repro" / "seed.db"),
    )
    parser.add_argument(
        "--out-dir",
        default=str(ROOT / "artifacts" / "concurrency_repro" / "repro003"),
    )
    parser.add_argument(
        "--phase",
        choices=("control", "stages", "differential", "all"),
        default="all",
    )
    parser.add_argument("--clients", type=int, default=4)
    parser.add_argument("--duration-sec", type=float, default=75)
    parser.add_argument("--reps", type=int, default=3)
    args = parser.parse_args()

    seed = Path(args.seed).resolve()
    if not seed.exists():
        raise SystemExit(f"missing seed: {seed}")
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Force unbuffered progress for long differential runs
    try:
        sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    except Exception:
        pass

    final: Dict[str, Any] = {
        "created_at": int(time.time()),
        "seed": str(seed),
        "seed_mb": round(seed.stat().st_size / (1024 * 1024), 2),
        "wsl_available": True,
        "docker_daemon": False,
        "gunicorn_claim": False,
        "harness_note": (
            "Flask-threaded Windows harness. Relative GC_DB_PATH bug fixed "
            "(absolute paths required when cwd=worktree)."
        ),
    }

    if args.phase in ("control", "all"):
        final["control"] = phase_control(seed, out_dir, args.clients, args.duration_sec)
    if args.phase in ("stages", "all"):
        final["stages"] = phase_stages(seed, out_dir)
    if args.phase in ("differential", "all"):
        # Use calibrated client count from control if available
        clients = args.clients
        if final.get("control") and not final["control"].get("CONTROL_CALIBRATED"):
            clients = 3
        final["differential"] = phase_differential(
            seed,
            out_dir,
            clients=clients,
            duration=args.duration_sec,
            reps=args.reps,
        )

    # Derive gates
    control = final.get("control") or {}
    final["CONTROL_CALIBRATED"] = bool(control.get("CONTROL_CALIBRATED"))
    diff = final.get("differential") or {}
    trees = diff.get("trees") or {}
    a = trees.get("A_9027ec0") or {}
    c = trees.get("C_7f3990b") or {}
    system_mode = False
    for t in trees.values():
        if float((t.get("slow5_maint_avg") or 0)) > 0 or float(
            (t.get("maintenance_penalty") or {}).get("p95_ms") or 0
        ) > 500:
            system_mode = True
    hist = False
    if a and c:
        pen_a = float((a.get("maintenance_penalty") or {}).get("p95_ms") or 0)
        pen_c = float((c.get("maintenance_penalty") or {}).get("p95_ms") or 0)
        # Historical only if C penalty significantly worse than A on same harness
        hist = pen_c > (pen_a + 1000) and pen_c > 1500

    final["SYSTEM_FAILURE_MODE"] = system_mode
    final["HISTORICAL_REGRESSION"] = hist
    final["ROOT_CAUSE"] = "under investigation"

    # Dominant stage from stages phase
    stages = ((final.get("stages") or {}).get("modes") or {}).get("all") or {}
    timed = stages.get("timed") or {}
    final["DOMINANT_MAINTENANCE_STAGE"] = timed.get("longest_stage")
    full_reconcile = False
    for st in timed.get("stages") or []:
        if st.get("stage") == "ranking":
            mode = (st.get("summary") or {}).get("mode")
            if mode == "full" or "full" in str(mode):
                full_reconcile = True
    final["FULL_RECONCILE_INVOLVED"] = full_reconcile

    out_path = out_dir / "repro003_summary.json"
    out_path.write_text(json.dumps(final, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote {out_path}")
    print(
        f"CONTROL_CALIBRATED={final['CONTROL_CALIBRATED']} "
        f"SYSTEM_FAILURE_MODE={final['SYSTEM_FAILURE_MODE']} "
        f"HISTORICAL_REGRESSION={final['HISTORICAL_REGRESSION']} "
        f"DOMINANT_STAGE={final.get('DOMINANT_MAINTENANCE_STAGE')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
