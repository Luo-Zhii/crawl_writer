"""Caching translated chunks.

Two reasons this exists. LLM providers bill per token, so re-translating a
novel after fixing one chapter would cost the whole book again. And a crawl
that is interrupted halfway should resume without redoing work, exactly like
chapter downloads do.
"""

from __future__ import annotations

import hashlib

from sqlmodel import Session, delete, func, select

from app.core.logging import get_logger
from app.db.models import TranslationCache

log = get_logger(__name__)


def cache_key(provider: str, source_lang: str, target_lang: str, text: str) -> str:
    """Hash of everything that would change the answer.

    The provider is part of the key on purpose: the same paragraph translated
    by Google and by an LLM are different results, and switching provider
    should not silently serve the old one.
    """
    digest = hashlib.sha256()
    digest.update(provider.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(f"{source_lang}>{target_lang}".encode())
    digest.update(b"\x00")
    digest.update(text.encode("utf-8"))
    return digest.hexdigest()


class TranslationCacheStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, provider: str, source_lang: str, target_lang: str, text: str) -> str | None:
        row = self.session.get(
            TranslationCache, cache_key(provider, source_lang, target_lang, text)
        )
        return row.text if row is not None else None

    def put(
        self, provider: str, source_lang: str, target_lang: str, text: str, translated: str
    ) -> None:
        key = cache_key(provider, source_lang, target_lang, text)
        if self.session.get(TranslationCache, key) is not None:
            return
        self.session.add(
            TranslationCache(
                key=key,
                provider=provider,
                source_lang=source_lang,
                target_lang=target_lang,
                text=translated,
            )
        )
        self.session.commit()

    def count(self) -> int:
        return self.session.exec(select(func.count()).select_from(TranslationCache)).one()

    def clear(self, *, provider: str | None = None) -> int:
        """Drop cached translations. Returns how many rows went.

        Needed when a glossary changes: the cached text was translated without
        the new terms, so serving it would quietly ignore the fix.
        """
        before = self.count()
        statement = delete(TranslationCache)
        if provider is not None:
            statement = statement.where(TranslationCache.provider == provider)
        self.session.exec(statement)
        self.session.commit()
        return before - self.count()
