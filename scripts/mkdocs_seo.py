"""MkDocs hook for the docs site's search, share and AI-answer metadata.

- Gives each page the description listed under ``extra.page_descriptions`` in mkdocs.yml, keyed by the page's path
  inside docs/, so the Markdown files need no front matter (front matter shows up as a table on GitHub).
- Puts the package version in ``extra.version`` for the structured data on the home page.
- Turns the FAQ page's "## Question" sections into schema.org FAQPage JSON-LD.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def on_config(config):
    init = (ROOT / "pbidriver" / "__init__.py").read_text(encoding="utf-8")
    config["extra"]["version"] = re.search(r'__version__ = "([^"]+)"', init).group(1)
    return config


def _plain(markdown: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", markdown)  # links -> their text
    text = re.sub(r"[`*_]", "", text)
    return " ".join(text.split())


def faq_jsonld(markdown: str) -> str | None:
    """FAQPage JSON-LD from '## Question' headings and the paragraphs under them."""
    entries = []
    for block in re.split(r"^## ", markdown, flags=re.M)[1:]:
        question, _, answer = block.partition("\n")
        answer = _plain(answer)
        if question.strip().endswith("?") and answer:
            entries.append({"@type": "Question", "name": question.strip(),
                            "acceptedAnswer": {"@type": "Answer", "text": answer}})
    if not entries:
        return None
    return json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": entries},
                      ensure_ascii=False)


def on_page_markdown(markdown, page, config, files):
    description = (config["extra"].get("page_descriptions") or {}).get(page.file.src_uri)
    if description and "description" not in page.meta:
        page.meta["description"] = description
    if page.file.src_uri == "faq.md":
        page.meta["faq_jsonld"] = faq_jsonld(markdown)
    return markdown
