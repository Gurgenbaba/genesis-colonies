"""One-shot documentation consistency patch for GC-MINE-ASC-NEXUS-001."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    src = path.read_text(encoding="utf-8")
    if new in src:
        print(f"{label}: already applied")
        return
    count = src.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one marker, got {count}")
    path.write_text(src.replace(old, new, 1), encoding="utf-8")


def main() -> int:
    buildings = ROOT / "docs" / "BUILDINGS_SYSTEM.md"
    effects = ROOT / "docs" / "EFFECTS.md"

    replace_once(
        buildings,
        '''| `metal_mine`, `crystal_mine`, `fuel_cell_plant` | Resolver soft-uncapped; **Build-Enqueue nur bis zum nächsten Ascension-Milestone `required_level(rank+1)`** |\n| `solar_plant` | `50 + planet_core_nexus + 2×geothermal_nexus` |\n| `metal_storage`, `crystal_storage`, `fuel_storage` | `50 + 2×geothermal_nexus` (ohne Core) |\n| alle übrigen | `50` |\n\nNexus hebt **kein** permanentes Mine-Hardcap mehr. Minen bleiben resolver-seitig uncapped, aber neue Queue-Jobs werden am nächsten Ascension-Milestone gestoppt, bis der Rank gekauft wurde. Legacy-Overlevel bleibt erhalten; Solar-/Storage-Caps bleiben. Mine Ascension: [MINE_EVOLUTION.md](MINE_EVOLUTION.md).''',
        '''| `metal_mine`, `crystal_mine`, `fuel_cell_plant` (Rank 0) | `50 + planet_core_nexus + 2×geothermal_nexus` — maximal **200** bei Nexus 50/50 |\n| dieselbe Mine nach Ascension I/II/III… | per-mine Gate `225 / 250 / 275 / …` (`required_level(rank+1)`) |\n| `solar_plant` | `50 + planet_core_nexus + 2×geothermal_nexus` (keine Mine-Ascension) |\n| `metal_storage`, `crystal_storage`, `fuel_storage` | `50 + 2×geothermal_nexus` (ohne Core) |\n| alle übrigen | `50` |\n\nDie Nexus-Gebäude sind die normale Produktions-Cap-Progression bis Level 200. Ab dort erweitert **nur die Ascension der jeweiligen Mine** deren Baugrenze. Der Rank ist `(planet_id, building_type)`-scoped: Ferronit, Crytite und Brennzellen schalten einander keine Stufen frei. Legacy-Overlevel bleibt erhalten. Mine Ascension: [MINE_EVOLUTION.md](MINE_EVOLUTION.md).''',
        "buildings cap contract",
    )

    replace_once(
        effects,
        '''| Building caps (core nexus, geothermal) | **Fixed** | EPIC-29: production mines uncapped ([MINE_EVOLUTION.md](MINE_EVOLUTION.md)); nexus still raises solar/storage caps; terraform = storage bonus only |''',
        '''| Building caps (core nexus, geothermal) | **Fixed** | Production mines + solar use Nexus cap `50 + core + 2×geo` through L200; Mine Ascension then extends **only the selected mine** by 25-level bands ([MINE_EVOLUTION.md](MINE_EVOLUTION.md)); storage keeps geo-only cap; terraform = storage bonus only |''',
        "effects cap contract",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
