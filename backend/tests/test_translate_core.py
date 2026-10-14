"""Chunking, glossary and cache — the parts that decide whether a translated
book reads consistently."""

from __future__ import annotations

import pytest
from sqlmodel import Session

from app.translate.base import chunk_text, split_paragraphs
from app.translate.cache import TranslationCacheStore, cache_key
from app.translate.glossary import Glossary

# --- chunking --------------------------------------------------------------


def test_short_text_is_one_chunk():
    assert chunk_text("một đoạn ngắn", 100) == ["một đoạn ngắn"]


def test_empty_text_produces_no_chunks():
    assert chunk_text("", 100) == []
    assert chunk_text("   \n\n  ", 100) == []


def test_paragraphs_are_grouped_up_to_the_limit():
    text = "\n\n".join(["a" * 30, "b" * 30, "c" * 30])

    chunks = chunk_text(text, 70)

    assert len(chunks) == 2
    assert chunks[0] == "a" * 30 + "\n\n" + "b" * 30


def test_paragraph_breaks_survive_chunking():
    """Translators keep blank lines, so the text must arrive with them."""
    text = "đoạn một\n\nđoạn hai"

    assert chunk_text(text, 100) == ["đoạn một\n\nđoạn hai"]


def test_a_paragraph_longer_than_the_limit_is_split_on_sentences():
    paragraph = "第一句。" * 20  # 80 chars, sentences of 4

    chunks = chunk_text(paragraph, 20)

    assert all(len(chunk) <= 20 for chunk in chunks)
    # Sentences stay whole: every piece ends on a full stop.
    assert all(chunk.endswith("。") for chunk in chunks)
    assert "".join(chunks) == paragraph


def test_a_single_enormous_sentence_is_cut_by_length():
    """Nothing else to do, but it must not be dropped."""
    sentence = "x" * 50

    chunks = chunk_text(sentence, 20)

    assert "".join(chunks) == sentence
    assert all(len(chunk) <= 20 for chunk in chunks)


def test_no_chunk_exceeds_the_limit():
    text = "\n\n".join("句子。" * 10 for _ in range(10))

    assert all(len(chunk) <= 120 for chunk in chunk_text(text, 120))


def test_nothing_is_lost_while_chunking():
    text = "\n\n".join(f"đoạn số {i} " + "nội dung " * 10 for i in range(8))

    rejoined = "\n\n".join(chunk_text(text, 200))

    assert split_paragraphs(rejoined) == split_paragraphs(text)


def test_limit_must_be_positive():
    with pytest.raises(ValueError):
        chunk_text("abc", 0)


# --- glossary --------------------------------------------------------------


def test_terms_are_substituted_before_translation():
    glossary = Glossary({"萧炎": "Tiêu Viêm"})

    assert glossary.apply("萧炎走了进来") == "Tiêu Viêm走了进来"


def test_longer_terms_win_over_shorter_prefixes():
    """Otherwise 萧炎天 would become "Tiêu Viêm天"."""
    glossary = Glossary({"萧炎": "Tiêu Viêm", "萧炎天": "Tiêu Viêm Thiên"})

    assert glossary.apply("萧炎天和萧炎") == "Tiêu Viêm Thiên和Tiêu Viêm"


def test_an_empty_glossary_changes_nothing():
    glossary = Glossary()

    assert glossary.apply("原文不变") == "原文不变"
    assert not glossary
    assert len(glossary) == 0


def test_blank_entries_are_ignored():
    glossary = Glossary({"  ": "x", "萧炎": "  ", "药老": "Dược Lão"})

    assert glossary.terms == {"药老": "Dược Lão"}


def test_repair_fixes_a_mangled_name():
    """Translators re-space and re-case names they were handed."""
    glossary = Glossary({"萧炎": "Tiêu Viêm"})

    assert glossary.repair("TiêuViêm bước vào") == "Tiêu Viêm bước vào"
    assert glossary.repair("tiêu viêm bước vào") == "Tiêu Viêm bước vào"
    assert glossary.repair("Tiêu-Viêm bước vào") == "Tiêu Viêm bước vào"


def test_repair_leaves_single_word_targets_alone():
    """Too risky: a one-word name would match ordinary prose."""
    glossary = Glossary({"丹": "Đan"})

    assert glossary.repair("đan dược") == "đan dược"


def test_leftover_source_terms_are_reported():
    """A Chinese name still in the output means the substitution missed."""
    glossary = Glossary({"萧炎": "Tiêu Viêm", "药老": "Dược Lão"})

    assert glossary.missing_from("萧炎 và Dược Lão") == ["萧炎"]
    assert glossary.missing_from("Tiêu Viêm và Dược Lão") == []


# --- cache -----------------------------------------------------------------


def test_cache_key_depends_on_everything_that_matters():
    base = cache_key("google", "zh", "vi", "文本")

    assert base == cache_key("google", "zh", "vi", "文本")
    assert base != cache_key("gemini", "zh", "vi", "文本"), "provider must count"
    assert base != cache_key("google", "zh", "en", "文本"), "target lang must count"
    assert base != cache_key("google", "zh", "vi", "别的"), "text must count"


def test_cache_round_trip(session: Session):
    store = TranslationCacheStore(session)

    assert store.get("google", "zh", "vi", "文本") is None

    store.put("google", "zh", "vi", "文本", "văn bản")

    assert store.get("google", "zh", "vi", "文本") == "văn bản"
    assert store.count() == 1


def test_cache_is_scoped_per_provider(session: Session):
    """Switching engine must not serve the previous engine's output."""
    store = TranslationCacheStore(session)
    store.put("google", "zh", "vi", "文本", "bản google")

    assert store.get("gemini", "zh", "vi", "文本") is None


def test_putting_the_same_key_twice_keeps_the_first(session: Session):
    store = TranslationCacheStore(session)
    store.put("google", "zh", "vi", "文本", "lần một")

    store.put("google", "zh", "vi", "文本", "lần hai")

    assert store.get("google", "zh", "vi", "文本") == "lần một"
    assert store.count() == 1


def test_cache_can_be_cleared(session: Session):
    """Needed after a glossary change: cached text predates the new terms."""
    store = TranslationCacheStore(session)
    store.put("google", "zh", "vi", "a", "A")
    store.put("gemini", "zh", "vi", "b", "B")

    removed = store.clear(provider="google")

    assert removed == 1
    assert store.get("google", "zh", "vi", "a") is None
    assert store.get("gemini", "zh", "vi", "b") == "B"


def test_clearing_everything(session: Session):
    store = TranslationCacheStore(session)
    store.put("google", "zh", "vi", "a", "A")
    store.put("gemini", "zh", "vi", "b", "B")

    assert store.clear() == 2
    assert store.count() == 0


def test_a_long_latin_sentence_is_cut_between_words():
    """Glossary names are Latin script by the time chunking runs, so cutting
    mid-word would damage them."""
    sentence = "Tiêu Viêm bước vào sân luyện đan rồi ngồi xuống bên lò"

    chunks = chunk_text(sentence, 20)

    assert all(len(chunk) <= 20 for chunk in chunks)
    # No chunk starts or ends mid-word.
    assert "Tiêu Viêm" in chunks[0]
    assert all(chunk == chunk.strip() for chunk in chunks)
    assert " ".join(chunks).split() == sentence.split()


def test_chinese_prose_without_spaces_still_gets_cut():
    """There is no word boundary to find, so the limit itself is the cut."""
    sentence = "一" * 50

    chunks = chunk_text(sentence, 20)

    assert "".join(chunks) == sentence
    assert all(len(chunk) <= 20 for chunk in chunks)
