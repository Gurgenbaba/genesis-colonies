#!/usr/bin/env python3
"""
GC-547 browser idle validation (Playwright + subprocess Flask).

Scenarios:
  1. Overview 60s idle — loops flat, gc-perf-idle set
  2. Tab hidden 30s — visual loops paused
  3. Build timer active → stops after completion

Usage:
  pip install playwright
  playwright install chromium
  python scripts/gc547_browser_audit.py
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
import uuid
import http.cookiejar
from pathlib import Path
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener, urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

AUDIT_INIT_SCRIPT = """
(() => {
  if (window.__gc547Hooked) return;
  window.__gc547Hooked = true;
  window.__gc547 = { raf: 0, intervalTicks: 0, timeoutTicks: 0 };
  const raf = window.requestAnimationFrame.bind(window);
  window.requestAnimationFrame = (cb) => raf((t) => {
    window.__gc547.raf += 1;
    return cb(t);
  });
  const si = window.setInterval.bind(window);
  window.setInterval = (fn, ms, ...rest) => si(() => {
    window.__gc547.intervalTicks += 1;
    return fn();
  }, ms, ...rest);
  const st = window.setTimeout.bind(window);
  window.setTimeout = (fn, ms, ...rest) => st(() => {
    window.__gc547.timeoutTicks += 1;
    return fn();
  }, ms, ...rest);
})();
"""

SNAPSHOT_JS = """
() => {
  const c = window.__gc547 || { raf: 0, intervalTicks: 0, timeoutTicks: 0 };
  const anims = (typeof document.getAnimations === 'function')
    ? document.getAnimations().filter(a => a.playState === 'running').length
    : -1;
  return {
    hidden: document.hidden,
    gcTabHidden: document.body.classList.contains('gc-tab-hidden'),
    gcPerfIdle: document.body.classList.contains('gc-perf-idle'),
    pollingRunning: !!(window.GC && GC.polling && GC.polling.running),
    shouldRunVisual: !!(window.GC && GC.shouldRunVisualLoops && GC.shouldRunVisualLoops()),
    raf: c.raf,
    intervalTicks: c.intervalTicks,
    timeoutTicks: c.timeoutTicks,
    runningAnimations: anims,
    hasBuildTimer: !!document.querySelector('[data-timer-target], [data-countdown-at], #build-eta-live'),
  };
}
"""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _setup_db(tmp_dir: Path) -> tuple[Path, str, str]:
    import game.db as dbmod
    import game.models as models
    from game.models import create_user, init_db

    db_file = tmp_dir / f"gc547_{uuid.uuid4().hex[:8]}.db"
    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_file)
    env["SECRET_KEY"] = "test-secret-key-not-default-value-32chars"
    env["GC_SKIP_MIGRATION_CHECK"] = "1"
    r = subprocess.run(
        [sys.executable, str(ROOT / "migrate.py")],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(r.stderr or r.stdout)

    dbmod.DB_PATH = db_file
    models.DB_PATH = db_file
    init_db()
    uname = f"gc547_{uuid.uuid4().hex[:8]}"
    password = "test-pass-123"
    ok, err, user = create_user(uname, password)
    if not ok or not user:
        raise RuntimeError(err or "create_user failed")
    try:
        from game.db import db
        db().close()
    except Exception:
        pass
    return db_file, uname, password


def _wait_server(base: str, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urlopen(f"{base}/login", timeout=2) as resp:
                if resp.status == 200:
                    return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError(f"server not ready: {base}")


def _start_server_subprocess(db_file: Path, port: int) -> subprocess.Popen:
    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_file)
    env["SECRET_KEY"] = "test-secret-key-not-default-value-32chars"
    env["GC_SKIP_MIGRATION_CHECK"] = "1"
    env["PORT"] = str(port)
    env["HOST"] = "127.0.0.1"
    env["FLASK_DEBUG"] = "0"
    env["GC_FLASK_THREADED"] = "1"
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "app.py")],
        cwd=str(ROOT),
        env=env,
    )
    time.sleep(2.5)
    _wait_server(f"http://127.0.0.1:{port}")
    return proc


def _http_login(base: str, uname: str, password: str) -> list[dict]:
    class _NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    jar = http.cookiejar.CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar), _NoRedirect())
    data = urlencode({"username": uname, "password": password}).encode()
    req = Request(f"{base}/login", data=data, method="POST")
    try:
        opener.open(req, timeout=15)
    except HTTPError as exc:
        if exc.code not in (302, 303):
            raise RuntimeError(f"login failed HTTP {exc.code}") from exc
    cookies = []
    for c in jar:
        cookies.append({
            "name": c.name,
            "value": c.value,
            "domain": "127.0.0.1",
            "path": c.path or "/",
        })
    if not cookies:
        raise RuntimeError("no cookies from HTTP login")
    return cookies


def _add_short_build(db_file: Path, username: str) -> None:
    import game.db as dbmod
    import game.models as models
    from game.db import db
    from game.models import add_build_job, get_homeworld

    dbmod.DB_PATH = db_file
    models.DB_PATH = db_file
    conn = db()
    row = conn.execute("SELECT id FROM players WHERE username = ?;", (username,)).fetchone()
    conn.close()
    if not row:
        raise RuntimeError("player not found")
    pid = int(row[0])
    planet = get_homeworld(player_id=pid)
    now = time.time()
    finish = now + 18
    add_build_job(int(planet["id"]), "metal_mine", now, finish)


def _delta(before: dict, after: dict) -> dict:
    return {
        "raf": after["raf"] - before["raf"],
        "intervalTicks": after["intervalTicks"] - before["intervalTicks"],
        "timeoutTicks": after["timeoutTicks"] - before["timeoutTicks"],
        "pollingRunning": after["pollingRunning"],
        "gcPerfIdle": after["gcPerfIdle"],
        "shouldRunVisual": after["shouldRunVisual"],
        "runningAnimations": after["runningAnimations"],
    }


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("FAIL: pip install playwright && playwright install chromium")
        return 2

    tmp = ROOT / ".tmp_gc547_audit"
    tmp.mkdir(exist_ok=True)
    port = _free_port()
    db_file, uname, password = _setup_db(tmp)
    base = f"http://127.0.0.1:{port}"
    proc = _start_server_subprocess(db_file, port)
    report: dict = {"scenarios": {}, "pass": True, "notes": [], "port": port}

    try:
        cookies = _http_login(base, uname, password)
        if not cookies:
            raise RuntimeError("no cookies from HTTP login")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            context.route(re.compile(r".*(fonts\.googleapis|fonts\.gstatic)\.com.*"), lambda r: r.abort())
            context.add_cookies(cookies)
            context.add_init_script(AUDIT_INIT_SCRIPT)
            page = context.new_page()
            page.set_default_timeout(90000)

            page.goto(f"{base}/overview", wait_until="commit")
            page.wait_for_selector("#resource-bar", timeout=60000)
            page.wait_for_function("typeof window.GC === 'object'", timeout=15000)
            page.evaluate("() => { if (GC.refreshGameState) return GC.refreshGameState('audit'); }")
            page.wait_for_function("window.GC.lastState && GC.lastState.ok === true", timeout=45000)

            # --- Scenario 1: Overview 60s idle ---
            page.wait_for_timeout(3000)
            s1_start = page.evaluate(SNAPSHOT_JS)
            page.wait_for_timeout(60000)
            s1_end = page.evaluate(SNAPSHOT_JS)
            s1 = _delta(s1_start, s1_end)
            report["scenarios"]["overview_60s_idle"] = {"delta": s1, "end": s1_end}
            if s1["intervalTicks"] > 80:
                report["pass"] = False
                report["notes"].append(f"S1: intervalTicks={s1['intervalTicks']} (>80 in 60s)")
            if not s1_end["gcPerfIdle"]:
                report["pass"] = False
                report["notes"].append("S1: body missing gc-perf-idle after idle settle")
            if s1["raf"] > 120:
                report["pass"] = False
                report["notes"].append(f"S1: raf={s1['raf']} (>120 in 60s)")
            if s1_end["runningAnimations"] > 0:
                report["notes"].append(f"S1: runningAnimations={s1_end['runningAnimations']}")

            # --- Scenario 2: Tab hidden 30s ---
            cdp = context.new_cdp_session(page)
            before_hidden = page.evaluate(SNAPSHOT_JS)
            cdp.send("Page.setWebLifecycleState", {"state": "hidden"})
            page.evaluate("() => document.dispatchEvent(new Event('visibilitychange'))")
            page.wait_for_timeout(500)
            mid_hidden = page.evaluate(SNAPSHOT_JS)
            page.wait_for_timeout(30000)
            after_hidden = page.evaluate(SNAPSHOT_JS)
            hidden_delta = _delta(before_hidden, after_hidden)
            report["scenarios"]["tab_hidden_30s"] = {
                "mid": mid_hidden,
                "delta": hidden_delta,
            }
            cdp.send("Page.setWebLifecycleState", {"state": "active"})
            page.evaluate("() => document.dispatchEvent(new Event('visibilitychange'))")
            page.wait_for_timeout(500)

            if mid_hidden.get("gcTabHidden") or mid_hidden.get("hidden"):
                if hidden_delta["intervalTicks"] > 12:
                    report["pass"] = False
                    report["notes"].append(f"S2: intervalTicks while hidden={hidden_delta['intervalTicks']}")
            else:
                report["notes"].append("S2: CDP hidden did not set document.hidden — manual tab test required")

            # --- Scenario 3: Build timer → stop after end ---
            _add_short_build(db_file, uname)
            page.goto(f"{base}/overview", wait_until="commit")
            page.wait_for_function("window.GC && GC.lastState", timeout=60000)
            page.wait_for_timeout(5000)
            active = page.evaluate(SNAPSHOT_JS)
            report["scenarios"]["build_timer_active"] = active
            if active.get("gcPerfIdle"):
                report["pass"] = False
                report["notes"].append("S3: gc-perf-idle set while build should be active")

            page.wait_for_timeout(22000)
            page.evaluate("() => GC.refreshGameState && GC.refreshGameState('audit')")
            page.wait_for_timeout(8000)
            after_build = page.evaluate(SNAPSHOT_JS)
            report["scenarios"]["build_timer_after"] = after_build
            if not after_build.get("gcPerfIdle"):
                report["pass"] = False
                report["notes"].append("S3: gc-perf-idle not set after build finished")

            browser.close()
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    out_path = ROOT / "docs" / "GC-547_BROWSER_VALIDATION.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nWrote {out_path}")
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
