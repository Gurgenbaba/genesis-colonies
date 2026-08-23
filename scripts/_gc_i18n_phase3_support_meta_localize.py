from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY = "support_message_meta"
VALUES = {
    "de": "%(sender)s · %(time)s",
    "en": "%(sender)s — %(time)s",
    "fr": "%(sender)s — %(time)s",
    "es": "%(sender)s — %(time)s",
    "pl": "%(sender)s — %(time)s",
    "tr": "%(sender)s • %(time)s",
    "ru": "%(sender)s — %(time)s",
    "pt": "%(sender)s — %(time)s",
}


def main() -> None:
    for lang, value in VALUES.items():
        path = ROOT / "locales" / f"{lang}.json"
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        old = data.get(KEY)
        if old is None:
            raise RuntimeError(f"{lang}: missing {KEY}")
        encoded_old = json.dumps(str(old), ensure_ascii=False)
        encoded_new = json.dumps(value, ensure_ascii=False)
        needle = f'{json.dumps(KEY)}: {encoded_old}'
        replacement = f'{json.dumps(KEY)}: {encoded_new}'
        if needle not in text:
            raise RuntimeError(f"{lang}: exact locale line not found")
        new_text = text.replace(needle, replacement, 1)
        parsed = json.loads(new_text)
        if parsed.get(KEY) != value:
            raise RuntimeError(f"{lang}: failed to update {KEY}")
        path.write_text(new_text, encoding="utf-8")
    print("Support message meta formats localized")


if __name__ == "__main__":
    main()
