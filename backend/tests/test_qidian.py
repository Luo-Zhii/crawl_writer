"""The Qidian adapter.

Qidian differs from the other Chinese sites in this project: there is no markup
to select against, the data arrives as JSON, and most of the book is behind a
paywall that still answers 200. The tests here are mostly about the paywall,
because getting that wrong means either skipping readable chapters or storing
teasers as if they were chapters.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.db.models import Lang, NovelStatus
from app.fetch.base import Response
from app.sources.base import ChapterLocked, SourceError
from app.sources.qidian import Qidian

FIXTURES = Path(__file__).parent / "fixtures" / "qidian"

NOVEL_URL = "https://m.qidian.com/book/99001/"
CATALOG_URL = "https://m.qidian.com/book/99001/catalog/"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def chapter_url(chapter_id: int) -> str:
    return f"https://m.qidian.com/chapter/99001/{chapter_id}/"


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


def make_source(routes: dict[str, str]) -> tuple[Qidian, FakeFetcher]:
    fetcher = FakeFetcher(routes)
    return Qidian(fetcher), fetcher


# --- url handling ----------------------------------------------------------


def test_handles_its_domain():
    assert Qidian.handles(NOVEL_URL)
    assert Qidian.handles("https://www.qidian.com/book/99001/")
    assert not Qidian.handles("https://uukanshu.cc/book/1/")


@pytest.mark.parametrize(
    "given",
    [
        NOVEL_URL,
        "https://m.qidian.com/book/99001",
        "https://www.qidian.com/book/99001/",
    ],
)
def test_canonical_url_normalises_to_the_mobile_host(given: str):
    """Desktop URLs are rewritten: only the mobile host answers requests."""
    source, _ = make_source({})
    assert source.canonical_url(given) == NOVEL_URL


def test_canonical_url_normalises_the_chapter_redirect():
    """``/book/<id>/<chapterId>/`` 301s to ``/chapter/...``; skip the hop."""
    source, _ = make_source({})
    assert (
        source.canonical_url("https://m.qidian.com/book/99001/55500001/")
        == chapter_url(55500001)
    )


def test_canonical_url_rejects_a_foreign_path():
    source, _ = make_source({})
    with pytest.raises(SourceError):
        source.canonical_url("https://m.qidian.com/rank/yuepiao/")


def test_chapter_urls_are_recognised():
    source, _ = make_source({})
    assert source.is_chapter_url(chapter_url(55500001))
    assert source.is_chapter_url("https://m.qidian.com/book/99001/55500001/")
    assert not source.is_chapter_url(NOVEL_URL)


@pytest.mark.asyncio
async def test_novel_url_is_recovered_from_a_chapter_url():
    source, _ = make_source({})
    assert await source.novel_url_from_chapter(chapter_url(55500001)) == NOVEL_URL


# --- novel info ------------------------------------------------------------


@pytest.mark.asyncio
async def test_novel_info_comes_out_of_the_json_payload():
    source, _ = make_source({NOVEL_URL: load("novel.html")})

    info = await source.novel_info(NOVEL_URL)

    assert info.title == "测试书名"
    assert info.author == "测试作者"
    assert info.lang is Lang.zh
    assert info.status is NovelStatus.ongoing
    assert info.description.startswith("这是一段为测试写的简介")
    assert info.url == NOVEL_URL


@pytest.mark.asyncio
async def test_genres_combine_channel_subcategory_and_tag():
    source, _ = make_source({NOVEL_URL: load("novel.html")})

    info = await source.novel_info(NOVEL_URL)

    assert info.genres == ["玄幻", "东方玄幻", "热血"]


@pytest.mark.asyncio
async def test_cover_is_built_from_the_book_id():
    """The page only references resized variants; the CDN path is stabler."""
    source, _ = make_source({NOVEL_URL: load("novel.html")})

    info = await source.novel_info(NOVEL_URL)

    assert info.cover_url.endswith("/99001/600.webp")


@pytest.mark.asyncio
async def test_a_gated_response_says_so_instead_of_crashing():
    """The desktop host returns a shell with no payload."""
    source, _ = make_source({NOVEL_URL: load("blocked.html")})

    with pytest.raises(SourceError, match="blocked this request|page format"):
        await source.novel_info(NOVEL_URL)


@pytest.mark.asyncio
async def test_an_unknown_book_id_is_reported():
    """An unknown id returns a payload whose pageData is null."""
    source, _ = make_source({NOVEL_URL: load("notfound.html")})

    with pytest.raises(SourceError, match="payload is empty"):
        await source.novel_info(NOVEL_URL)


@pytest.mark.asyncio
async def test_the_error_message_field_is_ignored():
    """Qidian sets errorMsg to "!undefined" on working pages too.

    Treating it as an error signal would reject every single page.
    """
    html = load("novel.html").replace('"errorMsg": ""', '"errorMsg": "!undefined"')
    source, _ = make_source({NOVEL_URL: html})

    info = await source.novel_info(NOVEL_URL)

    assert info.title == "测试书名"


# --- chapter list ----------------------------------------------------------


@pytest.mark.asyncio
async def test_chapter_list_reads_the_catalog_page():
    source, fetcher = make_source(
        {NOVEL_URL: load("novel.html"), CATALOG_URL: load("catalog.html")}
    )

    refs = await source.chapter_list(NOVEL_URL)

    assert CATALOG_URL in fetcher.requested
    assert [ref.title for ref in refs] == [
        "第一章 开端",
        "第二章 启程",
        "第三章 山路",
        "作者的话",
    ]


@pytest.mark.asyncio
async def test_paid_chapters_are_left_out_entirely():
    """Fetching them would spend a request to collect a teaser."""
    source, _ = make_source({CATALOG_URL: load("catalog.html")})

    refs = await source.chapter_list(NOVEL_URL)

    urls = [ref.url for ref in refs]
    assert chapter_url(55500004) not in urls
    assert chapter_url(55500005) not in urls


@pytest.mark.asyncio
async def test_a_free_chapter_inside_a_paid_volume_is_kept():
    """Author notes stay free even in a volume that is otherwise paid."""
    source, _ = make_source({CATALOG_URL: load("catalog.html")})

    refs = await source.chapter_list(NOVEL_URL)

    assert chapter_url(55500006) in [ref.url for ref in refs]


@pytest.mark.asyncio
async def test_numbering_follows_catalog_position_not_the_title():
    """Volume two restarts at 第一章, so titles alone would collide."""
    source, _ = make_source({CATALOG_URL: load("catalog.html")})

    refs = await source.chapter_list(NOVEL_URL)

    by_title = {ref.title: ref.number for ref in refs}
    assert by_title["第一章 开端"] == 1
    assert by_title["第三章 山路"] == 3
    # Sixth in the catalogue even though chapters 4 and 5 were skipped.
    assert by_title["作者的话"] == 6


@pytest.mark.asyncio
async def test_skipped_chapters_do_not_renumber_the_rest():
    """Numbers must stay stable, or a resume would redownload everything."""
    source, _ = make_source({CATALOG_URL: load("catalog.html")})

    refs = await source.chapter_list(NOVEL_URL)

    assert [ref.number for ref in refs] == [1, 2, 3, 6]


@pytest.mark.asyncio
async def test_volume_names_are_carried_through():
    source, _ = make_source({CATALOG_URL: load("catalog.html")})

    refs = await source.chapter_list(NOVEL_URL)

    assert refs[0].volume == "第一卷 免费卷"
    assert refs[-1].volume == "第二卷 付费卷"


@pytest.mark.asyncio
async def test_a_fully_paid_book_fails_with_a_clear_reason():
    catalog = load("catalog.html").replace('"sS": 1', '"sS": 0')
    source, _ = make_source({CATALOG_URL: catalog})

    with pytest.raises(SourceError, match="No free chapters"):
        await source.chapter_list(NOVEL_URL)


@pytest.mark.asyncio
async def test_a_catalog_without_volumes_is_an_error():
    source, _ = make_source({CATALOG_URL: load("catalog.html").replace('"vs"', '"vz"')})

    with pytest.raises(SourceError, match="no volumes"):
        await source.chapter_list(NOVEL_URL)


@pytest.mark.asyncio
async def test_an_entry_missing_the_readable_flag_is_kept():
    """If Qidian renames the field, skip nothing and let the fetch decide."""
    catalog = load("catalog.html").replace('"sS"', '"xx"')
    source, _ = make_source({CATALOG_URL: catalog})

    refs = await source.chapter_list(NOVEL_URL)

    assert len(refs) == 6


# --- chapter content -------------------------------------------------------


@pytest.mark.asyncio
async def test_a_free_chapter_returns_clean_paragraphs():
    url = chapter_url(55500001)
    source, _ = make_source({url: load("chapter_free.html")})

    text = await source.chapter_content(url)

    assert "这是一段为测试写的占位文字" in text
    # Paragraphs separated by a blank line, promo block stripped: the JSON
    # body still goes through the shared HTML cleaner.
    assert "\n\n" in text
    assert "推广横幅" not in text


@pytest.mark.asyncio
async def test_a_paid_chapter_is_reported_as_locked():
    url = chapter_url(55500004)
    source, _ = make_source({url: load("chapter_paid.html")})

    with pytest.raises(ChapterLocked):
        await source.chapter_content(url)


@pytest.mark.asyncio
async def test_a_bought_chapter_is_returned():
    url = chapter_url(55500005)
    source, _ = make_source({url: load("chapter_bought.html")})

    text = await source.chapter_content(url)

    assert "这一章已经购买过" in text


@pytest.mark.asyncio
async def test_a_teaser_is_caught_even_when_the_vip_flags_say_free():
    """200 plus parseable JSON is not proof we got the chapter."""
    html = load("chapter_paid.html").replace('"vipStatus": 1', '"vipStatus": 0')
    url = chapter_url(55500004)
    source, _ = make_source({url: html})

    with pytest.raises(ChapterLocked, match="teaser"):
        await source.chapter_content(url)


@pytest.mark.asyncio
async def test_font_obfuscated_text_is_refused():
    """Saving it would store convincing nonsense."""
    url = chapter_url(55500006)
    source, _ = make_source({url: load("chapter_font.html")})

    with pytest.raises(SourceError, match="custom font"):
        await source.chapter_content(url)


@pytest.mark.asyncio
async def test_an_empty_body_is_an_error():
    html = load("chapter_free.html").replace('"content": "<p>', '"content": "", "unused": "<p>')
    url = chapter_url(55500001)
    source, _ = make_source({url: html})

    with pytest.raises(SourceError, match="empty"):
        await source.chapter_content(url)


@pytest.mark.asyncio
async def test_a_chapter_url_in_book_form_is_fetched_from_the_canonical_url():
    """The adapter should not follow the site's 301 on every chapter."""
    url = chapter_url(55500001)
    source, fetcher = make_source({url: load("chapter_free.html")})

    await source.chapter_content("https://m.qidian.com/book/99001/55500001/")

    assert fetcher.requested == [url]
