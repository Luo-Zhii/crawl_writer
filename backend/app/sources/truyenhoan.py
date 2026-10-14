"""Adapter for truyenhoan.com.

Markup layout (verified live): a novel lives at ``/<slug>.<id>/`` with the
chapter list paginated under ``/<slug>.<id>/trang-N/``, while chapters sit at
``/<slug>/chuong-N.html`` — note the chapter path drops the numeric id, so the
two URL shapes have to be handled separately.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from app.core.logging import get_logger
from app.db.models import Lang, NovelStatus
from app.sources.base import ChapterRef, NovelInfo, NovelRef, Source, SourceError
from app.sources.registry import register
from app.sources.text import clean_container, clean_title, normalise

log = get_logger(__name__)

BASE = "https://truyenhoan.com"

# /ten-truyen.12345/ and optionally /trang-2/
_NOVEL_PATH = re.compile(r"^/(?P<slug>[^/]+?)\.(?P<id>\d+)/?(?:trang-\d+/?)?$")
# /ten-truyen/chuong-12.html
_CHAPTER_PATH = re.compile(r"^/(?P<slug>[^/]+?)/chuong-(?P<number>\d+)\.html$")
_PAGE_IN_URL = re.compile(r"/trang-(\d+)/?")

_STATUS_MAP = {
    "đang ra": NovelStatus.ongoing,
    "full": NovelStatus.completed,
    "hoàn thành": NovelStatus.completed,
    "hoàn": NovelStatus.completed,
    "tạm dừng": NovelStatus.ongoing,
    "drop": NovelStatus.ongoing,
}


@register
class TruyenHoan(Source):
    key = "truyenhoan"
    name = "Truyện Hoàn"
    domains = ("truyenhoan.com", "truyenfull.tv")
    lang = Lang.vi
    needs_browser = False

    # --- urls --------------------------------------------------------------

    def canonical_url(self, url: str) -> str:
        """Reduce any novel or chapter URL to the novel's main page.

        A chapter URL has no numeric id, so we cannot rebuild the novel URL
        from it directly; the novel page link is read off the chapter page by
        :meth:`novel_url_from_chapter`.
        """
        parts = urlsplit(url)
        path = parts.path if parts.path.endswith("/") else parts.path + "/"

        match = _NOVEL_PATH.match(path)
        if match:
            return f"{BASE}/{match['slug']}.{match['id']}/"

        if _CHAPTER_PATH.match(parts.path):
            return url.split("?")[0]

        raise SourceError("Not a recognised truyenhoan URL", url=url)

    def is_chapter_url(self, url: str) -> bool:
        return bool(_CHAPTER_PATH.match(urlsplit(url).path))

    async def novel_url_from_chapter(self, url: str) -> str:
        """Follow a chapter page back to its novel page."""
        soup = BeautifulSoup(await self._get(url), "lxml")
        link = soup.select_one("a.truyen-title, .truyen-title a, h1.title a")
        if link and link.get("href"):
            return self.canonical_url(urljoin(BASE, link["href"]))
        raise SourceError("Could not find the novel link on this chapter page", url=url)

    # --- search ------------------------------------------------------------

    async def search(self, query: str, *, limit: int = 20) -> list[NovelRef]:
        url = f"{BASE}/tim-kiem/?tukhoa={query.replace(' ', '+')}"
        soup = BeautifulSoup(await self._get(url), "lxml")

        results: list[NovelRef] = []
        for row in soup.select("div.list-truyen div.row, div.list.list-truyen div.row"):
            link = row.select_one("h3.truyen-title a, h3 a")
            if link is None or not link.get("href"):
                continue
            author = row.select_one("span.author, .author")
            image = row.select_one("div.lazyimg, img")
            results.append(
                NovelRef(
                    title=clean_title(link.get_text(" ", strip=True)),
                    url=self.canonical_url(urljoin(BASE, link["href"])),
                    author=author.get_text(" ", strip=True) if author else None,
                    cover_url=_image_src(image),
                )
            )
            if len(results) >= limit:
                break
        return results

    # --- novel -------------------------------------------------------------

    async def novel_info(self, url: str) -> NovelInfo:
        url = self.canonical_url(url)
        soup = BeautifulSoup(await self._get(url), "lxml")

        title_el = soup.select_one("h1.title, h3.title")
        if title_el is None:
            # Either the layout changed or we were redirected to the homepage,
            # which is what this site does for an unknown novel id.
            raise SourceError("No novel title found; layout may have changed", url=url)

        info = soup.select_one("div.info, div.info-holder div.info")
        cover = soup.select_one("div.book img, div.books img, div.book-img img")

        description = None
        desc_el = soup.select_one("div.desc-text, div.desc")
        if desc_el is not None:
            description = normalise(desc_el.get_text("\n")) or None

        return NovelInfo(
            title=clean_title(title_el.get_text(" ", strip=True)),
            url=url,
            author=_labelled_links(info, "tác giả") or _labelled_text(info, "tác giả"),
            cover_url=_absolute(_image_src(cover)),
            description=description,
            genres=_labelled_list(info, "thể loại"),
            status=_parse_status(_labelled_text(info, "trạng thái")),
            lang=self.lang,
        )

    async def chapter_list(self, url: str) -> list[ChapterRef]:
        """Collect every chapter, walking the pagination.

        Numbers come from the URL rather than a running counter: a missing
        chapter on the site would otherwise silently shift every number after
        it, and resume would then overwrite the wrong files.
        """
        url = self.canonical_url(url)
        slug = _slug_of(url)
        first = BeautifulSoup(await self._get(url), "lxml")

        chapters: dict[int, ChapterRef] = {}
        self._collect_chapters(first, chapters, slug)

        last_page = _last_page(first)
        for page in range(2, last_page + 1):
            page_url = f"{url}trang-{page}/"
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
        for link in soup.select("div#list-chapter a[href], ul.list-chapter a[href]"):
            href = urljoin(BASE, link["href"])
            match = _CHAPTER_PATH.match(urlsplit(href).path)
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

    # --- chapter -----------------------------------------------------------

    async def chapter_content(self, url: str) -> str:
        soup = BeautifulSoup(await self._get(url), "lxml")

        container = soup.select_one("div#chapter-c, div.chapter-c")
        if container is None:
            raise SourceError("No chapter body found; layout may have changed", url=url)

        return clean_container(container)


# --- helpers ---------------------------------------------------------------


def _info_row(info: Tag | None, label: str) -> Tag | None:
    """Find the ``div`` in the info block whose heading matches ``label``.

    The rows carry no classes, so the heading text is the only anchor.
    """
    if info is None:
        return None
    for row in info.find_all("div"):
        heading = row.find("h3")
        if heading and label in heading.get_text(" ", strip=True).lower():
            return row
    return None


def _labelled_links(info: Tag | None, label: str) -> str | None:
    row = _info_row(info, label)
    if row is None:
        return None
    names = [a.get_text(" ", strip=True) for a in row.find_all("a")]
    return ", ".join(n for n in names if n) or None


def _labelled_list(info: Tag | None, label: str) -> list[str]:
    row = _info_row(info, label)
    if row is None:
        return []
    return [a.get_text(" ", strip=True) for a in row.find_all("a") if a.get_text(strip=True)]


def _labelled_text(info: Tag | None, label: str) -> str | None:
    """Value of a row that has no link, e.g. the status."""
    row = _info_row(info, label)
    if row is None:
        return None
    heading = row.find("h3")
    text = row.get_text(" ", strip=True)
    if heading:
        text = text.replace(heading.get_text(" ", strip=True), "", 1)
    return text.strip(" :") or None


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


def _absolute(url: str | None) -> str | None:
    return urljoin(BASE, url) if url else None


def _slug_of(novel_url: str) -> str:
    match = _NOVEL_PATH.match(urlsplit(novel_url).path)
    if match is None:  # pragma: no cover - callers pass canonical URLs
        raise SourceError("Not a novel URL", url=novel_url)
    return match["slug"]


def _last_page(soup: BeautifulSoup) -> int:
    """Highest page number in the chapter-list pagination."""
    pages = [1]
    for link in soup.select("ul.pagination a[href], div.pagination a[href]"):
        match = _PAGE_IN_URL.search(link["href"])
        if match:
            pages.append(int(match.group(1)))
    return max(pages)
