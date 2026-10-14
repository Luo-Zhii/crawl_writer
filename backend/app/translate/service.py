"""Translation orchestration: chunking, glossary, cache and failover.

Providers only know how to translate one chunk. Everything that makes a whole
chapter come out readable happens here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.core.logging import get_logger
from app.db.session import session_scope
from app.translate.base import (
    ProviderUnavailable,
    TranslateProvider,
    TranslationError,
    chunk_text,
)
from app.translate.cache import TranslationCacheStore
from app.translate.glossary import Glossary

log = get_logger(__name__)

DEFAULT_SOURCE = "zh"
DEFAULT_TARGET = "vi"


@dataclass(slots=True)
class TranslationResult:
    text: str
    provider: str
    chunks: int = 0
    #: Chunks served from the cache rather than translated again.
    cached: int = 0
    #: Source terms still present afterwards, i.e. glossary misses.
    leftover_terms: list[str] = field(default_factory=list)


class TranslationService:
    """Translates chapter text using the first provider that works."""

    def __init__(
        self,
        providers: Sequence[TranslateProvider],
        *,
        glossary: Glossary | None = None,
        use_cache: bool = True,
        source_lang: str = DEFAULT_SOURCE,
        target_lang: str = DEFAULT_TARGET,
    ) -> None:
        if not providers:
            raise ValueError("at least one provider is required")
        self.providers = list(providers)
        self.glossary = glossary or Glossary()
        self.use_cache = use_cache
        self.source_lang = source_lang
        self.target_lang = target_lang

    @property
    def primary(self) -> TranslateProvider:
        return self.providers[0]

    # --- the work ----------------------------------------------------------

    async def translate(self, text: str) -> TranslationResult:
        """Translate a whole chapter."""
        if not text.strip():
            return TranslationResult(text=text, provider=self.primary.key)

        # Glossary terms go in before the text is split, so a name sitting on
        # a chunk boundary is still replaced as one piece.
        prepared = self.glossary.apply(text)

        last_error: TranslationError | None = None
        for provider in self.providers:
            try:
                result = await self._translate_with(provider, prepared)
            except ProviderUnavailable as exc:
                # Not configured: skip quietly, it is not a failure.
                log.debug("skipping %s: %s", provider.key, exc.message)
                last_error = exc
                continue
            except TranslationError as exc:
                log.warning("%s failed, trying the next provider: %s", provider.key, exc.message)
                last_error = exc
                continue

            result.text = self.glossary.repair(result.text)
            result.leftover_terms = self.glossary.missing_from(result.text)
            if result.leftover_terms:
                log.info(
                    "%d glossary term(s) survived translation untranslated",
                    len(result.leftover_terms),
                )
            return result

        assert last_error is not None
        raise last_error

    async def _translate_with(
        self, provider: TranslateProvider, prepared: str
    ) -> TranslationResult:
        chunks = chunk_text(prepared, provider.chunk_limit)
        out: list[str] = []
        cached = 0

        for chunk in chunks:
            hit = self._cache_get(provider.key, chunk)
            if hit is not None:
                out.append(hit)
                cached += 1
                continue

            translated = await provider.translate(
                chunk,
                source_lang=self.source_lang,
                target_lang=self.target_lang,
                glossary=self.glossary.terms or None,
            )
            self._cache_put(provider.key, chunk, translated)
            out.append(translated)

        return TranslationResult(
            text="\n\n".join(part.strip() for part in out if part.strip()),
            provider=provider.key,
            chunks=len(chunks),
            cached=cached,
        )

    # --- cache -------------------------------------------------------------

    def _cache_get(self, provider: str, chunk: str) -> str | None:
        if not self.use_cache:
            return None
        with session_scope() as session:
            return TranslationCacheStore(session).get(
                provider, self.source_lang, self.target_lang, chunk
            )

    def _cache_put(self, provider: str, chunk: str, translated: str) -> None:
        if not self.use_cache:
            return
        with session_scope() as session:
            TranslationCacheStore(session).put(
                provider, self.source_lang, self.target_lang, chunk, translated
            )

    async def aclose(self) -> None:
        for provider in self.providers:
            await provider.aclose()


# --- building the provider chain -------------------------------------------


def build_providers(
    *,
    preferred: str | None = None,
    api_keys: dict[str, str | None] | None = None,
) -> list[TranslateProvider]:
    """Assemble the provider chain, preferred first, Google last as a fallback.

    Google needs no key and always works well enough, so it stays at the end
    of the chain: if a paid provider is misconfigured or rate limited, the
    translation still completes rather than failing the job.
    """
    from app.translate.google import GoogleTranslateProvider
    from app.translate.llm import LLM_PROVIDERS

    keys = api_keys or {}
    chain: list[TranslateProvider] = []

    if preferred and preferred in LLM_PROVIDERS:
        key = keys.get(preferred)
        if key:
            chain.append(LLM_PROVIDERS[preferred](key))
        else:
            log.info("preferred provider %s has no API key; falling back", preferred)

    if preferred != "google":
        # Any other configured LLM, so a dead primary has somewhere to go.
        for name, cls in LLM_PROVIDERS.items():
            if name == preferred:
                continue
            if keys.get(name):
                chain.append(cls(keys[name]))

    chain.append(GoogleTranslateProvider())
    return chain


def glossary_for(novel_id: int) -> Glossary:
    """Load a novel's glossary."""
    from app.db.repository import GlossaryRepository

    with session_scope() as session:
        terms = GlossaryRepository(session).as_mapping(novel_id)
    return Glossary(terms)
