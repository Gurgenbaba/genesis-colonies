"""Public high-score board for the arcade easter egg on the developer portfolio.

The portfolio (gurgenbaba.github.io) is a static site, so the arcade runs fully
client-side and cannot be made cheat-proof. The goal here is to keep the board
clean, not forensic:

- every run starts with a signed, single-use run token (HMAC over issue time
  and nonce), so a score cannot be posted without having started a run;
- the claimed run length must fit inside the time since the token was issued,
  and the score must be reachable in that time;
- names are three letters, arcade style, with a small blocklist;
- per-IP rate limits live in memory only; no IP address is stored.

Requests arrive as CORS "simple" requests (text/plain JSON body, no cookies),
so no preflight handling is needed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from typing import Any

TOKEN_MAX_AGE_SECONDS = 2 * 3600
DURATION_SLACK_SECONDS = 5
MIN_RUN_SECONDS = 5
MAX_POINTS_PER_SECOND = 120
MAX_SCORE = 1_000_000
BOARD_SIZE = 10
BOARD_CACHE_TTL_SECONDS = 30
RUN_RATE = (30, 600.0)      # 30 run tokens per 10 minutes per IP
SUBMIT_RATE = (10, 600.0)   # 10 submissions per 10 minutes per IP

_NAME_RE = re.compile(r"^[A-Z]{3}$")
_BLOCKED_NAMES = frozenset({
    "ASS", "CUM", "DIC", "DIK", "FAG", "FCK", "FUC", "FUK", "KKK", "NGR",
    "NIG", "NZI", "SEX", "TIT", "WTF", "HTL", "SSS",
})

_RUN_BUCKETS: dict[str, list] = {}
_SUBMIT_BUCKETS: dict[str, list] = {}
_CACHE_LOCK = threading.Lock()
_BOARD_CACHE: dict[str, Any] = {"expires_at": 0.0, "rows": None}


def reset_arcade_state() -> None:
    _RUN_BUCKETS.clear()
    _SUBMIT_BUCKETS.clear()
    with _CACHE_LOCK:
        _BOARD_CACHE["expires_at"] = 0.0
        _BOARD_CACHE["rows"] = None


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def issue_run_token(secret: str, *, now: float | None = None) -> str:
    issued = int(time.time() if now is None else now)
    nonce = secrets.token_hex(8)
    payload = f"{issued}.{nonce}"
    return f"{payload}.{_sign(secret, payload)}"


def parse_run_token(secret: str, token: str, *, now: float | None = None) -> tuple[int, str] | None:
    """Return (issued_at, nonce) for a valid, unexpired token, else None."""
    parts = str(token or "").split(".")
    if len(parts) != 3 or not parts[0].isdigit() or not re.fullmatch(r"[0-9a-f]{16}", parts[1]):
        return None
    payload = f"{parts[0]}.{parts[1]}"
    if not hmac.compare_digest(_sign(secret, payload), parts[2]):
        return None
    issued = int(parts[0])
    ts = time.time() if now is None else now
    if issued > ts + 5 or ts - issued > TOKEN_MAX_AGE_SECONDS:
        return None
    return issued, parts[1]


def normalize_name(raw: Any) -> str | None:
    name = str(raw or "").strip().upper()
    if not _NAME_RE.match(name) or name in _BLOCKED_NAMES:
        return None
    return name


def validate_submission(secret: str, data: Any, *, now: float | None = None) -> tuple[dict[str, Any] | None, str]:
    """Check a submitted run. Returns (row, "") or (None, error_code)."""
    if not isinstance(data, dict):
        return None, "bad_request"
    parsed = parse_run_token(secret, data.get("token"), now=now)
    if parsed is None:
        return None, "bad_token"
    issued, nonce = parsed
    name = normalize_name(data.get("name"))
    if name is None:
        return None, "bad_name"
    try:
        score = int(data.get("score"))
        wave = int(data.get("wave"))
        duration_ms = int(data.get("duration_ms"))
    except (TypeError, ValueError):
        return None, "bad_request"
    ts = time.time() if now is None else now
    seconds = duration_ms / 1000.0
    if score <= 0 or score > MAX_SCORE or score % 10 != 0:
        return None, "implausible"
    if seconds < MIN_RUN_SECONDS or seconds > (ts - issued) + DURATION_SLACK_SECONDS:
        return None, "implausible"
    if score > seconds * MAX_POINTS_PER_SECOND + 200:
        return None, "implausible"
    if wave < 1 or wave > 1 + seconds / 4:
        return None, "implausible"
    return {
        "name": name,
        "score": score,
        "wave": wave,
        "duration_ms": duration_ms,
        "run_nonce": nonce,
        "created_at": int(ts),
    }, ""


def _load_board(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT name, score, wave, created_at FROM arcade_scores "
        "ORDER BY score DESC, created_at ASC LIMIT ?",
        (BOARD_SIZE,),
    ).fetchall()
    return [
        {"name": r["name"], "score": int(r["score"]), "wave": int(r["wave"]), "at": int(r["created_at"])}
        for r in rows
    ]


def get_board() -> list[dict[str, Any]] | None:
    now = time.time()
    with _CACHE_LOCK:
        if _BOARD_CACHE["rows"] is not None and now < _BOARD_CACHE["expires_at"]:
            return _BOARD_CACHE["rows"]
    from game.db import db, rollback

    try:
        conn = db()
        try:
            rows = _load_board(conn)
        finally:
            try:
                rollback(conn)
            except Exception:
                pass
            conn.close()
    except Exception:
        with _CACHE_LOCK:
            return _BOARD_CACHE["rows"]
    with _CACHE_LOCK:
        _BOARD_CACHE["rows"] = rows
        _BOARD_CACHE["expires_at"] = now + BOARD_CACHE_TTL_SECONDS
    return rows


def store_score(row: dict[str, Any]) -> tuple[bool, int | None]:
    """Insert once per run token. Returns (stored, rank within top board or None)."""
    from game.db import is_integrity_error, with_transaction

    try:
        with with_transaction() as conn:
            conn.execute(
                "INSERT INTO arcade_scores (name, score, wave, duration_ms, run_nonce, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (row["name"], row["score"], row["wave"], row["duration_ms"], row["run_nonce"], row["created_at"]),
            )
            better = conn.execute(
                "SELECT COUNT(*) AS cnt FROM arcade_scores WHERE score > ?", (row["score"],)
            ).fetchone()
    except Exception as exc:
        if is_integrity_error(exc):
            return False, None
        raise
    with _CACHE_LOCK:
        _BOARD_CACHE["expires_at"] = 0.0
    rank = int(better["cnt"] or 0) + 1
    return True, rank if rank <= BOARD_SIZE else None


def register_arcade_score_routes(app) -> None:
    from flask import current_app, jsonify, request

    from game.public_stats import allowed_origins
    from game.security import _rate_ok, client_ip

    if "api_public_arcade_scores" in app.view_functions:
        return

    def _cors(response):
        origin = (request.headers.get("Origin") or "").rstrip("/")
        if origin and origin in allowed_origins():
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        response.headers["Cache-Control"] = "no-store"
        return response

    def _error(code: str, status: int):
        response = jsonify({"ok": False, "error": code})
        response.status_code = status
        return _cors(response)

    @app.post("/api/public/arcade/run", endpoint="api_public_arcade_run")
    def _arcade_run():
        if not _rate_ok(_RUN_BUCKETS, client_ip(request), RUN_RATE[1], RUN_RATE[0]):
            return _error("rate_limited", 429)
        return _cors(jsonify({"ok": True, "token": issue_run_token(str(current_app.secret_key))}))

    @app.get("/api/public/arcade/scores", endpoint="api_public_arcade_scores")
    def _arcade_board():
        rows = get_board()
        if rows is None:
            return _error("board_unavailable", 503)
        return _cors(jsonify({"ok": True, "scores": rows}))

    @app.post("/api/public/arcade/scores", endpoint="api_public_arcade_submit")
    def _arcade_submit():
        if not _rate_ok(_SUBMIT_BUCKETS, client_ip(request), SUBMIT_RATE[1], SUBMIT_RATE[0]):
            return _error("rate_limited", 429)
        raw = request.get_data(cache=False, as_text=True)
        if len(raw) > 2048:
            return _error("bad_request", 400)
        try:
            data = json.loads(raw or "null")
        except ValueError:
            return _error("bad_request", 400)
        row, err = validate_submission(str(current_app.secret_key), data)
        if row is None:
            return _error(err, 422 if err == "implausible" else 400)
        stored, rank = store_score(row)
        if not stored:
            return _error("run_already_submitted", 409)
        return _cors(jsonify({"ok": True, "rank": rank, "scores": get_board() or []}))
