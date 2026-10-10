"""World Boss live poll: every helper used by wbLivePollTick must be in its scope.

wbLivePollTick lives in initWorldBossPage() but called wbLivePollUrl(), which was only
defined inside bindWorldBossAttackCooldownUnlock(): ReferenceError on the first tick, so
the poll never rescheduled itself and live boss HP never updated.
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "static" / "main.js").read_text(encoding="utf-8")


def _page_module() -> str:
    start = SRC.index("GC.modules.world_boss = function initWorldBossPage()")
    nxt = SRC.find("\n  GC.modules.", start + 10)
    return SRC[start : nxt if nxt != -1 else len(SRC)]


def test_poll_url_helper_is_defined_in_the_page_module_before_use():
    module = _page_module()
    define = re.search(r"const wbLivePollUrl\s*=", module)
    use_tick = module.index("const wbLivePollTick")
    assert define, "wbLivePollUrl must be defined in initWorldBossPage() scope"
    assert define.start() < use_tick


def test_poll_url_builder_is_shared_not_duplicated():
    assert SRC.count("function buildWorldBossLivePollUrl(root)") == 1
    assert SRC.count("buildWorldBossLivePollUrl(root)") >= 3  # definition + two scopes
