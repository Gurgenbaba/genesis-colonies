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


def get_internal_cron_token() -> str:
    """Bearer token for POST /api/internal/cron/* (ranking + vote re-engagement)."""
    return _env_str("GC_INTERNAL_CRON_TOKEN")


def is_game_worker_primary() -> bool:
    """
    GC-PERF-WORKER-001: when true, periodic poll queue-finish is disabled.

    Due jobs still finish on poll as a safety net; the external game worker
    (HTTP cron / scripts/run_game_worker.py) owns the regular finish cadence.
    """
    val = os.environ.get("GC_GAME_WORKER_PRIMARY", "0")
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def get_resource_persist_interval_sec() -> float:
    """
    GC-PERF-RES-001: minimum idle seconds before poll may persist projected resources.

    Default 600s (was hardcoded 120). Writes still happen on queue finish / fleet dirty.
    """
    return _env_float("GC_RESOURCE_PERSIST_SEC", 600.0, minimum=30.0, maximum=86_400.0)


def get_definition_cache_ttl_sec() -> float:
    """GC-PERF-CACHE-001: process-local definition cache TTL."""
    return _env_float("GC_DEFINITION_CACHE_TTL_SEC", 300.0, minimum=1.0, maximum=86_400.0)


def get_redis_url() -> str:
    """Optional Redis URL for ephemeral cache (never source of truth)."""
    return (os.environ.get("GC_REDIS_URL") or os.environ.get("REDIS_URL") or "").strip()


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


def is_command_map_dev_mode() -> bool:
    """When True, Command Map shows DEV PREVIEW badge and disclaimer (GC-597D)."""
    val = os.environ.get("GC_COMMAND_MAP_DEV_MODE", "0")
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def is_command_map_accessible(*, dev_query: str | None = None) -> bool:
    """Command Map is dev-only unless env flag or ?dev=1 (GC-593)."""
    if is_command_map_dev_mode():
        return True
    dev = str(dev_query or "").strip().lower()
    return dev in ("1", "true", "yes", "on")


def _env_str(name: str) -> str:
    val = str(os.environ.get(name) or "").strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
        val = val[1:-1].strip()
    return val


def get_discord_support_webhook_url() -> str:
    """Optional webhook for #ticket-feed (GC-656). Never commit the URL."""
    return _env_str("DISCORD_SUPPORT_WEBHOOK_URL")


def get_discord_bot_token() -> str:
    """Bot token for Discord API (forum threads). Never commit."""
    return _env_str("DISCORD_BOT_TOKEN")


def get_discord_support_forum_channel_id() -> str:
    """Forum channel ID for ingame support tickets (#tickets)."""
    return _env_str("DISCORD_SUPPORT_FORUM_CHANNEL_ID")


def get_discord_user_agent() -> str:
    custom = _env_str("DISCORD_USER_AGENT")
    if custom:
        return custom
    return "Genesis-Colonies/1.0 (+https://www.genesis-colonies.de)"


def get_discord_support_forum_tag_id(tag_key: str) -> str:
    """
    Forum tag snowflake by logical key: cheater, payments, anything, in_progress, done.
    Env: DISCORD_SUPPORT_TAG_CHEATER, DISCORD_SUPPORT_TAG_PAYMENTS, etc.
    """
    key = str(tag_key or "").strip().lower().replace("-", "_")
    env_name = f"DISCORD_SUPPORT_TAG_{key.upper()}"
    return _env_str(env_name)


def get_public_base_url() -> str:
    """Public site URL for outbound links (emails, Discord embeds)."""
    base = str(os.environ.get("PUBLIC_BASE_URL") or os.environ.get("GC_PUBLIC_URL") or "").strip()
    return base.rstrip("/")


def is_action_perf_debug_enabled() -> bool:
    """GC-841: optional action latency profiling (server logs + client console)."""
    val = os.environ.get("GC_PERF_DEBUG", "0")
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def is_nav_perf_debug_enabled() -> bool:
    """GC-PERF-002: browser PJAX navigation timing (console, debug only)."""
    val = os.environ.get("GC_NAV_PERF_DEBUG", "0")
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def is_ssr_perf_debug_enabled() -> bool:
    """GC-853: optional SSR page render profiling (server logs only)."""
    val = os.environ.get("GC_SSR_PERF_DEBUG", "0")
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _env_float(
    name: str,
    default: float,
    *,
    minimum: float = 0.0,
    maximum: float = 1.0,
) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return min(maximum, max(minimum, float(raw)))
    except ValueError:
        return default


def is_request_perf_debug_enabled() -> bool:
    """GC-PERF-REQUEST-TRACE: global slow-request profiling (server logs only)."""
    if is_action_perf_debug_enabled():
        return True
    val = os.environ.get("GC_REQUEST_PERF_DEBUG", "0")
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def get_request_perf_slow_ms() -> float:
    """Minimum total_ms before emitting a [GC REQUEST PERF] log line."""
    return _env_float("GC_REQUEST_PERF_SLOW_MS", 500.0, minimum=0.0, maximum=600_000.0)


def get_request_perf_sample() -> float:
    """Fraction of requests to measure (0.0–1.0)."""
    return _env_float("GC_REQUEST_PERF_SAMPLE", 1.0, minimum=0.0, maximum=1.0)


def get_perf_budgets() -> dict[str, float]:
    """
    GC-PERF-CORE-001: hard performance budgets (see docs/GC_PERF_CORE.md).

    Used by request-perf logging and scripts/perf_baseline.py.
    Env overrides: GC_PERF_BUDGET_<KEY> (e.g. GC_PERF_BUDGET_DIET_POLL_MS=40).
    """
    defaults: dict[str, float] = {
        "pjax_ssr_ms": 100.0,
        "action_ms": 120.0,
        "diet_poll_ms": 40.0,
        "diet_payload_bytes": 15_360.0,  # 15 KB
        "definition_lookup_ms": 1.0,
        "diet_sql_count": 5.0,
        "diet_sql_write_count": 0.0,
    }
    out: dict[str, float] = {}
    for key, default in defaults.items():
        env_key = "GC_PERF_BUDGET_" + key.upper()
        out[key] = _env_float(env_key, default, minimum=0.0, maximum=10_000_000.0)
    return out


def is_perf_budget_assert_enabled() -> bool:
    """When set, tests may fail on budget misses (never on by default in prod)."""
    val = os.environ.get("GC_PERF_BUDGET_ASSERT", "0")
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def get_client_runtime_config() -> dict[str, int | bool]:
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
        "command_map_dev_mode": is_command_map_dev_mode(),
        "action_perf_debug": is_action_perf_debug_enabled(),
        "nav_perf_debug": is_nav_perf_debug_enabled(),
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
        db_url = os.environ.get("DATABASE_URL", "").strip()
        if not db_url:
            errors.append(
                "GC_DB_BACKEND=postgres requires DATABASE_URL=postgresql://…"
            )
        else:
            try:
                import psycopg  # noqa: F401
                import psycopg_pool  # noqa: F401
            except ImportError:
                errors.append(
                    "GC_DB_BACKEND=postgres requires: pip install 'psycopg[binary]' psycopg_pool"
                )

    if strict and is_production():
        db_url = os.environ.get("DATABASE_URL", "").strip().lower()
        if backend == "sqlite" and (
            db_url.startswith("postgres://") or db_url.startswith("postgresql://")
        ):
            warnings.append(
                "DATABASE_URL points to PostgreSQL but GC_DB_BACKEND=sqlite — "
                "Postgres URL is ignored. Set GC_DB_BACKEND=postgres to use it, "
                "or unset DATABASE_URL for SQLite-only deploys."
            )
        if not get_internal_cron_token():
            warnings.append(
                "GC_INTERNAL_CRON_TOKEN is not set — ranking HTTP cron "
                "(POST /api/internal/cron/ranking) is disabled."
            )

    for w in warnings:
        print(f"[GC config] WARNING: {w}", file=sys.stderr)

    return errors


def init_config() -> None:
    """Load .env and normalize paths. Call once at process start."""
    _load_dotenv()
    _normalize_database_url()
    if not is_production():
        try:
            from game.discord_auth import discord_oauth_configured

            if not discord_oauth_configured():
                print(
                    "[GC config] Discord OAuth disabled — set DISCORD_CLIENT_ID and "
                    "DISCORD_CLIENT_SECRET in .env (optional: DISCORD_REDIRECT_URI or PUBLIC_BASE_URL).",
                    file=sys.stderr,
                )
        except Exception:
            pass
