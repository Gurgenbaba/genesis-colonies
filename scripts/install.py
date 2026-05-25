#!/usr/bin/env python3
"""
Genesis Colonies — production installer / first-time setup.

Usage:
    python scripts/install.py
    python scripts/install.py --venv --admin
    python scripts/install.py --non-interactive

Windows:
    py -3 scripts\\install.py --venv
"""

from __future__ import annotations

import argparse
import getpass
import os
import shutil
import subprocess
import sys
from pathlib import Path

MIN_PYTHON = (3, 10)
ROOT = Path(__file__).resolve().parent.parent


def log(msg: str) -> None:
    print(f"[GC install] {msg}")


def fail(msg: str, code: int = 1) -> None:
    log(f"ERROR: {msg}")
    raise SystemExit(code)


def check_python_version() -> None:
    if sys.version_info < MIN_PYTHON:
        fail(
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required, "
            f"found {sys.version_info.major}.{sys.version_info.minor}"
        )
    log(f"Python OK ({sys.version.split()[0]})")


def resolve_python(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    return Path(sys.executable)


def maybe_create_venv(use_venv: bool) -> Path:
    if not use_venv:
        return Path(sys.executable)

    venv_dir = ROOT / ".venv"
    py = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not py.exists():
        log(f"Creating venv at {venv_dir}")
        subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)])
    else:
        log(f"Using existing venv at {venv_dir}")
    return py


def pip_install(py: Path) -> None:
    log("Installing dependencies from requirements.txt")
    subprocess.check_call([str(py), "-m", "pip", "install", "--upgrade", "pip"])
    subprocess.check_call([str(py), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])


def ensure_env_file() -> Path:
    env_path = ROOT / ".env"
    example = ROOT / ".env.example"
    if env_path.exists():
        log(f".env already exists: {env_path}")
        return env_path
    if not example.exists():
        fail(".env.example not found")
    shutil.copyfile(example, env_path)
    log(f"Created .env from .env.example — edit SECRET_KEY before production")
    return env_path


def load_env_for_subprocess() -> dict[str, str]:
    env = os.environ.copy()
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            env.setdefault(key.strip(), val.strip().strip('"').strip("'"))
    return env


def check_writable_paths() -> None:
    from game.config import init_config
    from game.health import check_writable

    init_config()
    result = check_writable()
    if not result["ok"]:
        for path, info in result["paths"].items():
            if not info.get("ok"):
                fail(f"Path not writable: {path} ({info.get('error')})")
    log("Write permissions OK")


def run_database_setup(py: Path, env: dict[str, str]) -> None:
    log("Initializing database (init_db)")
    subprocess.check_call(
        [str(py), "-c", "from game.bootstrap import bootstrap_application; bootstrap_application(skip_migration_check=True)"],
        cwd=str(ROOT),
        env=env,
    )

    log("Running migrations (migrate.py)")
    subprocess.check_call([str(py), str(ROOT / "migrate.py")], cwd=str(ROOT), env=env)

    from game.config import init_config
    from game.migrations_util import migrations_are_current

    init_config()
    current, pending, err = migrations_are_current()
    if err:
        fail(f"Migration verification failed: {err}")
    if not current:
        fail(f"Migrations still pending: {', '.join(pending)}")
    log("Database and migrations OK")


def maybe_create_admin(py: Path, env: dict[str, str], *, ask: bool) -> None:
    if not ask:
        log("Skipping admin creation")
        return

    code = (
        "from game.config import init_config; init_config(); "
        "from game.models import db; "
        "c=db(); n=c.execute('SELECT COUNT(*) FROM users').fetchone()[0]; c.close(); "
        "print(n)"
    )
    out = subprocess.check_output([str(py), "-c", code], cwd=str(ROOT), env=env, text=True).strip()
    if int(out) > 0:
        log(f"Users already exist ({out}) — skip admin prompt")
        return

    log("No users found — create admin account")
    username = input("Admin username [admin]: ").strip() or "admin"
    while True:
        password = getpass.getpass("Admin password: ")
        confirm = getpass.getpass("Confirm password: ")
        if password and password == confirm:
            break
        print("[GC install] Passwords do not match or are empty. Try again.")

    create_code = (
        "from game.config import init_config; init_config(); "
        "from game.models import create_user; "
        f"ok, err, info = create_user({username!r}, {password!r}, is_admin=1); "
        "import sys; "
        "print('OK' if ok else err); "
        "sys.exit(0 if ok else 1)"
    )
    result = subprocess.run([str(py), "-c", create_code], cwd=str(ROOT), env=env, text=True)
    if result.returncode != 0:
        fail("Admin user creation failed")
    log(f"Admin user '{username}' created")


def print_next_steps(use_venv: bool) -> None:
    log("Installation complete.")
    if use_venv:
        if os.name == "nt":
            log("Activate venv:  .\\.venv\\Scripts\\Activate.ps1")
        else:
            log("Activate venv:  source .venv/bin/activate")
    log("Start dev server: python app.py")
    log("Health check:     curl http://127.0.0.1:5000/health")
    log("Production:       set APP_ENV=production and FLASK_DEBUG=0 in .env")
    log("Update existing:  git pull && pip install -r requirements.txt && python migrate.py")


def main() -> None:
    parser = argparse.ArgumentParser(description="Genesis Colonies installer")
    parser.add_argument("--venv", action="store_true", help="Create/use .venv and install deps there")
    parser.add_argument("--admin", action="store_true", help="Prompt for admin user if none exist")
    parser.add_argument("--non-interactive", action="store_true", help="No prompts (no admin creation)")
    parser.add_argument("--python", dest="python_exe", help="Python executable to use")
    args = parser.parse_args()

    interactive = not args.non_interactive

    log(f"Project root: {ROOT}")
    check_python_version()

    py = maybe_create_venv(args.venv) if args.venv else resolve_python(args.python_exe)
    if args.venv or args.python_exe:
        pip_install(py)
    else:
        log("Installing deps with current interpreter")
        pip_install(py)

    ensure_env_file()
    env = load_env_for_subprocess()

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    check_writable_paths()
    run_database_setup(py, env)

    if args.admin:
        maybe_create_admin(py, env, ask=True)
    elif interactive:
        ans = input("Create admin user if none exist? [y/N]: ").strip().lower()
        if ans in ("y", "yes"):
            maybe_create_admin(py, env, ask=True)

    print_next_steps(args.venv)


if __name__ == "__main__":
    main()
