"""Chinese text helpers.

Two jobs. First, chapter numbering: Chinese sites almost never put the chapter
number in the URL — those are database ids — but they do put it in the title
as ``第12章`` or ``第十二章``, so that is where the number has to come from.

Second, script conversion. The same novel is mirrored on simplified and
traditional sites, and a glossary of character names built from one will not
match the other, so translation normalises to one script first.
"""

from __future__ import annotations

import re
from functools import lru_cache

# 第12章 / 第12节 / 第12回, with or without spaces.
_ARABIC_CHAPTER = re.compile(r"第\s*(\d+)\s*[章节節回]")
# 第十二章 and friends.
_CHINESE_CHAPTER = re.compile(r"第\s*([零一二三四五六七八九十百千万〇两]+)\s*[章节節回]")
# "Chapter 12" on bilingual sites, and a bare leading number.
_LATIN_CHAPTER = re.compile(r"(?i)\bchapter\s*(\d+)")
_LEADING_NUMBER = re.compile(r"^\s*(\d{1,5})\s*[.、:：]")

_DIGITS = {
    "零": 0, "〇": 0,
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}


def chinese_to_int(text: str) -> int | None:
    """Convert a Chinese numeral to an int.

    Handles the forms that actually appear in chapter titles: 五, 十, 十五,
    二十, 二十五, 一百零八, 一千二百.
    """
    if not text:
        return None

    total = 0
    section = 0
    current = 0
    seen = False

    for char in text:
        if char in _DIGITS:
            current = _DIGITS[char]
            seen = True
        elif char in _UNITS:
            unit = _UNITS[char]
            # A bare 十 means ten, not zero times ten.
            if current == 0 and not section and unit == 10:
                current = 1
            if unit >= 10000:
                section = (section + current) * unit
                total += section
                section = 0
            else:
                section += (current or 1) * unit
            current = 0
            seen = True
        else:
            return None

    if not seen:
        return None
    return total + section + current


def parse_chapter_number(title: str) -> int | None:
    """Pull the chapter number out of a chapter title.

    Returns None when the title carries no number — author notes and prologues
    usually do not — so the caller can decide what to do about it.
    """
    if not title:
        return None

    match = _ARABIC_CHAPTER.search(title)
    if match:
        return int(match.group(1))

    match = _CHINESE_CHAPTER.search(title)
    if match:
        return chinese_to_int(match.group(1))

    match = _LATIN_CHAPTER.search(title)
    if match:
        return int(match.group(1))

    match = _LEADING_NUMBER.match(title)
    if match:
        return int(match.group(1))

    return None


@lru_cache(maxsize=4)
def _converter(config: str):
    """Build an OpenCC converter, or None when it is unavailable.

    Conversion is a nicety: if the dictionaries are missing we would rather
    store the original text than fail a crawl.
    """
    try:
        from opencc import OpenCC
    except ImportError:  # pragma: no cover - depends on install
        return None
    try:
        return OpenCC(config)
    except Exception:  # pragma: no cover - bad config or missing data
        return None


def to_simplified(text: str) -> str:
    """Traditional to simplified. Returns the input unchanged on failure."""
    if not text:
        return text
    converter = _converter("t2s")
    if converter is None:
        return text
    try:
        return converter.convert(text)
    except Exception:  # pragma: no cover
        return text


def to_traditional(text: str) -> str:
    """Simplified to traditional."""
    if not text:
        return text
    converter = _converter("s2t")
    if converter is None:
        return text
    try:
        return converter.convert(text)
    except Exception:  # pragma: no cover
        return text


def looks_traditional(text: str, *, sample: int = 400) -> bool:
    """Guess whether ``text`` is traditional Chinese.

    Compares the sample against its own simplified form: if converting changes
    a noticeable share of characters, it was traditional to begin with.
    """
    snippet = text[:sample]
    if not snippet.strip():
        return False
    converted = to_simplified(snippet)
    if converted == snippet:
        return False
    changed = sum(1 for a, b in zip(snippet, converted, strict=False) if a != b)
    return changed / max(len(snippet), 1) > 0.02
