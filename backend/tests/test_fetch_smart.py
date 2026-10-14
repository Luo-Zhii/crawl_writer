"""Routing between plain HTTP and the browser.

The browser costs about a second and a few hundred MB per page, so the rules
about when it gets used matter more than they look.
"""

from __future__ import annotations

import pytest

from app.fetch.base import Response
from app.fetch.browser import BrowserUnavailable
from app.fetch.errors import Blocked, NotFound
from app.fetch.smart import SmartFetcher, hosts_needing_browser

PLAIN_URL = "https://open.test/truyen/abc/chuong-1"
WALLED_URL = "https://walled.test/truyen/abc/chuong-1"


class FakeFetcher:
    """Records calls and answers with whatever it was told to."""

    def __init__(self, *, blocked_hosts: set[str] | None = None, label: str = "http") -> None:
        self.blocked_hosts = blocked_hosts or set()
        self.label = label
        self.calls: list[str] = []
        self.closed = False

    async def get(self, url: str, *, referer: str | None = None, encoding: str | None = None):
        self.calls.append(url)
        host = url.split("/")[2]
        if host in self.blocked_hosts:
            raise Blocked("Refused", url=url, status=403, reason="forbidden")
        return Response(
            url=url, status=200, text=f"body from {self.label}",
            from_browser=self.label == "browser",
        )

    async def get_bytes(self, url: str, *, referer: str | None = None) -> bytes:
        self.calls.append(url)
        return b"bytes"

    async def aclose(self) -> None:
        self.closed = True


def make(**kwargs) -> tuple[SmartFetcher, FakeFetcher, FakeFetcher]:
    http = FakeFetcher(label="http", blocked_hosts=kwargs.pop("http_blocks", set()))
    browser = FakeFetcher(label="browser", blocked_hosts=kwargs.pop("browser_blocks", set()))
    fetcher = SmartFetcher(http=http, browser=browser, **kwargs)
    return fetcher, http, browser


# --- the cheap path --------------------------------------------------------


async def test_plain_http_is_used_when_it_works():
    fetcher, http, browser = make()

    resp = await fetcher.get(PLAIN_URL)

    assert resp.from_browser is False
    assert http.calls == [PLAIN_URL]
    assert browser.calls == [], "the browser should not be started needlessly"


async def test_adapters_that_declare_needs_browser_skip_http_entirely():
    """No point being refused first when the adapter already knows."""
    fetcher, http, browser = make(browser_hosts={"walled.test"})

    resp = await fetcher.get(WALLED_URL)

    assert resp.from_browser is True
    assert http.calls == []
    assert browser.calls == [WALLED_URL]


async def test_browser_hosts_cover_subdomains():
    fetcher, http, browser = make(browser_hosts={"walled.test"})

    await fetcher.get("https://m.walled.test/a")

    assert browser.calls and not http.calls


async def test_www_prefix_is_ignored_when_matching():
    fetcher, _, browser = make(browser_hosts={"walled.test"})

    await fetcher.get("https://www.walled.test/a")

    assert browser.calls


# --- falling back ----------------------------------------------------------


async def test_a_blocked_host_is_retried_with_the_browser():
    fetcher, http, browser = make(http_blocks={"walled.test"})

    resp = await fetcher.get(WALLED_URL)

    assert resp.from_browser is True
    assert http.calls == [WALLED_URL]
    assert browser.calls == [WALLED_URL]


async def test_a_host_that_needed_the_browser_is_remembered():
    """Otherwise every chapter pays for one refused request first."""
    fetcher, http, browser = make(http_blocks={"walled.test"})

    await fetcher.get(WALLED_URL)
    await fetcher.get("https://walled.test/truyen/abc/chuong-2")

    assert len(http.calls) == 1, "http should only have been tried once"
    assert len(browser.calls) == 2


async def test_other_hosts_still_use_http_after_a_fallback():
    fetcher, http, browser = make(http_blocks={"walled.test"})

    await fetcher.get(WALLED_URL)
    await fetcher.get(PLAIN_URL)

    assert PLAIN_URL in http.calls
    assert PLAIN_URL not in browser.calls


async def test_blocked_in_the_browser_too_raises_and_stops_retrying():
    fetcher, http, browser = make(
        http_blocks={"walled.test"}, browser_blocks={"walled.test"}
    )

    with pytest.raises(Blocked):
        await fetcher.get(WALLED_URL)

    # Second attempt must not pay for the browser again.
    with pytest.raises(Blocked):
        await fetcher.get(WALLED_URL)

    assert len(browser.calls) == 1


async def test_non_block_errors_are_not_retried_with_the_browser():
    """A missing page is missing in a browser too."""

    class Missing(FakeFetcher):
        async def get(self, url, *, referer=None, encoding=None):
            self.calls.append(url)
            raise NotFound("gone", url=url, status=404)

    http = Missing()
    browser = FakeFetcher(label="browser")
    fetcher = SmartFetcher(http=http, browser=browser)

    with pytest.raises(NotFound):
        await fetcher.get(PLAIN_URL)

    assert browser.calls == []


# --- browser disabled or missing -------------------------------------------


async def test_block_is_reported_when_the_browser_is_disabled():
    fetcher = SmartFetcher(
        http=FakeFetcher(blocked_hosts={"walled.test"}),
        browser=None,
        browser_enabled=False,
    )

    with pytest.raises(Blocked) as exc:
        await fetcher.get(WALLED_URL)

    assert exc.value.reason == "forbidden"


async def test_missing_playwright_is_explained_in_the_block_message():
    """The user needs to know a browser would have helped, and how to get one."""

    class Unavailable(FakeFetcher):
        async def get(self, url, *, referer=None, encoding=None):
            raise BrowserUnavailable("Playwright is not installed. Install it with: ...",
                                     url=url)

    fetcher = SmartFetcher(
        http=FakeFetcher(blocked_hosts={"walled.test"}), browser=Unavailable()
    )

    with pytest.raises(Blocked) as exc:
        await fetcher.get(WALLED_URL)

    message = str(exc.value)
    assert "Refused" in message
    assert "Playwright is not installed" in message


# --- misc ------------------------------------------------------------------


async def test_get_bytes_uses_the_browser_for_walled_hosts():
    """Covers on a protected site need the browser's cookies."""
    fetcher, http, browser = make(browser_hosts={"walled.test"})

    await fetcher.get_bytes("https://walled.test/cover.jpg")

    assert browser.calls and not http.calls


async def test_get_bytes_uses_http_elsewhere():
    fetcher, http, browser = make()

    await fetcher.get_bytes("https://open.test/cover.jpg")

    assert http.calls and not browser.calls


async def test_closing_closes_both_when_it_owns_them():
    http = FakeFetcher()
    browser = FakeFetcher(label="browser")
    fetcher = SmartFetcher(http=http, browser=browser)
    fetcher._owns_browser = True  # as if SmartFetcher had created it

    await fetcher.aclose()

    assert http.closed and browser.closed


def test_browser_hosts_are_seeded_from_the_registry():
    """An adapter flagged needs_browser should route there without configuration."""
    hosts = hosts_needing_browser()

    # Nothing registered needs a browser yet, but the lookup must work and
    # return plain lowercase hostnames.
    assert isinstance(hosts, set)
    assert all(host == host.lower() for host in hosts)
