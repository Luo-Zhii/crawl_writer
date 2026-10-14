"""Fetching through a real browser.

Some sites answer plain HTTP with an anti-bot interstitial: a page of
JavaScript that, once executed, sets a cookie and reloads into the real
content. There is no way to satisfy that with ``httpx``, so for those hosts we
drive a headless Chromium instead.

The browser is expensive — roughly a second per page and a few hundred MB of
RAM — so it is launched lazily and only used for hosts that actually need it.
Cookies earned by passing a challenge are kept for the rest of the session and
can be persisted, which is what keeps the cost to one slow page per site
rather than one per chapter.
"""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlsplit

from app.core.logging import get_logger
from app.core.settings import Settings, get_settings
from app.fetch import block
from app.fetch.base import Response
from app.fetch.errors import Blocked, FetchError, NotFound, TransientError
from app.fetch.throttle import DomainThrottle

log = get_logger(__name__)

# How long to let a JS challenge resolve itself before giving up.
_CHALLENGE_TIMEOUT = 25.0
_CHALLENGE_POLL = 0.5

_HEADERS = {
    "Accept-Language": "vi,en-US;q=0.9,en;q=0.8,zh-CN;q=0.7",
}


class BrowserUnavailable(FetchError):
    """Playwright or its browser binary is not installed."""


class BrowserFetcher:
    """Fetches pages with Chromium, waiting out anti-bot challenges."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        throttle: DomainThrottle | None = None,
        cookies: list[dict[str, Any]] | None = None,
        headless: bool = True,
        challenge_timeout: float = _CHALLENGE_TIMEOUT,
    ) -> None:
        self._settings = settings or get_settings()
        self._headless = headless
        self._challenge_timeout = challenge_timeout
        self._initial_cookies = cookies or []

        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._lock = asyncio.Lock()

        self._throttle = throttle or DomainThrottle(
            delay=self._settings.per_domain_delay,
            # A browser page is heavy; opening many at once mostly just
            # thrashes memory.
            concurrency=min(self._settings.per_domain_concurrency, 2),
        )

    # --- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Launch the browser if it is not already running."""
        async with self._lock:
            if self._context is not None:
                return

            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:  # pragma: no cover - depends on install
                raise BrowserUnavailable(
                    "Playwright is not installed. Install it with: "
                    "uv pip install -e './backend[browser]' && playwright install chromium",
                    url="",
                ) from exc

            self._playwright = await async_playwright().start()
            try:
                self._browser = await self._playwright.chromium.launch(
                    headless=self._headless,
                    proxy={"server": self._settings.proxy} if self._settings.proxy else None,
                    args=[
                        # Shared memory is small in containers and Chromium
                        # crashes without this.
                        "--disable-dev-shm-usage",
                        "--no-sandbox",
                    ],
                )
            except Exception as exc:  # pragma: no cover - depends on install
                await self._shutdown()
                raise BrowserUnavailable(
                    f"Could not launch Chromium: {exc}. "
                    "Run: playwright install chromium",
                    url="",
                ) from exc

            self._context = await self._browser.new_context(
                user_agent=self._settings.user_agent,
                locale="vi-VN",
                viewport={"width": 1366, "height": 900},
                extra_http_headers=_HEADERS,
            )
            self._context.set_default_timeout(self._settings.request_timeout * 1000)

            if self._initial_cookies:
                await self._context.add_cookies(self._initial_cookies)
                log.info("browser started with %d saved cookie(s)", len(self._initial_cookies))
            else:
                log.info("browser started")

    async def aclose(self) -> None:
        async with self._lock:
            await self._shutdown()

    async def _shutdown(self) -> None:
        for name in ("_context", "_browser"):
            obj = getattr(self, name)
            if obj is not None:
                try:
                    await obj.close()
                except Exception:  # pragma: no cover - best effort teardown
                    log.debug("error closing %s", name, exc_info=True)
                setattr(self, name, None)
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:  # pragma: no cover
                log.debug("error stopping playwright", exc_info=True)
            self._playwright = None

    async def __aenter__(self) -> BrowserFetcher:
        await self.start()
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.aclose()

    @property
    def running(self) -> bool:
        return self._context is not None

    # --- cookies -----------------------------------------------------------

    async def cookies(self) -> list[dict[str, Any]]:
        """Current cookies, including any won by passing a challenge."""
        if self._context is None:
            return list(self._initial_cookies)
        return await self._context.cookies()

    # --- fetching ----------------------------------------------------------

    async def get(
        self,
        url: str,
        *,
        referer: str | None = None,
        encoding: str | None = None,  # noqa: ARG002 - the browser decodes for us
    ) -> Response:
        await self.start()
        host = urlsplit(url).netloc.lower()

        async with self._throttle.slot(host):
            page = await self._context.new_page()
            try:
                try:
                    nav = await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        referer=referer,
                    )
                except Exception as exc:
                    message = str(exc).split("\n")[0]
                    raise TransientError(f"Navigation failed: {message}", url=url) from exc

                status = nav.status if nav is not None else 200
                headers = dict(nav.headers) if nav is not None else {}

                if status in (404, 410):
                    raise NotFound("Page does not exist", url=url, status=status)

                text = await self._settle(page, url, status, headers)

                return Response(
                    url=page.url,
                    status=status,
                    text=text,
                    content=text.encode("utf-8"),
                    encoding="utf-8",
                    headers=headers,
                    from_browser=True,
                )
            finally:
                await page.close()

    async def _settle(
        self, page: Any, url: str, status: int, headers: dict[str, str]
    ) -> str:
        """Return the page body, waiting for a JS challenge to clear first."""
        text = await page.content()
        verdict = block.inspect(status, text, headers=headers)
        if not verdict.blocked:
            return text

        # A refusal expressed as a status code will not change however long we
        # wait, and its body is an error page. Waiting here and then accepting
        # the body is how an error page ends up stored as a chapter.
        if status in block.BLOCKED_STATUSES:
            raise Blocked(
                f"Request refused: {verdict.reason}",
                url=url,
                status=status,
                reason=verdict.reason,
            )

        log.info("challenge on %s, waiting up to %.0fs", urlsplit(url).netloc,
                 self._challenge_timeout)
        deadline = asyncio.get_running_loop().time() + self._challenge_timeout

        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(_CHALLENGE_POLL)
            try:
                text = await page.content()
            except Exception:  # pragma: no cover - page navigating under us
                continue
            # Once a challenge clears, the browser is showing a normal page,
            # so judge the new body on its own rather than by the status the
            # interstitial arrived with.
            if not block.inspect(200, text).blocked:
                log.info("challenge cleared for %s", urlsplit(url).netloc)
                return text

        raise Blocked(
            f"Anti-bot challenge did not clear: {verdict.reason}",
            url=url,
            status=status,
            reason=verdict.reason,
        )

    async def get_bytes(self, url: str, *, referer: str | None = None) -> bytes:
        """Fetch binary content (covers) using the browser's cookies."""
        await self.start()
        headers = {"Referer": referer} if referer else None
        response = await self._context.request.get(url, headers=headers)
        if response.status >= 400:
            raise FetchError("Could not fetch asset", url=url, status=response.status)
        return await response.body()
