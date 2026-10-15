"""The truyenhoan adapter, parsed against saved markup.

Fixtures mirror the site's structure with invented content; see
``tests/fixtures/truyenhoan/README.md``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.db.models import Lang, NovelStatus
from app.fetch.base import Response
from app.sources.base import SourceError
from app.sources.truyenhoan import TruyenHoan

FIXTURES = Path(__file__).parent / "fixtures" / "truyenhoan"

NOVEL_URL = "https://truyenhoan.com/kiem-khach-vo-danh.31415/"
CHAPTER_URL = "https://truyenhoan.com/kiem-khach-vo-danh/chuong-1.html"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeFetcher:
    """Serves fixture files by URL and records what was requested."""

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


def make_source(routes: dict[str, str]) -> tuple[TruyenHoan, FakeFetcher]:
    fetcher = FakeFetcher(routes)
    return TruyenHoan(fetcher), fetcher


def novel_routes() -> dict[str, str]:
    return {
        NOVEL_URL: load("novel.html"),
        f"{NOVEL_URL}trang-2/": load("novel_trang2.html"),
        f"{NOVEL_URL}trang-3/": load("novel_trang3.html"),
    }


# --- url handling ----------------------------------------------------------


def test_handles_its_domains():
    assert TruyenHoan.handles(NOVEL_URL)
    assert TruyenHoan.handles("https://www.truyenhoan.com/a.1/")
    assert TruyenHoan.handles("https://truyenfull.tv/a.1/")
    assert not TruyenHoan.handles("https://metruyencv.com/truyen/abc")


@pytest.mark.parametrize(
    "given",
    [
        NOVEL_URL,
        "https://truyenhoan.com/kiem-khach-vo-danh.31415",
        "https://truyenhoan.com/kiem-khach-vo-danh.31415/trang-4/",
        "https://www.truyenhoan.com/kiem-khach-vo-danh.31415/",
    ],
)
def test_canonical_url_normalises_novel_urls(given: str):
    """Pasting page 4 of the chapter list must still resolve to one library entry."""
    source, _ = make_source({})

    assert source.canonical_url(given) == NOVEL_URL


def test_canonical_url_keeps_chapter_urls_but_drops_query():
    source, _ = make_source({})

    assert source.canonical_url(f"{CHAPTER_URL}?ref=fb") == CHAPTER_URL


def test_canonical_url_rejects_unrelated_paths():
    source, _ = make_source({})

    with pytest.raises(SourceError):
        source.canonical_url("https://truyenhoan.com/random-path-without-slug/")


def test_is_chapter_url():
    source, _ = make_source({})

    assert source.is_chapter_url(CHAPTER_URL)
    assert not source.is_chapter_url(NOVEL_URL)


async def test_novel_url_can_be_recovered_from_a_chapter_page():
    """Users paste chapter links; the crawl still needs the novel page."""
    source, _ = make_source({CHAPTER_URL: load("chapter.html")})

    assert await source.novel_url_from_chapter(CHAPTER_URL) == NOVEL_URL


# --- novel info ------------------------------------------------------------


async def test_novel_info_reads_every_field():
    source, _ = make_source({NOVEL_URL: load("novel.html")})

    info = await source.novel_info(NOVEL_URL)

    assert info.title == "Kiếm Khách Vô Danh"
    assert info.author == "Mộng Trung Nhân"
    assert info.genres == ["Tiên Hiệp", "Kiếm Hiệp"]
    assert info.status is NovelStatus.ongoing
    assert info.lang is Lang.vi
    assert info.url == NOVEL_URL


async def test_novel_info_makes_the_cover_url_absolute():
    source, _ = make_source({NOVEL_URL: load("novel.html")})

    info = await source.novel_info(NOVEL_URL)

    assert info.cover_url is not None
    assert info.cover_url.startswith("https://truyenhoan.com/medias/covers/")


async def test_novel_info_description_is_clean_text():
    source, _ = make_source({NOVEL_URL: load("novel.html")})

    info = await source.novel_info(NOVEL_URL)

    assert info.description
    assert "<p>" not in info.description
    assert "thành cổ" in info.description


async def test_novel_info_accepts_a_non_canonical_url():
    source, fetcher = make_source({NOVEL_URL: load("novel.html")})

    await source.novel_info("https://truyenhoan.com/kiem-khach-vo-danh.31415/trang-2/")

    assert fetcher.requested == [NOVEL_URL]


async def test_homepage_fallback_is_reported_as_a_layout_problem():
    """An unknown id returns the homepage with HTTP 200; that is not a novel."""
    source, _ = make_source({NOVEL_URL: load("homepage.html")})

    with pytest.raises(SourceError, match="No novel title"):
        await source.novel_info(NOVEL_URL)


# --- chapter list ----------------------------------------------------------


async def test_chapter_list_walks_all_pages():
    source, fetcher = make_source(novel_routes())

    chapters = await source.chapter_list(NOVEL_URL)

    assert [c.number for c in chapters] == [1, 2, 3, 4, 5, 7, 10]
    assert f"{NOVEL_URL}trang-2/" in fetcher.requested
    assert f"{NOVEL_URL}trang-3/" in fetcher.requested


async def test_chapter_numbers_come_from_the_url_not_a_counter():
    """A gap on the site must stay a gap, or resume overwrites the wrong files."""
    source, _ = make_source(novel_routes())

    chapters = await source.chapter_list(NOVEL_URL)
    numbers = [c.number for c in chapters]

    assert 6 not in numbers
    assert numbers == sorted(numbers)


async def test_duplicate_chapter_links_are_collapsed():
    source, _ = make_source(novel_routes())

    chapters = await source.chapter_list(NOVEL_URL)

    assert len({c.number for c in chapters}) == len(chapters)


async def test_chapter_titles_prefer_the_title_attribute():
    source, _ = make_source(novel_routes())

    chapters = {c.number: c for c in await source.chapter_list(NOVEL_URL)}

    assert chapters[1].title == "Chương 1: Mưa trên thành cổ"
    # No subtitle on the site for this one, so the label is all we get.
    assert chapters[10].title == "Chương 10"


async def test_chapter_urls_are_absolute():
    source, _ = make_source(novel_routes())

    chapters = await source.chapter_list(NOVEL_URL)

    assert all(c.url.startswith("https://truyenhoan.com/") for c in chapters)
    # Relative href in the fixture for chapter 3.
    assert next(c for c in chapters if c.number == 3).url.endswith("/chuong-3.html")


async def test_links_from_other_novels_are_ignored():
    """The footer lists unrelated novels using the same markup."""
    source, _ = make_source(novel_routes())

    chapters = await source.chapter_list(NOVEL_URL)

    assert all("kiem-khach-vo-danh" in c.url for c in chapters)


async def test_empty_chapter_list_is_reported():
    source, _ = make_source({NOVEL_URL: load("homepage.html")})

    with pytest.raises(SourceError, match="Chapter list is empty"):
        await source.chapter_list(NOVEL_URL)


async def test_pagination_stops_when_a_page_adds_nothing():
    """Guards against looping over pages that repeat page 1."""
    routes = {
        NOVEL_URL: load("novel.html"),
        f"{NOVEL_URL}trang-2/": load("novel.html"),
        f"{NOVEL_URL}trang-3/": load("novel_trang3.html"),
    }
    source, fetcher = make_source(routes)

    await source.chapter_list(NOVEL_URL)

    assert f"{NOVEL_URL}trang-3/" not in fetcher.requested


# --- chapter content -------------------------------------------------------


async def test_chapter_content_is_clean_prose():
    source, _ = make_source({CHAPTER_URL: load("chapter.html")})

    text = await source.chapter_content(CHAPTER_URL)

    assert "Mưa đổ xuống mái ngói cũ" in text
    assert "đèn lồng đã thắp" in text
    assert "\n\n" in text, "paragraphs should be separated by a blank line"


async def test_chapter_content_strips_site_furniture():
    source, _ = make_source({CHAPTER_URL: load("chapter.html")})

    text = await source.chapter_content(CHAPTER_URL)

    assert "quảng cáo" not in text.lower()
    assert "truyenhoan.com" not in text
    assert "Nguồn" not in text
    assert "Chia sẻ" not in text
    assert "var ad" not in text
    assert "\u200b" not in text


async def test_missing_body_container_is_reported():
    source, _ = make_source({CHAPTER_URL: load("chapter_empty.html")})

    with pytest.raises(SourceError, match="No chapter body"):
        await source.chapter_content(CHAPTER_URL)


# --- search ----------------------------------------------------------------


async def test_search_returns_results():
    url = "https://truyenhoan.com/tim-kiem/?tukhoa=kiem+khach"
    source, _ = make_source({url: load("search.html")})

    results = await source.search("kiem khach")

    assert [r.title for r in results] == ["Kiếm Khách Vô Danh", "Kiếm Khách Giữa Phố"]
    assert results[0].author == "Mộng Trung Nhân"
    assert results[0].url == NOVEL_URL
    # Relative href normalised.
    assert results[1].url == "https://truyenhoan.com/kiem-khach-giua-pho.27182/"


async def test_search_respects_limit():
    url = "https://truyenhoan.com/tim-kiem/?tukhoa=kiem+khach"
    source, _ = make_source({url: load("search.html")})

    assert len(await source.search("kiem khach", limit=1)) == 1
