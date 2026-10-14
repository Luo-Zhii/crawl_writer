"""HTTP fetching layer."""

from app.fetch.base import Fetcher, Response
from app.fetch.browser import BrowserFetcher, BrowserUnavailable
from app.fetch.errors import (
    Blocked,
    FetchError,
    NotFound,
    RateLimited,
    TransientError,
)
from app.fetch.http import HttpFetcher
from app.fetch.smart import SmartFetcher, hosts_needing_browser

__all__ = [
    "Blocked",
    "BrowserFetcher",
    "BrowserUnavailable",
    "FetchError",
    "Fetcher",
    "HttpFetcher",
    "NotFound",
    "RateLimited",
    "Response",
    "SmartFetcher",
    "TransientError",
    "hosts_needing_browser",
]
