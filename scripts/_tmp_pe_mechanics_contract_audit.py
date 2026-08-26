from __future__ import annotations

import json
import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _bundle_has_effect(bundle: dict) -> bool:
    if not isinstance(bundle, dict):
        return False
    return any(
        bool(bundle.get(key))
        for key in ("unlocks", "flags", "export_slots", "queue_limits", "risk_modifiers")
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="gc_pe_mech_audit_") as tmp:
        db_path = Path(tmp) / "audit.db"
        os.environ["GC_DB_PATH"] = str(db_path)
        os.environ.setdefault("GC_SKIP_MIGRATION_CHECK", "1")
        os.environ.setdefault("GC_EMBEDDED_CRON", "0")
        os.environ.setdefault("APP_ENV", "development")
        os.environ.setdefault("FLASK_ENV", "development")
        os.environ.setdefault("SECRET_KEY", "pe-mechanics-audit-not-for-production")

        from game import db as gdb
        gdb._DB_PATH = None
        from game.models import db, init_db
        init_db()
        import migrate
        migrate.main()

        from game.planet_evolution.definitions import (
            get_ascensions,
            get_discoveries_defs,
            get_policies,
            get_research_defs,
            get_specializations,
            reload_definitions,
        )
        from game.planet_evolution.mechanics import _parse_mechanics_json

        conn = db()
        try:
            reload_definitions(conn)
            occurrences: list[tuple[str, str, str, object]] = []

            for key, row in get_research_defs().items():
                for field, value in (row.get("mechanics") or {}).items():
                    occurrences.append(("research", str(key), str(field), value))

            for key, row in get_policies().items():
                for field, value in (row.get("mechanics") or {}).items():
                    occurrences.append(("policy", str(key), str(field), value))

            for key, row in get_discoveries_defs().items():
                for field, value in (row.get("mechanics") or {}).items():
                    occurrences.append(("discovery", str(key), str(field), value))

            for key, row in get_ascensions().items():
                for field, value in (row.get("permanent_mechanics") or {}).items():
                    occurrences.append(("ascension", str(key), str(field), value))

            for spec_key, row in get_specializations().items():
                for tier_key, tier in (row.get("tier_mechanics") or {}).items():
                    if not isinstance(tier, dict):
                        continue
                    for field, value in tier.items():
                        occurrences.append((f"specialization:{tier_key}", str(spec_key), str(field), value))

            supported: dict[str, list[dict]] = defaultdict(list)
            special: dict[str, list[dict]] = defaultdict(list)
            unsupported: dict[str, list[dict]] = defaultdict(list)

            for domain, owner, field, value in occurrences:
                entry = {"domain": domain, "owner": owner, "value": value}
                if domain.startswith("specialization:") and field == "import_demands":
                    special[field].append(entry)
                    continue
                parsed = _parse_mechanics_json({field: value})
                if _bundle_has_effect(parsed):
                    supported[field].append(entry)
                else:
                    unsupported[field].append(entry)

            payload = {
                "supported_keys": sorted(supported),
                "special_consumers": {k: v for k, v in sorted(special.items())},
                "unsupported": {k: v for k, v in sorted(unsupported.items())},
                "unsupported_count": sum(len(v) for v in unsupported.values()),
                "unsupported_key_count": len(unsupported),
            }
            print("=== PE MECHANICS CONTRACT AUDIT ===")
            print(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False))
        finally:
            conn.close()
            gdb._DB_PATH = None


if __name__ == "__main__":
    main()
