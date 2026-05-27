#!/usr/bin/env python3
"""Smoke test planet evolution page and APIs."""
from __future__ import annotations

import json
import sys

from app import app
from game.models import db


def main() -> int:
    with app.test_client() as client:
        conn = db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users ORDER BY id LIMIT 1")
        row = cur.fetchone()
        conn.close()
        if not row:
            print("NO_USER")
            return 1
        uid = int(row["id"])
        with client.session_transaction() as sess:
            sess["user_id"] = uid

        r = client.get("/planet-evolution")
        print("GET /planet-evolution", r.status_code, len(r.data))
        if r.status_code != 200:
            print(r.data[:2000].decode("utf-8", errors="replace"))
            return 1

        html = r.get_data(as_text=True)
        checks = [
            "pe-planet-header",
            "pe-section-action",
            "pe-section-traits",
            "pe-section-specialization",
            "pe-section-research",
        ]
        for c in checks:
            ok = c in html
            print(f"  contains {c}:", ok)
            if not ok:
                return 1

        from game.planet_evolution.repository import get_active_planet_id

        conn = db()
        pid = get_active_planet_id(uid, conn=conn)
        conn.close()
        print("active planet", pid)

        r2 = client.get(f"/api/planets/{pid}/state")
        print("GET state", r2.status_code, r2.get_json().get("ok"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
