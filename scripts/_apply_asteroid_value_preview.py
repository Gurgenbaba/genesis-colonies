from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"anchor missing in {path}: {old[:120]!r}")
    if text.count(old) != 1:
        raise SystemExit(f"anchor not unique in {path}: {old[:120]!r} count={text.count(old)}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_asteroids() -> None:
    path = ROOT / "game" / "asteroids.py"

    replace_once(
        path,
        "import random\nimport time\n",
        "import random\nimport time\nfrom statistics import median\n",
    )

    replace_once(
        path,
        "ASTEROID_RESOURCE_RANGE = (500_000, 5_000_000)\n\nASTEROID_CATALOG",
        """ASTEROID_RESOURCE_RANGE = (500_000, 5_000_000)\n\n# GC-AST-VALUE-01: Standard belts keep the catalog roll shape, but newly\n# spawned fields scale with the live universe's mine progression.  The\n# canonical production curve remains owned by game.production_formula; this\n# module only derives a dimensionless reward multiplier from it.\nSTANDARD_BELT_TOP_N_MINES = 10\nSTANDARD_BELT_MIN_REFERENCE_LEVEL = 30\nSTANDARD_BELT_BASE_MULTIPLIER = 5.0\nSTANDARD_BELT_PROGRESS_EXPONENT = 0.45\nSTANDARD_BELT_MINE_BUILDING_BY_RESOURCE = {\n    \"metal\": \"metal_mine\",\n    \"crystal\": \"crystal_mine\",\n    \"fuel_cells\": \"fuel_cell_plant\",\n}\n\nASTEROID_CATALOG""",
    )

    replace_once(
        path,
        "def _roll_loot(asteroid_key: str, *, rng: Optional[random.Random] = None) -> Dict[str, int]:\n",
        """def _roll_loot(\n    asteroid_key: str,\n    *,\n    rng: Optional[random.Random] = None,\n    conn=None,\n) -> Dict[str, int]:\n""",
    )

    replace_once(
        path,
        """    split = dict(catalog.get(\"split\") or {})\n    equal = 1.0 / 3.0\n    out: Dict[str, int] = {}\n""",
        """    split = dict(catalog.get(\"split\") or {})\n    equal = 1.0 / 3.0\n    scale_map = _standard_belt_scale_map(conn) if conn is not None else {}\n    out: Dict[str, int] = {}\n""",
    )

    replace_once(
        path,
        """        out[key] = int(lo_i + round(span * t))\n        out[key] = max(lo_i, min(hi_i, out[key]))\n    return out\n\n\ndef _pick_weighted_key""",
        """        out[key] = int(lo_i + round(span * t))\n        out[key] = max(lo_i, min(hi_i, out[key]))\n        if scale_map:\n            out[key] = max(\n                lo_i,\n                int(round(out[key] * float(scale_map.get(key, 1.0) or 1.0))),\n            )\n    return out\n\n\ndef _pick_weighted_key""",
    )

    anchor = """def _top_n_building_levels(conn, building_type: str, *, valid: Iterable[str], n: int) -> List[int]:\n    if building_type not in valid:\n        return []\n    rows = conn.execute(\n        f\"SELECT {building_type} AS lvl FROM planet_buildings \"\n        f\"ORDER BY {building_type} DESC LIMIT ?;\",\n        (max(1, int(n)),),\n    ).fetchall()\n    return [int(r[\"lvl\"] or 0) for r in rows]\n\n\n"""
    helper = anchor + """def _standard_belt_reference_level(conn, resource: str) -> int:\n    \"\"\"Robust universe progression anchor for one standard-belt resource.\n\n    Top-N keeps the belt relevant to active progression, while the median\n    prevents one extreme account from inflating every public asteroid.  L30\n    is the minimum anchor so fresh universes still receive the intended\n    mid-game relevance floor.\n    \"\"\"\n    minimum = int(STANDARD_BELT_MIN_REFERENCE_LEVEL)\n    if conn is None or not table_exists(conn, \"planet_buildings\"):\n        return minimum\n    building_type = STANDARD_BELT_MINE_BUILDING_BY_RESOURCE.get(str(resource))\n    if not building_type:\n        return minimum\n    levels = _top_n_building_levels(\n        conn,\n        building_type,\n        valid=STANDARD_BELT_MINE_BUILDING_BY_RESOURCE.values(),\n        n=STANDARD_BELT_TOP_N_MINES,\n    )\n    positive = [max(0, int(level)) for level in levels if int(level or 0) > 0]\n    if not positive:\n        return minimum\n    return max(minimum, int(round(float(median(positive)))))\n\n\ndef _standard_belt_scale_map(conn) -> Dict[str, float]:\n    \"\"\"Adaptive standard-belt multiplier derived from canonical mine output.\n\n    At the L30 floor a standard field is already 5x the legacy roll.  Beyond\n    that, progression follows the canonical mine curve sub-linearly so normal\n    belts stay valuable without overtaking storage-scaled Mega Belts.\n    \"\"\"\n    from .production_formula import level_growth\n\n    out: Dict[str, float] = {}\n    floor_level = int(STANDARD_BELT_MIN_REFERENCE_LEVEL)\n    for resource in STANDARD_BELT_MINE_BUILDING_BY_RESOURCE:\n        reference_level = _standard_belt_reference_level(conn, resource)\n        floor_output = max(1.0, float(level_growth(resource, floor_level, 1.0)))\n        reference_output = max(\n            floor_output,\n            float(level_growth(resource, reference_level, 1.0)),\n        )\n        progression = max(1.0, reference_output / floor_output)\n        out[resource] = max(\n            1.0,\n            float(STANDARD_BELT_BASE_MULTIPLIER)\n            * (progression ** float(STANDARD_BELT_PROGRESS_EXPONENT)),\n        )\n    return out\n\n\n"""
    replace_once(path, anchor, helper)

    replace_once(
        path,
        "loot = _roll_loot(key, rng=rng)\n",
        "loot = _roll_loot(key, rng=rng, conn=conn)\n",
    )


def patch_galaxy_quick_action() -> None:
    path = ROOT / "static" / "js" / "galaxy-quick-action.js"

    replace_once(
        path,
        """    _unwatchRecycleArrivals: null,\n    _asteroidHelpHome: null,\n""",
        """    _unwatchRecycleArrivals: null,\n    _asteroidHelpHome: null,\n    _asteroidPreviewCache: new Map(),\n    _asteroidPreviewInflight: new Map(),\n""",
    )

    anchor = """    async resolveAvailableReclaimersAsync(root) {\n      const cached = this.getAvailableReclaimers(root);\n      if (cached > 0) return cached;\n      const { fetchGameAction } = deps();\n      if (!fetchGameAction) return null;\n      try {\n        const res = await fetchGameAction(\"/api/shipyard\", {\n          method: \"GET\",\n          headers: { Accept: \"application/json\", \"X-Requested-With\": \"XMLHttpRequest\" },\n        });\n        const payload = res?.data || res?.payload || res || {};\n        const ships = payload.current_ships || payload.ships || {};\n        if (ships && typeof ships === \"object\" && !Array.isArray(ships)) {\n          return Math.max(0, parseInt(ships.harvest_reclaimer || ships.recycler || \"0\", 10) || 0);\n        }\n        if (Array.isArray(ships)) {\n          const row = ships.find(\n            (s) => String(s?.ship_key || s?.key || \"\") === \"harvest_reclaimer\"\n          );\n          return Math.max(0, parseInt(row?.count || row?.amount || \"0\", 10) || 0);\n        }\n      } catch (_) {\n        return null;\n      }\n      return null;\n    },\n\n"""

    methods = anchor + """    formatAsteroidFlightDuration(seconds) {\n      const total = Math.max(0, parseInt(seconds || \"0\", 10) || 0);\n      if (total < 60) return `${total}s`;\n      const hours = Math.floor(total / 3600);\n      const minutes = Math.floor((total % 3600) / 60);\n      const secs = total % 60;\n      if (hours > 0) return `${hours}:${String(minutes).padStart(2, \"0\")}:${String(secs).padStart(2, \"0\")}`;\n      return `${minutes}:${String(secs).padStart(2, \"0\")}`;\n    },\n\n    asteroidPreviewKey(originPlanetId, g, s, p, sendCount) {\n      return `${originPlanetId}:${g}:${s}:${p}:${sendCount}`;\n    },\n\n    asteroidPreviewFromResponse(res) {\n      const payload = this.fleetPayload(res);\n      const candidates = [\n        payload?.preview,\n        payload?.data?.preview,\n        res?.preview,\n        res?.data?.preview,\n        res?.payload?.preview,\n      ];\n      return candidates.find((value) => value && typeof value === \"object\") || null;\n    },\n\n    renderAsteroidFlightPreview(wrap, preview, sendCount) {\n      if (!wrap || !preview) return;\n      const { formatNumber } = deps();\n      const fuelCost = Math.max(0, parseInt(preview.fuel_cost || \"0\", 10) || 0);\n      const fuelAvailable = Math.max(0, parseInt(preview.fuel_available || \"0\", 10) || 0);\n      const flightSeconds = Math.max(0, parseInt(preview.flight_seconds || \"0\", 10) || 0);\n      const count = Math.max(0, parseInt(sendCount || \"0\", 10) || 0);\n      const short = `⛽ ${formatNumber(fuelCost)} BZ · 🚀 ${formatNumber(count)} HR · ⏱ ${this.formatAsteroidFlightDuration(flightSeconds)}`;\n      const missing = Math.max(0, fuelCost - fuelAvailable);\n      const full = missing > 0\n        ? `${short} · ⚠ ${formatNumber(missing)} BZ`\n        : short;\n\n      const trigger = wrap.querySelector(\"[data-galaxy-ring-asteroid-recycle]\");\n      if (trigger) {\n        trigger.title = full;\n        trigger.setAttribute(\"aria-description\", full);\n      }\n\n      // Ring markers are intentionally tiny: keep their preview in the native\n      // tooltip. Board rows and the slot inspector get a compact visible line.\n      if (wrap.classList.contains(\"galaxy-ring-asteroid-wrap\")) return;\n      let line = wrap.querySelector(\"[data-galaxy-asteroid-flight-preview]\");\n      if (!line) {\n        line = document.createElement(\"span\");\n        line.className = \"galaxy-asteroid-flight-preview hint gc-mono\";\n        line.setAttribute(\"data-galaxy-asteroid-flight-preview\", \"\");\n        if (trigger) wrap.insertBefore(line, trigger);\n        else wrap.appendChild(line);\n      }\n      line.textContent = full;\n      line.classList.toggle(\"is-blocked\", missing > 0);\n    },\n\n    async loadAsteroidFlightPreview(wrap, root, { sendCount = null, force = false } = {}) {\n      if (!wrap) return null;\n      const { fetchGameAction } = deps();\n      if (!fetchGameAction) return null;\n\n      const g = parseInt(wrap.dataset.targetGalaxy || \"0\", 10);\n      const s = parseInt(wrap.dataset.targetSystem || \"0\", 10);\n      const p = parseInt(wrap.dataset.targetPosition || \"0\", 10);\n      const needed = Math.max(0, parseInt(wrap.dataset.recyclerSlots || \"0\", 10) || 0);\n      const originPlanetId = this.getOriginPlanetId(root);\n      if (!originPlanetId || !g || !s || !p || needed < 1) return null;\n\n      let count = sendCount === null ? null : Math.max(0, parseInt(sendCount || \"0\", 10) || 0);\n      if (count === null) {\n        const available = await this.resolveAvailableReclaimersAsync(root);\n        if (available === null) return null;\n        count = Math.min(available, needed);\n      }\n      if (count < 1) return null;\n\n      const key = this.asteroidPreviewKey(originPlanetId, g, s, p, count);\n      const now = Date.now();\n      const cached = this._asteroidPreviewCache.get(key);\n      if (!force && cached && now - cached.at < 15000) {\n        this.renderAsteroidFlightPreview(wrap, cached.preview, count);\n        return cached.preview;\n      }\n      if (!force && this._asteroidPreviewInflight.has(key)) {\n        const preview = await this._asteroidPreviewInflight.get(key);\n        if (preview) this.renderAsteroidFlightPreview(wrap, preview, count);\n        return preview;\n      }\n\n      const domPlanetId = deps().getDomPlanetId() || originPlanetId;\n      const request = (async () => {\n        try {\n          const res = await fetchGameAction(\"/api/fleet/preview\", {\n            method: \"POST\",\n            headers: {\n              \"Content-Type\": \"application/json\",\n              Accept: \"application/json\",\n              \"X-Requested-With\": \"XMLHttpRequest\",\n              ...(domPlanetId ? { \"X-GC-Dom-Planet-Id\": String(domPlanetId) } : {}),\n            },\n            body: JSON.stringify({\n              origin_planet_id: originPlanetId,\n              mission_type: \"recycle\",\n              target_galaxy: g,\n              target_system: s,\n              target_position: p,\n              ships: { harvest_reclaimer: count },\n              resources: {},\n              speed_percent: 100,\n            }),\n          });\n          const preview = this.asteroidPreviewFromResponse(res);\n          if (preview) {\n            this._asteroidPreviewCache.set(key, { at: Date.now(), preview });\n          }\n          return preview;\n        } catch (_) {\n          return null;\n        } finally {\n          this._asteroidPreviewInflight.delete(key);\n        }\n      })();\n      this._asteroidPreviewInflight.set(key, request);\n      const preview = await request;\n      if (preview) this.renderAsteroidFlightPreview(wrap, preview, count);\n      return preview;\n    },\n\n    handleAsteroidPreviewIntent(ev, root) {\n      const wrap = ev.target?.closest?.(\"[data-galaxy-ring-asteroid-wrap]\");\n      if (!wrap || !root.contains(wrap) || wrap.dataset.harvestLocked === \"1\") return;\n      void this.loadAsteroidFlightPreview(wrap, root);\n    },\n\n    resetAsteroidPreviewCache() {\n      this._asteroidPreviewCache.clear();\n      this._asteroidPreviewInflight.clear();\n    },\n\n"""
    replace_once(path, anchor, methods)

    replace_once(
        path,
        """      const sendCount = Math.min(available, needed);\n\n      if (!originPlanetId) {\n""",
        """      const sendCount = Math.min(available, needed);\n\n      if (!originPlanetId) {\n""",
    )

    # There are two sendCount blocks (debris + asteroid). Patch the asteroid one via its unique trailing guard.
    old = """      if (sendCount < 1) {\n        showNotify(\n          t(\n            \"galaxy_asteroid_harvest_no_ships\",\n            \"No Harvest Reclaimers free — wait for return or build more.\"\n          ),\n          \"error\"\n        );\n        return;\n      }\n\n      await this.runGuarded(btn, async () => {\n"""
    new = """      if (sendCount < 1) {\n        showNotify(\n          t(\n            \"galaxy_asteroid_harvest_no_ships\",\n            \"No Harvest Reclaimers free — wait for return or build more.\"\n          ),\n          \"error\"\n        );\n        return;\n      }\n\n      const preview = await this.loadAsteroidFlightPreview(wrap, root, { sendCount });\n      if (preview) {\n        const fuelCost = Math.max(0, parseInt(preview.fuel_cost || \"0\", 10) || 0);\n        const fuelAvailable = Math.max(0, parseInt(preview.fuel_available || \"0\", 10) || 0);\n        if (fuelCost > fuelAvailable) {\n          this.notifyFleetError(\"not_enough_fuel\", { preview }, null);\n          return;\n        }\n      }\n\n      await this.runGuarded(btn, async () => {\n"""
    replace_once(path, old, new)

    replace_once(
        path,
        """      const onDebris = (ev) => this.handleDebrisRecycleClick(ev, root);\n      const onAsteroid = (ev) => this.handleAsteroidRecycleClick(ev, root);\n      const onAsteroidHelp = (ev) => this.handleAsteroidHelpClick(ev);\n""",
        """      const onDebris = (ev) => this.handleDebrisRecycleClick(ev, root);\n      const onAsteroid = (ev) => this.handleAsteroidRecycleClick(ev, root);\n      const onAsteroidPreview = (ev) => this.handleAsteroidPreviewIntent(ev, root);\n      const onAsteroidHelp = (ev) => this.handleAsteroidHelpClick(ev);\n""",
    )

    replace_once(
        path,
        """      root.addEventListener(\"click\", onDebris);\n      root.addEventListener(\"click\", onAsteroid);\n      root.addEventListener(\"click\", onAsteroidHelp);\n""",
        """      root.addEventListener(\"click\", onDebris);\n      root.addEventListener(\"click\", onAsteroid);\n      root.addEventListener(\"pointerover\", onAsteroidPreview);\n      root.addEventListener(\"focusin\", onAsteroidPreview);\n      root.addEventListener(\"click\", onAsteroidHelp);\n""",
    )

    replace_once(
        path,
        """        root.removeEventListener(\"click\", onDebris);\n        root.removeEventListener(\"click\", onAsteroid);\n        root.removeEventListener(\"click\", onAsteroidHelp);\n""",
        """        root.removeEventListener(\"click\", onDebris);\n        root.removeEventListener(\"click\", onAsteroid);\n        root.removeEventListener(\"pointerover\", onAsteroidPreview);\n        root.removeEventListener(\"focusin\", onAsteroidPreview);\n        root.removeEventListener(\"click\", onAsteroidHelp);\n""",
    )

    replace_once(
        path,
        """        this.closeAsteroidHelp();\n        this.resetAttackPresetCache();\n""",
        """        this.closeAsteroidHelp();\n        this.resetAttackPresetCache();\n        this.resetAsteroidPreviewCache();\n""",
    )


def patch_docs() -> None:
    path = ROOT / "docs" / "ASTEROID_SYSTEM.md"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "- Harvest button disabled while own outbound fleet is flying.\n",
        "- Harvest button disabled while own outbound fleet is flying.\n- Hover/focus on an available Harvest action loads the canonical fleet preview (fuel, HR count, flight time); click reuses that preview and blocks locally-visible fuel shortages before send.\n",
    )
    text = text.replace(
        "| `ferronite_rock` | 70/25/5 M/C/F | 0.5M–5M each |\n| `crytite_shard` | 25/70/5 | 0.5M–5M each |\n| `fuel_ice` | 15/15/70 | 0.5M–5M each |\n| `mixed_belt` | 40/40/20 | 0.5M–5M each |",
        "| `ferronite_rock` | 70/25/5 M/C/F | base roll 0.5M–5M × adaptive multiplier |\n| `crytite_shard` | 25/70/5 | base roll 0.5M–5M × adaptive multiplier |\n| `fuel_ice` | 15/15/70 | base roll 0.5M–5M × adaptive multiplier |\n| `mixed_belt` | 40/40/20 | base roll 0.5M–5M × adaptive multiplier |",
    )
    old = "Each resource rolls independently inside the band; catalog split only biases toward the high end for preferred resources. Total field ≈ 1.5M–15M (contested prize vs large expos, not empire-breaker).\n\nCargo take"
    new = """Each resource still rolls independently inside the 0.5M–5M base band; catalog split only biases toward the high end for preferred resources. **New standard fields are then multiplied server-side** by an adaptive progression factor.\n\n### Adaptive Standard Belts (GC-AST-VALUE-01)\n\nStandard belts use the median level of the universe's top 10 relevant mines (`metal_mine`, `crystal_mine`, `fuel_cell_plant`) with a minimum reference of **L30**. At the L30 floor the legacy roll is multiplied by **5×**. Above L30 the multiplier grows sub-linearly with the canonical `game.production_formula.level_growth()` curve (`progression^0.45`). There is no fixed late-game hard cap; a single extreme account cannot dominate the reference because the median is used.\n\nThis scaling applies **only when a new standard asteroid is spawned**. Existing active fields keep their stored pool until claimed/expired. Mega Belts remain separately storage-scaled and are intentionally the jackpot tier.\n\nCargo take"""
    if old not in text:
        raise SystemExit("ASTEROID_SYSTEM adaptive paragraph anchor missing")
    text = text.replace(old, new, 1)
    path.write_text(text, encoding="utf-8")


def write_tests() -> None:
    path = ROOT / "tests" / "test_asteroid_value_preview.py"
    path.write_text(
        '''from __future__ import annotations\n\nimport random\nimport sqlite3\nfrom pathlib import Path\n\nfrom game.asteroids import (\n    STANDARD_BELT_BASE_MULTIPLIER,\n    _roll_loot,\n    _standard_belt_scale_map,\n)\n\n\ndef _mine_conn(level: int) -> sqlite3.Connection:\n    conn = sqlite3.connect(\":memory:\")\n    conn.row_factory = sqlite3.Row\n    conn.execute(\n        \"CREATE TABLE planet_buildings (metal_mine INTEGER, crystal_mine INTEGER, fuel_cell_plant INTEGER);\"\n    )\n    for _ in range(10):\n        conn.execute(\n            \"INSERT INTO planet_buildings (metal_mine, crystal_mine, fuel_cell_plant) VALUES (?, ?, ?);\",\n            (level, level, level),\n        )\n    return conn\n\n\ndef test_standard_belt_level30_floor_is_materially_higher_than_legacy_roll():\n    conn = _mine_conn(30)\n    try:\n        legacy = _roll_loot(\"mixed_belt\", rng=random.Random(77))\n        scaled = _roll_loot(\"mixed_belt\", rng=random.Random(77), conn=conn)\n        assert STANDARD_BELT_BASE_MULTIPLIER == 5.0\n        for resource in (\"metal\", \"crystal\", \"fuel_cells\"):\n            assert scaled[resource] >= int(legacy[resource] * 4.99)\n    finally:\n        conn.close()\n\n\ndef test_standard_belt_keeps_scaling_beyond_level30_without_hard_cap():\n    low = _mine_conn(30)\n    high = _mine_conn(80)\n    try:\n        low_scale = _standard_belt_scale_map(low)\n        high_scale = _standard_belt_scale_map(high)\n        for resource in (\"metal\", \"crystal\", \"fuel_cells\"):\n            assert low_scale[resource] >= 5.0\n            assert high_scale[resource] > low_scale[resource]\n    finally:\n        low.close()\n        high.close()\n\n\ndef test_galaxy_asteroid_preview_uses_server_fleet_preview_and_no_client_fuel_math():\n    root = Path(__file__).resolve().parents[1]\n    js = (root / \"static/js/galaxy-quick-action.js\").read_text(encoding=\"utf-8\")\n    assert 'fetchGameAction(\"/api/fleet/preview\"' in js\n    assert \"loadAsteroidFlightPreview\" in js\n    assert \"data-galaxy-asteroid-flight-preview\" in js\n    assert \"preview.fuel_cost\" in js\n    assert \"preview.fuel_available\" in js\n    assert 'mission_type: \"recycle\"' in js\n    assert \"calculate_fuel_cost\" not in js\n''',
        encoding="utf-8",
    )


def main() -> None:
    patch_asteroids()
    patch_galaxy_quick_action()
    patch_docs()
    write_tests()
    print("asteroid value + preview patch applied")


if __name__ == "__main__":
    main()
