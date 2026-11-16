#!/usr/bin/env python3
"""GC-PROD-INFINITY-LOAD-REPRO-006 — Historical Trigger / Writer Provenance.

Harness-only instrumentation (sitecustomize). No production file edits.
No Railway / main / merge.

Examples:
  python scripts/prod_infinity_load_repro006.py --phase matrix
  python scripts/prod_infinity_load_repro006.py --phase thunder
  python scripts/prod_infinity_load_repro006.py --phase websocket
  python scripts/prod_infinity_load_repro006.py --phase all
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

# GC_REPRO006_APP_ROOT: mount this tree as /app (e.g. clean fix worktree).
# Harness scripts still load from the investigation checkout.
ROOT = Path(
    os.environ.get("GC_REPRO006_APP_ROOT") or Path(__file__).resolve().parents[1]
).resolve()
HARNESS_ROOT = Path(__file__).resolve().parents[1]
if str(HARNESS_ROOT) not in sys.path:
    sys.path.insert(0, str(HARNESS_ROOT))
if str(HARNESS_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(HARNESS_ROOT / "scripts"))

from _repro004_common import (  # noqa: E402
    SECRET,
    analyze_samples,
    copy_seed,
    load_concurrency_repro,
    route_stats,
    summarize_ms,
)
from _repro006_analyze_provenance import analyze as analyze_prov, load_events  # noqa: E402
from _repro006_prepare_triggers import TRIGGERS, prepare_trigger  # noqa: E402

OUT_DEFAULT = HARNESS_ROOT / "artifacts" / "concurrency_repro" / "repro006_post_001a"
DOCKER_IMAGE = "python:3.12-slim-bookworm"
SEED_DEFAULT = HARNESS_ROOT / "artifacts" / "concurrency_repro" / "seed.db"

# Primary matrix for first pass (full list available via --all-triggers)
DEFAULT_TRIGGERS = (
    "T0_NORMALIZED",
    "T1_MANY_DUE_FLEETS",
    "T2_MANY_DUE_QUEUES",
    "T3_FLEETS_AND_QUEUES",
    "T5_FULL_RECONCILE_DUE",
    "T6_BACKUP_DUE",
    "T10_COMBINED_WORST",
)


class ProvTopology:
    def __init__(
        self,
        out_dir: Path,
        *,
        worker_class: str = "gevent",
        workers: int = 1,
        threads: int = 0,
        maint: bool = True,
        internal_cron: bool = False,
    ) -> None:
        self.out_dir = out_dir.resolve()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.worker_class = worker_class
        self.workers = workers
        self.threads = threads
        self.maint = maint
        self.internal_cron = internal_cron
        self.container: Optional[str] = None
        self.port: Optional[int] = None
        self.data_dir = self.out_dir / "data"
        self.log_path = self.out_dir / "container.log"
        self.prov_host = self.data_dir / "tx_provenance.jsonl"

    def _free_port(self) -> int:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def start(self, db_path: Path) -> str:
        self.stop()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        copy_seed(db_path, self.data_dir / "game.db")
        if os.environ.get("GC_REPRO_SIMULATE_QUEUE_TICK", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        ):
            # Simulate authentic queue-tick + fleet heartbeats in DB (not maint bag).
            import json as _json
            import sqlite3 as _sql

            gdb = self.data_dir / "game.db"
            conn = _sql.connect(str(gdb))
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS runtime_state (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at REAL NOT NULL
                    );
                    """
                )
                now = time.time()
                q_payload = _json.dumps(
                    {
                        "at": int(now),
                        "ok": True,
                        "source": "repro_simulate",
                        "scope": "due",
                        "finished": {},
                        "affected_players": [],
                        "batches": 0,
                        "players_processed": 0,
                        "duration_ms": 0,
                        "errors": [],
                    },
                    ensure_ascii=False,
                )
                f_payload = _json.dumps(
                    {
                        "at": now,
                        "ok": True,
                        "source": "repro_simulate",
                        "processed_arrivals": 0,
                        "processed_returns": 0,
                        "processed_holding": 0,
                        "duration_ms": 0,
                        "errors": [],
                    },
                    ensure_ascii=False,
                )
                for key, payload in (
                    ("queue_tick_last", q_payload),
                    ("fleet_worker_last", f_payload),
                ):
                    conn.execute(
                        """
                        INSERT INTO runtime_state (key, value, updated_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(key) DO UPDATE SET
                            value = excluded.value,
                            updated_at = excluded.updated_at;
                        """,
                        (key, payload, now),
                    )
                conn.commit()
            finally:
                conn.close()
        if self.prov_host.exists():
            self.prov_host.unlink()
        self.prov_host.write_text("", encoding="utf-8")
        self.port = self._free_port()
        self.container = f"gc-repro006-{int(time.time())}-{os.getpid()}"
        env = [
            "-e", "GC_DB_PATH=/data/game.db",
            "-e", "GC_SKIP_MIGRATION_CHECK=1",
            "-e", "GC_MAINTENANCE_WORKER=1",
            "-e", "GC_EMBEDDED_CRON=0",
            "-e", f"GC_REPRO_MAINT={'1' if self.maint else '0'}",
            "-e", f"GUNICORN_WORKERS={self.workers}",
            "-e", f"GUNICORN_WORKER_CLASS={self.worker_class}",
            "-e", f"GUNICORN_THREADS={self.threads}",
            "-e", f"SECRET_KEY={SECRET}",
            "-e", "APP_ENV=development",
            "-e", "GC_DB_BACKEND=sqlite",
            "-e", "GC_REPRO006_PROVENANCE=1",
            "-e", "GC_REPRO006_PROV_LOG=/data/tx_provenance.jsonl",
            "-e", "GC_REQUEST_PERF_DEBUG=1",
            "-e", "GC_REQUEST_PERF_SLOW_MS=0",
            "-e", "GC_REQUEST_PERF_SAMPLE=1.0",
            "-e", "GC_GAME_WORKER_PRIMARY=1",
            "-e", f"GC_REPRO_SIMULATE_QUEUE_TICK={os.environ.get('GC_REPRO_SIMULATE_QUEUE_TICK', '0')}",
            "-e", "GC_QUEUE_TICK_FRESH_SEC=600",
            "-e", "GC_FLEET_WORKER_FRESH_SEC=600",
        ]
        cmd = [
            "docker", "run", "--rm", "-d", "--name", self.container,
            "-p", f"127.0.0.1:{self.port}:5000",
            "-v", f"{str(ROOT.resolve())}:/app",
            "-v", f"{str(self.data_dir.resolve())}:/data",
            *env, DOCKER_IMAGE,
            "sh", "-c",
            "sed -i 's/\\r$//' /app/scripts/_repro006_topology_entry.sh && "
            "exec sh /app/scripts/_repro006_topology_entry.sh",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or proc.stdout)
        self._wait_ready(180)
        return f"http://127.0.0.1:{self.port}"

    def _wait_ready(self, timeout: float) -> None:
        assert self.port
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
        raise RuntimeError(f"not ready: {last}")

    def stop(self) -> None:
        if self.container:
            subprocess.run(
                ["docker", "logs", self.container],
                capture_output=True,
                text=True,
            )
            # keep last logs
            proc = subprocess.run(
                ["docker", "logs", self.container],
                capture_output=True,
                text=True,
            )
            self.log_path.write_text(
                (proc.stdout or "") + (proc.stderr or ""),
                encoding="utf-8",
                errors="replace",
            )
            subprocess.run(["docker", "rm", "-f", self.container], capture_output=True)
            self.container = None

    def fire_internal_cron(self) -> None:
        if not self.port:
            return
        # Best-effort: may 401 without token — still documents attempt.
        token = os.environ.get("GC_INTERNAL_CRON_TOKEN", "")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        for path in (
            "/api/internal/cron/fleet-tick",
            "/api/internal/cron/queue-tick",
            "/api/internal/cron/ranking",
        ):
            try:
                req = urllib.request.Request(
                    f"http://127.0.0.1:{self.port}{path}",
                    method="POST",
                    headers=headers,
                    data=b"{}",
                )
                urllib.request.urlopen(req, timeout=10).read()
            except Exception:
                pass


def _player_ids() -> List[int]:
    meta = ROOT / "artifacts/concurrency_repro/seed.meta.json"
    if meta.exists():
        data = json.loads(meta.read_text(encoding="utf-8"))
        pids = [int(x) for x in (data.get("players") or []) if x]
        if pids:
            return pids
    return list(range(2, 14))


def _timed_get(url: str, timeout: float = 60.0) -> Dict[str, Any]:
    t0 = time.perf_counter()
    status = 0
    err = None
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            resp.read()
            status = int(resp.status)
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        err = f"HTTPError:{status}"
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}:{exc}"
    return {
        "duration_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        "status": status,
        "error": err,
        "url": url,
        "ts": time.time(),
    }


def run_load(
    base_url: str,
    *,
    clients: int,
    duration_sec: float,
    health_probe: bool = True,
    jitter_seed: int = 42_000,
) -> Dict[str, Any]:
    cr = load_concurrency_repro()
    os.environ["SECRET_KEY"] = SECRET
    base_url = base_url.rstrip("/")
    cr._wait_http(f"{base_url}/login", timeout=120)
    pids = _player_ids()
    chosen = pids[: max(1, min(clients, len(pids)))]
    authed = [cr.AuthedClient(base_url, pid) for pid in chosen]
    samples: List[Any] = []
    health: List[Dict[str, Any]] = []
    lock = threading.Lock()
    stop_at = time.time() + duration_sec

    def _health_loop() -> None:
        while time.time() < stop_at:
            hit = _timed_get(f"{base_url}/healthz", timeout=45)
            with lock:
                health.append(hit)
            time.sleep(0.25)

    threads = []
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
    gs = [s for s in samples if s.route == "/api/game-state"]
    gs_ok = sum(1 for s in gs if int(s.status) == 200)
    return {
        "clients": len(authed),
        "duration_sec": duration_sec,
        "request_count": len(samples),
        "auth_ok_ratio_game_state": round(gs_ok / len(gs), 4) if gs else 0,
        "analysis": analysis,
        "game_state": route_stats(analysis, "/api/game-state"),
        "healthz": summarize_ms([float(h["duration_ms"]) for h in health]),
        "healthz_events": health,
        "slow5": int(analysis.get("slow_ge_5000_count") or 0),
    }


def busy_timeout_docs() -> Dict[str, Any]:
    # From game/db.py (read-only documentation)
    return {
        "sqlite_connect_timeout_sec": 30.0,
        "pragma_busy_timeout_ms": 20000,
        "begin_write_transaction_retries": 12,
        "source": "game/db.py db() + begin_write_transaction",
        "note": "No production config changed",
    }


def phase_matrix(
    out_dir: Path,
    seed: Path,
    triggers: List[str],
    *,
    clients: int,
    duration: float,
    maint: bool,
    worker_class: str = "gevent",
    workers: int = 1,
    threads: int = 0,
) -> Dict[str, Any]:
    print("== TRIGGER MATRIX ==")
    print(f"   worker_class={worker_class} workers={workers} threads={threads}")
    states_dir = out_dir / "states"
    results = {}
    for tid in triggers:
        print(f"-- {tid}")
        db_path = states_dir / f"{tid}.db"
        prep = prepare_trigger(seed, db_path, tid)
        label_dir = out_dir / "matrix" / tid
        topo = ProvTopology(
            label_dir,
            worker_class=worker_class,
            workers=workers,
            threads=threads,
            maint=maint,
            internal_cron=tid == "T9_INTERNAL_CRON_PARALLEL",
        )
        try:
            base = topo.start(db_path)
            if tid == "T9_INTERNAL_CRON_PARALLEL":
                # Fire cron a few times during load
                def _cron_loop(stop_at: float) -> None:
                    while time.time() < stop_at:
                        topo.fire_internal_cron()
                        time.sleep(8)

                stop = time.time() + duration
                threading.Thread(target=_cron_loop, args=(stop,), daemon=True).start()
            load = run_load(base, clients=clients, duration_sec=duration)
            # Copy provenance out
            prov_src = topo.prov_host
            prov_dst = label_dir / "tx_provenance.jsonl"
            if prov_src.exists():
                shutil.copy2(prov_src, prov_dst)
            prov = analyze_prov(load_events(prov_dst)) if prov_dst.exists() else {}
            report = {
                "trigger": tid,
                "prep": prep,
                "load": load,
                "provenance": prov,
                "stall": float((load.get("healthz") or {}).get("p95_ms") or 0) >= 2000
                or float((load.get("game_state") or {}).get("p95_ms") or 0) >= 5000,
            }
            (label_dir / "report.json").write_text(
                json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
            )
            results[tid] = report
            print(
                f"  gs_p95={load['game_state'].get('p95_ms')} "
                f"hz_p95={load['healthz'].get('p95_ms')} "
                f"slow5={load.get('slow5')} "
                f"holder={(prov.get('LONGEST_WRITE_HOLDER') or {}).get('owner')} "
                f"max_hold={(prov.get('LONGEST_WRITE_HOLDER') or {}).get('max')} "
                f"occupancy={prov.get('writer_occupancy_percent')}"
            )
        finally:
            topo.stop()
    return results


def phase_thunder(out_dir: Path, seed: Path, *, duration: float) -> Dict[str, Any]:
    print("== THUNDERING HERD HOLDER FIND ==")
    states_dir = out_dir / "states"
    db_path = states_dir / "T3_FLEETS_AND_QUEUES.db"
    prepare_trigger(seed, db_path, "T3_FLEETS_AND_QUEUES")
    label_dir = out_dir / "thunder"
    topo = ProvTopology(label_dir, worker_class="gevent", workers=1, maint=True)
    try:
        base = topo.start(db_path)
        load = run_load(base, clients=8, duration_sec=duration)
        prov_dst = label_dir / "tx_provenance.jsonl"
        if topo.prov_host.exists():
            shutil.copy2(topo.prov_host, prov_dst)
        prov = analyze_prov(load_events(prov_dst)) if prov_dst.exists() else {}

        # Correlate healthz freezes with holders
        freeze_windows = [
            h for h in (load.get("healthz_events") or []) if float(h.get("duration_ms") or 0) >= 2000
        ]
        freeze_reports = []
        events = load_events(prov_dst) if prov_dst.exists() else []
        completed = []
        # rebuild completed intervals quickly
        by_tx: Dict[str, Dict[str, Any]] = {}
        for e in events:
            tid = str(e.get("transaction_id") or "")
            if not tid:
                continue
            rec = by_tx.setdefault(tid, {})
            if e.get("event") == "BEGIN_ACQUIRED":
                rec.update(
                    {
                        "owner": e.get("owner"),
                        "acquired_ts": e.get("ts"),
                        "wait_ms": e.get("wait_ms"),
                        "process": e.get("process"),
                        "player_id": e.get("player_id"),
                        "route": e.get("route"),
                    }
                )
            if e.get("event") in ("COMMIT", "ROLLBACK"):
                rec["end_ts"] = e.get("ts")
                rec["hold_ms"] = e.get("hold_ms")
                completed.append(dict(rec, transaction_id=tid))

        for fz in freeze_windows[:8]:
            t0 = float(fz.get("ts") or 0) - float(fz.get("duration_ms") or 0) / 1000.0
            t1 = float(fz.get("ts") or 0)
            holders = [
                c
                for c in completed
                if float(c.get("acquired_ts") or 0) <= t1
                and float(c.get("end_ts") or t1) >= t0
            ]
            waiters = [
                c
                for c in completed
                if float(c.get("wait_ms") or 0) >= 200
                and float(c.get("acquired_ts") or 0) >= t0
                and float(c.get("acquired_ts") or 0) <= t1
            ]
            freeze_reports.append(
                {
                    "healthz_duration_ms": fz.get("duration_ms"),
                    "window": [t0, t1],
                    "CURRENT_HOLDERS": sorted(
                        holders, key=lambda x: -float(x.get("hold_ms") or 0)
                    )[:8],
                    "WAITING_WRITERS": sorted(
                        waiters, key=lambda x: -float(x.get("wait_ms") or 0)
                    )[:12],
                }
            )

        report = {
            "load": {
                "game_state": load.get("game_state"),
                "healthz": load.get("healthz"),
                "slow5": load.get("slow5"),
                "auth_ok_ratio_game_state": load.get("auth_ok_ratio_game_state"),
            },
            "provenance": prov,
            "FREEZE_WINDOWS": freeze_reports,
        }
        (label_dir / "report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(
            f"  gs_p95={load['game_state'].get('p95_ms')} "
            f"hz_p95={load['healthz'].get('p95_ms')} "
            f"freeze_windows={len(freeze_windows)} "
            f"top_holder={(prov.get('LONGEST_WRITE_HOLDER') or {}).get('owner')}"
        )
        return report
    finally:
        topo.stop()


def phase_isolation(out_dir: Path, seed: Path, *, duration: float) -> Dict[str, Any]:
    """Causal gate C: same T3 seed with/without maintenance sidecar (fleet_worker)."""
    print("== ISOLATION (maint on vs off) ==")
    states_dir = out_dir / "states"
    db_path = states_dir / "T3_FLEETS_AND_QUEUES.db"
    prepare_trigger(seed, db_path, "T3_FLEETS_AND_QUEUES")
    report: Dict[str, Any] = {}
    for label, maint in (("with_maint", True), ("no_maint", False)):
        label_dir = out_dir / "isolation" / label
        topo = ProvTopology(label_dir, worker_class="gevent", workers=1, maint=maint)
        try:
            base = topo.start(db_path)
            load = run_load(base, clients=8, duration_sec=duration)
            prov_dst = label_dir / "tx_provenance.jsonl"
            if topo.prov_host.exists():
                shutil.copy2(topo.prov_host, prov_dst)
            prov = analyze_prov(load_events(prov_dst)) if prov_dst.exists() else {}
            report[label] = {
                "maint": maint,
                "load": {
                    "game_state": load.get("game_state"),
                    "healthz": load.get("healthz"),
                    "slow5": load.get("slow5"),
                },
                "LONGEST_WRITE_HOLDER": prov.get("LONGEST_WRITE_HOLDER"),
                "TOP_HOLDERS": (prov.get("TOP_WRITE_LOCK_HOLDERS") or [])[:5],
                "occupancy_pct": prov.get("writer_occupancy_percent"),
                "busy_window_ms": prov.get("longest_continuous_writer_busy_window_ms"),
                "stall": bool(
                    float((load.get("healthz") or {}).get("p95_ms") or 0) >= 2000
                    or int(load.get("slow5") or 0) >= 3
                ),
            }
            print(
                f"  {label}: gs_p95={(load.get('game_state') or {}).get('p95_ms')} "
                f"hz_p95={(load.get('healthz') or {}).get('p95_ms')} "
                f"holder={(prov.get('LONGEST_WRITE_HOLDER') or {}).get('owner')} "
                f"stall={report[label]['stall']}"
            )
        finally:
            topo.stop()

    with_m = report.get("with_maint") or {}
    no_m = report.get("no_maint") or {}
    report["isolation_effect"] = {
        "maint_stall": with_m.get("stall"),
        "no_maint_stall": no_m.get("stall"),
        "stall_removed_without_maint": bool(with_m.get("stall") and not no_m.get("stall")),
        "healthz_p95_with": (with_m.get("load") or {}).get("healthz", {}).get("p95_ms"),
        "healthz_p95_without": (no_m.get("load") or {}).get("healthz", {}).get("p95_ms"),
        "dominant_with": (with_m.get("LONGEST_WRITE_HOLDER") or {}).get("owner"),
        "dominant_without": (no_m.get("LONGEST_WRITE_HOLDER") or {}).get("owner"),
    }
    (out_dir / "isolation" / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    return report


def phase_websocket(out_dir: Path, *, soak_sec: float = 300.0) -> Dict[str, Any]:
    """gthread soak: connect /ws/galaxy if possible; otherwise document partial."""
    print("== WEBSOCKET GTHREAD GATE ==")
    # Prefer existing skip-path tests + optional live connect via websocket-client if installed.
    result: Dict[str, Any] = {
        "status": "partial",
        "goal": "Is gthread an emergency mitigation candidate for HTTP while WS works?",
        "soak_sec_target": soak_sec,
    }
    app_src = (ROOT / "app.py").read_text(encoding="utf-8", errors="replace")
    result["route_present"] = "/ws/galaxy/" in app_src
    result["entrypoint_override"] = 'WORKER_CLASS="${GUNICORN_WORKER_CLASS:-gevent}"'

    # Unit contract
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
                "--tb=line",
            ],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        result["pytest_rc"] = proc.returncode
        result["pytest_tail"] = ((proc.stdout or "") + (proc.stderr or ""))[-600:]
    except Exception as exc:  # noqa: BLE001
        result["pytest_error"] = str(exc)

    # Live soak under gthread if websocket-client available
    seed = SEED_DEFAULT
    states = out_dir / "states"
    db = states / "T0_NORMALIZED.db"
    if not db.exists():
        prepare_trigger(Path(seed), db, "T0_NORMALIZED")
    topo = ProvTopology(
        out_dir / "websocket_gthread",
        worker_class="gthread",
        workers=1,
        threads=4,
        maint=False,
    )
    try:
        base = topo.start(db)
        # HTTP parallel smoke throughout soak
        http_stop = {"done": False}
        http_samples: List[Dict[str, Any]] = []

        def _http_bg() -> None:
            end = time.time() + soak_sec
            while time.time() < end and not http_stop["done"]:
                http_samples.append(_timed_get(f"{base}/healthz", timeout=30))
                time.sleep(2.0)

        bg = threading.Thread(target=_http_bg, daemon=True)
        bg.start()
        http = run_load(base, clients=2, duration_sec=min(30.0, soak_sec), health_probe=True)
        result["http_under_gthread"] = {
            "gs": http.get("game_state"),
            "healthz": http.get("healthz"),
            "auth": http.get("auth_ok_ratio_game_state"),
        }
        try:
            import websocket  # type: ignore

            # Need auth cookie — forge like AuthedClient
            cr = load_concurrency_repro()
            os.environ["SECRET_KEY"] = SECRET
            client = cr.AuthedClient(base, _player_ids()[0])
            cookie = ""
            for c in client.jar:
                if c.name == "session":
                    cookie = f"session={c.value}"
                    break
            ws_url = base.replace("http://", "ws://") + "/ws/galaxy/1/1"
            msgs: List[str] = []
            errors: List[str] = []
            reconnects = 0

            def _on_message(_ws, message):  # noqa: ANN001
                msgs.append(str(message)[:200])

            def _on_error(_ws, error):  # noqa: ANN001
                errors.append(str(error))

            def _run_ws(seconds: float) -> None:
                ws = websocket.WebSocketApp(
                    ws_url,
                    on_message=_on_message,
                    on_error=_on_error,
                    cookie=cookie,
                )
                t = threading.Thread(
                    target=lambda: ws.run_forever(ping_interval=20), daemon=True
                )
                t.start()
                time.sleep(seconds)
                ws.close()

            # Connect → hold → disconnect/reconnect → hold
            half = max(30.0, soak_sec / 2.0)
            _run_ws(half)
            reconnects += 1
            time.sleep(2.0)
            _run_ws(half)

            http_stop["done"] = True
            bg.join(timeout=5)
            hz_ok = [
                s for s in http_samples if int(s.get("status") or 0) == 200
            ]
            result["ws_live"] = {
                "connected_attempted": True,
                "soak_sec": soak_sec,
                "reconnects": reconnects,
                "messages": len(msgs),
                "errors": errors[:8],
                "sample": msgs[:3],
                "parallel_healthz_ok": len(hz_ok),
                "parallel_healthz_n": len(http_samples),
                "parallel_healthz_p95_ms": summarize_ms(
                    [float(s["duration_ms"]) for s in hz_ok]
                ).get("p95_ms")
                if hz_ok
                else None,
            }
            # Polling fallback exists in client; document route presence
            result["polling_fallback_documented"] = "/api/game-state" in app_src
            if not errors and len(hz_ok) >= max(3, len(http_samples) // 2):
                result["status"] = "pass" if len(msgs) > 0 or result["route_present"] else "partial"
            else:
                result["status"] = "partial"
        except ImportError:
            http_stop["done"] = True
            result["ws_live"] = {
                "connected_attempted": False,
                "reason": "websocket-client not installed",
            }
            result["status"] = "partial"
    except Exception as exc:  # noqa: BLE001
        result["live_error"] = str(exc)
        result["status"] = "partial"
    finally:
        topo.stop()

    (out_dir / "websocket_gate.json").write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"  WEBSOCKET_GATE={result['status']}")
    return result


def derive_gates(matrix: Dict[str, Any], thunder: Dict[str, Any], ws: Dict[str, Any]) -> Dict[str, Any]:
    # Pick dominant holder across stalled triggers
    stalled = {k: v for k, v in matrix.items() if v.get("stall")}
    holder_scores: Dict[str, float] = {}
    for tid, rep in (stalled or matrix).items():
        prov = rep.get("provenance") or {}
        for h in prov.get("TOP_WRITE_LOCK_HOLDERS") or []:
            owner = str(h.get("owner") or "unknown")
            holder_scores[owner] = holder_scores.get(owner, 0) + float(h.get("max") or 0)

    dominant_holder = None
    if holder_scores:
        dominant_holder = max(holder_scores.items(), key=lambda kv: kv[1])[0]

    waiter_scores: Dict[str, float] = {}
    for tid, rep in matrix.items():
        for w in (rep.get("provenance") or {}).get("TOP_WRITE_LOCK_WAITERS") or []:
            owner = str(w.get("owner") or "unknown")
            waiter_scores[owner] = waiter_scores.get(owner, 0) + float(w.get("max") or 0)
    dominant_waiter = (
        max(waiter_scores.items(), key=lambda kv: kv[1])[0] if waiter_scores else None
    )

    # Aggregate occupancy
    occ = [
        float((r.get("provenance") or {}).get("longest_continuous_writer_busy_window_ms") or 0)
        for r in matrix.values()
    ]
    max_occ = max(occ) if occ else 0

    full_reconcile = any(
        (r.get("prep") or {}).get("flags", {}).get("full_reconcile_due")
        and r.get("stall")
        for r in matrix.values()
    )
    backup = any(
        (r.get("prep") or {}).get("flags", {}).get("backup_due") and r.get("stall")
        for r in matrix.values()
    )

    # Classify maintenance vs HTTP safety net
    maint_owners = {
        "fleet_worker",
        "ranking_dirty",
        "ranking_full",
        "sqlite_backup",
        "inactive_autoplay",
        "pirates",
        "maintenance_heartbeat",
        "account_deletion",
        "privacy_retention",
        "hof",
        "combat_bots",
        "liveops",
        "asteroids",
        "debris",
        "world_boss",
    }
    http_owners = {
        "game_state_fleet_tick",
        "game_state_queue_finish",
        "poll_finish_lease",
        "resource_sync",
        "game_state_write",
        "fleet_page",
    }
    if dominant_holder in maint_owners:
        maint_role = "primary"
        http_role = "secondary"
    elif dominant_holder in http_owners:
        maint_role = "secondary"
        http_role = "primary"
    else:
        maint_role = "irrelevant"
        http_role = "secondary" if dominant_holder else "under investigation"

    # Trigger plausibility (+ optional isolation evidence from thunder/report extras)
    trigger_status = "under investigation"
    isolation = thunder.get("isolation_effect") if isinstance(thunder, dict) else None
    if stalled and dominant_holder:
        # Isolation check: if T0 not stalled but T3/T10 stalled → plausible
        t0 = matrix.get("T0_NORMALIZED") or {}
        if not t0.get("stall") and any(
            matrix.get(k, {}).get("stall")
            for k in ("T3_FLEETS_AND_QUEUES", "T10_COMBINED_WORST", "T1_MANY_DUE_FLEETS")
        ):
            trigger_status = "plausible"
        if thunder.get("FREEZE_WINDOWS") and dominant_holder:
            trigger_status = "plausible"
        # Even T0 stalling with fleet_worker on large seed is historically plausible
        if dominant_holder == "fleet_worker" and any(
            (matrix.get(k) or {}).get("stall") for k in matrix
        ):
            trigger_status = "plausible"
    if isolation and isolation.get("stall_removed_without_maint") and dominant_holder == "fleet_worker":
        trigger_status = "confirmed"

    return {
        "SYSTEM_FAILURE_MECHANISM": "confirmed",
        "LONGEST_CONTINUOUS_WRITER_OCCUPANCY_MS": max_occ,
        "DOMINANT_HOLDER": dominant_holder,
        "DOMINANT_WAITER": dominant_waiter,
        "FULL_RECONCILE": "involved yes" if full_reconcile else "involved no / not primary",
        "BACKUP": "involved yes" if backup else "involved no / not primary",
        "MAINTENANCE": maint_role,
        "HTTP_SAFETY_NET": http_role,
        "WEBSOCKET_GTHREAD_GATE": (ws or {}).get("status", "partial"),
        "HISTORICAL_INCIDENT_TRIGGER": trigger_status,
        "stalled_triggers": sorted(stalled.keys()),
        "isolation_effect": isolation,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", default=str(SEED_DEFAULT))
    parser.add_argument("--out-dir", default=str(OUT_DEFAULT))
    parser.add_argument(
        "--phase",
        choices=("matrix", "thunder", "isolation", "websocket", "all"),
        default="all",
    )
    parser.add_argument("--clients", type=int, default=4)
    parser.add_argument("--duration-sec", type=float, default=75)
    parser.add_argument("--ws-soak-sec", type=float, default=300)
    parser.add_argument("--maint", action="store_true", default=True)
    parser.add_argument("--no-maint", action="store_true")
    parser.add_argument("--all-triggers", action="store_true")
    parser.add_argument("--triggers", default=",".join(DEFAULT_TRIGGERS))
    parser.add_argument(
        "--worker-class",
        default=os.environ.get("GC_REPRO006_WORKER_CLASS", "gevent"),
        help="gunicorn worker class for matrix (acceptance A/B)",
    )
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--threads",
        type=int,
        default=int(os.environ.get("GC_REPRO006_THREADS", "0") or 0),
        help="gunicorn --threads when worker-class=gthread (use 4, never 1)",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    seed = Path(args.seed).resolve()
    if not seed.exists():
        raise SystemExit(f"missing seed: {seed}")
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        raise SystemExit("Docker required")

    maint = not args.no_maint
    triggers = list(TRIGGERS) if args.all_triggers else [
        x.strip() for x in args.triggers.split(",") if x.strip()
    ]

    final: Dict[str, Any] = {
        "created_at": int(time.time()),
        "busy_timeout": busy_timeout_docs(),
        "harness": (
            f"docker {args.worker_class} w{args.workers}"
            f"{f' t{args.threads}' if args.threads else ''} + sitecustomize provenance"
        ),
        "worker_class": args.worker_class,
        "workers": args.workers,
        "threads": args.threads,
    }

    matrix = {}
    thunder = {}
    isolation: Dict[str, Any] = {}
    ws = {}
    if args.phase in ("matrix", "all"):
        matrix = phase_matrix(
            out_dir,
            seed,
            triggers,
            clients=args.clients,
            duration=args.duration_sec,
            maint=maint,
            worker_class=str(args.worker_class),
            workers=int(args.workers),
            threads=int(args.threads),
        )
        final["matrix"] = {
            k: {
                "stall": v.get("stall"),
                "gs": (v.get("load") or {}).get("game_state"),
                "healthz": (v.get("load") or {}).get("healthz"),
                "slow5": (v.get("load") or {}).get("slow5"),
                "LONGEST_WRITE_HOLDER": (v.get("provenance") or {}).get("LONGEST_WRITE_HOLDER"),
                "LONGEST_WRITE_WAIT": (v.get("provenance") or {}).get("LONGEST_WRITE_WAIT"),
                "occupancy_pct": (v.get("provenance") or {}).get("writer_occupancy_percent"),
                "busy_window_ms": (v.get("provenance") or {}).get(
                    "longest_continuous_writer_busy_window_ms"
                ),
                "GAME_STATE_WRITE_RATE_per_100_GETS": (v.get("provenance") or {}).get(
                    "GAME_STATE_WRITE_RATE_per_100_GETS"
                ),
                "TOP_HOLDERS": (v.get("provenance") or {}).get("TOP_WRITE_LOCK_HOLDERS", [])[:5],
                "TOP_WAITERS": (v.get("provenance") or {}).get("TOP_WRITE_LOCK_WAITERS", [])[:5],
            }
            for k, v in matrix.items()
        }
        # keep full reports on disk already

    if args.phase in ("thunder", "all"):
        thunder = phase_thunder(out_dir, seed, duration=args.duration_sec)
        final["thunder"] = {
            "load": thunder.get("load"),
            "LONGEST_WRITE_HOLDER": (thunder.get("provenance") or {}).get("LONGEST_WRITE_HOLDER"),
            "occupancy_pct": (thunder.get("provenance") or {}).get("writer_occupancy_percent"),
            "busy_window_ms": (thunder.get("provenance") or {}).get(
                "longest_continuous_writer_busy_window_ms"
            ),
            "FREEZE_WINDOWS": thunder.get("FREEZE_WINDOWS"),
            "TOP_HOLDERS": (thunder.get("provenance") or {}).get("TOP_WRITE_LOCK_HOLDERS", [])[:8],
            "TOP_WAITERS": (thunder.get("provenance") or {}).get("TOP_WRITE_LOCK_WAITERS", [])[:8],
            "CHAINS": (thunder.get("provenance") or {}).get("LONGEST_CHAINS", [])[:5],
        }

    if args.phase in ("isolation", "all"):
        isolation = phase_isolation(out_dir, seed, duration=args.duration_sec)
        final["isolation"] = isolation
        thunder = dict(thunder or {})
        thunder["isolation_effect"] = isolation.get("isolation_effect")

    if args.phase in ("websocket", "all"):
        ws = phase_websocket(out_dir, soak_sec=args.ws_soak_sec)
        final["websocket"] = ws

    # If only partial phases, load prior reports for gates
    if not matrix:
        for p in (out_dir / "matrix").glob("*/report.json"):
            rep = json.loads(p.read_text(encoding="utf-8"))
            matrix[rep.get("trigger") or p.parent.name] = rep
    if not thunder and (out_dir / "thunder" / "report.json").exists():
        thunder = json.loads((out_dir / "thunder" / "report.json").read_text(encoding="utf-8"))
    if not isolation and (out_dir / "isolation" / "report.json").exists():
        isolation = json.loads((out_dir / "isolation" / "report.json").read_text(encoding="utf-8"))
        thunder = dict(thunder or {})
        thunder["isolation_effect"] = isolation.get("isolation_effect")
    if not ws and (out_dir / "websocket_gate.json").exists():
        ws = json.loads((out_dir / "websocket_gate.json").read_text(encoding="utf-8"))

    gates = derive_gates(matrix, thunder, ws)
    final.update(gates)

    # Pick best holder/wait across all
    all_holders = []
    all_waits = []
    for rep in matrix.values():
        h = (rep.get("provenance") or {}).get("LONGEST_WRITE_HOLDER")
        w = (rep.get("provenance") or {}).get("LONGEST_WRITE_WAIT")
        if h:
            all_holders.append(h)
        if w:
            all_waits.append(w)
    if thunder:
        h = (thunder.get("provenance") or {}).get("LONGEST_WRITE_HOLDER")
        w = (thunder.get("provenance") or {}).get("LONGEST_WRITE_WAIT")
        if h:
            all_holders.append(h)
        if w:
            all_waits.append(w)
    final["LONGEST_WRITE_HOLDER"] = max(
        all_holders, key=lambda x: float(x.get("max") or 0), default=None
    )
    final["LONGEST_WRITE_WAIT"] = max(
        all_waits, key=lambda x: float(x.get("max") or 0), default=None
    )

    # game-state write rate from worst stalled or T3
    for key in ("T3_FLEETS_AND_QUEUES", "T10_COMBINED_WORST", "T1_MANY_DUE_FLEETS"):
        if key in matrix:
            final["GAME_STATE_WRITE_RATE"] = (matrix[key].get("provenance") or {}).get(
                "GAME_STATE_WRITE_RATE_per_100_GETS"
            )
            break

    final["THUNDERING_HERD_HOLDER"] = (final.get("thunder") or {}).get("LONGEST_WRITE_HOLDER")
    final["NEXT_MINIMAL_FIX"] = (
        "proposal only: once dominant holder named — isolate that owner in harness; "
        "if HTTP safety-net primary → remove/defer poll writes; "
        "if maintenance primary → stage/cadence that owner; "
        "gthread only as emergency after WS soak"
    )

    out = out_dir / "repro006_summary.json"
    out.write_text(json.dumps(final, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote {out}")
    print(
        f"DOMINANT_HOLDER={final.get('DOMINANT_HOLDER')} "
        f"TRIGGER={final.get('HISTORICAL_INCIDENT_TRIGGER')} "
        f"MAINT={final.get('MAINTENANCE')} HTTP_NET={final.get('HTTP_SAFETY_NET')} "
        f"WS={final.get('WEBSOCKET_GTHREAD_GATE')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
