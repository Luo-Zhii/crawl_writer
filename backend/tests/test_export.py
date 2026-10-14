"""Exporters: TXT, JSON and EPUB.

The EPUB tests read the file back with ebooklib rather than just checking it
exists, since a corrupt archive still looks fine on disk.
"""

from __future__ import annotations

import json
import zipfile

import pytest
from ebooklib import epub as ebooklib_epub

from app.db.models import ChapterStatus, Lang
from app.db.repository import ChapterRepository
from app.db.storage import ChapterStorage
from app.export import ExportFormat, ExportService, NothingToExport
from app.export.base import ExportedChapter, chapter_heading, export_filename, slugify
from app.export.service import MEDIA_TYPES

BODY = "Mưa rơi trên mái ngói cũ.\n\nHắn lau lưỡi kiếm rồi bước vào thành."


# --- helpers ---------------------------------------------------------------


def seeded_novel(novel_factory, session, *, chapters: int = 3, translated: int = 0):
    """A novel with real text on disk, optionally with translations too."""
    novel = novel_factory(title="Kiếm Khách Vô Danh", chapters=chapters)
    storage = ChapterStorage()
    repo = ChapterRepository(session)

    for number in range(1, chapters + 1):
        storage.write(novel.id, number, f"Chương {number}\n\n{BODY}")
        row = repo.get_by_number(novel.id, number)
        repo.update(row, title=f"Chương {number}: Mưa trên thành cổ")
        if number <= translated:
            storage.write(novel.id, number, f"Chuong {number} da dich\n\n{BODY}",
                          translated=True)
            repo.update(row, has_translation=True)

    return novel


# --- slug and filename -----------------------------------------------------


def test_slugify_flattens_vietnamese_diacritics():
    assert slugify("Kiếm Khách Vô Danh") == "kiem-khach-vo-danh"
    assert slugify("Đấu Phá Thương Khung") == "dau-pha-thuong-khung"


def test_slugify_handles_unusable_titles():
    assert slugify("《仙門》") == "truyen"
    assert slugify("") == "truyen"
    assert slugify("a/b\\c:d") == "a-b-c-d"


def test_export_filename_marks_translations(novel_factory):
    novel = novel_factory(title="Tiên Môn")

    assert export_filename(novel, "epub") == "tien-mon.epub"
    assert export_filename(novel, "epub", translated=True) == "tien-mon-vi.epub"


def test_chapter_heading_avoids_duplicating_the_number():
    with_label = ExportedChapter(number=3, title="Chương 3: Thanh kiếm cũ", text="x")
    without = ExportedChapter(number=3, title="Thanh kiếm cũ", text="x")
    bare = ExportedChapter(number=3, title="", text="x")

    assert chapter_heading(with_label) == "Chương 3: Thanh kiếm cũ"
    assert chapter_heading(without) == "Chương 3: Thanh kiếm cũ"
    assert chapter_heading(bare) == "Chương 3"


# --- loading ---------------------------------------------------------------


def test_load_reads_text_from_disk(novel_factory, session):
    novel = seeded_novel(novel_factory, session, chapters=2)

    loaded, chapters, missing = ExportService().load(novel.id)

    assert loaded.title == "Kiếm Khách Vô Danh"
    assert [c.number for c in chapters] == [1, 2]
    assert BODY.split("\n\n")[0] in chapters[0].text
    assert missing == []


def test_load_skips_chapters_that_never_downloaded(novel_factory, session):
    novel = seeded_novel(novel_factory, session, chapters=3)
    repo = ChapterRepository(session)
    repo.update(repo.get_by_number(novel.id, 2), status=ChapterStatus.failed)

    _, chapters, _ = ExportService().load(novel.id)

    assert [c.number for c in chapters] == [1, 3]


def test_load_reports_rows_whose_file_vanished(novel_factory, session):
    """Marked done in the database but the file is gone."""
    novel = seeded_novel(novel_factory, session, chapters=2)
    ChapterStorage().delete_chapter(novel.id, 1)

    _, chapters, missing = ExportService().load(novel.id)

    assert [c.number for c in chapters] == [2]
    assert missing == [1]


def test_load_prefers_the_translation_when_asked(novel_factory, session):
    novel = seeded_novel(novel_factory, session, chapters=2, translated=2)

    _, chapters, _ = ExportService().load(novel.id, translated=True)

    assert all("da dich" in c.text for c in chapters)


def test_translated_export_falls_back_to_the_original(novel_factory, session):
    """A partly translated novel should still export as a whole book."""
    novel = seeded_novel(novel_factory, session, chapters=3, translated=1)

    _, chapters, missing = ExportService().load(novel.id, translated=True)

    assert len(chapters) == 3
    assert "da dich" in chapters[0].text
    assert "da dich" not in chapters[1].text
    assert missing == []


def test_load_unknown_novel_raises():
    with pytest.raises(LookupError):
        ExportService().load(4242)


# --- txt -------------------------------------------------------------------


def test_txt_export_contains_header_and_every_chapter(novel_factory, session):
    novel = seeded_novel(novel_factory, session, chapters=3)

    result = ExportService().export(novel.id, ExportFormat.txt)

    assert result.filename == "kiem-khach-vo-danh.txt"
    assert result.media_type == MEDIA_TYPES[ExportFormat.txt]
    assert result.chapters == 3

    text = result.path.read_text(encoding="utf-8")
    assert "Kiếm Khách Vô Danh" in text
    assert "Tác giả: Tác giả" in text
    assert novel.source_url in text
    for number in (1, 2, 3):
        assert f"Chương {number}: Mưa trên thành cổ" in text


# --- json ------------------------------------------------------------------


def test_json_export_structure(novel_factory, session):
    novel = seeded_novel(novel_factory, session, chapters=2)

    result = ExportService().export(novel.id, ExportFormat.json)
    payload = json.loads(result.path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["novel"]["title"] == "Kiếm Khách Vô Danh"
    assert payload["novel"]["source"] == "demo"
    assert payload["novel"]["lang"] == Lang.vi.value
    assert payload["export"]["chapter_count"] == 2
    assert [c["number"] for c in payload["chapters"]] == [1, 2]
    assert payload["chapters"][0]["text"]


def test_json_export_keeps_unicode_readable(novel_factory, session):
    novel = seeded_novel(novel_factory, session, chapters=1)

    result = ExportService().export(novel.id, ExportFormat.json)

    assert "Kiếm Khách" in result.path.read_text(encoding="utf-8")


# --- epub ------------------------------------------------------------------


def test_epub_is_a_valid_readable_book(novel_factory, session):
    novel = seeded_novel(novel_factory, session, chapters=3)

    result = ExportService().export(novel.id, ExportFormat.epub)

    assert result.filename == "kiem-khach-vo-danh.epub"
    assert result.media_type == "application/epub+zip"
    assert zipfile.is_zipfile(result.path)

    book = ebooklib_epub.read_epub(str(result.path))
    assert book.get_metadata("DC", "title")[0][0] == "Kiếm Khách Vô Danh"
    assert book.get_metadata("DC", "creator")[0][0] == "Tác giả"
    assert book.get_metadata("DC", "source")[0][0] == novel.source_url


def test_epub_has_a_chapter_per_downloaded_chapter(novel_factory, session):
    novel = seeded_novel(novel_factory, session, chapters=4)

    result = ExportService().export(novel.id, ExportFormat.epub)
    book = ebooklib_epub.read_epub(str(result.path))

    chapter_files = [
        item.file_name
        for item in book.get_items()
        if item.file_name.startswith("chap_")
    ]
    assert len(chapter_files) == 4
    # Zero padded so the archive sorts in reading order.
    assert chapter_files == sorted(chapter_files)
    assert "chap_00001.xhtml" in chapter_files


def test_epub_toc_lists_the_chapters(novel_factory, session):
    novel = seeded_novel(novel_factory, session, chapters=2)

    result = ExportService().export(novel.id, ExportFormat.epub)
    book = ebooklib_epub.read_epub(str(result.path))

    titles = [entry.title for entry in book.toc]
    assert "Thông tin truyện" in titles
    assert any("Chương 1" in title for title in titles)


def test_epub_escapes_markup_in_the_text(novel_factory, session):
    """Raw < or & in a chapter would otherwise corrupt the XHTML."""
    novel = seeded_novel(novel_factory, session, chapters=1)
    ChapterStorage().write(novel.id, 1, "Hắn nói <b>a & b</b> rồi đi.")

    result = ExportService().export(novel.id, ExportFormat.epub)
    book = ebooklib_epub.read_epub(str(result.path))

    body = next(
        item.get_content().decode("utf-8")
        for item in book.get_items()
        if item.file_name == "chap_00001.xhtml"
    )
    assert "&lt;b&gt;" in body
    assert "&amp;" in body


def test_epub_embeds_a_stored_cover(novel_factory, session):
    novel = seeded_novel(novel_factory, session, chapters=1)
    # A minimal PNG is enough to prove the image travels into the archive.
    png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c6300010000050001"
        "0d0a2db40000000049454e44ae426082"
    )
    ChapterStorage().write_cover(novel.id, png, suffix=".png")

    result = ExportService().export(novel.id, ExportFormat.epub)

    with zipfile.ZipFile(result.path) as archive:
        assert any("cover" in name for name in archive.namelist())


def test_epub_without_a_cover_still_builds(novel_factory, session):
    novel = seeded_novel(novel_factory, session, chapters=1)

    result = ExportService().export(novel.id, ExportFormat.epub)

    assert zipfile.is_zipfile(result.path)


# --- volume splitting ------------------------------------------------------


def test_large_novel_splits_into_a_zip_of_parts(novel_factory, session):
    novel = seeded_novel(novel_factory, session, chapters=5)

    result = ExportService().export(novel.id, ExportFormat.epub, volume_size=50)

    # Below the threshold: still one file.
    assert result.parts == 1
    assert result.filename.endswith(".epub")


def test_split_produces_one_epub_per_batch(novel_factory, session):
    novel = seeded_novel(novel_factory, session, chapters=5)

    # The API enforces a minimum of 50; the service itself takes any size.
    result = ExportService().export(novel.id, ExportFormat.epub, volume_size=2)

    assert result.parts == 3
    assert result.filename == "kiem-khach-vo-danh-epub.zip"
    assert result.media_type == "application/zip"

    with zipfile.ZipFile(result.path) as archive:
        names = sorted(archive.namelist())
    assert names == [
        "kiem-khach-vo-danh-phan-1.epub",
        "kiem-khach-vo-danh-phan-2.epub",
        "kiem-khach-vo-danh-phan-3.epub",
    ]


def test_split_parts_are_valid_books(novel_factory, session, tmp_path):
    novel = seeded_novel(novel_factory, session, chapters=4)

    result = ExportService().export(novel.id, ExportFormat.epub, volume_size=2)

    with zipfile.ZipFile(result.path) as archive:
        archive.extractall(tmp_path / "parts")

    first = tmp_path / "parts" / "kiem-khach-vo-danh-phan-1.epub"
    book = ebooklib_epub.read_epub(str(first))
    assert "Phần 1/2" in book.get_metadata("DC", "title")[0][0]
    chapters = [i for i in book.get_items() if i.file_name.startswith("chap_")]
    assert len(chapters) == 2


def test_loose_parts_are_cleaned_up_after_zipping(novel_factory, session):
    novel = seeded_novel(novel_factory, session, chapters=4)
    service = ExportService()

    service.export(novel.id, ExportFormat.epub, volume_size=2)

    leftovers = list(service.settings.exports_dir.glob("*-phan-*.epub"))
    assert leftovers == [], "the zip is what gets downloaded; parts are redundant"


# --- nothing to export -----------------------------------------------------


@pytest.mark.parametrize("fmt", list(ExportFormat))
def test_export_without_downloaded_chapters_is_refused(novel_factory, fmt):
    novel = novel_factory()  # rows only, no text on disk

    with pytest.raises(NothingToExport):
        ExportService().export(novel.id, fmt)


def test_export_unknown_novel_raises():
    with pytest.raises(LookupError):
        ExportService().export(4242, ExportFormat.txt)
