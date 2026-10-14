"""The fetcher contract.

Adapters only ever see this interface, so swapping an httpx request for a real
browser (Cloudflare-protected sites) changes nothing above this layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(slots=True)
class Response:
    """A fetched page, already decoded to text."""

    url: str
    status: int
    text: str
    content: bytes = b""
    encoding: str = "utf-8"
    headers: dict[str, str] = field(default_factory=dict)
    # True when the body came from a real browser rather than a plain request.
    from_browser: bool = False

    def __len__(self) -> int:
        return len(self.text)


@runtime_checkable
class Fetcher(Protocol):
    """Anything that can turn a URL into a :class:`Response`.

    Implementations raise from ``app.fetch.errors``: ``Blocked`` when the site
    refuses or challenges us, ``NotFound`` for 404/410, ``TransientError``
    when retries ran out.
    """

    async def get(self, url: str, *, referer: str | None = None,
                  encoding: str | None = None) -> Response: ...

    async def aclose(self) -> None: ...
