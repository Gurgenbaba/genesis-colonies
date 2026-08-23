from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY = "support_message_meta"
VALUE = "%(sender)s · %(time)s"


def append_locale_key(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if KEY in data:
        if data[KEY] != VALUE:
            raise RuntimeError(f"{path}: unexpected existing {KEY} value")
        return
    stripped = text.rstrip()
    if not stripped.endswith("}"):
        raise RuntimeError(f"{path}: not a JSON object")
    prefix = stripped[:-1].rstrip()
    line = f'  {json.dumps(KEY)}: {json.dumps(VALUE, ensure_ascii=False)}'
    new_text = prefix + ("\n" if prefix.endswith("{") else ",\n") + line + "\n}\n"
    parsed = json.loads(new_text)
    if parsed.get(KEY) != VALUE:
        raise RuntimeError(f"{path}: failed to append {KEY}")
    path.write_text(new_text, encoding="utf-8")


def patch_main_js() -> None:
    path = ROOT / "static" / "main.js"
    text = path.read_text(encoding="utf-8")
    old = '      meta.textContent = `${m.sender_name || t("support_unknown")} · ${formatTs(m.created_at)}`;\n'
    new = '''      meta.textContent = tf("support_message_meta", {\n        sender: m.sender_name || t("support_unknown"),\n        time: formatTs(m.created_at),\n      });\n'''
    if old not in text:
        if 'tf("support_message_meta"' in text:
            return
        raise RuntimeError("support message meta line not found")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_test() -> None:
    path = ROOT / "tests" / "test_i18n_hardening.py"
    text = path.read_text(encoding="utf-8")
    old = '    assert \'t("support_unknown")\' in main_js\n'
    if old not in text:
        anchor = '    assert \'t("support_reply_placeholder")\' in main_js\n'
        if anchor not in text:
            raise RuntimeError("support regression assertion anchor not found")
        text = text.replace(anchor, '    assert \'tf("support_message_meta"\' in main_js\n' + anchor, 1)
    elif 'tf("support_message_meta"' not in text:
        text = text.replace(old, old + '    assert \'tf("support_message_meta"\' in main_js\n', 1)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    for lang in ("de", "en", "fr", "es", "pl", "tr", "ru", "pt"):
        append_locale_key(ROOT / "locales" / f"{lang}.json")
    patch_main_js()
    patch_test()
    print("Support message meta localized")


if __name__ == "__main__":
    main()
