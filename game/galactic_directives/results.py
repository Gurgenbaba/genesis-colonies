"""Galactic directive election results inbox broadcast (GC-720G)."""

from __future__ import annotations

import html
import sqlite3
import time
from typing import Any, Dict, List, Optional

from ..db import begin_write_transaction, commit, db
from ..galaxy import get_galaxy_max
from ..i18n import DEFAULT_LOCALE, tr
from ..messages import SYSTEM_BROADCAST_SENDER, create_message
from .definitions import get_directive_definition, schema_ready
from .voting import _tally_votes, _ym_key


def _directive_label(key: Optional[str], *, locale: str) -> str:
    if not key:
        return "—"
    definition = get_directive_definition(key)
    label_key = (definition or {}).get("label_key") or f"gd_dir_{key}_title"
    return tr(str(label_key), str(key), locale=locale)


def _build_results_body(
    *,
    year: int,
    month: int,
    galaxies: List[Dict[str, Any]],
    locale: str,
) -> str:
    intro = tr(
        "gd_results_intro",
        "Die galaktische Abstimmung für %(year)s-%(month)02d ist abgeschlossen.",
        locale=locale,
        year=year,
        month=month,
    )
    parts = [f"<p>{html.escape(intro)}</p>"]
    for entry in galaxies:
        galaxy = int(entry["galaxy"])
        primary = _directive_label(entry.get("primary"), locale=locale)
        secondary = _directive_label(entry.get("secondary"), locale=locale)
        p_votes = int(entry.get("primary_votes") or 0)
        s_votes = int(entry.get("secondary_votes") or 0)
        total = int(entry.get("total_votes") or 0)
        line = tr(
            "gd_results_galaxy_line",
            "Galaxie %(galaxy)s — Primär: %(primary)s (%(primary_votes)s), Sekundär: %(secondary)s (%(secondary_votes)s), Stimmen gesamt: %(total)s",
            locale=locale,
            galaxy=galaxy,
            primary=primary,
            secondary=secondary,
            primary_votes=p_votes,
            secondary_votes=s_votes,
            total=total,
        )
        parts.append(f"<p>{html.escape(line)}</p>")
        if entry.get("tie_primary"):
            tie = tr(
                "gd_results_tie_primary",
                "Hinweis: Gleichstand bei der Primärdirektive — Zufallsentscheid.",
                locale=locale,
            )
            parts.append(f"<p><em>{html.escape(tie)}</em></p>")
        if entry.get("vote_bars"):
            bar_bits = []
            for key, count in entry["vote_bars"]:
                label = _directive_label(key, locale=locale)
                bar_bits.append(f"{html.escape(label)}: {int(count)}")
            parts.append(f"<p>{' · '.join(bar_bits)}</p>")
    link = tr(
        "gd_results_link",
        "Zur Galaktischen Politik: /galactic-politics",
        locale=locale,
    )
    parts.append(f"<p><a href=\"/galactic-politics\">{html.escape(link)}</a></p>")
    return "\n".join(parts)


def _collect_month_cycles(
    year: int,
    month: int,
    *,
    conn: sqlite3.Connection,
) -> List[Dict[str, Any]]:
    galaxy_max = int(get_galaxy_max(conn) or 1)
    rows = conn.execute(
        """
        SELECT * FROM gd_cycles
        WHERE year = ? AND month = ?
        ORDER BY galaxy ASC;
        """,
        (int(year), int(month)),
    ).fetchall()
    by_galaxy = {int(r["galaxy"]): dict(r) for r in rows}
    out: List[Dict[str, Any]] = []
    for galaxy_id in range(1, galaxy_max + 1):
        cycle = by_galaxy.get(galaxy_id)
        if cycle is None or not cycle.get("winning_primary"):
            return []
        tallies = _tally_votes(int(cycle["id"]), conn)
        out.append(
            {
                "galaxy": galaxy_id,
                "cycle_id": int(cycle["id"]),
                "primary": cycle.get("winning_primary"),
                "secondary": cycle.get("winning_secondary"),
                "primary_votes": int(cycle.get("winning_primary_votes") or 0),
                "secondary_votes": int(cycle.get("winning_secondary_votes") or 0),
                "total_votes": int(cycle.get("total_votes") or 0),
                "tie_primary": bool(int(cycle.get("is_tie_primary") or 0)),
                "results_sent": int(cycle.get("results_sent") or 0),
                "vote_bars": tallies,
            }
        )
    return out


def maybe_broadcast_cycle_results(
    year: int,
    month: int,
    *,
    conn: Optional[sqlite3.Connection] = None,
    now: Optional[int] = None,
) -> Dict[str, Any]:
    """
    When every playable galaxy has winners for ``(year, month)`` and results are
    not yet sent, broadcast one inbox message per player and mark ``results_sent``.
    """
    own_conn = conn is None
    if own_conn:
        conn = db()
    ts = int(now if now is not None else time.time())
    try:
        if not schema_ready(conn=conn):
            return {"ok": False, "reason": "not_ready", "sent": False}

        galaxies = _collect_month_cycles(int(year), int(month), conn=conn)
        if not galaxies:
            return {"ok": True, "sent": False, "reason": "incomplete"}

        if all(int(g.get("results_sent") or 0) == 1 for g in galaxies):
            return {"ok": True, "sent": False, "reason": "already_sent"}

        subject = tr(
            "gd_results_subject",
            "Galaktische Direktiven — Ergebnis %(year)s-%(month)02d",
            locale=DEFAULT_LOCALE,
            year=int(year),
            month=int(month),
        )
        body = _build_results_body(
            year=int(year),
            month=int(month),
            galaxies=galaxies,
            locale=DEFAULT_LOCALE,
        )
        metadata = {
            "kind": "gd_results",
            "year": int(year),
            "month": int(month),
            "ym": _ym_key(int(year), int(month)),
            "galaxies": [
                {
                    "galaxy": g["galaxy"],
                    "primary": g["primary"],
                    "secondary": g["secondary"],
                    "primary_votes": g["primary_votes"],
                    "secondary_votes": g["secondary_votes"],
                    "total_votes": g["total_votes"],
                    "tie_primary": g["tie_primary"],
                }
                for g in galaxies
            ],
        }

        player_rows = conn.execute("SELECT id FROM players ORDER BY id ASC;").fetchall()
        player_ids = [int(r["id"]) for r in player_rows]
        delivered = 0
        begin_write_transaction(conn)
        try:
            for pid in player_ids:
                result = create_message(
                    pid,
                    subject,
                    body,
                    category="system",
                    sender_name=SYSTEM_BROADCAST_SENDER,
                    metadata=metadata,
                    conn=conn,
                )
                if result.get("ok"):
                    delivered += 1
            conn.execute(
                """
                UPDATE gd_cycles
                SET results_sent = 1, updated_at = ?
                WHERE year = ? AND month = ?;
                """,
                (ts, int(year), int(month)),
            )
            commit(conn)
        except Exception:
            from ..db import rollback

            rollback(conn)
            raise

        return {
            "ok": True,
            "sent": True,
            "delivered": delivered,
            "galaxies": len(galaxies),
            "year": int(year),
            "month": int(month),
        }
    finally:
        if own_conn:
            conn.close()
