"""Shared adapter for Chinese raw novel sites.

These sites differ from the Vietnamese ones in two ways that matter:

* Chapter URLs carry database ids (``/book/27265/17948862.html``), not chapter
  numbers, so the number has to come from the title (``第12章``).
* The chapter list is usually one long page with no pagination, and the newest
  chapter is repeated at the top as a promo, which would otherwise be counted
  twice.

Subclasses supply the site's URL shapes and selectors; the parsing lives here.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from app.core.logging import get_logger
from app.db.models import Lang, NovelStatus
from app.sources.base import ChapterRef, NovelInfo, NovelRef, Source, SourceError
from app.sources.text import clean_container, normalise
from app.sources.zh_text import parse_chapter_number

log = get_logger(__name__)

_STATUS_MARKERS = (
    # (substring, status) — checked in order, first match wins.
    ("已完結", NovelStatus.completed),
    ("已完结", NovelStatus.completed),
    ("完結", NovelStatus.completed),
    ("完结", NovelStatus.completed),
    ("全本", NovelStatus.completed),
    ("連載", NovelStatus.ongoing),
    ("连载", NovelStatus.ongoing),
)

_AUTHOR_PREFIX = re.compile(r"^\s*(?:作\s*者|作者)\s*[:：]?\s*")


class ChineseNovelSource(Source):
    """Base class for Chinese raw sites."""

    lang = Lang.zh

    #: Site root, no trailing slash.
    base: str = ""
    #: Must capture a ``slug`` group identifying the novel.
    novel_re: re.Pattern[str]
    #: Must capture ``slug``; the chapter's own id is whatever follows.
    chapter_re: re.Pattern[str]

    # --- selectors (override per site) -------------------------------------

    title_selectors: str = "h1, .booktitle, span.title"
    author_selectors: str = (
        "meta[property='og:novel:author'], .author, .book .author, #info p"
    )
    description_selectors: str = ".description, .intro, #intro, .book-intro"
    status_selectors: str = ".state, .book, #info, .novel-detail"
    cover_selectors: str = "meta[property='og:image'], .book img, .cover img, #fmimg img"
    chapter_container_selectors: str = (
        "dl.chapterlist, ul.chapter-list, #list, .listmain, #chapterlist"
    )
    body_selectors: str = "#content, .content, #chaptercontent, .showtxt"
    search_template: str | None = None

    # --- url handling ------------------------------------------------------

    def build_novel_url(self, match: re.Match[str]) -> str:
        raise NotImplementedError

    def canonical_url(self, url: str) -> str:
        parts = urlsplit(url)
        path = parts.path

        chapter = self.chapter_re.match(path)
        if chapter:
            # Keep chapter URLs as given; they cannot be rewritten into a
            # novel URL, and novel_url_from_chapter reads the real link.
            return f"{self.base}{path}"

        match = self.novel_re.match(path if path.endswith("/") else path + "/")
        if match is None:
            match = self.novel_re.match(path)
        if match:
            return self.build_novel_url(match)

        raise SourceError(f"Not a recognised {self.key} URL", url=url)

    def is_chapter_url(self, url: str) -> bool:
        return bool(self.chapter_re.match(urlsplit(url).path))

    async def novel_url_from_chapter(self, url: str) -> str:
        """Rebuild the novel URL from the slug in the chapter path."""
        match = self.chapter_re.match(urlsplit(url).path)
        if match is None:
            raise SourceError("Not a chapter URL", url=url)
        return f"{self.base}/{self._novel_path_for(match['slug'])}"

    def _novel_path_for(self, slug: str) -> str:
        """Path (no leading slash) of the novel page for ``slug``."""
        raise NotImplementedError

    # --- novel -------------------------------------------------------------

    async def novel_info(self, url: str) -> NovelInfo:
        url = self.canonical_url(url)
        soup = BeautifulSoup(await self._get(url), "lxml")

        title = self._text(soup.select_one(self.title_selectors))
        if not title:
            raise SourceError("No novel title found; layout may have changed", url=url)

        return NovelInfo(
            title=title,
            url=url,
            author=self._author(soup),
            cover_url=self._cover(soup),
            description=self._description(soup),
            genres=self._genres(soup),
            status=self._status(soup),
            lang=self.lang,
        )

    def _author(self, soup: BeautifulSoup) -> str | None:
        element = soup.select_one(self.author_selectors)
        if element is None:
            return None
        raw = (
            element.get("content")
            if element.name == "meta"
            else element.get_text(" ", strip=True)
        )
        if not raw:
            return None
        # Sites write it as "作者: 名字" or "作者：名字".
        return _AUTHOR_PREFIX.sub("", raw).strip() or None

    def _description(self, soup: BeautifulSoup) -> str | None:
        element = soup.select_one(self.description_selectors)
        if element is None:
            return None
        return normalise(element.get_text("\n")) or None

    def _genres(self, soup: BeautifulSoup) -> list[str]:
        tags = soup.select("meta[property='og:novel:category']")
        return [value for tag in tags if (value := (tag.get("content") or "").strip())]

    def _status(self, soup: BeautifulSoup) -> NovelStatus:
        element = soup.select_one(self.status_selectors)
        if element is None:
            return NovelStatus.unknown
        text = element.get_text(" ", strip=True)
        for marker, status in _STATUS_MARKERS:
            if marker in text:
                return status
        return NovelStatus.unknown

    def _cover(self, soup: BeautifulSoup) -> str | None:
        element = soup.select_one(self.cover_selectors)
        if element is None:
            return None
        raw = element.get("content") if element.name == "meta" else (
            element.get("src") or element.get("data-src")
        )
        return urljoin(self.base, raw.strip()) if raw else None

    # --- chapters ----------------------------------------------------------

    async def chapter_list(self, url: str) -> list[ChapterRef]:
        url = self.canonical_url(url)
        soup = BeautifulSoup(await self._get(url), "lxml")
        slug = self._slug_of(url)

        container = soup.select_one(self.chapter_container_selectors)
        if container is None:
            raise SourceError("No chapter list found; layout may have changed", url=url)

        seen: dict[str, ChapterRef] = {}
        ordered: list[tuple[str, str]] = []

        for link in container.select("a[href]"):
            href = urljoin(url, link["href"])
            match = self.chapter_re.match(urlsplit(href).path)
            if match is None or match["slug"] != slug:
                continue
            title = self._text(link)
            if not title:
                continue
            # The newest chapter is repeated at the top of these pages; keep
            # the occurrence that sits in reading order, which is the later one.
            if href in seen:
                ordered = [(h, t) for h, t in ordered if h != href]
            seen[href] = ChapterRef(number=0, title=title, url=href)
            ordered.append((href, title))

        if not ordered:
            raise SourceError("Chapter list is empty; layout may have changed", url=url)

        return self._number_chapters(ordered)

    def _number_chapters(self, ordered: list[tuple[str, str]]) -> list[ChapterRef]:
        """Assign chapter numbers, preferring the number in each title.

        Done in two passes on purpose. Front matter like 新書感言 carries no
        number, and if it were numbered as it was encountered it would take
        the number 1 and push the real 第1章 to 2 — shifting the whole book.
        So every title-derived number is reserved first, and only then are the
        gaps filled.
        """
        numbers: list[int | None] = [parse_chapter_number(title) for _, title in ordered]

        used: set[int] = set()
        for index, number in enumerate(numbers):
            if number is None or number in used:
                # A repeated number cannot be trusted either; treat it as
                # unnumbered and let the second pass place it.
                numbers[index] = None
                continue
            used.add(number)

        for index, number in enumerate(numbers):
            if number is not None:
                continue
            numbers[index] = self._free_number_for(index, numbers, used)
            used.add(numbers[index])

        refs = [
            ChapterRef(number=number, title=title, url=href)
            for (href, title), number in zip(ordered, numbers, strict=True)
        ]
        unnumbered = sum(1 for _, title in ordered if parse_chapter_number(title) is None)
        if unnumbered:
            log.debug("%d/%d chapters had no number in the title", unnumbered, len(ordered))

        refs.sort(key=lambda ref: ref.number)
        return refs

    @staticmethod
    def _free_number_for(
        index: int, numbers: list[int | None], used: set[int]
    ) -> int:
        """Pick a free number for a chapter whose title carries none.

        Takes the slot immediately before the next numbered chapter when it is
        free, which puts a preface at 0 — the same number these sites give it
        themselves (第0章). That slot is tried *once*: searching downwards for
        any free number would fling a duplicate mid-book title to the front of
        the novel, which is worse than appending it at the end.
        """
        following = next((n for n in numbers[index + 1 :] if n is not None), None)
        if following is not None and following - 1 >= 0 and following - 1 not in used:
            return following - 1

        candidate = max(used, default=0) + 1
        while candidate in used:
            candidate += 1
        return candidate

    def _slug_of(self, novel_url: str) -> str:
        path = urlsplit(novel_url).path
        match = self.novel_re.match(path if path.endswith("/") else path + "/")
        if match is None:
            match = self.novel_re.match(path)
        if match is None:  # pragma: no cover - callers pass canonical URLs
            raise SourceError("Not a novel URL", url=novel_url)
        return match["slug"]

    # --- chapter content ---------------------------------------------------

    async def chapter_content(self, url: str) -> str:
        soup = BeautifulSoup(await self._get(url), "lxml")

        container = soup.select_one(self.body_selectors)
        if container is None:
            raise SourceError("No chapter body found; layout may have changed", url=url)

        return clean_container(container)

    # --- search ------------------------------------------------------------

    async def search(self, query: str, *, limit: int = 20) -> list[NovelRef]:
        if not self.search_template:
            raise NotImplementedError(f"{self.key} does not support search")

        url = self.search_template.format(query=query)
        soup = BeautifulSoup(await self._get(url), "lxml")

        results: list[NovelRef] = []
        for link in soup.select("a[href]"):
            href = urljoin(self.base, link["href"])
            if self.novel_re.match(urlsplit(href).path + "/") is None and (
                self.novel_re.match(urlsplit(href).path) is None
            ):
                continue
            title = self._text(link)
            if not title or len(title) > 60:
                continue
            canonical = self.canonical_url(href)
            if any(existing.url == canonical for existing in results):
                continue
            results.append(NovelRef(title=title, url=canonical))
            if len(results) >= limit:
                break
        return results

    # --- helpers -----------------------------------------------------------

    @staticmethod
    def _text(element: Tag | None) -> str:
        if element is None:
            return ""
        if element.name == "meta":
            return (element.get("content") or "").strip()
        return " ".join(element.get_text(" ", strip=True).split())
