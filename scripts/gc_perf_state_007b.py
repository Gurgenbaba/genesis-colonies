from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "game/inventory_boosters.py",
        '''def build_active_effects_for_hud(\n    user_id: int,\n    *,\n    conn,\n    locale: Optional[str] = None,\n    now: Optional[float] = None,\n) -> List[Dict[str, Any]]:\n''',
        '''def build_active_effects_for_hud(\n    user_id: int,\n    *,\n    conn,\n    locale: Optional[str] = None,\n    now: Optional[float] = None,\n    include_server_events: bool = True,\n) -> List[Dict[str, Any]]:\n''',
        "booster HUD signature",
    )
    replace_once(
        "game/inventory_boosters.py",
        '''    _merge_server_event_production_into_hud(out, now=ts, locale=locale, conn=conn)\n    return enrich_active_effects_with_resource_impacts(\n''',
        '''    if include_server_events:\n        _merge_server_event_production_into_hud(out, now=ts, locale=locale, conn=conn)\n    return enrich_active_effects_with_resource_impacts(\n''',
        "conditional server-event HUD merge",
    )
    replace_once(
        "game/overview_page.py",
        '''    effects = build_active_effects_for_hud(\n        int(user_id),\n        conn=conn,\n        locale=locale,\n        now=now,\n    )\n''',
        '''    effects = build_active_effects_for_hud(\n        int(user_id),\n        conn=conn,\n        locale=locale,\n        now=now,\n        include_server_events=False,\n    )\n''',
        "overview booster liveops call",
    )


if __name__ == "__main__":
    main()
