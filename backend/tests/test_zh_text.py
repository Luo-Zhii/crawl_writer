"""Chinese text helpers: chapter numbering and script conversion."""

from __future__ import annotations

import pytest

from app.sources.zh_text import (
    chinese_to_int,
    looks_traditional,
    parse_chapter_number,
    to_simplified,
    to_traditional,
)

# --- Chinese numerals ------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("一", 1),
        ("九", 9),
        ("十", 10),  # a bare 十 is ten, not zero tens
        ("十五", 15),
        ("二十", 20),
        ("二十五", 25),
        ("九十九", 99),
        ("一百", 100),
        ("一百零八", 108),
        ("二百五十", 250),
        ("一千", 1000),
        ("一千二百", 1200),
        ("两", 2),
        ("零", 0),
    ],
)
def test_chinese_numerals(text: str, expected: int):
    assert chinese_to_int(text) == expected


def test_non_numeral_text_is_rejected():
    assert chinese_to_int("雷火館") is None
    assert chinese_to_int("") is None


# --- chapter numbers -------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("第12章 雷火館", 12),
        ("第 12 章 雷火館", 12),
        ("第12节 甲", 12),
        ("第12回 甲", 12),
        ("第十二章 雷火館", 12),
        ("第一百零八回 丙", 108),
        ("Chapter 7: something", 7),
        ("chapter 7", 7),
        ("12. 甲乙丙", 12),
        ("12、甲乙丙", 12),
    ],
)
def test_chapter_numbers_are_parsed_from_titles(title: str, expected: int):
    """Chinese sites put database ids in URLs, so the title is the only source."""
    assert parse_chapter_number(title) == expected


@pytest.mark.parametrize("title", ["新書感言", "作者的話", "番外", "", "序章"])
def test_front_matter_has_no_number(title: str):
    """Returning None lets the caller decide, rather than inventing a number."""
    assert parse_chapter_number(title) is None


def test_arabic_wins_over_chinese_when_both_appear():
    assert parse_chapter_number("第3章 第十二節的回憶") == 3


# --- script conversion -----------------------------------------------------


def test_traditional_to_simplified():
    assert to_simplified("繁體連載") == "繁体连载"


def test_simplified_to_traditional():
    assert to_traditional("简体连载") == "簡體連載"


def test_conversion_leaves_other_text_alone():
    assert to_simplified("ABC 123") == "ABC 123"
    assert to_simplified("") == ""


def test_round_trip_keeps_meaning():
    original = "这个世界的灵气已经稀薄"

    assert to_simplified(to_traditional(original)) == original


def test_script_detection():
    traditional = "這個世界的靈氣已經稀薄到幾乎無法修煉的程度" * 3
    simplified = "这个世界的灵气已经稀薄到几乎无法修炼的程度" * 3

    assert looks_traditional(traditional) is True
    assert looks_traditional(simplified) is False


def test_script_detection_on_empty_or_latin_text():
    assert looks_traditional("") is False
    assert looks_traditional("plain ascii text") is False
