"""Chapter text on disk.

Layout::

    data/novels/<novel_id>/00001.txt       original text
    data/novels/<novel_id>/00001.vi.txt    translation, when there is one

Numbers are zero padded so a plain directory listing sorts in reading order.
Original and translation are separate files so re-translating never risks the
source text, and so a failed translation leaves the novel still readable.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from app.core.settings import get_settings


class ChapterStorage:
    def __init__(self, root: Path | None = None) -> None:
        self._root = root or get_settings().novels_dir

    # --- paths -------------------------------------------------------------

    def novel_dir(self, novel_id: int) -> Path:
        return self._root / str(novel_id)

    def path(self, novel_id: int, number: int, *, translated: bool = False) -> Path:
        suffix = ".vi.txt" if translated else ".txt"
        return self.novel_dir(novel_id) / f"{number:05d}{suffix}"

    # --- read/write --------------------------------------------------------

    def write(self, novel_id: int, number: int, text: str, *, translated: bool = False) -> int:
        """Write chapter text, returning its character count.

        Writes to a temp file then renames, so an interrupted run can never
        leave a half-written chapter that later looks complete.
        """
        target = self.path(novel_id, number, translated=translated)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".part")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(target)
        return len(text)

    def read(self, novel_id: int, number: int, *, translated: bool = False) -> str | None:
        target = self.path(novel_id, number, translated=translated)
        if not target.exists():
            return None
        return target.read_text(encoding="utf-8")

    def exists(self, novel_id: int, number: int, *, translated: bool = False) -> bool:
        return self.path(novel_id, number, translated=translated).exists()

    # --- cover -------------------------------------------------------------

    def cover_path(self, novel_id: int, suffix: str = ".jpg") -> Path:
        return self.novel_dir(novel_id) / f"cover{suffix}"

    def find_cover(self, novel_id: int) -> Path | None:
        """Locate a stored cover, whatever extension it was saved under."""
        for suffix in (".jpg", ".jpeg", ".png", ".webp"):
            candidate = self.cover_path(novel_id, suffix)
            if candidate.exists():
                return candidate
        return None

    def write_cover(self, novel_id: int, data: bytes, suffix: str = ".jpg") -> Path:
        target = self.cover_path(novel_id, suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(target)
        return target

    # --- cleanup -----------------------------------------------------------

    def delete_chapter(self, novel_id: int, number: int) -> None:
        for translated in (False, True):
            self.path(novel_id, number, translated=translated).unlink(missing_ok=True)

    def delete_novel(self, novel_id: int) -> None:
        shutil.rmtree(self.novel_dir(novel_id), ignore_errors=True)

    def disk_usage(self, novel_id: int) -> int:
        """Total bytes stored for a novel. Used by the library view."""
        directory = self.novel_dir(novel_id)
        if not directory.exists():
            return 0
        return sum(f.stat().st_size for f in directory.glob("*.txt") if f.is_file())


def get_storage() -> ChapterStorage:
    """FastAPI dependency."""
    return ChapterStorage()
