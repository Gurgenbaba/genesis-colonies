#!/usr/bin/env python3
"""GC-900: Translate locale files from EN (or fix German leakage in EN from DE)."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALES = ROOT / "locales"
sys.path.insert(0, str(ROOT))

from game.i18n import SUPPORTED_LANGUAGES  # noqa: E402

TARGET_LOCALES = tuple(code for code in SUPPORTED_LANGUAGES if code not in ("de", "en"))

# Terms that must stay in canon form across languages (placeholders in {{...}}).
CANON_TERMS: tuple[str, ...] = (
    "Genesis Colonies",
    "Genesis Academy",
    "Ferronite",
    "Crytite",
    "Fuel Cells",
    "Fuel Cell",
    "Aetherion",
    "Orbital Shipyard",
    "Defense Factory",
    "Command Center",
    "Research Lab",
    "Planetary Shield Generator",
    "Nanofactory",
    "Terraformer",
    "Geothermal Nexus",
    "Planet Core Nexus",
    "Extraction Path",
    "Ancient Alloy",
    "Living Crystal",
    "Dark Plasma",
    "Phase Crystal",
    "Quantum Data",
    "Mantle Alloy",
    "Crytite Gas",
    "Raw Ferronite",
    "Refined Ferronite",
    "Contraband",
    "TChat",
    "PJAX",
    "OGame",
)

GERMAN_HINTS = (
    "Produktionskette",
    "Spezialisierung",
    "Forschung",
    "Kolonie",
    "Planetare",
    "Experimentelle",
    "Schmuggler",
    "Tiefbau",
    "Verteidigung",
    "Allianz",
    "Spieler",
    "bannen",
    "Einstellungen",
    "Verifizierungs",
    "Optimiere",
    "Einloggen",
    "erstellen",
    "Drei Schritte",
    "Starte ",
    "Name der",
    "Keine ",
    "Noch ",
    "Ab Stufe",
    "Baue ",
    "Dieser Planet",
    "Mit aktueller",
    "festlegen",
    "ausgebaut",
    "freigeschaltet",
    "Schatten",
    "Rohstoffe",
    "Planetenkern",
    "Feindliche",
    "Kolonie-Scanner",
    "Live-Produktion",
    "Arbeiter",
    "Belagerung",
    "Schwarzmarkt",
    "Quanten",
    "KI-",
    "Ruinen",
    "Syndikat",
    "Unterwelt",
    "Politiken",
    "Aktive ",
    "Handels",
    "freischalten",
    "Orbitaler",
    "Festungs",
    "Meister",
    "Crytite-Produktion",
    "Schmuggelware",
    "Effizienz",
    "Flotten",
    "Urlaub",
    "Kernwerte",
    "Bann ",
    "gebannt",
    "Flottenspeed",
    "Scanner",
    "Bastion",
    "Wirtschaft",
    "Vermessung",
    "Aufstand",
    "Vorfall",
    "Durchbruch",
    "Output-Bonus",
    "Routen effizienter",
    "Breakthrough-Events",
    "Schmuggel",
    "Halten",
    "Friedlich",
    "Krieg",
    "Produktion / Bau",
)

_PLACEHOLDER_RE = re.compile(
    r"(%\([a-zA-Z0-9_]+\)[a-zA-Z]?|\{[a-zA-Z0-9_]+\}|%\([a-zA-Z0-9_]+\)s|%\([a-zA-Z0-9_]+\)d)"
)


def _load(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in data.items()}


def _write(path: Path, data: dict[str, str], key_order: list[str]) -> None:
    ordered = {k: data[k] for k in key_order if k in data}
    for k in sorted(data):
        if k not in ordered:
            ordered[k] = data[k]
    path.write_text(json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def is_german(val: str) -> bool:
    if re.search(r"[\u00df\u00e4\u00f6\u00fc\u00c4\u00d6\u00dc]", val):
        return True
    return any(h in val for h in GERMAN_HINTS)


def mask_text(text: str) -> tuple[str, list[str]]:
    tokens: list[str] = []
    out = text
    for term in sorted(CANON_TERMS, key=len, reverse=True):
        if term not in out:
            continue
        idx = len(tokens)
        tokens.append(term)
        out = out.replace(term, f"⟦T{idx}⟧")

    def ph_sub(match: re.Match[str]) -> str:
        tokens.append(match.group(0))
        return f"⟦P{len(tokens)-1}⟧"

    out = _PLACEHOLDER_RE.sub(ph_sub, out)
    return out, tokens


def unmask_text(text: str, tokens: list[str]) -> str:
    out = text
    for i, tok in enumerate(tokens):
        for pattern in (f"⟦T{i}⟧", f"⟦P{i}⟧", f"[[T{i}]]", f"[[P{i}]]"):
            out = out.replace(pattern, tok)
    # Repair common MT corruption of tokens
    out = out.replace("Ferronitee", "Ferronite").replace("ferronitee", "ferronite")
    out = re.sub(r"Ferronit(?!e)", "Ferronite", out)
    out = out.replace("Abbau-Pfad", "Extraction Path")
    return out


def _translator(source: str, target: str):
    from deep_translator import GoogleTranslator

    return GoogleTranslator(source=source, target=target)


def translate_batch(texts: list[str], *, source: str, target: str, retries: int = 3) -> list[str]:
    if not texts:
        return []
    masked = [mask_text(t) for t in texts]
    payload = [m[0] for m in masked]
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            tr = _translator(source, target)
            if hasattr(tr, "translate_batch"):
                raw = tr.translate_batch(payload)
            else:
                raw = [tr.translate(x) for x in payload]
            return [unmask_text(r or "", masked[i][1]) for i, r in enumerate(raw)]
        except Exception as exc:
            last_err = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"translate_batch failed {source}->{target}: {last_err}")


def translate_one(text: str, *, source: str, target: str) -> str:
    return translate_batch([text], source=source, target=target)[0]


def fix_en_german(*, scopes: set[str] | None = None, batch_size: int = 40) -> int:
    de = _load(LOCALES / "de.json")
    en = _load(LOCALES / "en.json")
    changed = 0
    keys = list(en.keys())
    todo: list[str] = []
    for key in keys:
        val = en[key]
        if not is_german(val):
            continue
        if scopes:
            ok = False
            if "pe" in scopes and key.startswith(("pe_", "desc_pe_", "spec_", "policy_", "trait_", "chain_", "event_")):
                ok = True
            if "overview" in scopes and key.startswith("overview_"):
                ok = True
            if "admin" in scopes and key.startswith(("admin_", "account_", "alliance_", "landing_", "login_", "register_", "galaxy_legend")):
                ok = True
            if "fleet" in scopes and key.startswith(("fleet_", "shipyard_", "defense_")) or key in ("shipyard", "fleet_shipyard_title", "nav_shipyard"):
                ok = True
            if not ok:
                continue
        todo.append(key)

    print(f"fix-en-german: {len(todo)} keys")
    for i in range(0, len(todo), batch_size):
        chunk = todo[i : i + batch_size]
        src_texts = [de.get(k, en[k]) for k in chunk]
        translated = translate_batch(src_texts, source="de", target="en")
        for key, new_val in zip(chunk, translated):
            if new_val and new_val != en[key]:
                en[key] = new_val
                changed += 1
        print(f"  batch {i // batch_size + 1}/{(len(todo) + batch_size - 1) // batch_size}")
        time.sleep(0.35)

    _write(LOCALES / "en.json", en, keys)
    return changed


def translate_locales(
    locales: tuple[str, ...],
    *,
    batch_size: int = 40,
    skip_english_identical: bool = True,
) -> dict[str, int]:
    en = _load(LOCALES / "en.json")
    de = _load(LOCALES / "de.json")
    key_order = list(de.keys()) + sorted(set(en) - set(de))
    stats: dict[str, int] = {}

    lang_map = {"pt": "pt", "fr": "fr", "es": "es", "pl": "pl", "tr": "tr", "ru": "ru"}

    for loc in locales:
        path = LOCALES / f"{loc}.json"
        target = _load(path) if path.exists() else dict(en)
        changed = 0
        keys = [k for k in key_order if k in en]
        todo = []
        for key in keys:
            if skip_english_identical and target.get(key) != en.get(key):
                continue
            todo.append(key)

        print(f"translate {loc}: {len(todo)} keys")
        for i in range(0, len(todo), batch_size):
            chunk = todo[i : i + batch_size]
            src_texts = [en[k] for k in chunk]
            translated = translate_batch(src_texts, source="en", target=lang_map[loc])
            for key, new_val in zip(chunk, translated):
                if new_val:
                    target[key] = new_val
                    changed += 1
            print(f"  {loc} batch {i // batch_size + 1}/{(len(todo) + batch_size - 1) // batch_size}", flush=True)
            time.sleep(0.35)
            if (i // batch_size) % 5 == 4:
                from scripts.gc900c_bootstrap_locales import _inject_language_names  # noqa: WPS433

                _inject_language_names(target, loc)
                _write(path, target, key_order)

        # Keep native language names
        from scripts.gc900c_bootstrap_locales import LANGUAGE_NAMES, _inject_language_names  # noqa: WPS433

        _inject_language_names(target, loc)
        _write(path, target, key_order)
        stats[loc] = changed
        print(f"  {loc}: {changed} updates", flush=True)

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="GC-900 locale translation")
    parser.add_argument("--fix-en-german", action="store_true", help="Translate German EN strings from DE source")
    parser.add_argument("--translate-all", action="store_true", help="Translate EN into fr/es/pl/tr/ru/pt")
    parser.add_argument(
        "--scopes",
        default="all",
        help="Comma scopes for --fix-en-german (pe,overview,admin,fleet,all)",
    )
    parser.add_argument("--locales", default="", help="Comma list e.g. fr,es,pl (default: all non-de/en)")
    parser.add_argument("--batch-size", type=int, default=40)
    args = parser.parse_args()

    if args.fix_en_german:
        scopes = None if args.scopes == "all" else set(args.scopes.split(","))
        n = fix_en_german(scopes=scopes, batch_size=args.batch_size)
        print(f"EN german fix: {n} keys updated")

    locales = tuple(x.strip() for x in args.locales.split(",") if x.strip()) or TARGET_LOCALES
    if args.translate_all or args.locales:
        stats = translate_locales(
            locales,
            batch_size=args.batch_size,
            skip_english_identical=not args.translate_all,
        )
        print("Translation stats:", stats)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
