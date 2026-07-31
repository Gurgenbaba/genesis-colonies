"""GC-CI — Social Identity: name styles visible on multiplayer surfaces."""

from pathlib import Path


def _read(rel: str) -> str:
    return Path(rel).read_text(encoding="utf-8")


def test_ranking_js_renders_gc_player_name_with_style():
    src = _read("static/main.js")
    fn = src.split("function rankingCommanderNameHtml(row)")[1].split("function rankingPlayerCell")[0]
    assert "GC.playerNameHtml" in fn
    assert "nameStyle" in fn or "name_style" in fn
    assert "gc-ranking-player-name" in fn


def test_hof_records_world_boss_use_player_name_link():
    hof = _read("templates/hall_of_fame.html")
    assert "player_name_link(battle.attacker_player_id" in hof
    assert "player_name_link(battle.defender_player_id" in hof
    # Hero strip must stay plain text (no HTML injection into T()).
    hero = hof.split("hof_hero_line")[1].split("{% endif %}")[0]
    assert "player_name_link" not in hero

    records = _read("templates/records.html")
    assert "player_name_link(record.player_id, record.player_name" in records

    wb = _read("templates/world_boss.html")
    assert "player_name_link(row.player_id, row.player_name)" in wb


def test_galaxy_orbit_label_no_nested_card_button():
    ring = _read("templates/partials/galaxy_ring_view.html")
    assert "enable_card=False" in ring
    assert "galaxy-ring-slot-owner-label" in ring
    assert "name_style=slot.name_style" in ring


def test_auction_alliance_fleet_use_player_name_html():
    main = _read("static/main.js")
    assert "auction-house-recent-name" in main
    auction_chunk = main.split("auction-house-recent-name")[0][-400:] + main.split("auction-house-recent-name")[1][:500]
    assert "GC.playerNameHtml" in auction_chunk

    assert "alliance-hub-donation-row" in main
    donation = main.split("alliance-hub-donation-row")[1][:800]
    assert "GC.playerNameHtml" in donation or "playerNameHtml" in main.split("data-alliance-donation-list")[1][:2500]

    assert "previewTargetOwner.innerHTML = GC.playerNameHtml" in main


def test_messages_combat_side_uses_styled_names():
    src = _read("static/js/messages.js")
    assert "combatActorNameHtml" in src or "GC.playerNameHtml" in src


def test_admin_balance_does_not_restore_leftmenu():
    admin = _read("static/admin.js")
    balance = admin.split("async function afterBalanceMutation")[1].split("async function loadAdminBalance")[0]
    assert "GC.restoreLeftmenuState" not in balance
    assert "restoreLeftmenuState(" not in balance
    assert "releaseShellNavigationBlockers" in balance


def test_wardrobe_social_preview_and_chips():
    edit = _read("templates/partials/player_card_edit.html")
    assert 'id="pc-social-preview"' in edit
    assert 'data-pc-chip="name_style"' in edit
    assert "playercard_social_preview" in edit

    css = _read("static/style.css")
    chip = css.split(".gc-pc-cosmetic-chip {")[1].split("}")[0]
    assert "999px" not in chip
    assert "--gc-radius-sm" in chip or "2px" in chip or "var(--gc-radius" in chip

    main = _read("static/main.js")
    assert "GC.openPlayerCardEdit" in main
    assert "shop_cosmetic_equip_hint" in main or "shop_cosmetic_equip" in main


def test_playercard_save_sync_includes_name_style():
    src = _read("app.py")
    block = src.split("def api_player_card_save")[1].split("def api_player_card_avatar_upload")[0]
    assert '"name_style"' in block or "'name_style'" in block
    main = _read("static/main.js")
    assert "GC.syncPlayerNameStyleVisuals" in main
    assert "hasNameStylePatch" in main or "name_style" in main.split("GC.syncPlayerAvatarVisuals")[1][:2500]
