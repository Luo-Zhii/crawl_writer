"""HttpFetcher behaviour, with the network mocked by respx."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.fetch.errors import Blocked, FetchError, NotFound, RateLimited, TransientError
from app.fetch.http import HttpFetcher
from app.fetch.throttle import DomainThrottle

URL = "https://truyen.test/truyen/abc/chuong-1"
CHAPTER_HTML = "<html><body><div class='chapter-c'>" + "Nội dung. " * 400 + "</div></body></html>"


class RecordingSleep:
    """Stands in for asyncio.sleep so retry tests finish instantly."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def make_fetcher(**kwargs) -> tuple[HttpFetcher, RecordingSleep]:
    sleep = RecordingSleep()
    fetcher = HttpFetcher(
        # No pacing in tests unless a test asks for it.
        throttle=DomainThrottle(delay=0.0, concurrency=4),
        sleep=sleep,
        **kwargs,
    )
    return fetcher, sleep


# --- happy path ------------------------------------------------------------


@respx.mock
async def test_get_returns_decoded_text():
    respx.get(URL).mock(return_value=httpx.Response(200, html=CHAPTER_HTML))
    fetcher, _ = make_fetcher()

    resp = await fetcher.get(URL)
    await fetcher.aclose()

    assert resp.status == 200
    assert "Nội dung." in resp.text
    assert resp.url == URL
    assert len(resp) == len(resp.text)


@respx.mock
async def test_request_looks_like_a_browser():
    route = respx.get(URL).mock(return_value=httpx.Response(200, html=CHAPTER_HTML))
    fetcher, _ = make_fetcher()

    await fetcher.get(URL, referer="https://truyen.test/truyen/abc")
    await fetcher.aclose()

    sent = route.calls.last.request
    assert "Mozilla/5.0" in sent.headers["user-agent"]
    assert sent.headers["accept-language"].startswith("vi")
    assert sent.headers["referer"] == "https://truyen.test/truyen/abc"


@respx.mock
async def test_cookies_are_sent():
    """Needed later for sites that only serve chapters to a logged-in session."""
    route = respx.get(URL).mock(return_value=httpx.Response(200, html=CHAPTER_HTML))
    fetcher, _ = make_fetcher(cookies={"sid": "abc123"})

    await fetcher.get(URL)
    await fetcher.aclose()

    assert "sid=abc123" in route.calls.last.request.headers["cookie"]


@respx.mock
async def test_redirects_are_followed_and_final_url_reported():
    respx.get(URL).mock(
        return_value=httpx.Response(302, headers={"location": "https://truyen.test/moved"})
    )
    respx.get("https://truyen.test/moved").mock(
        return_value=httpx.Response(200, html=CHAPTER_HTML)
    )
    fetcher, _ = make_fetcher()

    resp = await fetcher.get(URL)
    await fetcher.aclose()

    assert resp.url == "https://truyen.test/moved"


@respx.mock
async def test_gbk_page_is_decoded():
    """A Chinese raw site declaring GBK in markup only."""
    body = '<meta charset="gbk">第一章 开始'.encode("gb18030")
    respx.get(URL).mock(return_value=httpx.Response(200, content=body))
    fetcher, _ = make_fetcher()

    resp = await fetcher.get(URL)
    await fetcher.aclose()

    assert "第一章 开始" in resp.text
    assert resp.encoding == "gb18030"


@respx.mock
async def test_get_bytes_for_cover_images():
    respx.get("https://truyen.test/cover.jpg").mock(
        return_value=httpx.Response(200, content=b"\xff\xd8\xff\xe0jpegdata")
    )
    fetcher, _ = make_fetcher()

    data = await fetcher.get_bytes("https://truyen.test/cover.jpg")
    await fetcher.aclose()

    assert data.startswith(b"\xff\xd8")


# --- blocked ---------------------------------------------------------------


@respx.mock
async def test_403_raises_blocked_without_retrying():
    route = respx.get(URL).mock(return_value=httpx.Response(403))
    fetcher, sleep = make_fetcher()

    with pytest.raises(Blocked) as exc:
        await fetcher.get(URL)
    await fetcher.aclose()

    assert exc.value.status == 403
    assert route.call_count == 1, "retrying a refusal just wastes requests"
    assert sleep.calls == []


@respx.mock
async def test_522_raises_blocked():
    """Exactly what tangthuvien returned during research."""
    respx.get(URL).mock(return_value=httpx.Response(522))
    fetcher, _ = make_fetcher()

    with pytest.raises(Blocked) as exc:
        await fetcher.get(URL)
    await fetcher.aclose()

    assert "origin" in exc.value.reason


@respx.mock
async def test_challenge_page_with_status_200_raises_blocked():
    """The important one: a 200 challenge must never become chapter text."""
    challenge = "<html><head><title>Just a moment...</title></head></html>"
    respx.get(URL).mock(return_value=httpx.Response(200, html=challenge))
    fetcher, _ = make_fetcher()

    with pytest.raises(Blocked) as exc:
        await fetcher.get(URL)
    await fetcher.aclose()

    assert exc.value.status == 200
    assert "challenge" in exc.value.reason


@respx.mock
async def test_cloudflare_503_is_blocked_not_retried():
    route = respx.get(URL).mock(
        return_value=httpx.Response(503, headers={"server": "cloudflare"})
    )
    fetcher, _ = make_fetcher()

    with pytest.raises(Blocked):
        await fetcher.get(URL)
    await fetcher.aclose()

    assert route.call_count == 1


# --- missing ---------------------------------------------------------------


@respx.mock
@pytest.mark.parametrize("status", [404, 410])
async def test_missing_page_raises_not_found(status: int):
    route = respx.get(URL).mock(return_value=httpx.Response(status))
    fetcher, _ = make_fetcher()

    with pytest.raises(NotFound):
        await fetcher.get(URL)
    await fetcher.aclose()

    assert route.call_count == 1


# --- retries ---------------------------------------------------------------


@respx.mock
async def test_timeout_is_retried_then_succeeds():
    respx.get(URL).mock(
        side_effect=[
            httpx.TimeoutException("too slow"),
            httpx.Response(200, html=CHAPTER_HTML),
        ]
    )
    fetcher, sleep = make_fetcher()

    resp = await fetcher.get(URL)
    await fetcher.aclose()

    assert resp.status == 200
    assert len(sleep.calls) == 1


@respx.mock
async def test_connection_error_is_retried():
    respx.get(URL).mock(
        side_effect=[
            httpx.ConnectError("reset"),
            httpx.Response(200, html=CHAPTER_HTML),
        ]
    )
    fetcher, _ = make_fetcher()

    assert (await fetcher.get(URL)).status == 200
    await fetcher.aclose()


@respx.mock
async def test_retries_are_capped_then_transient_error_raised():
    route = respx.get(URL).mock(side_effect=httpx.TimeoutException("nope"))
    fetcher, sleep = make_fetcher()

    with pytest.raises(TransientError):
        await fetcher.get(URL)
    await fetcher.aclose()

    # max_retries defaults to 3: three attempts, two waits between them.
    assert route.call_count == 3
    assert len(sleep.calls) == 2


@respx.mock
async def test_backoff_grows_between_attempts():
    respx.get(URL).mock(side_effect=httpx.TimeoutException("nope"))
    fetcher, sleep = make_fetcher()

    with pytest.raises(TransientError):
        await fetcher.get(URL)
    await fetcher.aclose()

    assert sleep.calls[1] > sleep.calls[0], "waits should back off, not stay flat"


@respx.mock
async def test_server_error_is_retried_then_succeeds():
    respx.get(URL).mock(
        side_effect=[httpx.Response(500), httpx.Response(200, html=CHAPTER_HTML)]
    )
    fetcher, _ = make_fetcher()

    assert (await fetcher.get(URL)).status == 200
    await fetcher.aclose()


@respx.mock
async def test_persistent_server_error_raises_transient():
    respx.get(URL).mock(return_value=httpx.Response(502))
    fetcher, _ = make_fetcher()

    with pytest.raises(TransientError) as exc:
        await fetcher.get(URL)
    await fetcher.aclose()

    assert exc.value.status == 502


@respx.mock
async def test_429_honours_retry_after():
    respx.get(URL).mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "7"}),
            httpx.Response(200, html=CHAPTER_HTML),
        ]
    )
    fetcher, sleep = make_fetcher()

    await fetcher.get(URL)
    await fetcher.aclose()

    assert sleep.calls == [7.0]


@respx.mock
async def test_429_without_header_falls_back_to_backoff():
    respx.get(URL).mock(
        side_effect=[httpx.Response(429), httpx.Response(200, html=CHAPTER_HTML)]
    )
    fetcher, sleep = make_fetcher()

    await fetcher.get(URL)
    await fetcher.aclose()

    assert len(sleep.calls) == 1 and sleep.calls[0] > 0


@respx.mock
async def test_persistent_429_raises_rate_limited():
    respx.get(URL).mock(return_value=httpx.Response(429, headers={"retry-after": "1"}))
    fetcher, _ = make_fetcher()

    with pytest.raises(RateLimited) as exc:
        await fetcher.get(URL)
    await fetcher.aclose()

    assert exc.value.retry_after == 1.0


@respx.mock
async def test_unexpected_4xx_raises_fetch_error():
    respx.get(URL).mock(return_value=httpx.Response(418))
    fetcher, _ = make_fetcher()

    with pytest.raises(FetchError):
        await fetcher.get(URL)
    await fetcher.aclose()


# --- misc ------------------------------------------------------------------


@respx.mock
async def test_error_message_names_the_url():
    respx.get(URL).mock(return_value=httpx.Response(403))
    fetcher, _ = make_fetcher()

    with pytest.raises(Blocked) as exc:
        await fetcher.get(URL)
    await fetcher.aclose()

    assert URL in str(exc.value)
    assert "403" in str(exc.value)


@respx.mock
async def test_works_as_async_context_manager():
    respx.get(URL).mock(return_value=httpx.Response(200, html=CHAPTER_HTML))

    async with HttpFetcher(throttle=DomainThrottle(delay=0.0)) as fetcher:
        assert (await fetcher.get(URL)).status == 200
