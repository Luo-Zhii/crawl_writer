"""The uukanshu adapter and the shared Chinese base class.

Covers what makes Chinese raw sites different from the Vietnamese ones:
database-id chapter URLs, numbers parsed from titles, a duplicated "newest
chapter" promo at the top of the list, and front matter with no number.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.db.models import Lang, NovelStatus
from app.fetch.base import Response
from app.sources.base import SourceError
from app.sources.uukanshu import UuKanShu

FIXTURES = Path(__file__).parent / "fixtures" / "uukanshu"

NOVEL_URL = "https://uukanshu.cc/book/99001/"
CHAPTER_URL = "https://uukanshu.cc/book/99001/55500010.html"


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


def make_source(routes: dict[str, str]) -> tuple[UuKanShu, FakeFetcher]:
    fetcher = FakeFetcher(routes)
    return UuKanShu(fetcher), fetcher


# --- url handling ----------------------------------------------------------


def test_handles_its_domain():
    assert UuKanShu.handles(NOVEL_URL)
    assert UuKanShu.handles("https://www.uukanshu.cc/book/1/")
    assert not UuKanShu.handles("https://czbooks.net/n/abc")


@pytest.mark.parametrize(
    "given",
    [NOVEL_URL, "https://uukanshu.cc/book/99001", "https://www.uukanshu.cc/book/99001/"],
)
def test_canonical_url_normalises_novel_urls(given: str):
    source, _ = make_source({})

    assert source.canonical_url(given) == NOVEL_URL


def test_canonical_url_keeps_chapter_urls():
    source, _ = make_source({})

    assert source.canonical_url(CHAPTER_URL) == CHAPTER_URL


def test_unrelated_paths_are_rejected():
    source, _ = make_source({})

    with pytest.raises(SourceError):
        source.canonical_url("https://uukanshu.cc/quanben/")


def test_is_chapter_url():
    source, _ = make_source({})

    assert source.is_chapter_url(CHAPTER_URL)
    assert not source.is_chapter_url(NOVEL_URL)


async def test_novel_url_is_rebuilt_from_the_chapter_path():
    """The slug is in the chapter URL, so no extra request is needed."""
    source, fetcher = make_source({})

    assert await source.novel_url_from_chapter(CHAPTER_URL) == NOVEL_URL
    assert fetcher.requested == [], "rebuilding the URL should not fetch anything"


# --- novel info ------------------------------------------------------------


async def test_novel_info_fields():
    source, _ = make_source({NOVEL_URL: load("novel.html")})

    info = await source.novel_info(NOVEL_URL)

    assert info.title == "雲端劍客"
    assert info.author == "無名氏"
    assert info.genres == ["玄幻奇幻"]
    assert info.lang is Lang.zh
    assert info.url == NOVEL_URL


async def test_status_is_read_from_the_chinese_label():
    source, _ = make_source({NOVEL_URL: load("novel.html")})

    info = await source.novel_info(NOVEL_URL)

    assert info.status is NovelStatus.ongoing


async def test_cover_url_is_made_absolute():
    """The site uses a protocol-relative image URL."""
    source, _ = make_source({NOVEL_URL: load("novel.html")})

    info = await source.novel_info(NOVEL_URL)

    assert info.cover_url == "https://image.uukanshu.cc/99/99001/99001s.jpg"


async def test_description_is_clean_text():
    source, _ = make_source({NOVEL_URL: load("novel.html")})

    info = await source.novel_info(NOVEL_URL)

    assert info.description
    assert "斷劍" in info.description


async def test_missing_title_is_reported_as_a_layout_problem():
    source, _ = make_source({NOVEL_URL: load("missing.html")})

    with pytest.raises(SourceError, match="No novel title"):
        await source.novel_info(NOVEL_URL)


# --- chapter list ----------------------------------------------------------


async def test_chapter_numbers_come_from_the_titles():
    """URLs hold database ids, so the title is the only usable source."""
    source, _ = make_source({NOVEL_URL: load("novel.html")})

    chapters = await source.chapter_list(NOVEL_URL)
    by_number = {c.number: c.title for c in chapters}

    assert by_number[1] == "第1章 雲端之上"
    assert by_number[2] == "第二章 拾劍", "Chinese numerals must work too"
    assert by_number[3] == "第3章 斷劍重鑄"


async def test_duplicated_newest_chapter_promo_is_collapsed():
    source, _ = make_source({NOVEL_URL: load("novel.html")})

    chapters = await source.chapter_list(NOVEL_URL)

    urls = [c.url for c in chapters]
    assert len(urls) == len(set(urls))
    assert sum(1 for c in chapters if c.title == "第3章 斷劍重鑄") == 1


async def test_front_matter_without_a_number_still_gets_one():
    """"新書感言" has no 第N章, but it is a real page and must be fetchable."""
    source, _ = make_source({NOVEL_URL: load("novel.html")})

    chapters = await source.chapter_list(NOVEL_URL)
    titles = [c.title for c in chapters]

    assert "新書感言" in titles
    numbers = [c.number for c in chapters]
    assert len(numbers) == len(set(numbers)), "numbers must stay unique"


async def test_chapters_are_sorted_by_number():
    source, _ = make_source({NOVEL_URL: load("novel.html")})

    numbers = [c.number for c in await source.chapter_list(NOVEL_URL)]

    assert numbers == sorted(numbers)


async def test_links_to_other_novels_are_ignored():
    source, _ = make_source({NOVEL_URL: load("novel.html")})

    chapters = await source.chapter_list(NOVEL_URL)

    assert all("/book/99001/" in c.url for c in chapters)


async def test_missing_chapter_list_is_reported():
    source, _ = make_source({NOVEL_URL: load("missing.html")})

    with pytest.raises(SourceError, match="No chapter list"):
        await source.chapter_list(NOVEL_URL)


# --- chapter content -------------------------------------------------------


async def test_chapter_content_is_clean_prose():
    source, _ = make_source({CHAPTER_URL: load("chapter.html")})

    text = await source.chapter_content(CHAPTER_URL)

    assert "雲層很厚" in text
    assert "\n\n" in text


async def test_chapter_content_strips_site_furniture():
    source, _ = make_source({CHAPTER_URL: load("chapter.html")})

    text = await source.chapter_content(CHAPTER_URL)

    assert "廣告" not in text
    assert "uukanshu.cc" not in text
    assert "分享" not in text
    assert "var ad" not in text
    assert "\u200b" not in text
