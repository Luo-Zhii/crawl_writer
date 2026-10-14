"""EPUB export.

This is the format that matters for actually reading: it gives a table of
contents, remembers where you were, and works on phones and e-readers without
any conversion step.
"""

from __future__ import annotations

import html
import mimetypes
from pathlib import Path

from ebooklib import epub

from app.core.logging import get_logger
from app.db.models import Novel
from app.export.base import ExportedChapter, chapter_heading

log = get_logger(__name__)

# Styling stays minimal so the reader's own font and theme settings win.
_CSS = """
body { font-family: serif; line-height: 1.6; margin: 1em; }
h1, h2 { line-height: 1.3; }
p { margin: 0 0 0.9em 0; text-indent: 1.2em; }
.meta { color: #555; font-size: 0.9em; }
.meta p { text-indent: 0; }
"""


def _paragraphs(text: str) -> str:
    """Turn blank-line separated text into escaped XHTML paragraphs."""
    blocks = [block.strip() for block in text.split("\n\n") if block.strip()]
    out: list[str] = []
    for block in blocks:
        # Single newlines inside a block are soft breaks, not new paragraphs.
        escaped = html.escape(block).replace("\n", "<br/>")
        out.append(f"<p>{escaped}</p>")
    return "\n".join(out) or "<p></p>"


def _title_page(novel: Novel, chapter_count: int) -> epub.EpubHtml:
    rows = []
    if novel.author:
        rows.append(f"<p>Tác giả: {html.escape(novel.author)}</p>")
    if novel.genres:
        rows.append(f"<p>Thể loại: {html.escape(', '.join(novel.genres))}</p>")
    rows.append(f"<p>Số chương: {chapter_count}</p>")
    rows.append(f"<p>Nguồn: {html.escape(novel.source_url)}</p>")
    if novel.description:
        rows.append(f"<div>{_paragraphs(novel.description)}</div>")

    page = epub.EpubHtml(
        title="Thông tin truyện", file_name="title.xhtml", lang=novel.lang.value
    )
    page.content = (
        f"<h1>{html.escape(novel.title)}</h1>"
        f"<div class='meta'>{''.join(rows)}</div>"
    )
    return page


def _attach_cover(book: epub.EpubBook, cover: Path) -> None:
    media_type, _ = mimetypes.guess_type(cover.name)
    if media_type is None or not media_type.startswith("image/"):
        log.debug("skipping cover %s: unrecognised image type", cover)
        return
    book.set_cover(cover.name, cover.read_bytes())


def write(
    novel: Novel,
    chapters: list[ExportedChapter],
    target: Path,
    *,
    cover: Path | None = None,
    title_suffix: str = "",
) -> Path:
    """Write one EPUB file containing ``chapters``."""
    target.parent.mkdir(parents=True, exist_ok=True)

    book = epub.EpubBook()
    title = f"{novel.title}{title_suffix}"

    # A stable identifier means re-exporting updates the same book on a
    # reader rather than adding a duplicate.
    book.set_identifier(f"crawlw-{novel.source}-{novel.id}{title_suffix}")
    book.set_title(title)
    book.set_language(novel.lang.value)
    if novel.author:
        book.add_author(novel.author)
    book.add_metadata("DC", "source", novel.source_url)
    if novel.description:
        book.add_metadata("DC", "description", novel.description)
    for genre in novel.genres or []:
        book.add_metadata("DC", "subject", genre)

    if cover is not None and cover.exists():
        _attach_cover(book, cover)

    style = epub.EpubItem(
        uid="style",
        file_name="style/main.css",
        media_type="text/css",
        content=_CSS,
    )
    book.add_item(style)

    front = _title_page(novel, len(chapters))
    front.add_item(style)
    book.add_item(front)

    items: list[epub.EpubHtml] = []
    for chapter in chapters:
        heading = chapter_heading(chapter)
        item = epub.EpubHtml(
            title=heading,
            # Zero padding keeps the files in reading order inside the archive.
            file_name=f"chap_{chapter.number:05d}.xhtml",
            lang=novel.lang.value,
        )
        item.content = f"<h2>{html.escape(heading)}</h2>\n{_paragraphs(chapter.text)}"
        item.add_item(style)
        book.add_item(item)
        items.append(item)

    book.toc = [front, *items]
    book.spine = ["nav", front, *items]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    epub.write_epub(str(target), book)
    return target
