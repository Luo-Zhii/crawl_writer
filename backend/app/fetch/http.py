"""The plain HTTP fetcher.

Handles the boring-but-essential parts: a believable set of headers, polite
pacing per host, retries with backoff on the failures worth retrying, and a
hard stop when the site is clearly refusing us.
"""

from __future__ import annotations

import asyncio
import random
from urllib.parse import urlsplit

import httpx

from app.core.logging import get_logger
from app.core.settings import Settings, get_settings
from app.fetch import block
from app.fetch.base import Response
from app.fetch.decode import decode
from app.fetch.errors import Blocked, FetchError, NotFound, RateLimited, TransientError
from app.fetch.throttle import DomainThrottle

log = get_logger(__name__)

# Sent on every request. Novel sites are quick to refuse anything that looks
# like a script, and a missing Accept-Language in particular gets noticed.
_DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
    "image/webp,*/*;q=0.8",
    "Accept-Language": "vi,en-US;q=0.9,en;q=0.8,zh-CN;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}

# Caps the wait so one slow site cannot stall a crawl for minutes.
_MAX_BACKOFF = 30.0


class HttpFetcher:
    """Fetches pages over HTTP with retries and per-host throttling."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
        throttle: DomainThrottle | None = None,
        cookies: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        sleep=None,
    ) -> None:
        self._settings = settings or get_settings()
        self._owns_client = client is None
        self._sleep = sleep or asyncio.sleep

        merged = {**_DEFAULT_HEADERS, "User-Agent": self._settings.user_agent}
        if headers:
            merged.update(headers)

        self._client = client or httpx.AsyncClient(
            headers=merged,
            cookies=cookies or {},
            timeout=httpx.Timeout(self._settings.request_timeout),
            follow_redirects=True,
            proxy=self._settings.proxy,
        )
        self._throttle = throttle or DomainThrottle(
            delay=self._settings.per_domain_delay,
            concurrency=self._settings.per_domain_concurrency,
        )

    # --- public API --------------------------------------------------------

    async def get(
        self,
        url: str,
        *,
        referer: str | None = None,
        encoding: str | None = None,
    ) -> Response:
        """Fetch ``url`` as text, retrying transient failures."""
        raw = await self._get_raw(url, referer=referer)
        text, used = decode(
            raw.content,
            content_type=raw.headers.get("content-type"),
            override=encoding,
        )

        verdict = block.inspect(raw.status_code, text, headers=dict(raw.headers))
        if verdict.blocked:
            log.warning("blocked by %s: %s", _host(url), verdict.reason)
            raise Blocked(
                f"Request refused: {verdict.reason}",
                url=str(raw.url),
                status=raw.status_code,
                reason=verdict.reason,
            )

        return Response(
            url=str(raw.url),
            status=raw.status_code,
            text=text,
            content=raw.content,
            encoding=used,
            headers=dict(raw.headers),
        )

    async def get_bytes(self, url: str, *, referer: str | None = None) -> bytes:
        """Fetch binary content such as a cover image."""
        raw = await self._get_raw(url, referer=referer)
        return raw.content

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> HttpFetcher:
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.aclose()

    # --- internals ---------------------------------------------------------

    async def _get_raw(self, url: str, *, referer: str | None) -> httpx.Response:
        host = _host(url)
        headers = {"Referer": referer} if referer else None
        attempts = max(self._settings.max_retries, 1)
        last: FetchError | None = None

        for attempt in range(1, attempts + 1):
            try:
                async with self._throttle.slot(host):
                    raw = await self._client.get(url, headers=headers)
            except httpx.TimeoutException as exc:
                last = TransientError(f"Timed out after {self._settings.request_timeout}s",
                                      url=url)
                log.debug("timeout on %s (attempt %d/%d): %s", url, attempt, attempts, exc)
            except httpx.HTTPError as exc:
                # Connection reset, DNS failure, TLS error, broken proxy.
                last = TransientError(f"Network error: {exc.__class__.__name__}", url=url)
                log.debug("network error on %s (attempt %d/%d): %s", url, attempt, attempts, exc)
            else:
                status = raw.status_code

                if status in (404, 410):
                    raise NotFound("Page does not exist", url=str(raw.url), status=status)

                if status == 429:
                    retry_after = _retry_after(raw)
                    last = RateLimited("Rate limited", url=str(raw.url), status=status,
                                       retry_after=retry_after)
                    if attempt < attempts:
                        await self._sleep(retry_after or self._backoff(attempt))
                        continue
                    raise last

                # Anything Cloudflare-ish or outright refused: stop now, since
                # another identical request will get the same answer.
                verdict = block.inspect(status, "", headers=dict(raw.headers))
                if verdict.blocked:
                    raise Blocked(f"Request refused: {verdict.reason}", url=str(raw.url),
                                  status=status, reason=verdict.reason)

                if 500 <= status < 600:
                    last = TransientError("Server error", url=str(raw.url), status=status)
                    if attempt < attempts:
                        await self._sleep(self._backoff(attempt))
                        continue
                    raise last

                if status >= 400:
                    raise FetchError("Unexpected status", url=str(raw.url), status=status)

                return raw

            if attempt < attempts:
                await self._sleep(self._backoff(attempt))

        assert last is not None  # the loop always records a failure first
        raise last

    def _backoff(self, attempt: int) -> float:
        """Exponential backoff with jitter, so retries do not synchronise."""
        base = min(2.0 ** (attempt - 1), _MAX_BACKOFF)
        return base * (0.5 + random.random() / 2)


def _host(url: str) -> str:
    return urlsplit(url).netloc.lower()


def _retry_after(raw: httpx.Response) -> float | None:
    value = raw.headers.get("retry-after")
    if not value:
        return None
    try:
        return min(float(value), _MAX_BACKOFF)
    except ValueError:
        # The header also allows an HTTP date; backoff is a fine fallback.
        return None
