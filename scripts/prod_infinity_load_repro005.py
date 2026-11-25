#!/usr/bin/env python3
"""GC-PROD-INFINITY-LOAD-REPRO-005 — Worker-Class Causality.

Isolates: synchronous sqlite3 wait + sole gevent worker vs gthread.

No production fix / Railway / main / merge. #125 untouched.

Examples:
  python scripts/prod_infinity_load_repro005.py --phase micro
  python scripts/prod_infinity_load_repro005.py --phase service
  python scripts/prod_infinity_load_repro005.py --phase all
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from _repro004_common import (  # noqa: E402
    ROUTES,
    SECRET,
    analyze_samples,
    copy_seed,
    load_concurrency_repro,
    parse_server_perf,
    route_stats,
    summarize_ms,
)
from _repro004_prepare_state import prepare_state  # noqa: E402

OUT_DEFAULT = ROOT / "artifacts" / "concurrency_repro" / "repro005"
DOCKER_IMAGE = "python:3.12-slim-bookworm"
SEED_DEFAULT = ROOT / "artifacts" / "concurrency_repro" / "seed.db"

# Primary causality matrix (sync is control-only).
WORKER_CONFIGS = {
    "G1_gevent_w1": {"class": "gevent", "workers": 1, "threads": 0},
    "G2_gevent_w2": {"class": "gevent", "workers": 2, "threads": 0},
    "T1_gthread_w1_t4": {"class": "gthread", "workers": 1, "threads": 4},
    "T2_gthread_w2_t2": {"class": "gthread", "workers": 2, "threads": 2},
    "S1_sync_w1": {"class": "sync", "workers": 1, "threads": 0},
    "S2_sync_w2": {"class": "sync", "workers": 2, "threads": 0},
}

MICRO_CONFIGS = ("G1_gevent_w1", "T1_gthread_w1_t4", "S1_sync_w1", "G2_gevent_w2")
SERVICE_CONFIGS = ("G1_gevent_w1", "T1_gthread_w1_t4", "G2_gevent_w2", "T2_gthread_w2_t2")


class WorkerTopology:
    def __init__(
        self,
        out_dir: Path,
        *,
        worker_class: str,
        workers: int,
        threads: int = 0,
        maint: bool = False,
    ) -> None:
        self.out_dir = out_dir.resolve()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.worker_class = worker_class
        self.workers = int(workers)
        self.threads = int(threads)
        self.maint = bool(maint)
        self.container: Optional[str] = None
        self.port: Optional[int] = None
        self.log_path = self.out_dir / "container.log"
        self.data_dir = self.out_dir / "data"

    def _free_port(self) -> int:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def start(self, db_path: Path, *, reuse_db: bool = False) -> str:
        self.stop()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        game_db = self.data_dir / "game.db"
        if not reuse_db or not game_db.exists():
            copy_seed(db_path, game_db)
        if game_db.stat().st_size < 10_000_000:
            raise RuntimeError(f"db too small: {game_db.stat().st_size}")
        self.port = self._free_port()
        self.container = f"gc-repro005-{int(time.time())}-{os.getpid()}"
        self.log_path.write_text("", encoding="utf-8")

        env = [
            "-e",
            "GC_DB_PATH=/data/game.db",
            "-e",
            "GC_SKIP_MIGRATION_CHECK=1",
            "-e",
            "GC_MAINTENANCE_WORKER=1",
            "-e",
            "GC_EMBEDDED_CRON=0",
            "-e",
            f"GC_REPRO_MAINT={'1' if self.maint else '0'}",
            "-e",
            f"GUNICORN_WORKERS={self.workers}",
            "-e",
            f"GUNICORN_WORKER_CLASS={self.worker_class}",
            "-e",
            f"GUNICORN_THREADS={self.threads}",
            "-e",
            f"SECRET_KEY={SECRET}",
            "-e",
            "APP_ENV=development",
            "-e",
            "GC_DB_BACKEND=sqlite",
            "-e",
            "GC_REQUEST_PERF_DEBUG=1",
            "-e",
            "GC_REQUEST_PERF_SLOW_MS=0",
            "-e",
            "GC_REQUEST_PERF_SAMPLE=1.0",
        ]
        cmd = [
            "docker",
            "run",
            "--rm",
            "-d",
            "--name",
            self.container,
            "-p",
            f"127.0.0.1:{self.port}:5000",
            "-v",
            f"{str(ROOT.resolve())}:/app",
            "-v",
            f"{str(self.data_dir.resolve())}:/data",
            *env,
            DOCKER_IMAGE,
            "sh",
            "-c",
            "sed -i 's/\\r$//' /app/scripts/_repro005_topology_entry.sh && "
            "exec sh /app/scripts/_repro005_topology_entry.sh",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"docker run failed: {proc.stderr or proc.stdout}")
        self._wait_ready(timeout=180.0)
        self._capture_logs()
        return f"http://127.0.0.1:{self.port}"

    def _wait_ready(self, timeout: float) -> None:
        assert self.port is not None
        url = f"http://127.0.0.1:{self.port}/login"
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=3) as resp:
                    if int(resp.status) < 500:
                        return
            except Exception as exc:  # noqa: BLE001
                last = exc
            time.sleep(0.5)
        raise RuntimeError(f"container not ready: {last}")

    def _capture_logs(self) -> None:
        if not self.container:
            return
        proc = subprocess.run(
            ["docker", "logs", self.container],
            capture_output=True,
            text=True,
        )
        text = (proc.stdout or "") + (proc.stderr or "")
        self.log_path.write_text(text, encoding="utf-8", errors="replace")

    def stop(self) -> None:
        if self.container:
            subprocess.run(["docker", "rm", "-f", self.container], capture_output=True)
            self._capture_logs()
            self.container = None

    def exec_lock_holder(self, hold_sec: float) -> subprocess.Popen:
        assert self.container
        return subprocess.Popen(
            [
                "docker",
                "exec",
                self.container,
                "python",
                "/app/scripts/_repro005_lock_holder.py",
                "--db",
                "/data/game.db",
                "--hold-sec",
                str(hold_sec),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )


def _player_ids() -> List[int]:
    meta = ROOT / "artifacts/concurrency_repro/seed.meta.json"
    if meta.exists():
        data = json.loads(meta.read_text(encoding="utf-8"))
        pids = [int(x) for x in (data.get("players") or []) if x]
        if pids:
            return pids
    return list(range(2, 14))


def _timed_get(url: str, *, headers: Optional[Dict[str, str]] = None, timeout: float = 60.0) -> Dict[str, Any]:
    t0 = time.perf_counter()
    status = 0
    err = None
    nbytes = 0
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            status = int(resp.status)
            nbytes = len(body or b"")
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        try:
            nbytes = len(exc.read() or b"")
        except Exception:
            nbytes = 0
        err = f"HTTPError:{status}"
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}:{exc}"
    ms = (time.perf_counter() - t0) * 1000.0
    return {
        "url": url,
        "status": status,
        "duration_ms": round(ms, 2),
        "bytes": nbytes,
        "error": err,
    }


def run_load(
    base_url: str,
    *,
    clients: int,
    duration_sec: float,
    player_ids: List[int],
    health_probe: bool = True,
    jitter_seed: int = 42_000,
) -> Dict[str, Any]:
    cr = load_concurrency_repro()
    os.environ["SECRET_KEY"] = SECRET
    base_url = base_url.rstrip("/")
    cr._wait_http(f"{base_url}/login", timeout=120)
    chosen = player_ids[: max(1, min(clients, len(player_ids)))]
    authed = [cr.AuthedClient(base_url, pid) for pid in chosen]
    samples: List[Any] = []
    health_samples: List[float] = []
    lock = threading.Lock()
    stop_at = time.time() + duration_sec
    threads: List[threading.Thread] = []

    def _health_loop() -> None:
        while time.time() < stop_at:
            hit = _timed_get(f"{base_url}/healthz", timeout=45)
            with lock:
                health_samples.append(float(hit["duration_ms"]))
            time.sleep(0.2)

    for i, client in enumerate(authed):
        rng = random.Random(jitter_seed + i)
        t = threading.Thread(
            target=cr._client_loop,
            args=(client, stop_at, samples, lock, rng),
            daemon=True,
        )
        threads.append(t)
        t.start()
    if health_probe:
        ht = threading.Thread(target=_health_loop, daemon=True)
        threads.append(ht)
        ht.start()
    for t in threads:
        t.join()

    analysis = analyze_samples(samples, [])
    gs_samples = [s for s in samples if s.route == "/api/game-state"]
    gs_ok = sum(1 for s in gs_samples if int(s.status) == 200)
    return {
        "clients": len(authed),
        "duration_sec": duration_sec,
        "request_count": len(samples),
        "requests_per_sec": round(len(samples) / duration_sec, 2) if duration_sec else 0,
        "auth_ok_ratio_game_state": round(gs_ok / len(gs_samples), 4) if gs_samples else 0,
        "analysis": analysis,
        "game_state": route_stats(analysis, "/api/game-state"),
        "by_route": {r: route_stats(analysis, r) for r in ROUTES},
        "healthz": summarize_ms(health_samples),
        "slow2": int(analysis.get("slow_ge_2000_count") or 0),
        "slow5": int(analysis.get("slow_ge_5000_count") or 0),
    }


def microtest_once(
    topo: WorkerTopology,
    base_url: str,
    *,
    player_id: int,
    hold_sec: float = 5.0,
) -> Dict[str, Any]:
    """Hold BEGIN IMMEDIATE, fire write + healthz + login in parallel."""
    cr = load_concurrency_repro()
    os.environ["SECRET_KEY"] = SECRET
    client = cr.AuthedClient(base_url, player_id)

    # Warm /healthz so first-hit noise is not counted as the stall.
    warm = _timed_get(f"{base_url}/healthz", timeout=10)

    holder = topo.exec_lock_holder(hold_sec)
    assert holder.stdout is not None
    acquired = False
    buf_lines: List[str] = []
    deadline = time.time() + 20.0
    while time.time() < deadline:
        line = holder.stdout.readline()
        if line:
            buf_lines.append(line.rstrip())
            if "acquired_ms=" in line:
                acquired = True
                break
        elif holder.poll() is not None:
            break
        else:
            time.sleep(0.05)

    if not acquired:
        # Drain and fail soft — still fire probes for diagnostics.
        try:
            rest, _ = holder.communicate(timeout=2)
            if rest:
                buf_lines.extend(rest.splitlines())
        except Exception:
            pass

    results: Dict[str, Any] = {
        "warm_healthz_ms": warm.get("duration_ms"),
        "lock_acquired": acquired,
    }
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = {
            pool.submit(
                client.request,
                "/api/game-state",
                f"micro-write-{int(time.time() * 1000)}",
            ): "A_write_game_state",
            pool.submit(
                _timed_get, f"{base_url}/healthz", timeout=hold_sec + 25
            ): "B_healthz",
            pool.submit(
                _timed_get, f"{base_url}/login", timeout=hold_sec + 25
            ): "C_login_read",
        }
        for fut in as_completed(futs):
            key = futs[fut]
            try:
                val = fut.result()
                if hasattr(val, "duration_ms"):
                    results[key] = {
                        "duration_ms": round(float(val.duration_ms), 2),
                        "status": int(val.status),
                        "error": val.error,
                        "route": getattr(val, "route", None),
                    }
                else:
                    results[key] = val
            except Exception as exc:  # noqa: BLE001
                results[key] = {"error": str(exc), "duration_ms": None}

    try:
        rest, _ = holder.communicate(timeout=hold_sec + 30)
        if rest:
            buf_lines.extend(rest.splitlines())
    except Exception:
        holder.kill()
    results["lock_holder_log"] = "\n".join(buf_lines)[-1500:]
    results["lock_holder_rc"] = holder.returncode
    results["hold_sec"] = hold_sec
    return results


def phase_micro(
    out_dir: Path,
    state_db: Path,
    *,
    hold_sec: float,
    reps: int,
) -> Dict[str, Any]:
    print("== MICROTEST: lock-blocking worker-class causality ==")
    out: Dict[str, Any] = {"hold_sec": hold_sec, "reps": reps, "configs": {}}
    pids = _player_ids()
    for name in MICRO_CONFIGS:
        cfg = WORKER_CONFIGS[name]
        print(f"-- micro {name}")
        runs = []
        for rep in range(1, reps + 1):
            label_dir = out_dir / "micro" / name / f"r{rep}"
            topo = WorkerTopology(
                label_dir,
                worker_class=cfg["class"],
                workers=cfg["workers"],
                threads=cfg["threads"],
                maint=False,
            )
            try:
                base = topo.start(state_db)
                # Settle after boot
                time.sleep(1.0)
                hit = microtest_once(topo, base, player_id=pids[0], hold_sec=hold_sec)
                hit["rep"] = rep
                runs.append(hit)
                a = (hit.get("A_write_game_state") or {}).get("duration_ms")
                b = (hit.get("B_healthz") or {}).get("duration_ms")
                c = (hit.get("C_login_read") or {}).get("duration_ms")
                print(f"  rep={rep} A={a} B_healthz={b} C_login={c}")
            finally:
                topo.stop()
            time.sleep(0.5)

        def _avg(key: str) -> float:
            vals = [
                float((r.get(key) or {}).get("duration_ms") or 0)
                for r in runs
                if (r.get(key) or {}).get("duration_ms") is not None
            ]
            return round(sum(vals) / len(vals), 2) if vals else 0.0

        out["configs"][name] = {
            "worker": cfg,
            "runs": runs,
            "avg": {
                "writer_wait_ms": _avg("A_write_game_state"),
                "healthz_during_wait_ms": _avg("B_healthz"),
                "read_during_wait_ms": _avg("C_login_read"),
            },
        }
    return out


def phase_service(
    out_dir: Path,
    states: Dict[str, Path],
    *,
    clients: int,
    duration: float,
    configs: Tuple[str, ...] = SERVICE_CONFIGS,
) -> Dict[str, Any]:
    print("== SERVICE TEST S0/S5 ==")
    out: Dict[str, Any] = {}
    pids = _player_ids()
    for state_name, db_path in states.items():
        out[state_name] = {}
        for name in configs:
            cfg = WORKER_CONFIGS[name]
            label = f"{state_name}_{name}"
            print(f"-- service {label}")
            topo = WorkerTopology(
                out_dir / "service" / label,
                worker_class=cfg["class"],
                workers=cfg["workers"],
                threads=cfg["threads"],
                maint=False,
            )
            try:
                base = topo.start(db_path)
                load = run_load(
                    base,
                    clients=clients,
                    duration_sec=duration,
                    player_ids=pids,
                    health_probe=True,
                )
                report = {
                    "config": cfg,
                    "load": load,
                    "topology": {
                        "worker_class": cfg["class"],
                        "workers": cfg["workers"],
                        "threads": cfg["threads"],
                    },
                }
                (out_dir / f"{label}_report.json").write_text(
                    json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
                )
                gs = load["game_state"]
                hz = load["healthz"]
                print(
                    f"  gs_p50={gs.get('p50_ms')} gs_p95={gs.get('p95_ms')} "
                    f"hz_p95={hz.get('p95_ms')} slow5={load.get('slow5')} "
                    f"auth={load.get('auth_ok_ratio_game_state')}"
                )
                out[state_name][name] = report
            finally:
                topo.stop()
    return out


def phase_thundering(
    out_dir: Path,
    s5: Path,
    *,
    duration: float,
) -> Dict[str, Any]:
    print("== THUNDERING HERD S5 (8 clients) ==")
    out = {}
    pids = _player_ids()
    for name in ("G1_gevent_w1", "T1_gthread_w1_t4"):
        cfg = WORKER_CONFIGS[name]
        print(f"-- thunder {name}")
        topo = WorkerTopology(
            out_dir / "thunder" / name,
            worker_class=cfg["class"],
            workers=cfg["workers"],
            threads=cfg["threads"],
            maint=False,
        )
        try:
            base = topo.start(s5)
            load = run_load(
                base,
                clients=8,
                duration_sec=duration,
                player_ids=pids,
                health_probe=True,
            )
            out[name] = {"config": cfg, "load": load}
            print(
                f"  gs_p95={load['game_state'].get('p95_ms')} "
                f"hz_p95={load['healthz'].get('p95_ms')} slow5={load.get('slow5')}"
            )
        finally:
            topo.stop()
    return out


def phase_websocket_gate() -> Dict[str, Any]:
    """Check existing WS contracts / optional smoke — no production change."""
    print("== WEBSOCKET GATE ==")
    # Prefer existing unit contracts that encode gevent/WS assumptions.
    tests = [
        "tests/test_gc_request_perf_trace.py::test_should_skip_websocket_paths",
    ]
    # Discover skip-path test name flexibly
    src = (ROOT / "tests" / "test_gc_request_perf_trace.py").read_text(encoding="utf-8")
    has_skip = "should_skip_path" in src and "/ws/galaxy" in src
    result: Dict[str, Any] = {
        "gevent_reason": "docker-entrypoint: long-lived /ws/galaxy with gevent",
        "existing_skip_path_contract": has_skip,
        "browser_ws_live_test": "not present as dedicated pytest",
        "status": "partial",
    }
    # Smoke: import flask_sock + route exists
    app_src = (ROOT / "app.py").read_text(encoding="utf-8", errors="replace")
    result["route_present"] = '@sock.route("/ws/galaxy/' in app_src or "/ws/galaxy/" in app_src
    # Try running the skip-path assertions via pytest if available (quick).
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_gc_request_perf_trace.py",
                "-q",
                "-k",
                "skip_path or websocket or ws_galaxy",
                "--tb=no",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        result["pytest_rc"] = proc.returncode
        result["pytest_tail"] = ((proc.stdout or "") + (proc.stderr or ""))[-800:]
        if proc.returncode == 0:
            result["status"] = "pass"
        else:
            result["status"] = "partial"
    except Exception as exc:  # noqa: BLE001
        result["pytest_error"] = str(exc)
        result["status"] = "not tested"
    return result


def evaluate_causality(micro: Dict[str, Any]) -> Dict[str, Any]:
    g1 = ((micro.get("configs") or {}).get("G1_gevent_w1") or {}).get("avg") or {}
    t1 = ((micro.get("configs") or {}).get("T1_gthread_w1_t4") or {}).get("avg") or {}
    g_hz = float(g1.get("healthz_during_wait_ms") or 0)
    t_hz = float(t1.get("healthz_during_wait_ms") or 0)
    g_w = float(g1.get("writer_wait_ms") or 0)
    # Confirmed if gevent healthz rides with writer (~hold), gthread healthz stays low.
    gevent_blocked = g_hz >= 2000 and g_w >= 2000
    gthread_responsive = t_hz < max(500.0, g_hz * 0.25) if g_hz > 0 else t_hz < 500
    confirmed = bool(gevent_blocked and gthread_responsive)
    return {
        "SYSTEM_FAILURE_MECHANISM": "confirmed" if confirmed else "under investigation",
        "GEVENT_EVENT_LOOP_BLOCK": "confirmed yes" if gevent_blocked else "no",
        "gevent_w1": g1,
        "gthread_w1_t4": t1,
        "gate_gevent_healthz_high": gevent_blocked,
        "gate_gthread_healthz_low": gthread_responsive,
    }


def option_paper() -> Dict[str, Any]:
    return {
        "A_gthread_instead_of_gevent": {
            "freeze_risk": "low if OS threads allow concurrent green-path while one waits on sqlite",
            "sqlite_writer_contention": "unchanged (same DB)",
            "websocket_impact": "HIGH RISK — gevent chosen for long-lived /ws/galaxy",
            "impl_risk": "low (env override exists)",
            "deploy_risk": "medium — needs WS soak",
            "expected_perf": "better availability under lock waits; not fewer lock waits",
        },
        "B_more_gevent_workers": {
            "freeze_risk": "medium — other workers serve while one blocks",
            "sqlite_writer_contention": "may increase (more processes)",
            "websocket_impact": "low",
            "impl_risk": "low (GUNICORN_WORKERS)",
            "deploy_risk": "low-medium",
            "expected_perf": "REPRO-004: ~2x p95 improvement; stalls remain",
        },
        "C_remove_writes_from_GET_poll": {
            "freeze_risk": "low if hot path stays read-only",
            "sqlite_writer_contention": "reduced on poll path",
            "websocket_impact": "none",
            "impl_risk": "medium-high (correctness of fleet/queue freshness)",
            "deploy_risk": "medium",
            "expected_perf": "best structural fix for poll storms",
        },
        "D_offload_blocking_sqlite_to_thread_pool": {
            "freeze_risk": "low for gevent event loop",
            "sqlite_writer_contention": "unchanged",
            "websocket_impact": "none/low",
            "impl_risk": "high (conn ownership, greenlet safety)",
            "deploy_risk": "high",
            "expected_perf": "keeps gevent WS model while unblocking loop",
        },
        "E_postgres_long_term": {
            "freeze_risk": "low (no single-file writer lock)",
            "sqlite_writer_contention": "eliminated",
            "websocket_impact": "none",
            "impl_risk": "very high (migration)",
            "deploy_risk": "high",
            "expected_perf": "architectural endgame",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", default=str(SEED_DEFAULT))
    parser.add_argument("--out-dir", default=str(OUT_DEFAULT))
    parser.add_argument(
        "--phase",
        choices=("micro", "service", "thundering", "websocket", "all"),
        default="all",
    )
    parser.add_argument("--clients", type=int, default=4)
    parser.add_argument("--duration-sec", type=float, default=60)
    parser.add_argument("--hold-sec", type=float, default=5.0)
    parser.add_argument("--micro-reps", type=int, default=3)
    args = parser.parse_args()

    seed = Path(args.seed).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if not seed.exists():
        raise SystemExit(f"missing seed: {seed}")

    # Ensure Docker
    di = subprocess.run(["docker", "info"], capture_output=True, text=True)
    if di.returncode != 0:
        raise SystemExit("Docker daemon required for REPRO-005")

    states_dir = out_dir / "states"
    s0 = states_dir / "S0_NORMALIZED.db"
    s5 = states_dir / "S5_FLEET_AND_QUEUES.db"
    if not s0.exists():
        print("Preparing S0...")
        prepare_state(seed, s0, "S0_NORMALIZED")
    if not s5.exists():
        print("Preparing S5...")
        prepare_state(seed, s5, "S5_FLEET_AND_QUEUES")

    final: Dict[str, Any] = {
        "created_at": int(time.time()),
        "seed": str(seed),
        "note": "SYSTEM FAILURE MECHANISM vs HISTORICAL INCIDENT TRIGGER separated",
        "harness": "docker gunicorn worker-class causality",
    }

    if args.phase in ("micro", "all"):
        # Use S5 so game-state write path is more likely to hit BEGIN IMMEDIATE.
        final["micro"] = phase_micro(out_dir, s5, hold_sec=args.hold_sec, reps=args.micro_reps)
        final["causality"] = evaluate_causality(final["micro"])

    if args.phase in ("service", "all"):
        final["service"] = phase_service(
            out_dir,
            {"S0": s0, "S5": s5},
            clients=args.clients,
            duration=args.duration_sec,
        )

    if args.phase in ("thundering", "all"):
        final["thundering"] = phase_thundering(out_dir, s5, duration=args.duration_sec)

    if args.phase in ("websocket", "all"):
        final["websocket"] = phase_websocket_gate()

    final["options_paper"] = option_paper()

    # Gates
    causality = final.get("causality") or evaluate_causality(final.get("micro") or {})
    final["SYSTEM_FAILURE_MECHANISM"] = causality.get("SYSTEM_FAILURE_MECHANISM", "under investigation")
    final["GEVENT_EVENT_LOOP_BLOCK"] = causality.get("GEVENT_EVENT_LOOP_BLOCK", "under investigation")
    final["HISTORICAL_INCIDENT_TRIGGER"] = "under investigation"
    final["ROOT_CAUSE"] = {
        "Mechanism": final["SYSTEM_FAILURE_MECHANISM"],
        "Trigger": final["HISTORICAL_INCIDENT_TRIGGER"],
    }
    final["WEBSOCKET_GATE"] = (final.get("websocket") or {}).get("status", "not tested")
    final["BEST_WORKER_MODEL"] = (
        "experimental: prefer gthread for availability IF websocket gate passes; "
        "else keep gevent and pursue option C/D"
    )
    final["NEXT_ACTION"] = (
        "If mechanism confirmed: do NOT flip worker class in prod yet — "
        "soak websocket/galaxy; prefer evaluating poll-path write removal (C) "
        "and/or thread-offload of blocking sqlite (D). Search historical trigger next."
    )

    out_path = out_dir / "repro005_summary.json"
    out_path.write_text(json.dumps(final, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote {out_path}")
    print(
        f"SYSTEM_FAILURE_MECHANISM={final['SYSTEM_FAILURE_MECHANISM']} "
        f"GEVENT_EVENT_LOOP_BLOCK={final['GEVENT_EVENT_LOOP_BLOCK']} "
        f"WEBSOCKET_GATE={final['WEBSOCKET_GATE']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
