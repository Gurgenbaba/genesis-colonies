"""
Genesis Colonies – central configuration from environment variables.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT_DIR / ".env"
ENV_EXAMPLE = ROOT_DIR / ".env.example"
VERSION_FILE = ROOT_DIR / "VERSION"

INSECURE_SECRET_KEYS = frozenset({
    "",
    "change-me-dev-secret",
    "change-me",
    "dev",
    "development",
    "secret",
    "admin",
    "test",
    "changeme",
})


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_FILE, override=False)
    except ImportError:
        if ENV_FILE.exists():
            for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                os.environ.setdefault(key, val)


def _normalize_database_url() -> None:
    """Map DATABASE_URL -> GC_DB_PATH for SQLite deployments."""
    if os.environ.get("GC_DB_PATH", "").strip():
        return
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        legacy = os.environ.get("DATABASE_PATH", "").strip()
        if legacy:
            p = Path(legacy)
            if not p.is_absolute():
                p = ROOT_DIR / p
            os.environ["GC_DB_PATH"] = str(p.resolve())
        return
    if url.startswith("sqlite:///"):
        raw = url[len("sqlite:///"):]
        p = Path(raw)
        if not p.is_absolute() and len(raw) > 1 and raw[1] != ":":
            p = ROOT_DIR / raw
        os.environ["GC_DB_PATH"] = str(p.resolve())
    elif url.startswith("sqlite://"):
        raw = url[len("sqlite://"):]
        p = Path(raw)
        if not p.is_absolute():
            p = ROOT_DIR / raw
        os.environ["GC_DB_PATH"] = str(p.resolve())


def get_app_version() -> str:
    try:
        if VERSION_FILE.exists():
            v = VERSION_FILE.read_text(encoding="utf-8").strip()
            if v:
                return v
    except OSError:
        pass
    return "0.0.0-dev"


def is_production() -> bool:
    env = (
        os.environ.get("APP_ENV")
        or os.environ.get("FLASK_ENV")
        or "development"
    ).strip().lower()
    return env in ("production", "prod")


def is_debug_enabled() -> bool:
    val = os.environ.get("FLASK_DEBUG", os.environ.get("DEBUG", "0"))
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def get_secret_key() -> str:
    return os.environ.get("SECRET_KEY", "").strip()


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        return default


def get_gunicorn_workers() -> int:
    """
    Gunicorn worker count. SQLite allows one writer — default 1 for sqlite deployments.
    Override with GUNICORN_WORKERS when using a future Postgres backend.
    """
    backend = os.environ.get("GC_DB_BACKEND", "sqlite").strip().lower()
    default = 1 if backend == "sqlite" else 2
    return _env_int("GUNICORN_WORKERS", default, minimum=1)


def get_client_runtime_config() -> dict[str, int]:
    """
    Client poll intervals (ms) injected into templates as GC_CLIENT_CONFIG.

    Production defaults are slower to reduce SQLite lock pressure on small hosts.
    Override: GC_POLL_ACTIVE_MS, GC_POLL_IDLE_MS, GC_POLL_HIDDEN_MS, GC_SHIPYARD_POLL_MS.
    """
    if is_production():
        defaults = {
            "poll_active_ms": 8000,
            "poll_idle_ms": 12000,
            "poll_hidden_ms": 30000,
            "shipyard_poll_ms": 10000,
        }
    else:
        defaults = {
            "poll_active_ms": 3000,
            "poll_idle_ms": 5000,
            "poll_hidden_ms": 15000,
            "shipyard_poll_ms": 5000,
        }
    return {
        "poll_active_ms": _env_int("GC_POLL_ACTIVE_MS", defaults["poll_active_ms"], minimum=2000),
        "poll_idle_ms": _env_int("GC_POLL_IDLE_MS", defaults["poll_idle_ms"], minimum=3000),
        "poll_hidden_ms": _env_int("GC_POLL_HIDDEN_MS", defaults["poll_hidden_ms"], minimum=10000),
        "shipyard_poll_ms": _env_int(
            "GC_SHIPYARD_POLL_MS", defaults["shipyard_poll_ms"], minimum=3000
        ),
    }


def validate_config(*, strict: bool | None = None) -> list[str]:
    """
    Validate environment. Returns list of error strings (empty = OK).
    strict=True in production; strict=False logs warnings only in dev.
    """
    if strict is None:
        strict = is_production()

    errors: list[str] = []
    warnings: list[str] = []

    secret = get_secret_key()
    if not secret:
        msg = "SECRET_KEY is not set. Set a long random value in .env"
        if strict:
            errors.append(msg)
        else:
            warnings.append(msg + " (using ephemeral key for this process)")

    elif secret.lower() in INSECURE_SECRET_KEYS:
        msg = "SECRET_KEY is an insecure default. Change it before production."
        if strict:
            errors.append(msg)
        else:
            warnings.append(msg)

    if is_production() and is_debug_enabled():
        msg = "FLASK_DEBUG/DEBUG must be off in production (APP_ENV=production)."
        if strict:
            errors.append(msg)
        else:
            warnings.append(msg)

    backend = os.environ.get("GC_DB_BACKEND", "sqlite").strip().lower()
    if backend not in ("sqlite", "postgres"):
        errors.append(f"Unsupported GC_DB_BACKEND: {backend}")

    if backend == "postgres":
        msg = (
            "GC_DB_BACKEND=postgres is not implemented yet. "
            "For Railway/production use GC_DB_BACKEND=sqlite, GC_DB_PATH=/data/game.db, "
            "and a persistent volume at /data. Do not add or link PostgreSQL on Railway yet."
        )
        errors.append(msg)

    if strict and is_production():
        db_url = os.environ.get("DATABASE_URL", "").strip().lower()
        if db_url.startswith("postgres://") or db_url.startswith("postgresql://"):
            warnings.append(
                "DATABASE_URL points to PostgreSQL but is ignored — the app uses SQLite only. "
                "Unset DATABASE_URL or remove the Postgres service link; set GC_DB_PATH=/data/game.db."
            )

    for w in warnings:
        print(f"[GC config] WARNING: {w}", file=sys.stderr)

    return errors


def init_config() -> None:
    """Load .env and normalize paths. Call once at process start."""
    _load_dotenv()
    _normalize_database_url()
