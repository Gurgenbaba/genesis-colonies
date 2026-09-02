#!/usr/bin/env python3
from pathlib import Path

path = Path("static/main.js")
src = path.read_text(encoding="utf-8")
needle = '''  function mapActionError(reason, payload) {
    if (reason === "not_enough_resources" && payload) {
'''
replacement = '''  function mapActionError(reason, payload) {
    if (reason === "ascension_required") {
      const progress = t("buildings_mine_evo_progress", "Nächste Ascension");
      const action = t("buildings_mine_evo_action", "Ascension einleiten");
      return `${progress}: ${action}`;
    }
    if (reason === "not_enough_resources" && payload) {
'''
if needle not in src:
    raise SystemExit("mapActionError insertion point not found")
path.write_text(src.replace(needle, replacement, 1), encoding="utf-8")
