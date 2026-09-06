"""Fleet SSR perf contracts: shared state plus mode-specific heavy contexts."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_fleet_route_builds_only_the_requested_heavy_context():
    app = _read("app.py")
    route = app.split('def fleet_view():', 1)[1].split('\n@app.route("/alliance")', 1)[0]

    assert "GC-PERF-FLEET-SSR-005" in route
    assert 'request.args.get("mode", "send")' in route
    assert 'if fleet_mode == "send":' in route
    assert route.count("get_planets_by_player(") == 1
    assert "page_planets = [dict(p) for p in get_planets_by_player" in route
    assert route.count("planet_rows=page_planets") == 2
    assert "maintenance_prepared=True" not in route

    branches = route.split('                if fleet_mode == "send":', 1)[1]
    send_branch, logistics_branch = branches.split('                else:', 1)
    assert "build_fleet_page_context(" in send_branch
    assert "build_logistics_page_context(" not in send_branch
    assert "build_logistics_page_context(" in logistics_branch
    assert '"ready": bool(logistics_ctx.get("ready"))' in logistics_branch
    assert "build_fleet_page_context(" not in logistics_branch


def test_logistics_builder_only_skips_maintenance_when_explicitly_prepared():
    src = _read("game/fleet.py")
    block = src.split("def build_logistics_page_context(", 1)[1].split(
        "def seed_planet_ships_stack(", 1
    )[0]

    assert "maintenance_prepared: bool = False" in block
    assert "if not maintenance_prepared:" in block
    assert block.count("_finish_due_shipyard_on_planet(") == 1
    assert block.count("process_fleet_tick(") == 1
    assert "planet_rows if planet_rows is not None else get_planets_by_player" in block
    assert "if fleet_slots is not None" in block
    assert "if mission_locks is not None" in block


def test_fleet_builder_accepts_shared_planet_rows_with_historical_fallback():
    src = _read("game/fleet.py")
    block = src.split("def build_fleet_page_context(", 1)[1]

    assert "planet_rows: Sequence[Mapping[str, Any]] | None = None" in block
    assert "planet_rows if planet_rows is not None else get_planets_by_player" in block
    # Send remains the canonical maintenance owner when the Send mode is requested.
    assert "_finish_due_shipyard_on_planet(conn, int(planet_id), int(player_id))" in block
    assert "process_fleet_tick(player_id=int(player_id), conn=conn)" in block
