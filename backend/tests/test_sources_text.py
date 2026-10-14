"""Chapter text cleaning."""

from __future__ import annotations

from bs4 import BeautifulSoup

from app.sources.text import clean_container, clean_title, looks_like_content, normalise


def container(html: str):
    return BeautifulSoup(f"<div id='chapter-c'>{html}</div>", "lxml").select_one("#chapter-c")


def test_br_becomes_paragraph_breaks():
    text = clean_container(container("Dòng một.<br>Dòng hai.<br><br>Dòng ba."))

    assert "Dòng một." in text
    assert "Dòng hai." in text
    assert text.count("\n\n") >= 1


def test_paragraph_tags_are_kept_apart():
    text = clean_container(container("<p>Câu một.</p><p>Câu hai.</p>"))

    assert "Câu một.\n\nCâu hai." in text


def test_script_and_style_are_removed():
    text = clean_container(container("Nội dung.<script>var a=1;</script><style>p{}</style>"))

    assert "var a" not in text
    assert "p{}" not in text


def test_ad_containers_are_removed():
    html = (
        "<div class='ads-holder quangcao'>Đặt quảng cáo</div>"
        "Nội dung thật."
        "<ins class='adsbygoogle'></ins>"
        "<div class='share-buttons social'>Chia sẻ</div>"
    )

    text = clean_container(container(html))

    assert "Nội dung thật." in text
    assert "quảng cáo" not in text.lower()
    assert "Chia sẻ" not in text


def test_nested_ad_containers_are_handled():
    """Live pages nest ad slots; dropping the outer one must not break the walk."""
    html = (
        "<div class='ads'><div class='banner'><ins class='adsbygoogle'>"
        "<span class='sponsor'>Quảng cáo</span></ins></div></div>"
        "Nội dung thật."
    )

    text = clean_container(container(html))

    assert "Nội dung thật." in text
    assert "Quảng cáo" not in text


def test_credit_and_source_lines_are_dropped():
    html = "Nội dung.<br>Đọc truyện tại truyenhoan.com<br>Nguồn: sưu tầm<br>Tiếp tục."

    text = clean_container(container(html))

    assert "Nội dung." in text
    assert "Tiếp tục." in text
    assert "truyenhoan.com" not in text
    assert "Nguồn" not in text


def test_separator_lines_are_dropped():
    text = clean_container(container("Trên.<br>---<br>Dưới."))

    assert "---" not in text
    assert "Trên." in text and "Dưới." in text


def test_zero_width_characters_are_stripped():
    """Some sites inject these to break naive scrapers."""
    text = normalise("Nội\u200bdung\ufeff bình thường")

    assert "\u200b" not in text
    assert "\ufeff" not in text


def test_whitespace_is_collapsed():
    assert normalise("Nhiều    khoảng   trắng") == "Nhiều khoảng trắng"
    assert normalise("Dùng\u00a0nbsp") == "Dùng nbsp"


def test_blank_line_runs_are_capped():
    assert normalise("Một\n\n\n\n\nHai") == "Một\n\nHai"


def test_leading_and_trailing_blank_lines_are_trimmed():
    assert normalise("\n\n  Nội dung  \n\n") == "Nội dung"


def test_looks_like_content_guards_against_empty_chapters():
    assert looks_like_content("x" * 250) is True
    assert looks_like_content("quá ngắn") is False
    assert looks_like_content("") is False
    assert looks_like_content("x" * 50, minimum=10) is True


def test_clean_title_fixes_split_labels():
    """Site markup splits the word across spans, giving "Chương12"."""
    assert clean_title("Chương12") == "Chương 12"
    assert clean_title("Chương  7") == "Chương 7"


def test_clean_title_trims_punctuation_and_novel_name():
    assert clean_title("  Chương 3: Thanh kiếm cũ  ") == "Chương 3: Thanh kiếm cũ"
    assert clean_title("- Chương 5 -") == "Chương 5"
