"""JSON export.

For feeding the text somewhere else: another reader, a script, a translation
pass. Structured rather than pretty.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.db.models import Novel
from app.export.base import ExportedChapter

SCHEMA_VERSION = 1


def build(
    novel: Novel, chapters: list[ExportedChapter], *, translated: bool = False
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "novel": {
            "title": novel.title,
            "author": novel.author,
            "description": novel.description,
            "genres": list(novel.genres or []),
            "lang": novel.lang.value,
            "status": novel.status.value,
            "source": novel.source,
            "source_url": novel.source_url,
            "cover_url": novel.cover_url,
        },
        "export": {
            "translated": translated,
            "chapter_count": len(chapters),
        },
        "chapters": [
            {
                "number": chapter.number,
                "title": chapter.title,
                "volume": chapter.volume,
                "text": chapter.text,
            }
            for chapter in chapters
        ],
    }


def write(
    novel: Novel,
    chapters: list[ExportedChapter],
    target: Path,
    *,
    translated: bool = False,
) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = build(novel, chapters, translated=translated)
    # ensure_ascii=False keeps the file readable and roughly a third smaller
    # for Vietnamese and Chinese text.
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return target
