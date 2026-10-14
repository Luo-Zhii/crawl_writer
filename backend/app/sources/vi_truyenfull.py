"""Shared adapter for the "truyenfull" layout.

Several Vietnamese convert sites run the same Bootstrap-era template: an
``h1`` title, a classless ``div.info`` whose rows are labelled by ``h3`` text,
``div.desc-text`` for the blurb, chapters in ``#list-chapter ul.list-chapter``
paginated with ``ul.pagination``, and the chapter body in ``#chapter-c``.

Only the URL shapes differ between them, so subclasses supply those and
inherit the parsing. Keeping one copy of the selectors means a template change
is fixed once rather than per site.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from app.core.logging import get_logger
from app.db.models import Lang, NovelStatus
from app.sources.base import ChapterRef, NovelInfo, NovelRef, Source, SourceError
from app.sources.text import clean_container, clean_title, normalise

log = get_logger(__name__)

_STATUS_MAP = {
    "đang ra": NovelStatus.ongoing,
    "full": NovelStatus.completed,
    "hoàn thành": NovelStatus.completed,
    "hoàn": NovelStatus.completed,
    "tạm dừng": NovelStatus.ongoing,
    "drop": NovelStatus.ongoing,
}

_PAGE_IN_URL = re.compile(r"/trang-(\d+)/?")

_TITLE_SELECTORS = "h1.title, h3.title, h1"
_INFO_SELECTORS = "div.info, div.info-holder div.info"
_COVER_SELECTORS = "div.book img, div.books img, div.book-img img, div.thumb img"
_DESC_SELECTORS = "div.desc-text, div.desc"
_CHAPTER_LINK_SELECTORS = "div#list-chapter a[href], ul.list-chapter a[href]"
_BODY_SELECTORS = "div#chapter-c, div.chapter-c"
_NOVEL_BACKLINK_SELECTORS = "a.truyen-title, .truyen-title a, h1.title a"


class TruyenFullFamily(Source):
    """Base class for sites using the truyenfull template."""

    lang = Lang.vi

    #: Site root, no trailing slash.
    base: str = ""
    #: Must capture a ``slug`` group; may also capture ``id``.
    novel_re: re.Pattern[str]
    #: Must capture ``slug`` and ``number`` groups.
    chapter_re: re.Pattern[str]
    #: Search URL with a ``{query}`` placeholder, or None when unsupported.
    search_template: str | None = None

    # --- url shapes (subclass responsibility) ------------------------------

    def build_novel_url(self, match: re.Match[str]) -> str:
        """Rebuild the canonical novel URL from a path match."""
        raise NotImplementedError

    def build_page_url(self, novel_url: str, page: int) -> str:
        """URL of page ``page`` of the chapter list."""
        return f"{novel_url}trang-{page}/"

    # --- url handling ------------------------------------------------------

    def canonical_url(self, url: str) -> str:
        parts = urlsplit(url)
        path = parts.path if parts.path.endswith("/") else parts.path + "/"

        match = self.novel_re.match(path)
        if match:
            return self.build_novel_url(match)

        if self.chapter_re.match(parts.path):
            # A chapter URL cannot be turned into a novel URL by rewriting:
            # see novel_url_from_chapter.
            return url.split("?")[0]

        raise SourceError(f"Not a recognised {self.key} URL", url=url)

    def is_chapter_url(self, url: str) -> bool:
        return bool(self.chapter_re.match(urlsplit(url).path))

    async def novel_url_from_chapter(self, url: str) -> str:
        """Follow a chapter page back to its novel page."""
        soup = BeautifulSoup(await self._get(url), "lxml")
        link = soup.select_one(_NOVEL_BACKLINK_SELECTORS)
        if link and link.get("href"):
            return self.canonical_url(urljoin(self.base, link["href"]))
        raise SourceError("Could not find the novel link on this chapter page", url=url)

    # --- search ------------------------------------------------------------

    async def search(self, query: str, *, limit: int = 20) -> list[NovelRef]:
        if not self.search_template:
            raise NotImplementedError(f"{self.key} does not support search")

        url = self.search_template.format(query=query.replace(" ", "+"))
        soup = BeautifulSoup(await self._get(url), "lxml")

        results: list[NovelRef] = []
        for row in soup.select("div.list-truyen div.row, div.list.list-truyen div.row"):
            link = row.select_one("h3.truyen-title a, h3 a")
            if link is None or not link.get("href"):
                continue
            author = row.select_one("span.author, .author")
            image = row.select_one("div.lazyimg img, img")
            results.append(
                NovelRef(
                    title=clean_title(link.get_text(" ", strip=True)),
                    url=self.canonical_url(urljoin(self.base, link["href"])),
                    author=author.get_text(" ", strip=True) if author else None,
                    cover_url=_absolute(self.base, _image_src(image)),
                )
            )
            if len(results) >= limit:
                break
        return results

    # --- novel -------------------------------------------------------------

    async def novel_info(self, url: str) -> NovelInfo:
        url = self.canonical_url(url)
        soup = BeautifulSoup(await self._get(url), "lxml")

        title_el = soup.select_one(_TITLE_SELECTORS)
        if title_el is None:
            # These sites answer an unknown novel with their homepage and
            # HTTP 200, so a missing title is the only signal.
            raise SourceError("No novel title found; layout may have changed", url=url)

        info = soup.select_one(_INFO_SELECTORS)
        cover = soup.select_one(_COVER_SELECTORS)

        description = None
        desc_el = soup.select_one(_DESC_SELECTORS)
        if desc_el is not None:
            description = normalise(desc_el.get_text("\n")) or None

        return NovelInfo(
            title=clean_title(title_el.get_text(" ", strip=True)),
            url=url,
            author=_labelled_value(info, "tác giả"),
            cover_url=_absolute(self.base, _image_src(cover)),
            description=description,
            genres=_labelled_values(info, "thể loại"),
            status=_parse_status(_labelled_text(info, "trạng thái")),
            lang=self.lang,
        )

    async def chapter_list(self, url: str) -> list[ChapterRef]:
        """Collect every chapter, walking the pagination.

        Numbers come from the URL rather than a running counter: a missing
        chapter on the site would otherwise shift every number after it, and
        resume would then overwrite the wrong files.
        """
        url = self.canonical_url(url)
        slug = self._slug_of(url)
        first = BeautifulSoup(await self._get(url), "lxml")

        chapters: dict[int, ChapterRef] = {}
        self._collect_chapters(first, chapters, slug)

        for page in range(2, _last_page(first) + 1):
            page_url = self.build_page_url(url, page)
            soup = BeautifulSoup(await self._get(page_url, referer=url), "lxml")
            before = len(chapters)
            self._collect_chapters(soup, chapters, slug)
            if len(chapters) == before:
                # Pagination claimed more pages than exist; stop rather than
                # hammering the site for empty pages.
                log.debug("no new chapters on %s, stopping pagination", page_url)
                break

        if not chapters:
            raise SourceError("Chapter list is empty; layout may have changed", url=url)

        return [chapters[number] for number in sorted(chapters)]

    def _collect_chapters(
        self, soup: BeautifulSoup, into: dict[int, ChapterRef], slug: str
    ) -> None:
        for link in soup.select(_CHAPTER_LINK_SELECTORS):
            href = urljoin(self.base, link["href"])
            match = self.chapter_re.match(urlsplit(href).path)
            if match is None:
                continue
            # The footer and sidebar reuse this markup to advertise other
            # novels, so only links under this novel's slug count.
            if match["slug"] != slug:
                continue
            number = int(match["number"])
            if number in into:
                continue
            into[number] = ChapterRef(
                number=number,
                title=_chapter_title(link, number),
                url=href,
            )

    def _slug_of(self, novel_url: str) -> str:
        match = self.novel_re.match(urlsplit(novel_url).path)
        if match is None:  # pragma: no cover - callers pass canonical URLs
            raise SourceError("Not a novel URL", url=novel_url)
        return match["slug"]

    # --- chapter -----------------------------------------------------------

    async def chapter_content(self, url: str) -> str:
        soup = BeautifulSoup(await self._get(url), "lxml")

        container = soup.select_one(_BODY_SELECTORS)
        if container is None:
            raise SourceError("No chapter body found; layout may have changed", url=url)

        return clean_container(container)


# --- helpers ---------------------------------------------------------------


def _info_row(info: Tag | None, label: str) -> Tag | None:
    """Find the row in the info block whose heading matches ``label``.

    The rows carry no classes, so the heading text is the only anchor.
    """
    if info is None:
        return None
    for row in info.find_all(["div", "li", "p"]):
        heading = row.find(["h3", "strong", "b"])
        if heading and label in heading.get_text(" ", strip=True).lower():
            return row
    return None


def _labelled_text(info: Tag | None, label: str) -> str | None:
    """The row's value with its label removed."""
    row = _info_row(info, label)
    if row is None:
        return None
    heading = row.find(["h3", "strong", "b"])
    text = row.get_text(" ", strip=True)
    if heading:
        text = text.replace(heading.get_text(" ", strip=True), "", 1)
    return text.strip(" :") or None


def _labelled_value(info: Tag | None, label: str) -> str | None:
    """Row value, preferring linked names but falling back to plain text.

    Some sites link the author, others just print the name.
    """
    row = _info_row(info, label)
    if row is None:
        return None
    names = [a.get_text(" ", strip=True) for a in row.find_all("a")]
    joined = ", ".join(n for n in names if n)
    return joined or _labelled_text(info, label)


def _labelled_values(info: Tag | None, label: str) -> list[str]:
    row = _info_row(info, label)
    if row is None:
        return []
    names = [a.get_text(" ", strip=True) for a in row.find_all("a") if a.get_text(strip=True)]
    if names:
        return names
    # Unlinked lists are comma separated.
    text = _labelled_text(info, label)
    return [part.strip() for part in text.split(",") if part.strip()] if text else []


def _parse_status(value: str | None) -> NovelStatus:
    if not value:
        return NovelStatus.unknown
    lowered = value.strip().lower()
    for needle, status in _STATUS_MAP.items():
        if needle in lowered:
            return status
    return NovelStatus.unknown


def _chapter_title(link: Tag, number: int) -> str:
    """Prefer the ``title`` attribute, which carries the full chapter name."""
    attr = (link.get("title") or "").strip()
    if attr:
        # Stored as "Novel name - Chương 12: Something".
        _, _, tail = attr.partition(" - ")
        candidate = clean_title(tail or attr)
        if candidate:
            return candidate

    text = clean_title(link.get_text(" ", strip=True))
    return text or f"Chương {number}"


def _image_src(img: Tag | None) -> str | None:
    if img is None:
        return None
    for attr in ("src", "data-src", "data-original", "data-lazy-src"):
        value = (img.get(attr) or "").strip()
        if value and not value.startswith("data:"):
            return value
    return None


def _absolute(base: str, url: str | None) -> str | None:
    return urljoin(base, url) if url else None


def _last_page(soup: BeautifulSoup) -> int:
    """Highest page number in the chapter-list pagination."""
    pages = [1]
    for link in soup.select("ul.pagination a[href], div.pagination a[href]"):
        match = _PAGE_IN_URL.search(link["href"])
        if match:
            pages.append(int(match.group(1)))
    return max(pages)
