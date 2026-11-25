#!/usr/bin/env python3
"""GC-PROD-INFINITY-LOAD-REPRO-004 — production topology + state replay.

Uses Docker (gunicorn gevent + maintenance sidecar) when available.
No hotfix / no Railway / no main merge.

Examples:
  python scripts/prod_infinity_load_repro004.py --phase topology
  python scripts/prod_infinity_load_repro004.py --phase control
  python scripts/prod_infinity_load_repro004.py --phase sidecar
  python scripts/prod_infinity_load_repro004.py --phase states --states S0_NORMALIZED,S5_FLEET_AND_QUEUES
  python scripts/prod_infinity_load_repro004.py --phase all
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from _repro004_common import (  # noqa: E402
    ROUTES,
    SECRET,
    STATE_IDS,
    aggregate_write_paths,
    analyze_samples,
    copy_seed,
    load_concurrency_repro,
    parse_server_perf,
    penalty,
    route_stats,
    summarize_ms,
    topology_verified,
    verify_topology_logs,
)

OUT_DEFAULT = ROOT / "artifacts" / "concurrency_repro" / "repro004"
DOCKER_IMAGE = "python:3.12-slim-bookworm"


class TopologyRunner:
    def __init__(self, out_dir: Path, *, workers: int = 1, maint: bool = True) -> None:
        self.out_dir = out_dir.resolve()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.workers = int(workers)
        self.maint = bool(maint)
        self.container: Optional[str] = None
        self.port: Optional[int] = None
        self.log_path = self.out_dir / "container.log"

    def _free_port(self) -> int:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def start(self, db_path: Path) -> str:
        self.stop()
        data_dir = self.out_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        game_db = data_dir / "game.db"
        copy_seed(db_path, game_db)
        self.port = self._free_port()
        self.container = f"gc-repro004-{int(time.time())}"
        self.log_path.write_text("", encoding="utf-8")

        repo = str(ROOT.resolve())
        data = str(data_dir.resolve())
        env = [
            "-e",
            f"GC_DB_PATH=/data/game.db",
            "-e",
            "GC_SKIP_MIGRATION_CHECK=1",
            "-e",
            "GC_MAINTENANCE_WORKER=1",
            "-e",
            "GC_EMBEDDED_CRON=0",
            "-e",
            f"GC_REPRO004_MAINT={'1' if self.maint else '0'}",
            "-e",
            f"GUNICORN_WORKERS={self.workers}",
            "-e",
            "GUNICORN_WORKER_CLASS=gevent",
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
            "-e",
            "GC_FLASK_THREADED=0",
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
            f"{repo}:/app",
            "-v",
            f"{data}:/data",
            *env,
            DOCKER_IMAGE,
            "sh",
            "-c",
            "sed -i 's/\\r$//' /app/scripts/_repro004_topology_entry.sh && exec sh /app/scripts/_repro004_topology_entry.sh",
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

    def restart(self, db_path: Path) -> str:
        """Stop/start container keeping same DB directory."""
        data_dir = self.out_dir / "data"
        if not (data_dir / "game.db").exists():
            copy_seed(db_path, data_dir / "game.db")
        was_maint = self.maint
        was_workers = self.workers
        self.stop()
        self.maint = was_maint
        self.workers = was_workers
        return self.start(data_dir / "game.db")


def run_load(
    base_url: str,
    *,
    clients: int,
    duration_sec: float,
    player_ids: List[int],
    jitter_seed: int = 42_000,
    health_probe: bool = False,
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
            t0 = time.time()
            try:
                with urllib.request.urlopen(f"{base_url}/healthz", timeout=30) as resp:
                    resp.read()
                    status = int(resp.status)
            except Exception:
                status = 0
            ms = (time.time() - t0) * 1000.0
            with lock:
                health_samples.append(ms)
            if ms >= 2000:
                print(f"[HEALTHZ SLOW] {ms:.0f}ms status={status}")
            time.sleep(0.25)

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

    wall = duration_sec
    analysis = analyze_samples(samples, [])
    gs_samples = [s for s in samples if s.route == "/api/game-state"]
    gs_ok = sum(1 for s in gs_samples if int(s.status) == 200)
    report = {
        "clients": len(authed),
        "duration_sec": duration_sec,
        "request_count": len(samples),
        "requests_per_sec": round(len(samples) / wall, 2) if wall else 0,
        "auth_ok_ratio_game_state": round(gs_ok / len(gs_samples), 4) if gs_samples else 0,
        "analysis": analysis,
        "game_state": route_stats(analysis, "/api/game-state"),
        "galaxy": route_stats(analysis, "/galaxy"),
        "by_route": {r: route_stats(analysis, r) for r in ROUTES},
        "healthz": summarize_ms(health_samples),
    }
    return report


def run_experiment(
    *,
    label: str,
    db_path: Path,
    out_dir: Path,
    clients: int,
    duration_sec: float,
    player_ids: List[int],
    workers: int = 1,
    maint: bool = True,
    health_probe: bool = False,
) -> Dict[str, Any]:
    runner = TopologyRunner(out_dir / label, workers=workers, maint=maint)
    try:
        base = runner.start(db_path)
        print(f"{label}: {base} workers={workers} maint={maint}")
        load = run_load(
            base,
            clients=clients,
            duration_sec=duration_sec,
            player_ids=player_ids,
            health_probe=health_probe,
        )
        runner._capture_logs()
        logs = runner.log_path.read_text(encoding="utf-8", errors="replace")
        topo = verify_topology_logs(logs)
        if not maint:
            topo["no_sidecar_mode"] = True
        perf = parse_server_perf(runner.log_path)
        payload = {
            "label": label,
            "base_url": base,
            "topology_checks": topo,
            "topology_verified": topology_verified(topo),
            "load": load,
            "write_paths": aggregate_write_paths(perf),
            "perf_rows": len(perf),
        }
        (out_dir / f"{label}_report.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        gs = load["game_state"]
        print(
            f"{label}: gs_p50={gs.get('p50_ms')} gs_p95={gs.get('p95_ms')} "
            f"slow5={load['analysis'].get('slow_ge_5000_count')} "
            f"topo={payload['topology_verified']}"
        )
        return payload
    finally:
        runner.stop()


def phase_topology(out_dir: Path, db_path: Path) -> Dict[str, Any]:
    rep = run_experiment(
        label="topology_check",
        db_path=db_path,
        out_dir=out_dir,
        clients=1,
        duration_sec=10,
        player_ids=_player_ids(db_path),
        workers=1,
        maint=True,
    )
    return rep


def phase_control(out_dir: Path, db_path: Path, clients: int, duration: float) -> Dict[str, Any]:
    return run_experiment(
        label="control_no_maint",
        db_path=db_path,
        out_dir=out_dir,
        clients=clients,
        duration_sec=duration,
        player_ids=_player_ids(db_path),
        workers=1,
        maint=False,
    )


def phase_sidecar(
    out_dir: Path,
    db_path: Path,
    clients: int,
    duration: float,
    *,
    control: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    rep = run_experiment(
        label="sidecar_maint",
        db_path=db_path,
        out_dir=out_dir,
        clients=clients,
        duration_sec=duration,
        player_ids=_player_ids(db_path),
        workers=1,
        maint=True,
    )
    if control:
        rep["maintenance_penalty"] = penalty(
            rep["load"]["game_state"],
            control["load"]["game_state"],
        )
    return rep


def phase_states(
    out_dir: Path,
    seed: Path,
    state_ids: List[str],
    clients: int,
    duration: float,
) -> Dict[str, Any]:
    from _repro004_prepare_state import prepare_state

    results = {}
    for sid in state_ids:
        state_db = out_dir / "states" / f"{sid}.db"
        prepare_state(seed, state_db, sid)
        results[sid] = run_experiment(
            label=f"state_{sid}",
            db_path=state_db,
            out_dir=out_dir,
            clients=clients,
            duration_sec=duration,
            player_ids=_player_ids(state_db),
            workers=1,
            maint=True,
            health_probe=False,
        )
    return results


def phase_thundering_herd(out_dir: Path, state_db: Path, clients: int, duration: float) -> Dict[str, Any]:
    return run_experiment(
        label="thundering_herd_S5",
        db_path=state_db,
        out_dir=out_dir,
        clients=max(clients, 8),
        duration_sec=duration,
        player_ids=_player_ids(state_db),
        workers=1,
        maint=True,
        health_probe=True,
    )


def phase_gevent_block(out_dir: Path, state_db: Path) -> Dict[str, Any]:
    """Load S5 + parallel /healthz to detect whole-worker blocking."""
    rep = run_experiment(
        label="gevent_block_probe",
        db_path=state_db,
        out_dir=out_dir,
        clients=10,
        duration_sec=75,
        player_ids=_player_ids(state_db),
        workers=1,
        maint=True,
        health_probe=True,
    )
    hz = rep["load"].get("healthz") or {}
    rep["GEVENT_WORKER_BLOCKED_BY_SQLITE_WAIT"] = bool(
        float(hz.get("p95_ms") or 0) >= 2000.0 or float(hz.get("max_ms") or 0) >= 5000.0
    )
    return rep


def phase_workers_compare(out_dir: Path, db_path: Path, clients: int, duration: float) -> Dict[str, Any]:
    w1 = run_experiment(
        label="workers_1",
        db_path=db_path,
        out_dir=out_dir,
        clients=clients,
        duration_sec=duration,
        player_ids=_player_ids(db_path),
        workers=1,
        maint=True,
    )
    w2 = run_experiment(
        label="workers_2",
        db_path=db_path,
        out_dir=out_dir,
        clients=clients,
        duration_sec=duration,
        player_ids=_player_ids(db_path),
        workers=2,
        maint=True,
    )
    return {
        "workers_1": w1,
        "workers_2": w2,
        "delta_p95": round(
            float(w2["load"]["game_state"].get("p95_ms") or 0)
            - float(w1["load"]["game_state"].get("p95_ms") or 0),
            2,
        ),
    }


def phase_restart(out_dir: Path, state_db: Path, clients: int, duration: float) -> Dict[str, Any]:
    runner = TopologyRunner(out_dir / "restart_test", workers=1, maint=True)
    try:
        base = runner.start(state_db)
        before = run_load(
            base,
            clients=clients,
            duration_sec=duration,
            player_ids=_player_ids(state_db),
        )
        runner.stop()
        base2 = runner.start(state_db)
        after = run_load(
            base2,
            clients=clients,
            duration_sec=duration,
            player_ids=_player_ids(state_db),
        )
        cleared = float(before["game_state"].get("p95_ms") or 0) > 1500 and float(
            after["game_state"].get("p95_ms") or 0
        ) < float(before["game_state"].get("p95_ms") or 0) * 0.6
        return {
            "before": before,
            "after": after,
            "RESTART_CLEARS_STALL": "yes" if cleared else "no",
        }
    finally:
        runner.stop()


def _player_ids(db_path: Path) -> List[int]:
    meta = db_path.with_suffix(".meta.json")
    seed_meta = ROOT / "artifacts/concurrency_repro/seed.meta.json"
    path = meta if meta.exists() else seed_meta
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        pids = [int(x) for x in (data.get("players") or []) if x]
        if pids:
            return pids
        return [int(data.get("primary_player_id") or 2)]
    return list(range(2, 14))


def _docker_ok() -> bool:
    try:
        proc = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=30)
        return proc.returncode == 0
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", default=str(ROOT / "artifacts/concurrency_repro/seed.db"))
    parser.add_argument("--out-dir", default=str(OUT_DEFAULT))
    parser.add_argument(
        "--phase",
        choices=(
            "topology",
            "control",
            "sidecar",
            "states",
            "thundering",
            "gevent",
            "workers",
            "restart",
            "owner",
            "all",
        ),
        default="all",
    )
    parser.add_argument("--clients", type=int, default=4)
    parser.add_argument("--duration-sec", type=float, default=75)
    parser.add_argument("--states", default="S0_NORMALIZED,S5_FLEET_AND_QUEUES,S7_WORST_PLAUSIBLE")
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    seed = Path(args.seed).resolve()
    if not seed.exists():
        raise SystemExit(f"missing seed: {seed}")

    if not _docker_ok():
        raise SystemExit("Docker daemon required for REPRO-004 production topology")

    s0 = out_dir / "states" / "S0_NORMALIZED.db"
    if not s0.exists():
        from _repro004_prepare_state import prepare_state

        prepare_state(seed, s0, "S0_NORMALIZED")

    final: Dict[str, Any] = {
        "created_at": int(time.time()),
        "seed": str(seed),
        "harness": "docker gunicorn gevent + optional maintenance sidecar",
    }

    if args.phase in ("owner", "all"):
        subprocess.run([sys.executable, str(ROOT / "scripts/_repro004_owner_matrix.py")], check=False)
        om_src = ROOT / "artifacts/concurrency_repro/repro004/owner_matrix.json"
        om = out_dir / "owner_matrix.json"
        if om_src.exists() and om_src.resolve() != om.resolve():
            shutil.copy2(om_src, om)
        elif om_src.exists():
            om = om_src
        final["owner_matrix"] = json.loads(om.read_text(encoding="utf-8")) if om.exists() else {}

    if args.phase in ("topology", "all"):
        final["topology"] = phase_topology(out_dir, s0)

    control = None
    if args.phase in ("control", "all"):
        control = phase_control(out_dir, s0, args.clients, args.duration_sec)
        final["control"] = control

    if args.phase in ("sidecar", "all"):
        if control is None and (out_dir / "control_no_maint_report.json").exists():
            control = json.loads(
                (out_dir / "control_no_maint_report.json").read_text(encoding="utf-8")
            )
        final["sidecar"] = phase_sidecar(
            out_dir,
            s0,
            args.clients,
            args.duration_sec,
            control=control,
        )

    if args.phase in ("states", "all"):
        ids = [s.strip() for s in args.states.split(",") if s.strip()]
        final["states"] = phase_states(out_dir, seed, ids, args.clients, args.duration_sec)

    s5 = out_dir / "states" / "S5_FLEET_AND_QUEUES.db"
    if args.phase in ("thundering", "all"):
        from _repro004_prepare_state import prepare_state

        if not s5.exists():
            prepare_state(seed, s5, "S5_FLEET_AND_QUEUES")
        final["thundering_herd"] = phase_thundering_herd(
            out_dir, s5, args.clients, args.duration_sec
        )

    if args.phase in ("gevent", "all"):
        from _repro004_prepare_state import prepare_state

        if not s5.exists():
            prepare_state(seed, s5, "S5_FLEET_AND_QUEUES")
        final["gevent"] = phase_gevent_block(out_dir, s5)

    if args.phase in ("workers", "all"):
        final["workers"] = phase_workers_compare(out_dir, s5 if s5.exists() else s0, args.clients, args.duration_sec)

    if args.phase in ("restart", "all"):
        from _repro004_prepare_state import prepare_state

        if not s5.exists():
            prepare_state(seed, s5, "S5_FLEET_AND_QUEUES")
        final["restart"] = phase_restart(out_dir, s5, args.clients, min(args.duration_sec, 45))

    # Gates
    topo = (final.get("topology") or {}).get("topology_verified")
    final["PRODUCTION_TOPOLOGY"] = "verified" if topo else "not verified"
    ctrl_gs = ((final.get("control") or {}).get("load") or {}).get("game_state") or {}
    side = final.get("sidecar") or {}
    final["CONTROL"] = ctrl_gs
    final["SIDECAR_PENALTY"] = side.get("maintenance_penalty")
    final["SYSTEM_FAILURE_MODE"] = any(
        float(((v.get("load") or {}).get("analysis") or {}).get("slow_ge_5000_count") or 0) > 0
        for v in final.values()
        if isinstance(v, dict) and "load" in v
    )
    final["HISTORICAL_INCIDENT"] = "reproduced no"
    final["ROOT_CAUSE"] = "under investigation"
    gevent = final.get("gevent") or {}
    final["GEVENT_WORKER_BLOCKED_BY_SQLITE_WAIT"] = gevent.get(
        "GEVENT_WORKER_BLOCKED_BY_SQLITE_WAIT", "not tested"
    )

    summary_path = out_dir / "repro004_summary.json"
    summary_path.write_text(json.dumps(final, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote {summary_path}")
    print(f"PRODUCTION_TOPOLOGY={final['PRODUCTION_TOPOLOGY']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
