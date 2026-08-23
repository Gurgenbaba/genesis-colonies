from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLEET = ROOT / "game" / "fleet.py"
TEST = ROOT / "tests" / "test_noob_protection.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, got {count}")
    return text.replace(old, new, 1)


def main() -> None:
    fleet = FLEET.read_text(encoding="utf-8")
    fleet = replace_once(
        fleet,
        "    min_def = int(math.ceil(atk_score / fac)) if atk_score > 0 else 0\n",
        "    # Integer ceil division keeps arbitrary-precision scores out of IEEE-754.\n    min_def = ((atk_score + fac - 1) // fac) if atk_score > 0 else 0\n",
        "noob protection ceil division",
    )
    compile(fleet, str(FLEET), "exec")
    FLEET.write_text(fleet, encoding="utf-8")

    test = TEST.read_text(encoding="utf-8")
    test = replace_once(
        test,
        "        (int(player_id), int(score_total), int(score_total), 0),\n",
        "        (int(player_id), str(int(score_total)), str(int(score_total)), '0'),\n",
        "noob test score TEXT binding",
    )
    if "test_noob_protection_arbitrary_precision_score_math" not in test:
        test += '''\n\ndef test_noob_protection_arbitrary_precision_score_math(noob_db):\n    atk = _player()\n    def_id, _, _ = _foreign_player()\n    conn = db()\n    _set_active(atk, conn=conn)\n    _set_active(def_id, conn=conn)\n    huge = 10**500 + 3\n    _set_score(atk, huge, conn=conn)\n    _set_score(def_id, (huge + NOOB_PROTECTION_FACTOR - 1) // NOOB_PROTECTION_FACTOR, conn=conn)\n    conn.commit()\n    info = get_noob_protection_status(atk, def_id, conn=conn)\n    assert info["attacker_score"] == huge\n    assert info["min_defender_score"] == (huge + NOOB_PROTECTION_FACTOR - 1) // NOOB_PROTECTION_FACTOR\n    assert info["max_defender_score"] == huge * NOOB_PROTECTION_FACTOR\n    assert info["allowed"] is True\n    conn.close()\n'''
    TEST.write_text(test, encoding="utf-8")

    assert "math.ceil(atk_score / fac)" not in fleet
    print("GC-SCORE-BIGNUM noob guard applied successfully")


if __name__ == "__main__":
    main()
