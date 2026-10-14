"""Adapter for czbooks.net (小說狂人), a traditional-Chinese raw site.

URL shapes: novel at ``/n/<code>`` and chapters at ``/n/<code>/<chapterCode>``,
both using short alphanumeric codes rather than numbers. Links on the site are
protocol-relative (``//czbooks.net/...``), which ``urljoin`` handles.
"""

from __future__ import annotations

import re

from app.sources.registry import register
from app.sources.zh_base import ChineseNovelSource

BASE = "https://czbooks.net"


@register
class CzBooks(ChineseNovelSource):
    key = "czbooks"
    name = "小說狂人"
    domains = ("czbooks.net",)
    needs_browser = False

    base = BASE
    novel_re = re.compile(r"^/n/(?P<slug>[A-Za-z0-9]+)/?$")
    chapter_re = re.compile(r"^/n/(?P<slug>[A-Za-z0-9]+)/(?P<chapter>[A-Za-z0-9]+)/?$")
    search_template = f"{BASE}/search?q={{query}}"

    title_selectors = "span.title, .info span.title, h1"
    author_selectors = ".author a, .author, meta[property='og:novel:author']"
    description_selectors = ".description, .novel-description"
    status_selectors = ".novel-detail, .state"
    chapter_container_selectors = "ul.nav.chapter-list, ul.chapter-list, .chapter-list"
    body_selectors = "div.content, .content"

    def build_novel_url(self, match: re.Match[str]) -> str:
        return f"{BASE}/n/{match['slug']}"

    def _novel_path_for(self, slug: str) -> str:
        return f"n/{slug}"
