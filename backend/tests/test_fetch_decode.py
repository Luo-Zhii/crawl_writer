"""Byte-to-text decoding, mostly for Chinese raw sites."""

from __future__ import annotations

from app.fetch.decode import charset_from_content_type, charset_from_meta, decode

GBK_TEXT = "第一章 开始修炼"


def test_utf8_page():
    text, encoding = decode("Chương 1: Khởi đầu".encode(), content_type="text/html; charset=utf-8")

    assert text == "Chương 1: Khởi đầu"
    assert encoding == "utf-8"


def test_meta_charset_wins_over_missing_header():
    """Typical 69shu/biquge page: GBK declared only in the markup."""
    raw = f'<meta http-equiv="Content-Type" content="text/html; charset=gbk">{GBK_TEXT}'.encode(
        "gb18030"
    )

    text, encoding = decode(raw)

    assert GBK_TEXT in text
    assert encoding == "gb18030"


def test_gb2312_is_widened_to_gb18030():
    """Sites declare gb2312 but use characters outside it; decoding must not fail."""
    raw = f'<meta charset="gb2312">{GBK_TEXT}'.encode("gb18030")

    text, encoding = decode(raw)

    assert GBK_TEXT in text
    assert encoding == "gb18030"


def test_meta_outranks_a_wrong_header():
    """A server claiming utf-8 while sending GBK would otherwise give mojibake."""
    raw = f'<meta charset="gbk">{GBK_TEXT}'.encode("gb18030")

    text, _ = decode(raw, content_type="text/html; charset=utf-8")

    assert GBK_TEXT in text


def test_explicit_override_wins():
    raw = GBK_TEXT.encode("gb18030")

    text, encoding = decode(raw, override="gb18030")

    assert text == GBK_TEXT
    assert encoding == "gb18030"


def test_detection_when_nothing_is_declared():
    raw = GBK_TEXT.encode("gb18030")

    text, encoding = decode(raw)

    assert GBK_TEXT in text
    assert encoding


def test_iso_8859_1_default_is_treated_as_utf8():
    """Servers that set no charset get labelled latin-1; that is almost never true."""
    text, _ = decode("Chương 1".encode(), content_type="text/html; charset=iso-8859-1")

    assert text == "Chương 1"


def test_unknown_charset_falls_back_instead_of_raising():
    text, encoding = decode("Chương 1".encode(), override="not-a-real-charset")

    assert "Chương 1" in text
    assert encoding


def test_empty_body():
    assert decode(b"") == ("", "utf-8")


def test_charset_helpers():
    assert charset_from_content_type("text/html; charset=UTF-8") == "utf-8"
    assert charset_from_content_type("text/html") is None
    assert charset_from_meta(b"<meta charset='gbk'>") == "gb18030"
    assert charset_from_meta(b"<html><body>no meta</body></html>") is None
