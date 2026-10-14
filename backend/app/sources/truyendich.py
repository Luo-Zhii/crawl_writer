"""Adapter for truyendich.vn.

Same template as truyenhoan but simpler URLs: the novel is ``/<slug>/`` and
chapters are ``/<slug>/chuong-N/``, with no numeric id anywhere.
"""

from __future__ import annotations

import re

from app.db.models import Lang
from app.sources.base import SourceError
from app.sources.registry import register
from app.sources.vi_truyenfull import TruyenFullFamily

BASE = "https://truyendich.vn"

# Paths that look like a novel but are site sections, not stories.
_RESERVED = (
    "tim-kiem",
    "danh-sach",
    "the-loai",
    "tac-gia",
    "xep-hang",
    "truyen-hot",
    "truyen-moi",
    "truyen-full",
    "dang-nhap",
    "dang-ky",
    "thong-bao",
)


@register
class TruyenDich(TruyenFullFamily):
    key = "truyendich"
    name = "Truyện Dịch"
    domains = ("truyendich.vn",)
    lang = Lang.vi
    needs_browser = False

    base = BASE
    # /ten-truyen/ and optionally /trang-2/
    novel_re = re.compile(r"^/(?P<slug>[^/]+)/(?:trang-\d+/?)?$")
    # /ten-truyen/chuong-12/
    chapter_re = re.compile(r"^/(?P<slug>[^/]+)/chuong-(?P<number>\d+)/?$")
    search_template = f"{BASE}/tim-kiem/?tukhoa={{query}}"

    def build_novel_url(self, match: re.Match[str]) -> str:
        slug = match["slug"]
        if slug in _RESERVED:
            # The novel pattern is a single path segment, so without this a
            # category page would be crawled as if it were a story.
            raise SourceError(f"'{slug}' is a site section, not a novel", url=f"{BASE}/{slug}/")
        return f"{BASE}/{slug}/"
