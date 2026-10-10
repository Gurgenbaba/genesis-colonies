"""options.js must not call helpers that no longer exist.

8642218a replaced the sound mode buttons with sliders and removed
setNotifySoundToggleUi/readNotifySoundMode, but initOptionsPage() still called them:
ReferenceError on /options, so everything bound after that line (resend verification,
mail updates, Discord unlink, safety countdowns, vacation repair) never ran.
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = (Path(__file__).resolve().parents[1] / "static" / "js" / "options.js").read_text(encoding="utf-8")
CALL = re.compile(r"(?<![\w.$])((?:set|read|bind|sync|publish|apply|render|update|init)[A-Z]\w*)\s*\(")
DEF = re.compile(r"(?:function\s+|(?:const|let|var)\s+)([A-Za-z_$][\w$]*)")


def test_no_calls_to_undefined_local_helpers():
    defined = set(DEF.findall(SRC))
    called = set(CALL.findall(SRC))
    missing = sorted(name for name in called if name not in defined)
    assert not missing, f"options.js calls helpers that are not defined: {missing}"


def test_removed_sound_mode_helpers_are_gone():
    assert "setNotifySoundToggleUi" not in SRC
    assert "readNotifySoundMode" not in SRC
