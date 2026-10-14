"""Shared pieces for the exporters."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from app.db.models import Novel

# Vietnamese đ/Đ have no decomposed form, so they need replacing by hand.
_DIACRITIC_FIXES = {"đ": "d", "Đ": "D"}
_NON_SLUG = re.compile(r"[^a-zA-Z0-9]+")


@dataclass(slots=True)
class ExportedChapter:
    """One chapter, text already loaded from disk."""

    number: int
    title: str
    text: str
    volume: str | None = None


@dataclass(slots=True)
class ExportResult:
    """What an exporter produced."""

    path: Path
    filename: str
    media_type: str
    chapters: int = 0
    #: Chapters listed in the database but with no text on disk.
    missing: list[int] = field(default_factory=list)
    #: Set when the export was split and zipped.
    parts: int = 1

    @property
    def size_bytes(self) -> int:
        return self.path.stat().st_size if self.path.exists() else 0


def slugify(value: str, *, fallback: str = "truyen", max_length: int = 60) -> str:
    """Make a filename-safe slug, with Vietnamese diacritics flattened.

    Keeps exported files readable on any filesystem without needing to quote
    them in a shell.
    """
    for char, replacement in _DIACRITIC_FIXES.items():
        value = value.replace(char, replacement)

    decomposed = unicodedata.normalize("NFKD", value)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    slug = _NON_SLUG.sub("-", ascii_only).strip("-").lower()
    slug = re.sub(r"-{2,}", "-", slug)[:max_length].strip("-")
    return slug or fallback


def export_filename(novel: Novel, extension: str, *, translated: bool = False) -> str:
    suffix = "-vi" if translated else ""
    return f"{slugify(novel.title)}{suffix}.{extension.lstrip('.')}"


def chapter_heading(chapter: ExportedChapter) -> str:
    """Title for a chapter, with the number added when it is not already there."""
    title = chapter.title.strip()
    if re.match(r"(?i)^ch(?:ương|uong|apter)\s*\d+", title):
        return title
    return f"Chương {chapter.number}: {title}" if title else f"Chương {chapter.number}"
