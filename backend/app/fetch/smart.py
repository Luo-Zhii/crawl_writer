"""Choosing between plain HTTP and a browser, per host.

Plain HTTP is roughly a hundred times cheaper than driving Chromium, so it is
always tried first unless an adapter already declares it will not work. When a
host turns out to be protected, the browser takes over *and the host is
remembered*, so the rest of that crawl skips the pointless first attempt.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from app.core.logging import get_logger
from app.core.settings import Settings, get_settings
from app.fetch.base import Fetcher, Response
from app.fetch.browser import BrowserFetcher, BrowserUnavailable
from app.fetch.errors import Blocked
from app.fetch.http import HttpFetcher

log = get_logger(__name__)


def hosts_needing_browser() -> set[str]:
    """Hosts whose adapters already know plain HTTP will not work."""
    from app.sources import all_sources

    return {
        domain.lower()
        for source in all_sources()
        if source.needs_browser
        for domain in source.domains
    }


class SmartFetcher:
    """A :class:`Fetcher` that routes each URL to the cheapest thing that works."""

    def __init__(
        self,
        *,
        http: Fetcher | None = None,
        browser: Fetcher | None = None,
        settings: Settings | None = None,
        browser_enabled: bool = True,
        browser_hosts: set[str] | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._http = http or HttpFetcher(settings=self._settings)
        self._browser = browser
        self._owns_browser = browser is None
        self._browser_enabled = browser_enabled
        self._browser_hosts = (
            browser_hosts if browser_hosts is not None else hosts_needing_browser()
        )
        # Hosts the browser also failed on: stop paying for Chromium there.
        self._hopeless: set[str] = set()

    # --- routing -----------------------------------------------------------

    def _host(self, url: str) -> str:
        return urlsplit(url).netloc.lower().removeprefix("www.")

    def needs_browser(self, url: str) -> bool:
        host = self._host(url)
        return any(host == known or host.endswith(f".{known}") for known in self._browser_hosts)

    def remember_browser_host(self, url: str) -> None:
        self._browser_hosts.add(self._host(url))

    def _get_browser(self) -> Fetcher | None:
        if not self._browser_enabled:
            return None
        if self._browser is None:
            self._browser = BrowserFetcher(settings=self._settings)
        return self._browser

    # --- Fetcher protocol --------------------------------------------------

    async def get(
        self, url: str, *, referer: str | None = None, encoding: str | None = None
    ) -> Response:
        host = self._host(url)

        if self.needs_browser(url) and host not in self._hopeless:
            browser = self._get_browser()
            if browser is not None:
                return await browser.get(url, referer=referer, encoding=encoding)
            log.warning("%s needs a browser but browser fetching is disabled", host)

        try:
            return await self._http.get(url, referer=referer, encoding=encoding)
        except Blocked as blocked:
            browser = self._get_browser() if host not in self._hopeless else None
            if browser is None:
                raise

            log.info("%s blocked over http (%s), retrying with the browser",
                     host, blocked.reason)
            try:
                response = await browser.get(url, referer=referer, encoding=encoding)
            except BrowserUnavailable as exc:
                # Report the original refusal, with the install hint attached.
                raise Blocked(
                    f"{blocked.message}. A browser would be needed, but: {exc}",
                    url=url,
                    status=blocked.status,
                    reason=blocked.reason,
                ) from exc
            except Blocked:
                # The browser could not get in either; stop trying for this host.
                self._hopeless.add(host)
                raise

            # Worked: every later request for this host goes straight to the
            # browser instead of being refused first.
            self.remember_browser_host(url)
            return response

    async def get_bytes(self, url: str, *, referer: str | None = None) -> bytes:
        if self.needs_browser(url):
            browser = self._get_browser()
            if browser is not None and hasattr(browser, "get_bytes"):
                return await browser.get_bytes(url, referer=referer)
        return await self._http.get_bytes(url, referer=referer)

    async def aclose(self) -> None:
        await self._http.aclose()
        if self._browser is not None and self._owns_browser:
            await self._browser.aclose()
            self._browser = None
