"""Keeping proper nouns consistent.

Machine translation renders the same character name several different ways
across a long novel, which is the single biggest thing that makes a translated
book hard to follow. A glossary pins each name to one reading.

The substitution happens *before* the text is sent: replacing 萧炎 with
"Tiêu Viêm" up front works because translators leave Latin-script words they
do not recognise alone, whereas asking them nicely afterwards does not. A
second pass afterwards repairs the cases where a translator still mangled
spacing or capitalisation.
"""

from __future__ import annotations

import re

from app.core.logging import get_logger

log = get_logger(__name__)


class Glossary:
    """A set of source -> target term replacements."""

    def __init__(self, terms: dict[str, str] | None = None) -> None:
        # Longest first so 萧炎天 is replaced before 萧炎.
        cleaned = (
            (source.strip(), target.strip())
            for source, target in (terms or {}).items()
            if source.strip() and target.strip()
        )
        self._terms = dict(
            sorted(cleaned, key=lambda item: len(item[0]), reverse=True)
        )
        self._pattern = self._build_pattern()

    def _build_pattern(self) -> re.Pattern[str] | None:
        if not self._terms:
            return None
        return re.compile("|".join(re.escape(term) for term in self._terms))

    def __len__(self) -> int:
        return len(self._terms)

    def __bool__(self) -> bool:
        return bool(self._terms)

    @property
    def terms(self) -> dict[str, str]:
        return dict(self._terms)

    # --- passes ------------------------------------------------------------

    def apply(self, text: str) -> str:
        """Replace source terms with their target reading, before translating."""
        if self._pattern is None or not text:
            return text
        return self._pattern.sub(lambda match: self._terms[match.group(0)], text)

    def repair(self, text: str) -> str:
        """Fix target terms the translator damaged, after translating.

        Translators sometimes re-space or re-case a name they were handed
        ("TiêuViêm", "tiêu viêm"), so each target term is matched loosely and
        rewritten to its canonical form.
        """
        if not self._terms or not text:
            return text

        for target in set(self._terms.values()):
            text = _canonicalise(text, target)
        return text

    def missing_from(self, text: str) -> list[str]:
        """Source terms that survived translation untranslated.

        Useful as a warning: if a Chinese name is still in the output, the
        glossary substitution did not take and the chapter will read oddly.
        """
        return [term for term in self._terms if term in text]


def _canonicalise(text: str, target: str) -> str:
    """Rewrite loose spellings of ``target`` back to ``target``."""
    words = target.split()
    if len(words) < 2:
        return text

    # "Tiêu Viêm" also matches "TiêuViêm", "tiêu  viêm", "Tiêu-Viêm".
    loose = r"[\s\-]*".join(re.escape(word) for word in words)
    pattern = re.compile(loose, re.IGNORECASE)
    return pattern.sub(target, text)


def normalise_source(text: str, *, to_simplified: bool = True) -> str:
    """Normalise the script before matching glossary terms.

    The same novel is mirrored on simplified and traditional sites, so a
    glossary built from one would silently miss on the other.
    """
    if not to_simplified:
        return text
    from app.sources.zh_text import to_simplified as convert

    return convert(text)
