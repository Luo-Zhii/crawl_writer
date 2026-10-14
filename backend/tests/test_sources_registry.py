"""Adapter registry and the URL -> adapter lookup."""

from __future__ import annotations

import pytest

from app.db.models import Lang
from app.sources import registry
from app.sources.base import Source
from app.sources.registry import UnsupportedSite, resolve
from app.sources.truyenhoan import TruyenHoan


class DummyFetcher:
    async def get(self, url, *, referer=None, encoding=None):  # pragma: no cover
        raise NotImplementedError

    async def aclose(self):  # pragma: no cover
        pass


def test_truyenhoan_is_registered():
    assert TruyenHoan in registry.all_sources()
    assert registry.get_by_key("truyenhoan") is TruyenHoan


def test_lookup_by_url():
    assert registry.find_for_url("https://truyenhoan.com/abc.123/") is TruyenHoan
    assert registry.find_for_url("https://www.truyenhoan.com/abc.123/") is TruyenHoan


def test_lookup_covers_alias_domain():
    """truyenfull.tv redirects to truyenhoan, so the same adapter serves both."""
    assert registry.find_for_url("https://truyenfull.tv/abc.123/") is TruyenHoan


def test_subdomains_are_matched():
    assert registry.find_for_url("https://m.truyenhoan.com/abc.123/") is TruyenHoan


def test_unknown_site_returns_none():
    assert registry.find_for_url("https://example.com/truyen/abc") is None


def test_resolve_builds_an_adapter_instance():
    fetcher = DummyFetcher()
    source = resolve("https://truyenhoan.com/abc.123/", fetcher)

    assert isinstance(source, TruyenHoan)
    assert source.fetcher is fetcher


def test_resolve_raises_for_unsupported_site():
    with pytest.raises(UnsupportedSite) as exc:
        resolve("https://example.com/truyen/abc", DummyFetcher())

    assert "example.com" in str(exc.value)


def test_every_adapter_declares_its_metadata():
    """Guards against a new adapter shipping without the fields the UI needs."""
    for source_cls in registry.all_sources():
        assert source_cls.key, f"{source_cls.__name__} has no key"
        assert source_cls.name, f"{source_cls.key} has no display name"
        assert source_cls.domains, f"{source_cls.key} declares no domains"
        assert isinstance(source_cls.lang, Lang)
        assert all(not d.startswith("www.") for d in source_cls.domains)


def test_duplicate_keys_are_rejected():
    class Clashing(Source):
        key = "truyenhoan"
        name = "Clash"
        domains = ("clash.test",)

        def canonical_url(self, url):  # pragma: no cover
            return url

        async def novel_info(self, url):  # pragma: no cover
            ...

        async def chapter_list(self, url):  # pragma: no cover
            ...

        async def chapter_content(self, url):  # pragma: no cover
            ...

    with pytest.raises(ValueError, match="Duplicate source key"):
        registry.register(Clashing)


def test_adapter_without_a_key_is_rejected():
    class Keyless(Source):
        name = "No key"
        domains = ("keyless.test",)

        def canonical_url(self, url):  # pragma: no cover
            return url

        async def novel_info(self, url):  # pragma: no cover
            ...

        async def chapter_list(self, url):  # pragma: no cover
            ...

        async def chapter_content(self, url):  # pragma: no cover
            ...

    with pytest.raises(ValueError, match="must define a key"):
        registry.register(Keyless)


async def test_search_is_optional():
    source = TruyenHoan(DummyFetcher())

    # The base class refuses rather than silently returning nothing, so a
    # caller can tell "no results" from "not supported".
    class Minimal(Source):
        key = "minimal-test"
        name = "Minimal"
        domains = ("minimal.test",)

        def canonical_url(self, url):
            return url

        async def novel_info(self, url):  # pragma: no cover
            ...

        async def chapter_list(self, url):  # pragma: no cover
            ...

        async def chapter_content(self, url):  # pragma: no cover
            ...

    with pytest.raises(NotImplementedError):
        await Minimal(DummyFetcher()).search("abc")

    assert source.lang is Lang.vi
