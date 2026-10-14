"""Detecting "the site said no".

Anti-bot pages are the main trap when crawling novel sites: many answer with
HTTP 200 and a body full of JavaScript, so a naive crawler happily stores the
challenge page as chapter text. We look at both the status code and the body.
"""

from __future__ import annotations

from dataclasses import dataclass

# Status codes that mean "refused", not "broken". Cloudflare's 52x family is
# about its own link to the origin, so retrying the same request rarely helps
# inside one crawl; we surface it instead of burning retries.
BLOCKED_STATUSES: dict[int, str] = {
    401: "authentication required",
    403: "forbidden",
    451: "blocked for legal reasons",
    520: "Cloudflare: unknown origin error",
    521: "Cloudflare: origin refused the connection",
    522: "Cloudflare: origin connection timed out",
    523: "Cloudflare: origin unreachable",
    524: "Cloudflare: origin timed out",
    525: "Cloudflare: TLS handshake with origin failed",
    526: "Cloudflare: invalid origin certificate",
    527: "Cloudflare: railgun error",
}

# Fragments that only ever appear on an interstitial, never in a chapter.
_STRONG_MARKERS: tuple[str, ...] = (
    "/cdn-cgi/challenge-platform",
    "cf-browser-verification",
    "cf_chl_opt",
    "__cf_chl_",
    "jschl_vc",
    "jschl-answer",
    "ddos-guard",
    "_incapsula_resource",
    "sucuri_cloudproxy",
    "attention required! | cloudflare",
    "just a moment...",
    "checking your browser before accessing",
    "enable javascript and cookies to continue",
    "verifying you are human",
    "请开启javascript",
    "浏览器安全检查中",
    "访问验证",
)

# Weaker hints. A real chapter can mention a captcha, so these only count when
# the body is too short to be a chapter.
_WEAK_MARKERS: tuple[str, ...] = (
    "captcha",
    "recaptcha",
    "hcaptcha",
    "turnstile",
    "robot",
    "人机验证",
    "验证码",
)

# Below this, a 200 response is too thin to be a real page.
_THIN_BODY_CHARS = 2500


@dataclass(frozen=True)
class BlockVerdict:
    blocked: bool
    reason: str | None = None


def inspect(status: int, body: str, *, headers: dict[str, str] | None = None) -> BlockVerdict:
    """Decide whether a response is a refusal or a challenge rather than content."""
    if status in BLOCKED_STATUSES:
        return BlockVerdict(True, BLOCKED_STATUSES[status])

    # Cloudflare marks its own interstitials; 503 + this header is a challenge,
    # while a bare 503 is just an overloaded site worth retrying.
    server = (headers or {}).get("server", "").lower()
    if status == 503 and ("cloudflare" in server or "ddos-guard" in server):
        return BlockVerdict(True, "anti-bot challenge (HTTP 503)")

    if status != 200:
        return BlockVerdict(False)

    lowered = body.lower()
    for marker in _STRONG_MARKERS:
        if marker in lowered:
            return BlockVerdict(True, f"anti-bot challenge page (matched {marker!r})")

    if len(body) < _THIN_BODY_CHARS:
        for marker in _WEAK_MARKERS:
            if marker in lowered:
                return BlockVerdict(True, f"short page mentioning {marker!r}, likely a challenge")

    return BlockVerdict(False)
