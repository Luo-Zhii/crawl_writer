"""Chapter text storage on disk."""

from __future__ import annotations

from app.db.storage import ChapterStorage


def test_write_then_read_roundtrip(storage: ChapterStorage):
    text = "Chương 1\n\nTiêu Viêm mở mắt.\n"
    count = storage.write(1, 1, text)

    assert count == len(text)
    assert storage.read(1, 1) == text
    assert storage.exists(1, 1)


def test_read_missing_returns_none(storage: ChapterStorage):
    assert storage.read(999, 1) is None
    assert not storage.exists(999, 1)


def test_translation_is_separate_from_original(storage: ChapterStorage):
    storage.write(1, 1, "原文内容")
    storage.write(1, 1, "Nội dung đã dịch", translated=True)

    assert storage.read(1, 1) == "原文内容"
    assert storage.read(1, 1, translated=True) == "Nội dung đã dịch"
    assert storage.path(1, 1) != storage.path(1, 1, translated=True)


def test_filenames_are_zero_padded_so_listing_sorts(storage: ChapterStorage):
    for number in (1, 2, 10, 100):
        storage.write(7, number, f"ch {number}")

    names = sorted(p.name for p in storage.novel_dir(7).glob("*.txt"))
    assert names == ["00001.txt", "00002.txt", "00010.txt", "00100.txt"]


def test_write_leaves_no_partial_file(storage: ChapterStorage):
    storage.write(1, 1, "xong")
    leftovers = list(storage.novel_dir(1).glob("*.part"))
    assert leftovers == []


def test_delete_chapter_removes_both_variants(storage: ChapterStorage):
    storage.write(1, 1, "goc")
    storage.write(1, 1, "dich", translated=True)

    storage.delete_chapter(1, 1)

    assert not storage.exists(1, 1)
    assert not storage.exists(1, 1, translated=True)


def test_delete_novel_removes_directory(storage: ChapterStorage):
    storage.write(5, 1, "a")
    storage.write(5, 2, "b")

    storage.delete_novel(5)

    assert not storage.novel_dir(5).exists()


def test_delete_novel_is_safe_when_missing(storage: ChapterStorage):
    storage.delete_novel(424242)  # must not raise


def test_disk_usage_counts_stored_bytes(storage: ChapterStorage):
    assert storage.disk_usage(3) == 0

    storage.write(3, 1, "abcd")
    storage.write(3, 2, "ef")

    assert storage.disk_usage(3) == 6
