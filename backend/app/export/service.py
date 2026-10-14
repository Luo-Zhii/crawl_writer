"""Export orchestration.

Loads a novel plus whatever chapter text is on disk, then hands it to the
writer for the requested format. Only chapters that actually downloaded are
included: a half-finished crawl still exports cleanly, just shorter.
"""

from __future__ import annotations

import zipfile
from enum import StrEnum
from pathlib import Path

from app.core.logging import get_logger
from app.core.settings import Settings, get_settings
from app.db.models import ChapterStatus, Novel
from app.db.repository import ChapterRepository, NovelRepository
from app.db.session import session_scope
from app.db.storage import ChapterStorage
from app.export import epub as epub_writer
from app.export import json_export, txt
from app.export.base import ExportedChapter, ExportResult, export_filename, slugify

log = get_logger(__name__)


class ExportFormat(StrEnum):
    txt = "txt"
    json = "json"
    epub = "epub"


MEDIA_TYPES = {
    ExportFormat.txt: "text/plain; charset=utf-8",
    ExportFormat.json: "application/json",
    ExportFormat.epub: "application/epub+zip",
}


class NothingToExport(Exception):
    """No chapter text on disk yet, so there is no book to build."""


class ExportService:
    def __init__(
        self,
        *,
        storage: ChapterStorage | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.storage = storage or ChapterStorage()
        self.settings = settings or get_settings()

    # --- loading -----------------------------------------------------------

    def load(
        self, novel_id: int, *, translated: bool = False
    ) -> tuple[Novel, list[ExportedChapter], list[int]]:
        """Read the novel row and every chapter whose text exists on disk."""
        with session_scope() as session:
            novel = NovelRepository(session).get(novel_id)
            if novel is None:
                raise LookupError(f"Novel {novel_id} not found")

            rows = ChapterRepository(session).list_for_novel(novel_id)
            chapters: list[ExportedChapter] = []
            missing: list[int] = []

            for row in rows:
                if row.status is not ChapterStatus.done:
                    continue
                text = self.storage.read(novel_id, row.number, translated=translated)
                if text is None and translated:
                    # Fall back to the original so a partially translated novel
                    # still exports as a complete book.
                    text = self.storage.read(novel_id, row.number)
                if not text or not text.strip():
                    missing.append(row.number)
                    continue
                chapters.append(
                    ExportedChapter(
                        number=row.number,
                        title=row.title,
                        text=text,
                        volume=row.volume,
                    )
                )

            session.expunge(novel)
            return novel, chapters, missing

    # --- exporting ---------------------------------------------------------

    def export(
        self,
        novel_id: int,
        fmt: ExportFormat,
        *,
        translated: bool = False,
        volume_size: int | None = None,
    ) -> ExportResult:
        novel, chapters, missing = self.load(novel_id, translated=translated)
        if not chapters:
            raise NothingToExport(
                f"No downloaded chapters for novel {novel_id}; run a crawl first"
            )

        out_dir = self.settings.exports_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        if fmt is ExportFormat.txt:
            filename = export_filename(novel, "txt", translated=translated)
            path = txt.write(novel, chapters, out_dir / filename)
            parts = 1
        elif fmt is ExportFormat.json:
            filename = export_filename(novel, "json", translated=translated)
            path = json_export.write(
                novel, chapters, out_dir / filename, translated=translated
            )
            parts = 1
        else:
            path, filename, parts = self._export_epub(
                novel, chapters, out_dir, translated=translated, volume_size=volume_size
            )

        result = ExportResult(
            path=path,
            filename=filename,
            media_type="application/zip" if parts > 1 else MEDIA_TYPES[fmt],
            chapters=len(chapters),
            missing=missing,
            parts=parts,
        )
        log.info(
            "exported novel %s as %s: %d chapters, %d part(s), %d bytes",
            novel_id,
            fmt.value,
            result.chapters,
            result.parts,
            result.size_bytes,
        )
        return result

    def _export_epub(
        self,
        novel: Novel,
        chapters: list[ExportedChapter],
        out_dir: Path,
        *,
        translated: bool,
        volume_size: int | None,
    ) -> tuple[Path, str, int]:
        cover = self.storage.find_cover(novel.id)

        if not volume_size or len(chapters) <= volume_size:
            filename = export_filename(novel, "epub", translated=translated)
            path = epub_writer.write(novel, chapters, out_dir / filename, cover=cover)
            return path, filename, 1

        # Long novels are split: a single 5000-chapter EPUB is slow to open on
        # a phone, and some readers simply give up on it.
        batches = [
            chapters[start : start + volume_size]
            for start in range(0, len(chapters), volume_size)
        ]
        slug = slugify(novel.title)
        suffix = "-vi" if translated else ""
        parts: list[Path] = []

        for index, batch in enumerate(batches, start=1):
            part_name = f"{slug}{suffix}-phan-{index}.epub"
            parts.append(
                epub_writer.write(
                    novel,
                    batch,
                    out_dir / part_name,
                    cover=cover,
                    title_suffix=f" — Phần {index}/{len(batches)}",
                )
            )

        zip_name = f"{slug}{suffix}-epub.zip"
        zip_path = out_dir / zip_name
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for part in parts:
                archive.write(part, arcname=part.name)
                # The zip is what gets downloaded; the loose parts would just
                # take up space twice.
                part.unlink(missing_ok=True)

        return zip_path, zip_name, len(batches)
