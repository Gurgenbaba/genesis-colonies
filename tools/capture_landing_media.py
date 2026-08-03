#!/usr/bin/env python3
"""
Capture real Genesis Colonies UI screenshots + Ken-Burns hero loop for the landing page.

Usage:
  pip install playwright imageio-ffmpeg Pillow
  playwright install chromium
  python tools/capture_landing_media.py

Writes into static/img/landing/{hero.*,shots/,moments/}.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "static" / "img" / "landing"
SHOTS_DIR = OUT_DIR / "shots"
MOMENTS_DIR = OUT_DIR / "moments"
PASSWORD = "test-pass-123"

SHOT_ROUTES: list[tuple[str, str]] = [
    ("shot-01-overview", "/overview"),
    ("shot-02-galaxy", "/galaxy"),
    ("shot-03-world-boss", "/world-boss"),
    ("shot-04-fleet", "/fleet"),
    ("shot-05-inventory", "/inventory"),
    ("shot-06-empire", "/empire"),
    ("shot-07-story", "/story"),
    ("shot-08-politics", "/galactic-politics"),
    ("shot-09-titans", "/overview"),
    ("shot-10-auctions", "/auction-house"),
    ("shot-11-research", "/research"),
    ("shot-12-commander", "/skilltree"),
]

# Focused live-moment clips: route + CSS selector (real UI region, not full-page copy).
# Falls back to crop fractions of a gallery shot if the selector is missing.
MOMENT_CLIPS: list[dict] = [
    {
        "stem": "moment-01-resources",
        "path": "/overview",
        "selector": "#resource-bar, .resource-bar.resource-bar-cmd, .resource-bar",
        "fallback_shot": "shot-01-overview",
        "crop": (0.16, 0.04, 0.84, 0.22),
    },
    {
        "stem": "moment-02-build",
        "path": "/buildings",
        "selector": ".gc-building-card, .buildings-grid, [data-endpoint='buildings'] .gc-page",
        "fallback_shot": "shot-01-overview",
        "crop": (0.18, 0.20, 0.72, 0.82),
    },
    {
        "stem": "moment-03-fleet",
        "path": "/fleet",
        "selector": ".fleet-dispatch, .fleet-page, [data-endpoint='fleet'] .gc-main, .gc-page",
        "fallback_shot": "shot-04-fleet",
        "crop": (0.18, 0.18, 0.78, 0.88),
    },
    {
        "stem": "moment-04-boss",
        "path": "/world-boss",
        "selector": ".world-boss-page, .wb-hero, [data-endpoint='world-boss'] .gc-main, .gc-page",
        "fallback_shot": "shot-03-world-boss",
        "crop": (0.18, 0.16, 0.78, 0.88),
    },
    {
        "stem": "moment-05-loot",
        "path": "/inventory",
        "selector": ".inventory-page, .inv-grid, [data-endpoint='inventory'] .gc-main, .gc-page",
        "fallback_shot": "shot-05-inventory",
        "crop": (0.18, 0.16, 0.78, 0.88),
    },
]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_server(base: str, timeout: float = 90.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urlopen(f"{base}/login", timeout=2) as resp:
                if resp.status == 200:
                    return
        except Exception:
            time.sleep(0.3)
    raise RuntimeError(f"server not ready: {base}")


def _setup_db(tmp_dir: Path) -> tuple[Path, str, str]:
    db_file = tmp_dir / f"landing_capture_{uuid.uuid4().hex[:8]}.db"
    os.environ["GC_DB_PATH"] = str(db_file)
    os.environ["SECRET_KEY"] = "test-secret-key-not-default-value-32chars"
    os.environ["GC_SKIP_MIGRATION_CHECK"] = "1"

    import game.db as dbmod
    import game.models as models
    from game.bootstrap import bootstrap_application
    from game.models import create_user, get_homeworld, init_db, save_planet_buildings

    env = os.environ.copy()
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
    bootstrap_application(skip_migration_check=True)

    uname = f"landing_showcase_{uuid.uuid4().hex[:6]}"
    ok, err, user = create_user(uname, PASSWORD)
    if not ok or not user:
        raise RuntimeError(err or "create_user failed")

    pid = int(user["id"])
    hw = get_homeworld(player_id=pid)
    save_planet_buildings(
        int(hw["id"]),
        {
            "metal_mine": 12,
            "crystal_mine": 10,
            "solar_plant": 14,
            "fuel_cell_plant": 8,
            "research_lab": 7,
            "shipyard": 5,
            "metal_storage": 8,
            "crystal_storage": 8,
            "fuel_storage": 6,
            "command_center": 4,
            "radar_array": 3,
            "defense_factory": 3,
        },
    )

    from game.fleet import add_planet_ships

    conn = dbmod.db()
    try:
        conn.execute(
            """
            UPDATE planets SET
              metal = 250000, crystal = 180000, fuel_cells = 90000,
              name = 'Showcase Prime'
            WHERE id = ?;
            """,
            (int(hw["id"]),),
        )
        try:
            add_planet_ships(
                int(hw["id"]),
                pid,
                {"spark_drone": 40},
                conn=conn,
            )
        except Exception:
            pass
        for tech, lvl in (
            ("energy_tech", 6),
            ("espionage_tech", 4),
            ("computer_tech", 5),
            ("weapons_tech", 3),
        ):
            try:
                conn.execute(
                    """
                    INSERT INTO research_levels (user_id, tech_key, level)
                    VALUES (?, ?, ?)
                    ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;
                    """,
                    (pid, tech, lvl),
                )
            except Exception:
                pass
        conn.commit()
    finally:
        conn.close()

    try:
        dbmod.db().close()
    except Exception:
        pass

    return db_file, uname, PASSWORD


def _start_server(db_file: Path, port: int) -> subprocess.Popen:
    env = os.environ.copy()
    env["GC_DB_PATH"] = str(db_file)
    env["SECRET_KEY"] = "test-secret-key-not-default-value-32chars"
    env["GC_SKIP_MIGRATION_CHECK"] = "1"
    env["PORT"] = str(port)
    env["HOST"] = "127.0.0.1"
    env["FLASK_DEBUG"] = "0"
    env["GC_FLASK_THREADED"] = "1"
    env["GC_FLASK_RELOADER"] = "0"
    log_path = Path(tempfile.gettempdir()) / f"gc_landing_server_{port}.log"
    log_fh = open(log_path, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "app.py")],
        cwd=str(ROOT),
        env=env,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
    )
    proc._gc_log_fh = log_fh  # type: ignore[attr-defined]
    proc._gc_log_path = log_path  # type: ignore[attr-defined]
    time.sleep(2.0)
    try:
        _wait_server(f"http://127.0.0.1:{port}", timeout=60.0)
    except Exception:
        try:
            log_fh.flush()
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
        except Exception:
            tail = ""
        raise RuntimeError(f"server not ready on {port}\n{tail}")
    return proc


def _dismiss_overlays(page) -> None:
    """Close cookie notice + what's-new so marketing shots show the real UI."""
    # Mark as seen before UI can re-open the panel after deferred /api/whats-new.
    page.evaluate(
        """() => {
          try { localStorage.setItem('gc_cookie_notice', '1'); } catch (e) {}
          try {
            const mark = (k) => localStorage.setItem(k, '1');
            mark('gc_whats_new_seen');
            const verEl = document.querySelector('[data-gc-version]');
            const ver = verEl && verEl.getAttribute('data-gc-version');
            if (ver) mark('gc_whats_new_seen_v' + ver);
            for (const k of Object.keys(localStorage)) {
              if (k.startsWith('gc_whats_new_seen')) mark(k);
            }
          } catch (e) {}
        }"""
    )
    try:
        btn = page.locator("[data-cookie-notice-accept], [data-cookie-accept]").first
        if btn.count():
            btn.click(timeout=1500)
    except Exception:
        pass

    # What's-new loads deferred — wait briefly then dismiss / force-hide.
    for _ in range(16):
        try:
            root = page.locator("#gc-whats-new")
            if root.count() and root.is_visible():
                try:
                    root.locator("[data-whats-new-dismiss]").first.click(timeout=1500)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            still = page.evaluate(
                """() => {
                  const hide = (el) => {
                    if (!el) return;
                    el.hidden = true;
                    el.classList.add('hidden');
                    el.setAttribute('hidden', '');
                    el.style.setProperty('display', 'none', 'important');
                    el.style.setProperty('visibility', 'hidden', 'important');
                    el.style.setProperty('pointer-events', 'none', 'important');
                  };
                  hide(document.getElementById('gc-whats-new'));
                  hide(document.querySelector('[data-cookie-notice]'));
                  hide(document.getElementById('gc-cookie-notice'));
                  const wn = document.getElementById('gc-whats-new');
                  return !!(wn && !wn.hidden && !wn.classList.contains('hidden')
                            && getComputedStyle(wn).display !== 'none');
                }"""
            )
            if not still:
                break
        except Exception:
            break
        page.wait_for_timeout(250)


def _playwright_login(page, base: str, uname: str, password: str) -> None:
    """Log in via the real login form (more reliable than injecting session cookies)."""
    page.goto(f"{base}/login", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector('input[name="username"]', timeout=20000)
    page.fill('input[name="username"]', uname)
    page.fill('input[name="password"]', password)
    with page.expect_navigation(wait_until="domcontentloaded", timeout=45000):
        page.click('button[type="submit"]')
    if "/login" in page.url or "/register" in page.url:
        raise RuntimeError(f"login did not leave auth page: {page.url}")
    try:
        page.wait_for_selector("#resource-bar, .gc-sidebar, [data-endpoint='overview']", timeout=30000)
    except Exception:
        page.wait_for_timeout(2000)
    if "/login" in page.url:
        raise RuntimeError(f"still on login after submit: {page.url}")


def _to_webp(png_path: Path, webp_path: Path, quality: int = 82) -> None:
    from PIL import Image

    with Image.open(png_path) as im:
        im = im.convert("RGB")
        im.save(webp_path, "WEBP", quality=quality, method=6)


def _find_ffmpeg() -> str:
    which = shutil.which("ffmpeg")
    if which:
        return which
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise RuntimeError(
            "ffmpeg not found. Install system ffmpeg or: pip install imageio-ffmpeg"
        ) from exc


def _build_hero(shot_webps: list[Path], ffmpeg: str) -> None:
    """Ken-Burns slideshow ~28s from ordered WebP shots + endcard (concat clips)."""
    if not shot_webps:
        raise RuntimeError("no shots for hero")

    work = OUT_DIR / "_hero_work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    from PIL import Image, ImageDraw, ImageFont

    frames: list[Path] = []
    target = (1920, 1080)
    for i, src in enumerate(shot_webps):
        with Image.open(src) as im:
            im = im.convert("RGB")
            src_w, src_h = im.size
            scale = max(target[0] / src_w, target[1] / src_h)
            nw, nh = int(src_w * scale), int(src_h * scale)
            im = im.resize((nw, nh), Image.Resampling.LANCZOS)
            left = (nw - target[0]) // 2
            top = (nh - target[1]) // 2
            im = im.crop((left, top, left + target[0], top + target[1]))
            out = work / f"frame_{i:02d}.png"
            im.save(out, "PNG")
            frames.append(out)

    end = Image.new("RGB", target, (4, 8, 16))
    draw = ImageDraw.Draw(end)
    try:
        font_lg = ImageFont.truetype("arial.ttf", 64)
        font_sm = ImageFont.truetype("arial.ttf", 36)
    except Exception:
        font_lg = ImageFont.load_default()
        font_sm = font_lg
    y = 420
    for text, font, color in (
        ("GENESIS COLONIES", font_lg, (70, 229, 255)),
        ("Build your Empire. Conquer the Galaxy.", font_sm, (200, 230, 240)),
        ("PLAY NOW", font_sm, (127, 255, 217)),
    ):
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        draw.text(((target[0] - tw) // 2, y), text, font=font, fill=color)
        y += 70
    end_path = work / "frame_end.png"
    end.save(end_path, "PNG")
    frames.append(end_path)

    poster = OUT_DIR / "hero-poster.webp"
    curated = OUT_DIR / "hero.mp4"
    if not curated.is_file():
        with Image.open(frames[0]) as im:
            im.save(poster, "WEBP", quality=85, method=6)

    per = 3.0
    clip_paths: list[Path] = []
    for i, f in enumerate(frames):
        clip = work / f"clip_{i:02d}.mp4"
        print(f"hero clip {i + 1}/{len(frames)}", flush=True)
        subprocess.run(
            [
                ffmpeg, "-y", "-loop", "1", "-t", str(per), "-i", str(f),
                "-vf", "scale=1920:1080,format=yuv420p",
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-preset", "ultrafast", "-crf", "23", str(clip),
            ],
            check=True,
            capture_output=True,
            timeout=90,
        )
        clip_paths.append(clip)

    list_file = work / "concat.txt"
    list_file.write_text(
        "".join(f"file '{p.resolve().as_posix()}'\n" for p in clip_paths),
        encoding="utf-8",
    )
    curated = OUT_DIR / "hero.mp4"
    mp4 = OUT_DIR / ("hero2.mp4" if curated.is_file() else "hero.mp4")
    webm = OUT_DIR / "hero.webm"
    print(f"Building {mp4.name} (Ken-Burns)…", flush=True)
    subprocess.run(
        [
            ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy", "-movflags", "+faststart", str(mp4),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )

    print("Skipping hero.webm (mp4 is enough)", flush=True)
    webm.unlink(missing_ok=True)

    shutil.rmtree(work, ignore_errors=True)
    if curated.is_file() and mp4.name == "hero2.mp4":
        print("Kept curated hero.mp4; Ken-Burns ->", mp4.name, flush=True)
    else:
        print("Hero written:", mp4.name, poster.name, flush=True)


def _crop_fraction(im, crop: tuple[float, float, float, float]):
    from PIL import Image

    w, h = im.size
    left, top, right, bottom = crop
    box = (
        max(0, int(w * left)),
        max(0, int(h * top)),
        min(w, int(w * right)),
        min(h, int(h * bottom)),
    )
    if box[2] - box[0] < 64 or box[3] - box[1] < 64:
        return im.copy()
    return im.crop(box)


def _encode_moment_loop(still_png: Path, moment_stem: str, ffmpeg: str) -> None:
    """Short Ken-Burns mp4 (~4s loop) + webp poster from a focused UI still."""
    from PIL import Image, ImageOps

    MOMENTS_DIR.mkdir(parents=True, exist_ok=True)
    poster = MOMENTS_DIR / f"{moment_stem}.webp"
    mp4 = MOMENTS_DIR / f"{moment_stem}.mp4"
    work = MOMENTS_DIR / f"_{moment_stem}_work.png"

    target = (1280, 720)
    with Image.open(still_png) as im:
        im = im.convert("RGB")
        # Contain (not cover): keep the full UI clip visible — resource bars etc. are wide/short.
        fitted = ImageOps.contain(im, target, Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", target, (4, 8, 16))
        ox = (target[0] - fitted.size[0]) // 2
        oy = (target[1] - fitted.size[1]) // 2
        canvas.paste(fitted, (ox, oy))
        canvas.save(work, "PNG")
        canvas.save(poster, "WEBP", quality=84, method=6)

    # Subtle zoom-in Ken Burns (~4s @ 30fps) on the padded 16:9 frame
    vf = (
        "scale=1400:788:force_original_aspect_ratio=increase,"
        "crop=1280:720,"
        "zoompan=z='min(1.08,1+0.0006*on)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        "d=120:s=1280x720:fps=30,"
        "format=yuv420p"
    )
    cmd = [
        ffmpeg,
        "-y",
        "-loop",
        "1",
        "-i",
        str(work),
        "-vf",
        vf,
        "-t",
        "4",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-movflags",
        "+faststart",
        "-pix_fmt",
        "yuv420p",
        str(mp4),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    work.unlink(missing_ok=True)
    if r.returncode != 0 or not mp4.is_file() or mp4.stat().st_size < 1000:
        print(f"  moment mp4 failed ({moment_stem}): {r.stderr[-400:] if r.stderr else 'no stderr'}", flush=True)
        mp4.unlink(missing_ok=True)
    else:
        print(f"  moment loop {mp4.name} + {poster.name}", flush=True)


def _capture_moment_clip(page, base: str, spec: dict, shot_index: dict[str, Path], ffmpeg: str) -> None:
    """Capture a focused UI region for a live moment (selector clip, else shot crop)."""
    from PIL import Image

    stem = spec["stem"]
    png = MOMENTS_DIR / f"_{stem}_raw.png"
    MOMENTS_DIR.mkdir(parents=True, exist_ok=True)
    captured = False

    try:
        page.goto(f"{base}{spec['path']}", wait_until="domcontentloaded", timeout=60000)
        if "/login" in page.url:
            raise RuntimeError("redirected to login")
        try:
            page.wait_for_selector("#resource-bar, .gc-sidebar, .gc-page", timeout=20000)
        except Exception:
            page.wait_for_timeout(1000)
        page.wait_for_timeout(600)
        _dismiss_overlays(page)
        page.wait_for_timeout(300)

        for sel in [s.strip() for s in str(spec.get("selector") or "").split(",") if s.strip()]:
            try:
                loc = page.locator(sel).first
                if loc.count() and loc.is_visible(timeout=1200):
                    box = loc.bounding_box()
                    if box and box.get("width", 0) >= 80 and box.get("height", 0) >= 40:
                        # Pad short/wide HUD strips so moments stay readable after 16:9 letterbox.
                        pad_x = max(24, int(box["width"] * 0.02))
                        pad_y = max(36, int(box["height"] * 0.35))
                        clip = {
                            "x": max(0, box["x"] - pad_x),
                            "y": max(0, box["y"] - pad_y),
                            "width": box["width"] + pad_x * 2,
                            "height": box["height"] + pad_y * 2,
                        }
                        page.screenshot(path=str(png), clip=clip)
                        captured = True
                        print(f"  clip via {sel!r}", flush=True)
                        break
            except Exception:
                continue
    except Exception as exc:
        print(f"  moment navigate skip {stem}: {exc}", flush=True)

    if not captured:
        fb = shot_index.get(spec.get("fallback_shot") or "")
        if fb and fb.is_file():
            with Image.open(fb) as im:
                cropped = _crop_fraction(im.convert("RGB"), tuple(spec.get("crop") or (0, 0, 1, 1)))
                cropped.save(png, "PNG")
                captured = True
                print(f"  crop fallback from {fb.name}", flush=True)

    if not captured:
        print(f"  SKIP moment {stem}: no clip", flush=True)
        return

    _encode_moment_loop(png, stem, ffmpeg)
    png.unlink(missing_ok=True)




def capture(
    base_url: str | None = None,
    username: str = "admin",
    password: str = "admin",
) -> int:
    print("capture: checking playwright…", flush=True)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("FAIL: pip install playwright && playwright install chromium")
        return 2

    print("capture: resolving ffmpeg…", flush=True)
    ffmpeg = _find_ffmpeg()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    MOMENTS_DIR.mkdir(parents=True, exist_ok=True)

    proc = None
    tmp_ctx = None
    uname = username
    pwd = password

    try:
        if base_url:
            base = base_url.rstrip("/")
            print(f"Using existing server {base} as {uname}", flush=True)
            _wait_server(base, timeout=20.0)
        else:
            tmp_ctx = tempfile.TemporaryDirectory(prefix="gc_landing_cap_")
            tmp = Path(tmp_ctx.name)
            port = _free_port()
            print(f"capture: seeding DB in {tmp} …", flush=True)
            db_file, uname, pwd = _setup_db(tmp)
            # Prefer requested credentials if seed created a different user —
            # for self-hosted temp DB we keep the seeded showcase user.
            base = f"http://127.0.0.1:{port}"
            print(f"Starting server on {base} …", flush=True)
            proc = _start_server(db_file, port)

        shot_webps: list[Path] = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                device_scale_factor=1,
            )
            context.add_init_script(
                """() => {
                  try { localStorage.setItem('gc_cookie_notice', '1'); } catch (e) {}
                  try {
                    localStorage.setItem('gc_whats_new_seen', '1');
                    localStorage.setItem('gc_whats_new_seen_v0.9.1', '1');
                    localStorage.setItem('gc_whats_new_seen_v0.9.2', '1');
                    for (const k of Object.keys(localStorage)) {
                      if (k.startsWith('gc_whats_new_seen')) localStorage.setItem(k, '1');
                    }
                  } catch (e) {}
                }"""
            )
            page = context.new_page()
            page.set_default_timeout(60000)
            print(f"capture: form login as {uname} …", flush=True)
            _playwright_login(page, base, uname, pwd)
            page.wait_for_timeout(1200)
            _dismiss_overlays(page)
            print(f"capture: logged in at {page.url}", flush=True)

            for stem, path in SHOT_ROUTES:
                url = f"{base}{path}"
                print(f"Capture {stem}: {url}", flush=True)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    if "/login" in page.url:
                        raise RuntimeError(f"redirected to login for {path}")
                    try:
                        page.wait_for_selector("#resource-bar, .gc-sidebar, .gc-page", timeout=25000)
                    except Exception:
                        page.wait_for_timeout(1500)
                    page.wait_for_timeout(800)
                    _dismiss_overlays(page)
                    if stem == "shot-09-titans":
                        # Open a Titan companion popover when available (distinct from Overview).
                        try:
                            hot = page.locator("[data-companion-owned='1'], .overview-companion-hotspot").first
                            if hot.count() and hot.is_visible(timeout=1500):
                                hot.click(timeout=2000)
                                page.wait_for_timeout(600)
                        except Exception:
                            pass
                    page.wait_for_timeout(400)
                    png = SHOTS_DIR / f"{stem}.png"
                    webp = SHOTS_DIR / f"{stem}.webp"
                    page.screenshot(path=str(png), full_page=False)
                    _to_webp(png, webp)
                    png.unlink(missing_ok=True)
                    # Ken-Burns backup uses the primary 8 marketing shots only.
                    if stem.startswith("shot-0") and int(stem.split("-")[1]) <= 8:
                        shot_webps.append(webp)
                    print(f"  ok {webp.relative_to(ROOT)}", flush=True)
                except Exception as exc:
                    print(f"  SKIP {stem}: {exc}", flush=True)

            shot_index = {p.stem: p for p in shot_webps}
            for spec in MOMENT_CLIPS:
                print(f"Moment {spec['stem']} …", flush=True)
                try:
                    _capture_moment_clip(page, base, spec, shot_index, ffmpeg)
                except Exception as exc:
                    print(f"  SKIP {spec['stem']}: {exc}", flush=True)

            browser.close()

        if shot_webps:
            _build_hero(shot_webps, ffmpeg)
        else:
            print("No shots captured — hero skipped", flush=True)
            return 1

        print("Done. Assets in", OUT_DIR.relative_to(ROOT), flush=True)
        return 0
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except Exception:
                proc.kill()
            try:
                fh = getattr(proc, "_gc_log_fh", None)
                if fh:
                    fh.close()
            except Exception:
                pass
        if tmp_ctx is not None:
            tmp_ctx.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture landing marketing media from live UI")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:5000",
        help="Existing Flask server (default: http://127.0.0.1:5000). Use '' for temp DB.",
    )
    parser.add_argument("--user", default="admin", help="Login username (default: admin)")
    parser.add_argument("--password", default="admin", help="Login password (default: admin)")
    args = parser.parse_args()
    base = args.base_url.strip() or None
    return capture(base_url=base, username=args.user, password=args.password)


if __name__ == "__main__":
    raise SystemExit(main())
