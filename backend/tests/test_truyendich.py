"""The truyendich adapter.

Covers what differs from truyenhoan: single-segment novel URLs, a plain
``h1`` title, unlinked genres, and extra rows in the info block. The shared
parsing itself is exercised by both adapters' test files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.db.models import Lang, NovelStatus
from app.fetch.base import Response
from app.sources.base import SourceError
from app.sources.truyendich import TruyenDich

FIXTURES = Path(__file__).parent / "fixtures" / "truyendich"

NOVEL_URL = "https://truyendich.vn/ho-lo-bay-sac/"
CHAPTER_URL = "https://truyendich.vn/ho-lo-bay-sac/chuong-1/"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeFetcher:
    def __init__(self, routes: dict[str, str]) -> None:
        self.routes = routes
        self.requested: list[str] = []

    async def get(self, url: str, *, referer: str | None = None, encoding: str | None = None):
        self.requested.append(url)
        try:
            body = self.routes[url]
        except KeyError:  # pragma: no cover - surfaces a wrong URL in a test
            raise AssertionError(f"unexpected request: {url}") from None
        return Response(url=url, status=200, text=body)

    async def aclose(self) -> None:
        pass


def make_source(routes: dict[str, str]) -> tuple[TruyenDich, FakeFetcher]:
    fetcher = FakeFetcher(routes)
    return TruyenDich(fetcher), fetcher


def novel_routes() -> dict[str, str]:
    return {
        NOVEL_URL: load("novel.html"),
        f"{NOVEL_URL}trang-2/": load("novel_trang2.html"),
    }


# --- url handling ----------------------------------------------------------


def test_handles_only_its_domain():
    assert TruyenDich.handles(NOVEL_URL)
    assert TruyenDich.handles("https://www.truyendich.vn/abc/")
    assert not TruyenDich.handles("https://truyenhoan.com/abc.1/")


@pytest.mark.parametrize(
    "given",
    [
        NOVEL_URL,
        "https://truyendich.vn/ho-lo-bay-sac",
        "https://truyendich.vn/ho-lo-bay-sac/trang-7/",
        "https://www.truyendich.vn/ho-lo-bay-sac/",
    ],
)
def test_canonical_url_normalises_novel_urls(given: str):
    source, _ = make_source({})

    assert source.canonical_url(given) == NOVEL_URL


def test_canonical_url_keeps_chapter_urls_but_drops_query():
    source, _ = make_source({})

    assert source.canonical_url(f"{CHAPTER_URL}?ref=fb") == CHAPTER_URL


@pytest.mark.parametrize(
    "section",
    [
        "https://truyendich.vn/tim-kiem/",
        "https://truyendich.vn/danh-sach/",
        "https://truyendich.vn/the-loai/",
        "https://truyendich.vn/xep-hang/",
    ],
)
def test_site_sections_are_not_mistaken_for_novels(section: str):
    """A novel is one path segment here, so category pages have to be excluded."""
    source, _ = make_source({})

    with pytest.raises(SourceError, match="site section"):
        source.canonical_url(section)


def test_is_chapter_url():
    source, _ = make_source({})

    assert source.is_chapter_url(CHAPTER_URL)
    assert not source.is_chapter_url(NOVEL_URL)


async def test_novel_url_can_be_recovered_from_a_chapter_page():
    source, _ = make_source({CHAPTER_URL: load("chapter.html")})

    assert await source.novel_url_from_chapter(CHAPTER_URL) == NOVEL_URL


# --- novel info ------------------------------------------------------------


async def test_novel_info_reads_a_plain_h1_title():
    """This site has no `title` class on the heading."""
    source, _ = make_source({NOVEL_URL: load("novel.html")})

    info = await source.novel_info(NOVEL_URL)

    assert info.title == "Hồ Lô Bảy Sắc"
    assert info.url == NOVEL_URL
    assert info.lang is Lang.vi


async def test_novel_info_reads_an_unlinked_author():
    source, _ = make_source({NOVEL_URL: load("novel.html")})

    info = await source.novel_info(NOVEL_URL)

    assert info.author == "Diêu Vọng Nam Sơn"


async def test_unlinked_genres_are_split_on_commas():
    source, _ = make_source({NOVEL_URL: load("novel.html")})

    info = await source.novel_info(NOVEL_URL)

    assert info.genres == ["Truyện Tiên Hiệp", "Truyện Huyền Huyễn"]


async def test_status_row_is_picked_over_the_similar_looking_one():
    """The info block has both "Tình trạng: VIP" and "Trạng thái: Full"."""
    source, _ = make_source({NOVEL_URL: load("novel.html")})

    info = await source.novel_info(NOVEL_URL)

    assert info.status is NovelStatus.completed


async def test_cover_url_is_absolute():
    source, _ = make_source({NOVEL_URL: load("novel.html")})

    info = await source.novel_info(NOVEL_URL)

    assert info.cover_url == "https://truyendich.vn/story-thumb/ho-lo-bay-sac.jpg"


async def test_description_is_clean_text():
    source, _ = make_source({NOVEL_URL: load("novel.html")})

    info = await source.novel_info(NOVEL_URL)

    assert info.description
    assert "<p>" not in info.description
    assert "hồ lô cũ" in info.description


async def test_homepage_fallback_is_reported_as_a_layout_problem():
    source, _ = make_source({NOVEL_URL: load("homepage.html")})

    with pytest.raises(SourceError, match="No novel title"):
        await source.novel_info(NOVEL_URL)


# --- chapter list ----------------------------------------------------------


async def test_chapter_list_walks_pagination_and_keeps_gaps():
    source, fetcher = make_source(novel_routes())

    chapters = await source.chapter_list(NOVEL_URL)

    assert [c.number for c in chapters] == [1, 2, 3, 5, 6]
    assert f"{NOVEL_URL}trang-2/" in fetcher.requested


async def test_chapter_titles_come_from_the_title_attribute():
    source, _ = make_source(novel_routes())

    chapters = {c.number: c for c in await source.chapter_list(NOVEL_URL)}

    assert chapters[1].title == "Chương 1: Gian hàng ven chợ"
    assert chapters[6].title == "Chương 6"


async def test_chapter_urls_are_absolute():
    source, _ = make_source(novel_routes())

    chapters = await source.chapter_list(NOVEL_URL)

    assert all(c.url.startswith("https://truyendich.vn/ho-lo-bay-sac/") for c in chapters)


async def test_other_novels_in_the_sidebar_are_ignored():
    source, _ = make_source(novel_routes())

    chapters = await source.chapter_list(NOVEL_URL)

    assert all("ho-lo-bay-sac" in c.url for c in chapters)
    assert 88 not in [c.number for c in chapters]


async def test_empty_chapter_list_is_reported():
    source, _ = make_source({NOVEL_URL: load("homepage.html")})

    with pytest.raises(SourceError, match="Chapter list is empty"):
        await source.chapter_list(NOVEL_URL)


# --- chapter content -------------------------------------------------------


async def test_chapter_content_is_clean_prose():
    source, _ = make_source({CHAPTER_URL: load("chapter.html")})

    text = await source.chapter_content(CHAPTER_URL)

    assert "Gian hàng kê sát bờ tường" in text
    assert "\n\n" in text


async def test_chapter_content_strips_site_furniture():
    source, _ = make_source({CHAPTER_URL: load("chapter.html")})

    text = await source.chapter_content(CHAPTER_URL)

    assert "quảng cáo" not in text.lower()
    assert "truyendich.vn" not in text
    assert "Nguồn" not in text
    assert "Chia sẻ" not in text
    assert "var ad" not in text
    assert "\u200b" not in text
