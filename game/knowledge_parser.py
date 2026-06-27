"""Parse Player Article blocks from Master Docs (GC-950)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs"

SECTION_KEYS = {
    "quick help": "quick_help",
    "summary": "summary",
    "why": "why",
    "how it works": "how_it_works",
    "tips": "tips",
    "faq": "faq",
    "related systems": "related_systems",
    "commander tips": "commander_tips",
    "discord summary": "discord_summary",
}

PLAYER_ARTICLE_HEADER = re.compile(r"^##\s+Player Article\s*$", re.MULTILINE)
YAML_FENCE = re.compile(r"```yaml\s*\n(.*?)```", re.DOTALL)
SECTION_HEADER = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _parse_faq_block(text: str) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    parts = re.split(r"\n(?=\*\*)", text.strip())
    for part in parts:
        chunk = part.strip()
        if not chunk:
            continue
        m = re.match(r"\*\*(.+?)\*\*\s*\n?(.*)", chunk, re.DOTALL)
        if m:
            items.append({"q": m.group(1).strip(), "a": m.group(2).strip()})
    return items


def _parse_bullets(text: str) -> List[str]:
    lines = []
    for line in text.strip().splitlines():
        line = line.strip()
        if line.startswith("- "):
            lines.append(line[2:].strip())
        elif line.startswith("* "):
            lines.append(line[2:].strip())
    return lines


def _parse_related(text: str) -> List[str]:
    out: List[str] = []
    for line in text.strip().splitlines():
        line = line.strip()
        if line.startswith("- "):
            out.append(line[2:].strip())
    return out


def parse_player_article_block(block: str) -> Optional[Dict[str, Any]]:
    yaml_match = YAML_FENCE.search(block)
    if not yaml_match:
        return None
    try:
        raw_yaml = yaml_match.group(1).strip()
        if raw_yaml.startswith("---"):
            raw_yaml = raw_yaml[3:].strip()
        if raw_yaml.endswith("---"):
            raw_yaml = raw_yaml[:-3].strip()
        meta = yaml.safe_load(raw_yaml) or {}
    except yaml.YAMLError:
        return None
    if not meta.get("codex_id"):
        return None

    body_start = yaml_match.end()
    body = block[body_start:]
    sections: Dict[str, Any] = {}
    matches = list(SECTION_HEADER.finditer(body))
    for i, match in enumerate(matches):
        title = match.group(1).strip().lower()
        key = SECTION_KEYS.get(title)
        if not key:
            continue
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        content = body[start:end].strip()
        if key == "faq":
            sections[key] = _parse_faq_block(content)
        elif key in ("commander_tips", "tips"):
            sections[key] = _parse_bullets(content)
        elif key == "related_systems":
            sections[key] = _parse_related(content)
        else:
            sections[key] = content

    return {"meta": meta, "sections": sections}


def extract_player_articles_from_markdown(text: str) -> List[Dict[str, Any]]:
    articles: List[Dict[str, Any]] = []
    for header_match in PLAYER_ARTICLE_HEADER.finditer(text):
        start = header_match.start()
        next_header = PLAYER_ARTICLE_HEADER.search(text, header_match.end())
        end = next_header.start() if next_header else len(text)
        block = text[start:end]
        parsed = parse_player_article_block(block)
        if parsed:
            articles.append(parsed)
    return articles


def load_player_articles_from_docs(docs_dir: Path | None = None) -> List[Dict[str, Any]]:
    base = docs_dir or DOCS_DIR
    articles: List[Dict[str, Any]] = []
    for path in sorted(base.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for article in extract_player_articles_from_markdown(text):
            article["source_doc"] = path.name
            articles.append(article)
    return articles


def build_catalog(articles: List[Dict[str, Any]]) -> Dict[str, Any]:
    catalog: Dict[str, Any] = {"articles": {}, "routes": {}, "bands": {}}
    tips_pool: List[Dict[str, str]] = []

    for article in articles:
        meta = dict(article.get("meta") or {})
        codex_id = str(meta.get("codex_id") or "").strip()
        if not codex_id:
            continue
        sections = article.get("sections") or {}
        band = str(meta.get("band") or "—")
        catalog["articles"][codex_id] = {
            "codex_id": codex_id,
            "band": band,
            "difficulty": str(meta.get("difficulty") or "beginner"),
            "estimated_read": str(meta.get("estimated_read") or ""),
            "surfaces": list(meta.get("surfaces") or []),
            "routes": list(meta.get("routes") or []),
            "related_codex": list(meta.get("related_codex") or sections.get("related_systems") or []),
            "unlock": dict(meta.get("unlock") or {"type": "always"}),
            "teaser_key": str(meta.get("teaser_key") or ""),
            "terminology": str(meta.get("terminology") or ""),
            "source_doc": str(article.get("source_doc") or ""),
            "faq_count": len(sections.get("faq") or []),
            "tip_count": len(sections.get("commander_tips") or []),
        }
        catalog["bands"].setdefault(band, []).append(codex_id)
        for route in meta.get("routes") or []:
            catalog["routes"].setdefault(str(route), []).append(codex_id)
        for tip in sections.get("commander_tips") or []:
            tips_pool.append({"codex_id": codex_id, "text": tip})

    for band in catalog["bands"]:
        catalog["bands"][band] = sorted(catalog["bands"][band])

    catalog["commander_tips_pool"] = tips_pool
    return catalog


def locale_keys_for_article(
    codex_id: str,
    sections: Dict[str, Any],
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    prefix = f"codex_{codex_id}"
    title = str((meta or {}).get("title") or "").strip()
    keys: Dict[str, str] = {
        f"{prefix}_title": title or codex_id.replace("_", " ").title(),
    }
    if sections.get("quick_help"):
        keys[f"{prefix}_quick_help"] = str(sections["quick_help"])
    if sections.get("summary"):
        keys[f"{prefix}_summary"] = str(sections["summary"])
    if sections.get("why"):
        keys[f"{prefix}_why"] = str(sections["why"])
    if sections.get("how_it_works"):
        keys[f"{prefix}_how_it_works"] = str(sections["how_it_works"])
    if sections.get("discord_summary"):
        keys[f"{prefix}_discord_summary"] = str(sections["discord_summary"])
    for i, item in enumerate(sections.get("faq") or []):
        keys[f"{prefix}_faq_{i}_q"] = str(item.get("q") or "")
        keys[f"{prefix}_faq_{i}_a"] = str(item.get("a") or "")
    for i, tip in enumerate(sections.get("commander_tips") or []):
        keys[f"{prefix}_tip_{i}"] = str(tip)
    return keys


def build_locale_map(articles: List[Dict[str, Any]]) -> Dict[str, str]:
    merged: Dict[str, str] = {}
    for article in articles:
        codex_id = str((article.get("meta") or {}).get("codex_id") or "")
        if not codex_id:
            continue
        merged.update(
            locale_keys_for_article(
                codex_id,
                article.get("sections") or {},
                article.get("meta"),
            )
        )
    return merged
