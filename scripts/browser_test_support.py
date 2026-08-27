#!/usr/bin/env python3
"""Shared Playwright support for Genesis Sentinel.

This module is QA infrastructure only. Sandbox mode always uses a disposable
SQLite database and a dedicated Flask subprocess; it never opens game/game.db.
"""

from __future__ import annotations

import os
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
DEFAULT_SECRET = "sentinel-test-secret-key-not-for-production-32chars"


@dataclass
class SandboxRuntime:
    base_url: str
    db_file: Path
    username: str
    password: str
    process: subprocess.Popen
    log_handle: IO[str]
    temp_dir: Path

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


def _server_env(db_file: Path, port: int | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": "development",
            "FLASK_ENV": "development",
            "FLASK_DEBUG": "0",
            "GC_DB_BACKEND": "sqlite",
            "GC_DB_PATH": str(db_file),
            "GC_SKIP_MIGRATION_CHECK": "1",
            "GC_EMBEDDED_CRON": "0",
            "GC_FLASK_THREADED": "1",
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
    raise RuntimeError(f"Sentinel Flask subprocess not ready: {base_url}")


def _create_test_player(db_file: Path) -> tuple[str, str]:
    # Keep the parent process aligned with the disposable DB before importing
    # Genesis DB modules. The server itself starts in a separate process.
    previous_db = os.environ.get("GC_DB_PATH")
    previous_secret = os.environ.get("SECRET_KEY")
    previous_skip = os.environ.get("GC_SKIP_MIGRATION_CHECK")
    os.environ["GC_DB_PATH"] = str(db_file)
    os.environ["SECRET_KEY"] = DEFAULT_SECRET
    os.environ["GC_SKIP_MIGRATION_CHECK"] = "1"
    try:
        import game.db as dbmod
        import game.models as models
        from game.models import create_user, init_db

        dbmod.DB_PATH = db_file
        models.DB_PATH = db_file
        init_db()

        username = f"SentinelQA{uuid.uuid4().hex[:6]}"
        password = "Sentinel-pass-123!"
        ok, error, user = create_user(username, password)
        if not ok or not user:
            raise RuntimeError(error or "create_user failed")
        try:
            from game.db import db

            db().close()
        except Exception:
            pass
        return username, password
    finally:
        if previous_db is None:
            os.environ.pop("GC_DB_PATH", None)
        else:
            os.environ["GC_DB_PATH"] = previous_db
        if previous_secret is None:
            os.environ.pop("SECRET_KEY", None)
        else:
            os.environ["SECRET_KEY"] = previous_secret
        if previous_skip is None:
            os.environ.pop("GC_SKIP_MIGRATION_CHECK", None)
        else:
            os.environ["GC_SKIP_MIGRATION_CHECK"] = previous_skip


def start_sandbox(artifact_root: Path) -> SandboxRuntime:
    artifact_root.mkdir(parents=True, exist_ok=True)
    temp_root = ROOT / ".tmp_sentinel"
    temp_root.mkdir(exist_ok=True)
    temp_dir = temp_root / uuid.uuid4().hex[:12]
    temp_dir.mkdir(parents=True, exist_ok=False)
    db_file = temp_dir / "sentinel.db"

    migration = subprocess.run(
        [sys.executable, str(ROOT / "migrate.py")],
        cwd=str(ROOT),
        env=_server_env(db_file),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if migration.returncode != 0:
        details = (migration.stderr or migration.stdout or "").strip()
        raise RuntimeError(f"Sentinel migration failed: {details}")

    username, password = _create_test_player(db_file)
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    log_handle = (artifact_root / "server.log").open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "app.py")],
        cwd=str(ROOT),
        env=_server_env(db_file, port),
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

    return SandboxRuntime(
        base_url=base_url,
        db_file=db_file,
        username=username,
        password=password,
        process=process,
        log_handle=log_handle,
        temp_dir=temp_dir,
    )


def login_with_ui(page, base_url: str, username: str, password: str) -> None:
    page.goto(f"{base_url.rstrip('/')}/login", wait_until="domcontentloaded")
    page.locator("#username").fill(username)
    page.locator("#password").fill(password)
    page.locator("form.auth-form button[type='submit']").click()
    try:
        page.wait_for_url(lambda url: "/login" not in url, timeout=30_000)
    except Exception as exc:
        error = ""
        form_error = page.locator("#form-error")
        if form_error.count():
            try:
                error = form_error.inner_text(timeout=1_000).strip()
            except Exception:
                error = ""
        raise RuntimeError(f"Sentinel UI login failed: {error or page.url}") from exc


def safe_name(value: str) -> str:
    chars = []
    for char in value.lower():
        if char.isalnum():
            chars.append(char)
        elif char in {"-", "_"}:
            chars.append(char)
        else:
            chars.append("-")
    return "".join(chars).strip("-") or "page"
