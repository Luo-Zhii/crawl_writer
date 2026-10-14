"""The source adapter contract.

One adapter per site, all answering the same four questions: what is this
novel, what chapters does it have, what is in a chapter, and (optionally) what
matches a search. Everything above this layer — the crawl pipeline, the API,
the exporters — is written against this interface, so adding a site never
means touching the pipeline.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.db.models import Lang, NovelStatus
from app.fetch.base import Fetcher


@dataclass(slots=True)
class NovelRef:
    """A search hit: enough to show a result row and start a crawl."""

    title: str
    url: str
    author: str | None = None
    cover_url: str | None = None


@dataclass(slots=True)
class NovelInfo:
    """Everything the library needs about a novel."""

    title: str
    url: str
    author: str | None = None
    cover_url: str | None = None
    description: str | None = None
    genres: list[str] = field(default_factory=list)
    status: NovelStatus = NovelStatus.unknown
    lang: Lang = Lang.vi


@dataclass(slots=True)
class ChapterRef:
    """A chapter's place in the book, without its text."""

    number: int
    title: str
    url: str
    volume: str | None = None


class SourceError(Exception):
    """The page loaded but did not look like what we expected.

    Raised when a selector finds nothing. Kept separate from fetch errors
    because the fix is different: this means the site changed its markup, not
    that the network failed or we got blocked.
    """

    def __init__(self, message: str, *, url: str) -> None:
        super().__init__(f"{message}: {url}")
        self.url = url


class ChapterLocked(SourceError):
    """The chapter exists but is paid or members-only.

    Not a failure: there is nothing to retry and nothing to fix, so the crawl
    records it as skipped and moves on.
    """


class Source(ABC):
    """Base class for site adapters."""

    #: Stable identifier stored in ``Novel.source``. Never rename it; existing
    #: rows point at it.
    key: str = ""
    #: Human readable name for the UI.
    name: str = ""
    #: Hosts this adapter handles, without "www.".
    domains: tuple[str, ...] = ()
    #: Language of the text as published.
    lang: Lang = Lang.vi
    #: True when plain HTTP will not get through (Cloudflare, JS rendering).
    needs_browser: bool = False
    #: Force a charset when the site lies about it.
    encoding: str | None = None

    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher

    # --- url handling ------------------------------------------------------

    @classmethod
    def handles(cls, url: str) -> bool:
        host = urlsplit(url).netloc.lower().removeprefix("www.")
        return any(host == domain or host.endswith(f".{domain}") for domain in cls.domains)

    @abstractmethod
    def canonical_url(self, url: str) -> str:
        """Normalise a user-pasted URL to the novel's main page.

        People paste chapter links and URLs with tracking junk; the library
        needs one stable URL per novel so re-adding finds the existing entry.
        """

    # --- fetching ----------------------------------------------------------

    async def _get(self, url: str, *, referer: str | None = None) -> str:
        resp = await self.fetcher.get(url, referer=referer, encoding=self.encoding)
        return resp.text

    # --- the contract ------------------------------------------------------

    async def search(self, query: str, *, limit: int = 20) -> list[NovelRef]:
        """Find novels by name. Not every site has usable search."""
        raise NotImplementedError(f"{self.key} does not support search")

    @abstractmethod
    async def novel_info(self, url: str) -> NovelInfo: ...

    @abstractmethod
    async def chapter_list(self, url: str) -> list[ChapterRef]: ...

    @abstractmethod
    async def chapter_content(self, url: str) -> str:
        """Return the chapter body as clean text, paragraphs separated by blank lines."""
