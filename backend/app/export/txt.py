"""Plain text export.

One file for the whole novel, with a short header and chapters separated by a
rule. Deliberately boring: the point is that any reader, phone app or script
can open it.
"""

from __future__ import annotations

from pathlib import Path

from app.db.models import Novel
from app.export.base import ExportedChapter, chapter_heading

_SEPARATOR = "\n\n" + "-" * 60 + "\n\n"


def render(novel: Novel, chapters: list[ExportedChapter]) -> str:
    header = [novel.title]
    if novel.author:
        header.append(f"Tác giả: {novel.author}")
    if novel.genres:
        header.append(f"Thể loại: {', '.join(novel.genres)}")
    header.append(f"Nguồn: {novel.source_url}")
    header.append(f"Số chương: {len(chapters)}")
    if novel.description:
        header.append("")
        header.append(novel.description)

    body = [f"{chapter_heading(chapter)}\n\n{chapter.text.strip()}" for chapter in chapters]
    return "\n".join(header) + _SEPARATOR + _SEPARATOR.join(body) + "\n"


def write(novel: Novel, chapters: list[ExportedChapter], target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(novel, chapters), encoding="utf-8")
    return target
