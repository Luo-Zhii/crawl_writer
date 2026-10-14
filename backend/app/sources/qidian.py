"""Adapter for Qidian (起点中文网), free chapters only.

Qidian is different from the other Chinese sites here in three ways.

First, the desktop site is behind an anti-bot gate: ``www.qidian.com`` answers
a plain request with HTTP 202 and a ~200 byte body instead of the page. The
mobile site serves the real thing, so this adapter works entirely against
``m.qidian.com``.

Second, nothing is in the markup. The mobile site is a vite-plugin-ssr app that
ships its data as JSON inside a ``vite-plugin-ssr_pageContext`` script tag, so
there are no selectors to maintain — the parsing here is dictionary lookups.

Third, most of the book is paid. Qidian gives away the first volume and charges
for the rest, so an adapter that tried to download everything would spend
thousands of requests collecting paywall stubs. The catalogue marks what is
readable, which is used to skip those chapters without fetching them.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from app.core.logging import get_logger
from app.db.models import Lang, NovelStatus
from app.sources.base import (
    ChapterLocked,
    ChapterRef,
    NovelInfo,
    NovelRef,
    Source,
    SourceError,
)
from app.sources.registry import register
from app.sources.text import clean_container, normalise

log = get_logger(__name__)

BASE = "https://m.qidian.com"

#: The JSON blob the mobile app renders its pages from.
_PAGE_CONTEXT_RE = re.compile(
    r'<script[^>]*id="vite-plugin-ssr_pageContext"[^>]*>(.*?)</script>', re.S
)

_NOVEL_RE = re.compile(r"^/book/(?P<slug>\d+)/?$")
# Both shapes appear: /book/<id>/<chapterId>/ 301-redirects to /chapter/...
_CHAPTER_RE = re.compile(r"^/(?:chapter|book)/(?P<slug>\d+)/(?P<chapter>\d+)/?$")

_STATUS_MARKERS = (
    ("完本", NovelStatus.completed),
    ("已完結", NovelStatus.completed),
    ("已完结", NovelStatus.completed),
    ("完結", NovelStatus.completed),
    ("完结", NovelStatus.completed),
    ("連載", NovelStatus.ongoing),
    ("连载", NovelStatus.ongoing),
)


@register
class Qidian(Source):
    key = "qidian"
    name = "起点中文网"
    domains = ("qidian.com",)
    lang = Lang.zh
    # The mobile site answers plain requests, so no browser is needed. The
    # desktop host does need one, and is deliberately not supported.
    needs_browser = False

    # --- url handling ------------------------------------------------------

    def canonical_url(self, url: str) -> str:
        path = urlsplit(url).path

        chapter = _CHAPTER_RE.match(path)
        if chapter:
            return f"{BASE}/chapter/{chapter['slug']}/{chapter['chapter']}/"

        novel = _NOVEL_RE.match(path)
        if novel:
            return f"{BASE}/book/{novel['slug']}/"

        raise SourceError("Not a recognised Qidian URL", url=url)

    def is_chapter_url(self, url: str) -> bool:
        return bool(_CHAPTER_RE.match(urlsplit(url).path))

    async def novel_url_from_chapter(self, url: str) -> str:
        match = _CHAPTER_RE.match(urlsplit(url).path)
        if match is None:
            raise SourceError("Not a chapter URL", url=url)
        return f"{BASE}/book/{match['slug']}/"

    def _book_id(self, url: str) -> str:
        match = _NOVEL_RE.match(urlsplit(url).path)
        if match is None:
            raise SourceError("Not a novel URL", url=url)
        return match["slug"]

    # --- the JSON payload --------------------------------------------------

    async def _page_data(self, url: str) -> dict[str, Any]:
        """Return ``pageProps.pageData`` for a mobile page.

        Raises :class:`SourceError` rather than returning a partial dict: a
        missing payload means the site switched away from vite-plugin-ssr, and
        every caller below would otherwise fail on a confusing ``KeyError``.
        """
        html = await self._get(url)

        match = _PAGE_CONTEXT_RE.search(html)
        if match is None:
            # The desktop host answers 202 with a near-empty body. Saying so
            # beats "no payload found" when someone pastes a www URL.
            raise SourceError(
                "No page payload found; Qidian may have blocked this request "
                "or changed its page format",
                url=url,
            )

        try:
            context = json.loads(match.group(1))["pageContext"]
        except (ValueError, KeyError) as exc:
            raise SourceError(f"Page payload is not readable ({exc})", url=url) from exc

        # Note: ``errorMsg`` is not checked. It is the literal string
        # "!undefined" on every page, working or not, so it carries no signal.
        # A missing ``pageData`` is what actually marks an unknown book id.
        data = (context.get("pageProps") or {}).get("pageData")
        if not isinstance(data, dict) or not data:
            raise SourceError(
                "Page payload is empty; the book id may not exist", url=url
            )
        return data

    # --- novel -------------------------------------------------------------

    async def novel_info(self, url: str) -> NovelInfo:
        url = self.canonical_url(url)
        book_id = self._book_id(url)
        info = (await self._page_data(url)).get("bookInfo") or {}

        title = (info.get("bookName") or "").strip()
        if not title:
            raise SourceError("No novel title in the payload", url=url)

        return NovelInfo(
            title=title,
            url=url,
            author=(info.get("authorName") or "").strip() or None,
            cover_url=self._cover_url(book_id),
            description=normalise(info.get("desc") or "") or None,
            genres=self._genres(info),
            status=self._status(info),
            lang=self.lang,
        )

    @staticmethod
    def _cover_url(book_id: str) -> str:
        """Covers live on Yuewen's CDN, keyed by book id.

        Built rather than scraped: the mobile page references the cover through
        a CSS background and a srcset of resized variants, and the predictable
        CDN path is both stabler and gives the full-size image.
        """
        return f"https://bookcover.yuewen.com/qdbimg/349573/{book_id}/600.webp"

    @staticmethod
    def _genres(info: dict[str, Any]) -> list[str]:
        """Channel, sub-category and the editorial tag, de-duplicated."""
        candidates = [
            info.get("chanName"),
            info.get("subCateName"),
            (info.get("bookTag") or {}).get("tagName"),
        ]
        genres: list[str] = []
        for value in candidates:
            name = (value or "").strip()
            if name and name not in genres:
                genres.append(name)
        return genres

    @staticmethod
    def _status(info: dict[str, Any]) -> NovelStatus:
        text = f"{info.get('actionStatus') or ''} {info.get('bookStatus') or ''}"
        for marker, status in _STATUS_MARKERS:
            if marker in text:
                return status
        return NovelStatus.unknown

    # --- chapters ----------------------------------------------------------

    async def chapter_list(self, url: str) -> list[ChapterRef]:
        url = self.canonical_url(url)
        book_id = self._book_id(url)
        data = await self._page_data(f"{BASE}/book/{book_id}/catalog/")

        volumes = data.get("vs")
        if not isinstance(volumes, list) or not volumes:
            raise SourceError("Catalogue has no volumes", url=url)

        refs: list[ChapterRef] = []
        number = 0
        locked = 0

        for volume in volumes:
            volume_name = (volume.get("vN") or "").strip() or None
            for entry in volume.get("cs") or []:
                chapter_id = entry.get("id")
                title = (entry.get("cN") or "").strip()
                if not chapter_id or not title:
                    continue

                # Position in the catalogue is the chapter number. Unlike the
                # other Chinese sites this does not come from the title: Qidian
                # numbers restart inside each volume, so titles alone would
                # collide across volumes.
                number += 1

                if not _is_readable(entry):
                    locked += 1
                    continue

                refs.append(
                    ChapterRef(
                        number=number,
                        title=title,
                        url=f"{BASE}/chapter/{book_id}/{chapter_id}/",
                        volume=volume_name,
                    )
                )

        if not refs:
            raise SourceError(
                f"No free chapters: all {locked} chapters need to be bought",
                url=url,
            )

        if locked:
            log.info(
                "qidian %s: %d free chapters, skipping %d paid", book_id, len(refs), locked
            )
        return refs

    # --- chapter content ---------------------------------------------------

    async def chapter_content(self, url: str) -> str:
        url = self.canonical_url(url)
        chapter = (await self._page_data(url)).get("chapterInfo") or {}

        if not _is_unlocked(chapter):
            raise ChapterLocked("Chapter has to be bought", url=url)

        # Scrambled-font chapters would be stored as plausible-looking
        # nonsense, which is worse than failing: the glyphs are remapped
        # through a per-chapter font file we do not apply.
        if chapter.get("randomFont") or chapter.get("fixedFontWoff2"):
            raise SourceError(
                "Chapter text is obfuscated with a custom font", url=url
            )

        body = chapter.get("content") or ""
        if not body.strip():
            raise SourceError("Chapter body is empty", url=url)

        text = clean_container(BeautifulSoup(body, "lxml"))

        # A paywalled chapter still ships a short teaser. Comparing against the
        # word count the catalogue promised catches that even when the vip
        # flags are missing or wrong.
        words = chapter.get("wordsCount") or 0
        if words and len(text) < words * 0.3:
            raise ChapterLocked(
                f"Only a {len(text)} character teaser of a {words} character chapter",
                url=url,
            )

        return text

    # --- search ------------------------------------------------------------

    async def search(self, query: str, *, limit: int = 20) -> list[NovelRef]:
        data = await self._page_data(f"{BASE}/search/?kw={query}")

        books = data.get("books") or data.get("bookList") or []
        results: list[NovelRef] = []
        for book in books:
            book_id = book.get("bookId") or book.get("bid")
            title = (book.get("bookName") or book.get("bName") or "").strip()
            if not book_id or not title:
                continue
            results.append(
                NovelRef(
                    title=title,
                    url=f"{BASE}/book/{book_id}/",
                    author=(book.get("authorName") or "").strip() or None,
                    cover_url=self._cover_url(str(book_id)),
                )
            )
            if len(results) >= limit:
                break
        return results


# --- paywall rules ---------------------------------------------------------


def _is_readable(entry: dict[str, Any]) -> bool:
    """Whether a catalogue entry can be downloaded.

    ``sS`` is the catalogue's "can you read this" flag, and it accounts for
    purchases when cookies are configured, so a bought chapter is included
    rather than skipped. Entries that omit it are treated as readable: the
    chapter fetch checks again and will skip it there, which is the safer way
    round if Qidian renames the field.
    """
    if "sS" not in entry:
        return True
    return entry["sS"] == 1


def _is_unlocked(chapter: dict[str, Any]) -> bool:
    """Whether a fetched chapter actually contains the text.

    ``vipStatus`` marks a paid chapter and ``isBuy`` whether this session owns
    it, so a paid chapter is only readable when it has been bought.
    """
    if not chapter.get("vipStatus"):
        return True
    return bool(chapter.get("isBuy"))
