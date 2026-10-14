"""Fetch failures, split by what the caller should do about them.

The split matters: a blocked request needs a different fetcher or a proxy, a
transient one just needs another try, and a missing page means the chapter
list is stale. Lumping them together is how crawlers end up saving challenge
pages as chapter text.
"""

from __future__ import annotations


class FetchError(Exception):
    """Base class. Carries the URL so logs point at something actionable."""

    def __init__(self, message: str, *, url: str, status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.url = url
        self.status = status

    def __str__(self) -> str:
        suffix = f" (HTTP {self.status})" if self.status else ""
        return f"{self.message}{suffix}: {self.url}"


class Blocked(FetchError):
    """The site refused us, or answered with an anti-bot challenge.

    Retrying the same way will not help. The crawl should switch to the
    browser fetcher, add a proxy or cookies, or stop and report.
    """

    def __init__(self, message: str, *, url: str, status: int | None = None,
                 reason: str | None = None) -> None:
        super().__init__(message, url=url, status=status)
        self.reason = reason or message


class NotFound(FetchError):
    """404/410. The page is gone; the chapter list is probably out of date."""


class TransientError(FetchError):
    """Timeout, connection reset, 5xx. Worth retrying."""


class RateLimited(TransientError):
    """429. Retry, but slower, and honour Retry-After when present."""

    def __init__(self, message: str, *, url: str, status: int | None = None,
                 retry_after: float | None = None) -> None:
        super().__init__(message, url=url, status=status)
        self.retry_after = retry_after
