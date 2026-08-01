"""Translate Story Ops locale keys into es/fr/pl/pt/ru/tr (literary DE source).

Batched Google MT via deep_translator with brand-token protection.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from deep_translator import GoogleTranslator

ROOT = Path(__file__).resolve().parents[1]
LOCALES = ROOT / "locales"

STORY_PREFIXES = (
    "story_",
    "nav_story",
    "nav_badge_story",
    "free_shop",
    "inv_ark",
    "inv_story",
    "codex_unlock_story",
)

BRANDS = [
    "Living Lattice",
    "Genesis Ark",
    "Story Ops",
    "Androgyn-Echo",
    "Androgyn Echo",
    "Ark-Token",
    "Free Shop",
    "Timekeeper",
    "High Command",
    "Ferronite",
    "Crytite",
    "Imperium",
    "Androgyn",
    "Void Cult",
    "Iron Collective",
    "Nomad Swarm",
    "Ash Raiders",
    "Salt Cartel",
    "Corsairs",
    "Planet Evolution",
    "Seed-Ark",
    "Seed Ark",
    "Battle Pass",
    "Genesis Pass",
    "World Boss",
    "Ark Signal",
    "Void Patrol",
    "Pause",
    "Stop",
]

TARGET_LANGS = {
    "es": "es",
    "fr": "fr",
    "pl": "pl",
    "pt": "pt",
    "ru": "ru",
    "tr": "tr",
}

SEP = "\n<<<GC>>>\n"
BATCH_CHARS = 3500


def is_story_key(key: str) -> bool:
    return any(key.startswith(p) for p in STORY_PREFIXES)


def protect(text: str) -> tuple[str, dict[str, str]]:
    mapping: dict[str, str] = {}
    out = text
    for i, brand in enumerate(sorted(BRANDS, key=len, reverse=True)):
        token = f"[[B{i}]]"
        if brand in out:
            mapping[token] = brand
            out = out.replace(brand, token)
    return out, mapping


def unprotect(text: str, mapping: dict[str, str]) -> str:
    out = text
    for token, brand in mapping.items():
        out = out.replace(token, brand)
        out = out.replace(token.lower(), brand)
        inner = token[2:-2]
        out = out.replace(f"[ [{inner}] ]", brand)
        out = out.replace(f"[[ {inner} ]]", brand)
    return out


def translate_batch(translator: GoogleTranslator, texts: list[str]) -> list[str]:
    """Translate a list of strings; returns same length."""
    if not texts:
        return []
    protected_list: list[str] = []
    maps: list[dict[str, str]] = []
    for t in texts:
        p, m = protect(str(t))
        protected_list.append(p)
        maps.append(m)

    # Pack into character-limited batches
    batches: list[list[int]] = []
    current: list[int] = []
    size = 0
    for idx, p in enumerate(protected_list):
        add = len(p) + len(SEP)
        if current and size + add > BATCH_CHARS:
            batches.append(current)
            current = []
            size = 0
        current.append(idx)
        size += add
    if current:
        batches.append(current)

    results = [""] * len(texts)
    for batch_idxs in batches:
        payload = SEP.join(protected_list[i] for i in batch_idxs)
        translated = None
        last_err: Exception | None = None
        for attempt in range(6):
            try:
                translated = translator.translate(payload)
                last_err = None
                break
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                time.sleep(1.2 * (attempt + 1))
        if last_err is not None or translated is None:
            # Fallback: one-by-one
            for i in batch_idxs:
                one = protected_list[i]
                try:
                    results[i] = unprotect(translator.translate(one) or one, maps[i])
                except Exception:
                    results[i] = unprotect(one, maps[i])
                time.sleep(0.05)
            continue

        parts = translated.split("<<<GC>>>")
        parts = [p.strip("\n") for p in parts]
        if len(parts) != len(batch_idxs):
            # Separator mangled — fallback per item
            for i in batch_idxs:
                one = protected_list[i]
                try:
                    results[i] = unprotect(translator.translate(one) or one, maps[i])
                except Exception:
                    results[i] = unprotect(one, maps[i])
                time.sleep(0.05)
        else:
            for j, i in enumerate(batch_idxs):
                results[i] = unprotect(parts[j], maps[i])
        time.sleep(0.15)
    return results


def translate_locale(locale: str, lang_code: str, keys: list[str], en: dict, de: dict) -> dict[str, int]:
    path = LOCALES / f"{locale}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    translator = GoogleTranslator(source="de", target=lang_code)

    sources: list[str] = []
    for key in keys:
        de_val = de.get(key)
        if de_val is not None and str(de_val).strip() != "":
            sources.append(str(de_val))
        else:
            sources.append(str(en.get(key, "")))

    print(f"{locale}: translating {len(sources)} strings…", flush=True)
    translated = translate_batch(translator, sources)
    identical = 0
    for key, val in zip(keys, translated):
        data[key] = val
        if val == en.get(key):
            identical += 1
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{locale}: done identical_to_en={identical}/{len(keys)}", flush=True)
    return {"identical": identical, "total": len(keys)}


def main() -> None:
    en = json.loads((LOCALES / "en.json").read_text(encoding="utf-8"))
    de = json.loads((LOCALES / "de.json").read_text(encoding="utf-8"))
    keys = sorted(k for k in en if is_story_key(k))
    print(f"Story keys: {len(keys)}", flush=True)

    # Parallelize locales (Google may rate-limit; 3 workers is a balance)
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = {
            pool.submit(translate_locale, loc, code, keys, en, de): loc
            for loc, code in TARGET_LANGS.items()
        }
        for fut in as_completed(futs):
            loc = futs[fut]
            try:
                fut.result()
            except Exception as exc:  # noqa: BLE001
                print(f"{loc} FAILED: {exc}", flush=True)
                raise


if __name__ == "__main__":
    main()
