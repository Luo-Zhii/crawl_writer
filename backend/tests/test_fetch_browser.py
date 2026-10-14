"""The browser fetcher, driven against a local server.

These tests launch a real Chromium, so they are slower than the rest of the
suite. They are worth it: the whole point of this fetcher is surviving a page
that only becomes readable after its JavaScript runs, and nothing short of a
real browser proves that works.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.fetch.browser import BrowserFetcher
from app.fetch.errors import Blocked, NotFound

playwright = pytest.importorskip("playwright", reason="browser extra not installed")

# A page that looks like a Cloudflare interstitial, then rewrites itself into
# the real article a moment later — the shape of challenge we must survive.
CHALLENGE_PAGE = """<!doctype html>
<html><head><title>Just a moment...</title></head>
<body>
  <div id="cf-browser-verification">Checking your browser before accessing</div>
  <script>
    setTimeout(function () {
      document.title = "Chương 1";
      document.body.innerHTML =
        '<div id="chapter-c" class="chapter-c">' +
        'Noi dung that cua chuong sau khi vuot qua thu thach. '.repeat(40) +
        '</div>';
    }, 400);
  </script>
</body></html>
"""

REAL_PAGE = """<!doctype html>
<html><head><title>Chương 1</title></head>
<body><div id="chapter-c" class="chapter-c">%s</div></body></html>
""" % ("Mot doan van ban du dai de khong bi coi la trang rong. " * 40)

STUCK_PAGE = """<!doctype html>
<html><head><title>Just a moment...</title></head>
<body><div id="cf-browser-verification">Checking your browser before accessing</div>
</body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        routes = {
            "/ok": (200, REAL_PAGE),
            "/challenge": (200, CHALLENGE_PAGE),
            "/stuck": (200, STUCK_PAGE),
            "/missing": (404, "<html><body>nope</body></html>"),
            "/refused": (403, "<html><body>forbidden</body></html>"),
        }
        status, body = routes.get(self.path, (404, "<html>?</html>"))
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args) -> None:
        """Keep the test output quiet."""


@pytest.fixture(scope="module")
def server() -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
async def fetcher() -> Iterator[BrowserFetcher]:
    browser = BrowserFetcher(challenge_timeout=8.0)
    try:
        yield browser
    finally:
        await browser.aclose()


# --- lifecycle -------------------------------------------------------------


async def test_browser_starts_lazily(fetcher: BrowserFetcher, server: str):
    assert fetcher.running is False

    await fetcher.get(f"{server}/ok")

    assert fetcher.running is True


async def test_close_is_idempotent(fetcher: BrowserFetcher, server: str):
    await fetcher.get(f"{server}/ok")

    await fetcher.aclose()
    await fetcher.aclose()  # must not raise

    assert fetcher.running is False


# --- fetching --------------------------------------------------------------


async def test_plain_page_is_returned(fetcher: BrowserFetcher, server: str):
    resp = await fetcher.get(f"{server}/ok")

    assert resp.status == 200
    assert "Mot doan van ban" in resp.text
    assert resp.from_browser is True, "callers use this to tell how it was fetched"


async def test_challenge_page_is_waited_out(fetcher: BrowserFetcher, server: str):
    """The real reason this fetcher exists."""
    resp = await fetcher.get(f"{server}/challenge")

    assert "Noi dung that cua chuong" in resp.text
    assert "cf-browser-verification" not in resp.text


async def test_a_challenge_that_never_clears_is_reported(
    fetcher: BrowserFetcher, server: str
):
    fetcher._challenge_timeout = 2.0

    with pytest.raises(Blocked) as exc:
        await fetcher.get(f"{server}/stuck")

    assert "did not clear" in str(exc.value)


async def test_404_is_not_found(fetcher: BrowserFetcher, server: str):
    with pytest.raises(NotFound):
        await fetcher.get(f"{server}/missing")


async def test_403_is_blocked(fetcher: BrowserFetcher, server: str):
    with pytest.raises(Blocked):
        await fetcher.get(f"{server}/refused")


async def test_unreachable_host_is_transient(fetcher: BrowserFetcher):
    from app.fetch.errors import TransientError

    with pytest.raises(TransientError):
        # Port 1 is reserved and nothing listens there.
        await fetcher.get("http://127.0.0.1:1/ok")


# --- cookies ---------------------------------------------------------------


async def test_cookies_can_be_preloaded(server: str):
    """Pasting a session cookie is how paid chapters become reachable."""
    browser = BrowserFetcher(
        cookies=[{"name": "sid", "value": "abc", "domain": "127.0.0.1", "path": "/"}]
    )
    try:
        await browser.get(f"{server}/ok")
        names = {cookie["name"] for cookie in await browser.cookies()}
    finally:
        await browser.aclose()

    assert "sid" in names


async def test_cookies_are_readable_before_the_browser_starts():
    browser = BrowserFetcher(cookies=[{"name": "sid", "value": "abc"}])

    assert await browser.cookies() == [{"name": "sid", "value": "abc"}]
