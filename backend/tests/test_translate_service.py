"""Translation orchestration: failover, caching and glossary passes."""

from __future__ import annotations

import pytest
from sqlmodel import Session

from app.translate.base import ProviderUnavailable, TranslateProvider, TranslationError
from app.translate.cache import TranslationCacheStore
from app.translate.glossary import Glossary
from app.translate.service import TranslationService, build_providers


class FakeProvider(TranslateProvider):
    """Records what it was asked and answers however the test wants."""

    def __init__(
        self,
        key: str = "fake",
        *,
        chunk_limit: int = 100,
        fail: Exception | None = None,
        prefix: str = "[vi] ",
    ) -> None:
        self.key = key
        self.name = key.title()
        self.chunk_limit = chunk_limit
        self._fail = fail
        self._prefix = prefix
        self.calls: list[str] = []
        self.glossaries: list[dict[str, str] | None] = []
        self.closed = False

    async def translate(self, text, *, source_lang, target_lang, glossary=None):
        self.calls.append(text)
        self.glossaries.append(glossary)
        if self._fail is not None:
            raise self._fail
        return self._prefix + text

    async def aclose(self) -> None:
        self.closed = True


# --- the happy path --------------------------------------------------------


async def test_translates_a_whole_chapter():
    provider = FakeProvider()
    service = TranslationService([provider], use_cache=False)

    result = await service.translate("第一段\n\n第二段")

    assert result.text.startswith("[vi]")
    assert result.provider == "fake"
    assert result.chunks == 1


async def test_blank_text_is_returned_unchanged():
    provider = FakeProvider()
    service = TranslationService([provider], use_cache=False)

    result = await service.translate("   ")

    assert result.text == "   "
    assert provider.calls == []


async def test_long_text_is_sent_in_several_chunks():
    provider = FakeProvider(chunk_limit=30)
    service = TranslationService([provider], use_cache=False)

    result = await service.translate("\n\n".join("đoạn " * 5 for _ in range(4)))

    assert result.chunks > 1
    assert len(provider.calls) == result.chunks


async def test_paragraph_structure_survives():
    provider = FakeProvider(chunk_limit=20, prefix="")
    service = TranslationService([provider], use_cache=False)

    result = await service.translate("một\n\nhai\n\nba")

    assert result.text == "một\n\nhai\n\nba"


def test_at_least_one_provider_is_required():
    with pytest.raises(ValueError):
        TranslationService([])


# --- glossary --------------------------------------------------------------


async def test_glossary_is_applied_before_sending():
    """Substituting up front is what makes the name survive translation."""
    provider = FakeProvider(prefix="")
    service = TranslationService(
        [provider], glossary=Glossary({"萧炎": "Tiêu Viêm"}), use_cache=False
    )

    result = await service.translate("萧炎走了进来")

    assert "Tiêu Viêm" in provider.calls[0]
    assert "萧炎" not in result.text


async def test_glossary_is_also_passed_to_the_provider():
    """LLMs do better with the terms in the prompt as well."""
    provider = FakeProvider()
    service = TranslationService(
        [provider], glossary=Glossary({"萧炎": "Tiêu Viêm"}), use_cache=False
    )

    await service.translate("萧炎")

    assert provider.glossaries[0] == {"萧炎": "Tiêu Viêm"}


async def test_glossary_repairs_a_mangled_name_afterwards():
    provider = FakeProvider(prefix="")

    class Mangling(FakeProvider):
        async def translate(self, text, *, source_lang, target_lang, glossary=None):
            self.calls.append(text)
            return text.replace("Tiêu Viêm", "TiêuViêm")

    provider = Mangling(prefix="")
    service = TranslationService(
        [provider], glossary=Glossary({"萧炎": "Tiêu Viêm"}), use_cache=False
    )

    result = await service.translate("萧炎走了")

    assert "Tiêu Viêm" in result.text
    assert "TiêuViêm" not in result.text


async def test_untranslated_terms_are_reported():
    class Passthrough(FakeProvider):
        async def translate(self, text, *, source_lang, target_lang, glossary=None):
            return text

    service = TranslationService(
        [Passthrough()], glossary=Glossary({"药老": "Dược Lão"}), use_cache=False
    )

    # The glossary substitutes it, so nothing is left over.
    assert (await service.translate("药老")).leftover_terms == []


async def test_a_term_survives_when_the_text_is_split():
    """Glossary runs before chunking, so a name is never half-substituted."""
    provider = FakeProvider(chunk_limit=20, prefix="")
    service = TranslationService(
        [provider], glossary=Glossary({"萧炎": "Tiêu Viêm"}), use_cache=False
    )

    result = await service.translate("第一段很长很长很长。\n\n萧炎走了进来。")

    assert result.chunks > 1, "the text should have been split"
    assert "Tiêu Viêm" in result.text


# --- failover --------------------------------------------------------------


async def test_falls_through_to_the_next_provider_on_failure():
    broken = FakeProvider("broken", fail=TranslationError("boom", provider="broken"))
    working = FakeProvider("working")
    service = TranslationService([broken, working], use_cache=False)

    result = await service.translate("文本")

    assert result.provider == "working"


async def test_unconfigured_providers_are_skipped_quietly():
    missing = FakeProvider(
        "gemini", fail=ProviderUnavailable("no key", provider="gemini")
    )
    google = FakeProvider("google")
    service = TranslationService([missing, google], use_cache=False)

    result = await service.translate("文本")

    assert result.provider == "google"


async def test_the_last_error_is_raised_when_everything_fails():
    first = FakeProvider("a", fail=TranslationError("first", provider="a"))
    second = FakeProvider("b", fail=TranslationError("second", provider="b"))
    service = TranslationService([first, second], use_cache=False)

    with pytest.raises(TranslationError, match="second"):
        await service.translate("文本")


async def test_closing_closes_every_provider():
    first, second = FakeProvider("a"), FakeProvider("b")
    service = TranslationService([first, second], use_cache=False)

    await service.aclose()

    assert first.closed and second.closed


# --- caching ---------------------------------------------------------------


async def test_identical_text_is_only_translated_once(session: Session):
    provider = FakeProvider()
    service = TranslationService([provider], use_cache=True)

    first = await service.translate("第一段")
    second = await service.translate("第一段")

    assert len(provider.calls) == 1, "the second pass should come from the cache"
    assert second.text == first.text
    assert second.cached == 1


async def test_cache_is_written_through(session: Session):
    service = TranslationService([FakeProvider()], use_cache=True)

    await service.translate("第一段")

    assert TranslationCacheStore(session).count() == 1


async def test_switching_provider_bypasses_the_cache(session: Session):
    """The two engines give different output; serving the old one would lie."""
    first = FakeProvider("google", prefix="[google] ")
    await TranslationService([first], use_cache=True).translate("第一段")

    second = FakeProvider("gemini", prefix="[gemini] ")
    result = await TranslationService([second], use_cache=True).translate("第一段")

    assert result.text.startswith("[gemini]")
    assert len(second.calls) == 1


async def test_cache_can_be_disabled(session: Session):
    provider = FakeProvider()
    service = TranslationService([provider], use_cache=False)

    await service.translate("第一段")
    await service.translate("第一段")

    assert len(provider.calls) == 2
    assert TranslationCacheStore(session).count() == 0


# --- provider chain --------------------------------------------------------


def test_google_is_always_the_last_resort():
    """It needs no key, so a misconfigured paid provider never fails a job."""
    chain = build_providers(preferred="gemini", api_keys={"gemini": "k"})

    assert [p.key for p in chain][0] == "gemini"
    assert chain[-1].key == "google"


def test_preferred_provider_without_a_key_is_dropped():
    chain = build_providers(preferred="openai", api_keys={})

    assert [p.key for p in chain] == ["google"]


def test_other_configured_providers_become_fallbacks():
    chain = build_providers(
        preferred="gemini", api_keys={"gemini": "a", "anthropic": "b"}
    )

    keys = [p.key for p in chain]
    assert keys[0] == "gemini"
    assert "anthropic" in keys
    assert keys[-1] == "google"


def test_choosing_google_gives_just_google():
    chain = build_providers(preferred="google", api_keys={"gemini": "a"})

    assert [p.key for p in chain] == ["google"]
