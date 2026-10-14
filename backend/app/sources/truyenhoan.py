"""Adapter for truyenhoan.com.

Layout is the shared truyenfull template (see ``vi_truyenfull``). What is
specific here is the URL shape: a novel lives at ``/<slug>.<id>/`` while its
chapters sit at ``/<slug>/chuong-N.html`` — the chapter path drops the numeric
id, so the two shapes have to be matched separately.
"""

from __future__ import annotations

import re

from app.db.models import Lang
from app.sources.registry import register
from app.sources.vi_truyenfull import TruyenFullFamily

BASE = "https://truyenhoan.com"


@register
class TruyenHoan(TruyenFullFamily):
    key = "truyenhoan"
    name = "Truyện Hoàn"
    domains = ("truyenhoan.com", "truyenfull.tv")
    lang = Lang.vi
    needs_browser = False

    base = BASE
    # /ten-truyen.12345/ and optionally /trang-2/
    novel_re = re.compile(r"^/(?P<slug>[^/]+?)\.(?P<id>\d+)/?(?:trang-\d+/?)?$")
    # /ten-truyen/chuong-12.html
    chapter_re = re.compile(r"^/(?P<slug>[^/]+?)/chuong-(?P<number>\d+)\.html$")
    search_template = f"{BASE}/tim-kiem/?tukhoa={{query}}"

    def build_novel_url(self, match: re.Match[str]) -> str:
        return f"{BASE}/{match['slug']}.{match['id']}/"
