"""The translation provider contract and text chunking.

Providers all answer the same question — turn this Chinese text into
Vietnamese — but they differ wildly in cost, quality and how much text they
accept per call, so the pipeline treats them as interchangeable and lets the
user pick.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod


class TranslationError(Exception):
    """A provider could not translate this text."""

    def __init__(self, message: str, *, provider: str, retryable: bool = True) -> None:
        super().__init__(f"{provider}: {message}")
        self.message = message
        self.provider = provider
        #: False for things another attempt will not fix (bad key, bad request).
        self.retryable = retryable


class ProviderUnavailable(TranslationError):
    """The provider is not usable at all, e.g. no API key configured."""

    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(message, provider=provider, retryable=False)


class TranslateProvider(ABC):
    """Translates text between two languages."""

    #: Stable id used in settings and in the cache key.
    key: str = ""
    #: Human readable name for the UI.
    name: str = ""
    #: Largest chunk this provider should be sent, in characters.
    chunk_limit: int = 2000
    #: True when the provider bills per token, so the cache matters more.
    metered: bool = False

    @abstractmethod
    async def translate(
        self,
        text: str,
        *,
        source_lang: str,
        target_lang: str,
        glossary: dict[str, str] | None = None,
    ) -> str:
        """Translate one chunk. Must raise :class:`TranslationError` on failure."""

    async def aclose(self) -> None:  # noqa: B027 - optional hook, not every provider owns a client
        """Release any client this provider owns."""


# --- chunking --------------------------------------------------------------

# Split on blank lines first: paragraphs are the unit that survives
# translation intact.
_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")
# Chinese and Latin sentence enders, kept with the sentence they close.
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;…])")


def split_paragraphs(text: str) -> list[str]:
    return [part.strip() for part in _PARAGRAPH_SPLIT.split(text) if part.strip()]


def chunk_text(text: str, limit: int) -> list[str]:
    """Group text into chunks no longer than ``limit`` characters.

    Paragraphs are kept whole wherever possible, because a sentence split
    across two requests loses the context the translator needs and often comes
    back with a different tone. A paragraph longer than the limit is split on
    sentence boundaries, and only a single sentence longer than the limit is
    cut by length.
    """
    if limit <= 0:
        raise ValueError("limit must be positive")

    chunks: list[str] = []
    current: list[str] = []
    size = 0

    def flush() -> None:
        nonlocal current, size
        if current:
            chunks.append("\n\n".join(current))
            current = []
            size = 0

    for paragraph in split_paragraphs(text):
        if len(paragraph) > limit:
            flush()
            chunks.extend(_split_long(paragraph, limit))
            continue

        # +2 for the blank line that will rejoin them.
        if size and size + len(paragraph) + 2 > limit:
            flush()
        current.append(paragraph)
        size += len(paragraph) + 2

    flush()
    return chunks


def _split_long(paragraph: str, limit: int) -> list[str]:
    pieces: list[str] = []
    current = ""

    for sentence in _SENTENCE_SPLIT.split(paragraph):
        if not sentence:
            continue
        if len(sentence) > limit:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(_hard_split(sentence, limit))
            continue
        if len(current) + len(sentence) > limit:
            pieces.append(current)
            current = sentence
        else:
            current += sentence

    if current:
        pieces.append(current)
    return pieces


def _hard_split(sentence: str, limit: int) -> list[str]:
    """Last resort for a sentence with no usable punctuation.

    Cuts at the last space before the limit so words stay whole — which also
    protects glossary names, since those have been substituted in by now and
    are Latin script with spaces. Chinese prose has no spaces, so there the
    cut falls on the limit itself.
    """
    pieces: list[str] = []
    rest = sentence

    while len(rest) > limit:
        window = rest[:limit]
        cut = window.rfind(" ")
        # Only honour a space that is not right at the start, otherwise a
        # leading space would make no progress.
        if cut <= 0:
            cut = limit
        pieces.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()

    if rest:
        pieces.append(rest)
    return pieces
