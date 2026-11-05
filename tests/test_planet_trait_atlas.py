"""Trait Atlas regression: deterministic read model and no hidden-DNA leakage."""

import json

from game.planet_evolution import trait_atlas


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows
        self.queries = []

    def execute(self, sql, args):
        self.queries.append((sql, args))
        return _FakeCursor(self._rows)


def _planet_row(pid, name, reveal, *, geology=(), anomaly=(), hidden=()):
    return {
        "id": pid,
        "name": name,
        "dna_reveal_tier": reveal,
        "geology_traits_json": json.dumps(list(geology)),
        "atmosphere_traits_json": "[]",
        "environment_traits_json": "[]",
        "anomaly_traits_json": json.dumps(list(anomaly)),
        "hidden_traits_json": json.dumps(list(hidden)),
    }


def _dna(*, geology=(), anomaly=(), hidden=()):
    return {
        "geology_traits": list(geology),
        "atmosphere_traits": [],
        "environment_traits": [],
        "anomaly_traits": list(anomaly),
        "hidden_traits": list(hidden),
    }


def _definitions(monkeypatch):
    monkeypatch.setattr(
        trait_atlas, "get_traits", lambda: {
            "ferronit_rich_crust": {"category": "geology", "rarity": "common"},
            "ancient_ruins": {"category": "anomaly", "rarity": "rare"},
            "subsurface_vault_hint": {"category": "hidden", "rarity": "rare"},
        }
    )
    monkeypatch.setattr(
        trait_atlas, "get_research_defs", lambda: {
            "ancient_t1_ruins_survey": {
                "label_key": "pe_ancient_t1",
                "requirements": {"traits_any": ["ancient_ruins"]},
            }
        }
    )
    monkeypatch.setattr(
        trait_atlas, "get_specializations", lambda: {
            "ai_controlled_world": {
                "label_key": "spec_ai_controlled",
                "required_traits_any": ["ancient_ruins"],
            }
        }
    )


def test_trait_atlas_hides_unestablished_planets_and_hidden_dna(monkeypatch):
    _definitions(monkeypatch)
    conn = _FakeConn([
        _planet_row(5, "Genesis Ark", 0, geology=("ferronit_rich_crust",), hidden=("subsurface_vault_hint",)),
        _planet_row(6, "Outpost", 0, anomaly=("ancient_ruins",)),
    ])
    result = trait_atlas.build_trait_atlas(
        planet_id=5, player_id=9,
        dna=_dna(geology=("ferronit_rich_crust",), hidden=("subsurface_vault_hint",)),
        reveal_tier=0, conn=conn,
    )
    assert result["on_current"] == 0
    assert result["known_empire"] == 0
    assert result["unknown_on_current"] is None
    assert result["next_reveal_level"] == 3
    assert all(row["owned_planets"] == [] for row in result["entries"])
    assert all(row["status"] == "unfound" for row in result["entries"])
    assert len(conn.queries) == 1
    assert conn.queries[0][1] == (9,)


def test_trait_atlas_matches_owned_worlds_and_research_paths(monkeypatch):
    _definitions(monkeypatch)
    conn = _FakeConn([
        _planet_row(5, "Genesis Ark", 1, geology=("ferronit_rich_crust",), hidden=("subsurface_vault_hint",)),
        _planet_row(6, "Ruins IX", 1, anomaly=("ancient_ruins",)),
    ])
    result = trait_atlas.build_trait_atlas(
        planet_id=5, player_id=9,
        dna=_dna(geology=("ferronit_rich_crust",), hidden=("subsurface_vault_hint",)),
        reveal_tier=1, conn=conn,
    )
    by_key = {row["key"]: row for row in result["entries"]}
    assert by_key["ferronit_rich_crust"]["status"] == "current"
    assert by_key["ancient_ruins"]["status"] == "empire"
    assert by_key["ancient_ruins"]["owned_planets"] == [
        {"planet_id": 6, "name": "Ruins IX", "is_current": False}
    ]
    assert by_key["ancient_ruins"]["techs"] == [
        {"key": "ancient_t1_ruins_survey", "label_key": "pe_ancient_t1"}
    ]
    assert by_key["ancient_ruins"]["specializations"] == [
        {"key": "ai_controlled_world", "label_key": "spec_ai_controlled"}
    ]
    assert result["next_reveal_level"] == 15
    assert result["known_empire"] == 3


def test_trait_atlas_reveal_stage_two_and_template_contract(monkeypatch):
    _definitions(monkeypatch)
    conn = _FakeConn([_planet_row(5, "Genesis Ark", 2, geology=("ferronit_rich_crust",), hidden=("subsurface_vault_hint",))])
    result = trait_atlas.build_trait_atlas(
        planet_id=5, player_id=9,
        dna=_dna(geology=("ferronit_rich_crust",), hidden=("subsurface_vault_hint",)),
        reveal_tier=2, conn=conn,
    )
    by_key = {row["key"]: row for row in result["entries"]}
    assert by_key["subsurface_vault_hint"]["status"] == "current"
    assert result["unknown_on_current"] == 0
    assert result["next_reveal_level"] is None

    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    tpl = (root / "templates" / "planet_evolution.html").read_text(encoding="utf-8")
    assert 'id="pe-section-trait-atlas"' in tpl
    assert "entry.owned_planets" in tpl
    assert "entry.techs" in tpl
    assert "entry.specializations" in tpl


def test_dna_milestone_progress_is_server_computed_and_never_previews_tier_zero(monkeypatch):
    _definitions(monkeypatch)
    rows = [_planet_row(5, "Ark", 1, geology=("ferronit_rich_crust",), hidden=("subsurface_vault_hint",))]
    base = dict(planet_id=5, player_id=9, dna=_dna(geology=("ferronit_rich_crust",)), conn=_FakeConn(rows))

    hidden = trait_atlas.build_trait_atlas(**base, reveal_tier=0, planet_level=12)
    assert hidden["reveal_progress"] is None
    assert hidden["on_current"] == 0

    early = trait_atlas.build_trait_atlas(**base, reveal_tier=1, planet_level=3)
    assert early["reveal_progress"] == {
        "current_level": 3, "target_level": 15, "levels_remaining": 12, "pct": 0,
    }
    middle = trait_atlas.build_trait_atlas(**base, reveal_tier=1, planet_level=9)
    assert middle["reveal_progress"]["pct"] == 50
    assert middle["reveal_progress"]["levels_remaining"] == 6
    stale = trait_atlas.build_trait_atlas(**base, reveal_tier=1, planet_level=19)
    assert stale["reveal_progress"]["pct"] == 100
    assert stale["reveal_progress"]["levels_remaining"] == 0
    fully_revealed = trait_atlas.build_trait_atlas(**base, reveal_tier=2, planet_level=20)
    assert fully_revealed["reveal_progress"] is None


def test_dna_progress_bar_is_read_only_and_hidden_before_establishment():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    tpl = (root / "templates" / "planet_evolution.html").read_text(encoding="utf-8")
    assert "atlas.next_reveal_level and atlas.can_see_current" in tpl
    assert 'class="pe-atlas-reveal-meter"' in tpl
    assert 'value="{{ atlas.reveal_progress.pct }}"' in tpl
    assert "atlas.reveal_progress.current_level" in tpl
