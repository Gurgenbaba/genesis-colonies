"""
GC-856 — Multi-route SSR perf measurement (GC_SSR_PERF_DEBUG=1).

Usage:
  python tools/ssr_measure.py <user_id> /fleet 3
  python tools/ssr_measure.py <user_id> "/buildings?tab=resources" 3
  python tools/ssr_measure.py --username Bobby /shipyard 3
  python tools/ssr_measure.py <user_id> --all 3

Requires local game.db (or GC_DB_PATH). Emits [GC SSR PERF] lines to stdout.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_ROUTES = (
    "/fleet",
    "/buildings?tab=resources",
    "/shipyard",
    "/defense",
    "/overview",
)


def _resolve_user_id(*, user_id: int | None, username: str | None) -> int:
    if user_id is not None:
        return int(user_id)
    if not username:
        raise SystemExit("user_id or --username required")
    os.environ.setdefault("GC_SKIP_MIGRATION_CHECK", "1")
    from game.bootstrap import bootstrap_application
    from game.models import get_user_by_username

    bootstrap_application(skip_migration_check=True)
    row = get_user_by_username(str(username).strip())
    if not row:
        raise SystemExit(f"unknown username: {username}")
    return int(row["id"])


def _load_app():
    os.environ.setdefault("GC_SSR_PERF_DEBUG", "1")
    os.environ.setdefault("GC_SKIP_MIGRATION_CHECK", "1")
    os.environ.setdefault("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from game.bootstrap import bootstrap_application

    bootstrap_application(skip_migration_check=True)
    import importlib

    import app as app_module

    importlib.reload(app_module)
    return app_module.app


def _measure_route(client, path: str, *, n: int, pause_sec: float) -> None:
    route_label = urlparse(path).path or path
    print(f"--- route={path} requests={n} ---", flush=True)
    for i in range(n):
        t0 = time.perf_counter()
        resp = client.get(path)
        dt = (time.perf_counter() - t0) * 1000.0
        print(
            f"req{i + 1} status={resp.status_code} client_ms={dt:.0f} bytes={len(resp.data)}",
            flush=True,
        )
        if i == 0 and pause_sec > 0:
            time.sleep(pause_sec)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GC-856 SSR route measurement")
    parser.add_argument("user_id", nargs="?", type=int, help="Player user_id")
    parser.add_argument("path", nargs="?", default="/fleet", help="Route path (with query)")
    parser.add_argument("count", nargs="?", type=int, default=3, help="Request count")
    parser.add_argument("--username", "-u", help="Resolve user_id from username")
    parser.add_argument("--all", action="store_true", help="Measure all GC-856 default routes")
    parser.add_argument("--pause", type=float, default=0.3, help="Pause after cold request (sec)")
    args = parser.parse_args(argv)

    uid = _resolve_user_id(user_id=args.user_id, username=args.username)
    routes = list(DEFAULT_ROUTES) if args.all else [args.path]

    app = _load_app()
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    print(f"user_id={uid} GC_SSR_PERF_DEBUG=1", flush=True)
    for route in routes:
        _measure_route(client, route, n=max(1, int(args.count)), pause_sec=args.pause)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
