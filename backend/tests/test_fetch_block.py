"""Block detection.

These cases are the whole point of the fetcher: a challenge page that gets
mistaken for content ends up stored as a chapter, and the user only finds out
when they open the book.
"""

from __future__ import annotations

import pytest

from app.fetch import block

CHAPTER_BODY = (
    "<html><body><div class='chapter-c'>" + "Tiêu Viêm nhíu mày. " * 400 + "</div></body></html>"
)


def test_normal_page_is_not_blocked():
    assert block.inspect(200, CHAPTER_BODY).blocked is False


@pytest.mark.parametrize("status", [401, 403, 451, 520, 521, 522, 523, 524, 525, 526, 527])
def test_refusal_statuses_are_blocked(status: int):
    verdict = block.inspect(status, "")

    assert verdict.blocked is True
    assert verdict.reason


def test_cloudflare_522_names_the_origin_problem():
    """Seen for real on tangthuvien during research, so keep the message useful."""
    verdict = block.inspect(522, "")

    assert "origin" in verdict.reason


@pytest.mark.parametrize(
    "body",
    [
        "<html><head><title>Just a moment...</title></head><body></body></html>",
        "<div id='cf-browser-verification'></div>",
        "<script src='/cdn-cgi/challenge-platform/h/b/orchestrate'></script>",
        "<html>Checking your browser before accessing the site.</html>",
        "<html>Enable JavaScript and cookies to continue</html>",
        "<html><body>DDoS-Guard</body></html>",
        "<script>var s,t,o,p,b,r,e,a,k,i,n,g,f,jschl_vc</script>",
        "<html>浏览器安全检查中...</html>",
    ],
)
def test_challenge_page_served_as_200_is_blocked(body: str):
    verdict = block.inspect(200, body)

    assert verdict.blocked is True


def test_detection_is_case_insensitive():
    assert block.inspect(200, "<TITLE>JUST A MOMENT...</TITLE>").blocked is True


def test_503_from_cloudflare_is_a_challenge():
    verdict = block.inspect(503, "", headers={"server": "cloudflare"})

    assert verdict.blocked is True


def test_plain_503_is_left_for_retry():
    """An overloaded origin should be retried, not reported as a block."""
    verdict = block.inspect(503, "", headers={"server": "nginx"})

    assert verdict.blocked is False


def test_short_page_mentioning_captcha_is_blocked():
    verdict = block.inspect(200, "<html><body>Please solve the captcha</body></html>")

    assert verdict.blocked is True


def test_long_chapter_mentioning_captcha_is_kept():
    """A chapter is allowed to talk about captchas without being discarded."""
    body = "<html><body>" + "Hắn nhìn captcha trên màn hình. " * 300 + "</body></html>"

    assert block.inspect(200, body).blocked is False


def test_other_statuses_are_not_blocked():
    assert block.inspect(301, "").blocked is False
    assert block.inspect(404, "").blocked is False
