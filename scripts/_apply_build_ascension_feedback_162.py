#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "static" / "main.js"


def main() -> int:
    src = MAIN.read_text(encoding="utf-8")
    old = '''  function mapActionError(reason, payload) {\n    if (reason === "not_enough_resources" && payload) {\n'''
    new = '''  function mapActionError(reason, payload) {\n    if (reason === "ascension_required") {\n      const progress = t("buildings_mine_evo_progress", "Nächste Ascension");\n      const action = t("buildings_mine_evo_action", "Ascension einleiten");\n      return `${progress}: ${action}`;\n    }\n    if (reason === "not_enough_resources" && payload) {\n'''
    count = src.count(old)
    if count != 1:
        raise SystemExit(f"mapActionError anchor: expected 1, found {count}")
    MAIN.write_text(src.replace(old, new, 1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
