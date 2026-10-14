"""Adapter for uukanshu.cc (UU看書), a traditional-Chinese raw site.

URL shapes: novel at ``/book/<id>/`` and chapters at
``/book/<id>/<chapterId>.html``, where the chapter id is a database key and
says nothing about ordering — so numbers come from the ``第N章`` in each title.
"""

from __future__ import annotations

import re

from app.sources.registry import register
from app.sources.zh_base import ChineseNovelSource

BASE = "https://uukanshu.cc"


@register
class UuKanShu(ChineseNovelSource):
    key = "uukanshu"
    name = "UU看書"
    domains = ("uukanshu.cc",)
    needs_browser = False

    base = BASE
    novel_re = re.compile(r"^/book/(?P<slug>\d+)/$")
    chapter_re = re.compile(r"^/book/(?P<slug>\d+)/(?P<chapter>\d+)\.html$")
    search_template = f"{BASE}/search?keyword={{query}}"

    # The whole catalogue sits in one definition list on the novel page.
    chapter_container_selectors = "dl.chapterlist, dl.book.chapterlist"
    body_selectors = ".content, #content"
    # The info block repeats the title, author, word count, genre and status
    # as plain text, so the status check reads the whole block.
    status_selectors = "dl.book, .book"

    def build_novel_url(self, match: re.Match[str]) -> str:
        return f"{BASE}/book/{match['slug']}/"

    def _novel_path_for(self, slug: str) -> str:
        return f"book/{slug}/"
