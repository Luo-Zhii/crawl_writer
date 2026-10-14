"""Adapter registry: URL in, the right adapter out."""

from __future__ import annotations

from app.fetch.base import Fetcher
from app.sources.base import Source


class UnsupportedSite(Exception):
    def __init__(self, url: str) -> None:
        super().__init__(f"No adapter handles this URL: {url}")
        self.url = url


_REGISTRY: list[type[Source]] = []


def register(source_cls: type[Source]) -> type[Source]:
    """Class decorator that makes an adapter discoverable."""
    if not source_cls.key:
        raise ValueError(f"{source_cls.__name__} must define a key")
    existing = {cls.key for cls in _REGISTRY}
    if source_cls.key in existing:
        raise ValueError(f"Duplicate source key: {source_cls.key}")
    _REGISTRY.append(source_cls)
    return source_cls


def all_sources() -> list[type[Source]]:
    return list(_REGISTRY)


def find_for_url(url: str) -> type[Source] | None:
    for source_cls in _REGISTRY:
        if source_cls.handles(url):
            return source_cls
    return None


def get_by_key(key: str) -> type[Source] | None:
    for source_cls in _REGISTRY:
        if source_cls.key == key:
            return source_cls
    return None


def resolve(url: str, fetcher: Fetcher) -> Source:
    """Build the adapter for ``url``, or raise :class:`UnsupportedSite`."""
    source_cls = find_for_url(url)
    if source_cls is None:
        raise UnsupportedSite(url)
    return source_cls(fetcher)
