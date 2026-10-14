"""Library endpoints: list, inspect, edit and delete novels."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.api.schemas import (
    ChapterListResponse,
    ChapterRead,
    ChapterSummary,
    NovelDetail,
    NovelListResponse,
    NovelSummary,
    NovelUpdate,
    ReadingProgress,
)
from app.db.models import ChapterStatus, utcnow
from app.db.repository import ChapterRepository, NovelRepository
from app.db.session import get_session
from app.db.storage import ChapterStorage, get_storage
from app.export import ExportFormat, ExportService, NothingToExport

router = APIRouter(prefix="/novels", tags=["novels"])


def _detail(novel, chapters: ChapterRepository, storage: ChapterStorage) -> NovelDetail:
    counts = chapters.status_counts(novel.id)
    return NovelDetail(
        **NovelSummary.model_validate(novel).model_dump(),
        description=novel.description,
        genres=novel.genres or [],
        last_checked_at=novel.last_checked_at,
        chapter_count=sum(counts.values()),
        chapters_done=counts.get(ChapterStatus.done.value, 0),
        chapters_pending=counts.get(ChapterStatus.pending.value, 0),
        chapters_failed=counts.get(ChapterStatus.failed.value, 0),
        chapters_skipped=counts.get(ChapterStatus.skipped_vip.value, 0),
        disk_bytes=storage.disk_usage(novel.id),
    )


@router.get("", response_model=NovelListResponse)
def list_novels(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    followed: bool | None = None,
    session: Session = Depends(get_session),
) -> NovelListResponse:
    repo = NovelRepository(session)
    items = repo.list(limit=limit, offset=offset, followed=followed)
    return NovelListResponse(
        items=[NovelSummary.model_validate(n) for n in items],
        total=repo.count(followed=followed),
        limit=limit,
        offset=offset,
    )


@router.get("/{novel_id}", response_model=NovelDetail)
def get_novel(
    novel_id: int,
    session: Session = Depends(get_session),
    storage: ChapterStorage = Depends(get_storage),
) -> NovelDetail:
    novel = NovelRepository(session).get(novel_id)
    if novel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Novel not found")
    return _detail(novel, ChapterRepository(session), storage)


@router.patch("/{novel_id}", response_model=NovelDetail)
def update_novel(
    novel_id: int,
    payload: NovelUpdate,
    session: Session = Depends(get_session),
    storage: ChapterStorage = Depends(get_storage),
) -> NovelDetail:
    repo = NovelRepository(session)
    novel = repo.get(novel_id)
    if novel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Novel not found")
    changes = payload.model_dump(exclude_unset=True)
    if changes:
        novel = repo.update(novel, **changes)
    return _detail(novel, ChapterRepository(session), storage)


@router.delete("/{novel_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_novel(
    novel_id: int,
    session: Session = Depends(get_session),
    storage: ChapterStorage = Depends(get_storage),
) -> None:
    repo = NovelRepository(session)
    novel = repo.get(novel_id)
    if novel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Novel not found")
    # Rows first, then files: a leftover file is harmless, a row pointing at
    # missing text is not.
    repo.delete(novel)
    storage.delete_novel(novel_id)


@router.get("/{novel_id}/chapters/{number}", response_model=ChapterRead)
def read_chapter(
    novel_id: int,
    number: int,
    translated: bool = Query(False, description="Return the translation when there is one"),
    session: Session = Depends(get_session),
    storage: ChapterStorage = Depends(get_storage),
) -> ChapterRead:
    """One chapter with its text, for the in-browser reader."""
    novel = NovelRepository(session).get(novel_id)
    if novel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Novel not found")

    repo = ChapterRepository(session)
    chapter = repo.get_by_number(novel_id, number)
    if chapter is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chapter not found")

    want_translation = translated and chapter.has_translation
    text = storage.read(novel_id, number, translated=want_translation)
    if text is None and want_translation:
        # Asked for the translation but the file is gone: fall back rather
        # than showing an empty reader.
        want_translation = False
        text = storage.read(novel_id, number)
    if text is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This chapter has not been downloaded yet",
        )

    # Neighbours come from the database, not number±1, because chapter
    # numbering has gaps on most sites.
    numbers = [row.number for row in repo.list_for_novel(novel_id)]
    position = numbers.index(number)

    return ChapterRead(
        number=number,
        title=chapter.title,
        text=text,
        translated=want_translation,
        has_translation=chapter.has_translation,
        prev_number=numbers[position - 1] if position > 0 else None,
        next_number=numbers[position + 1] if position + 1 < len(numbers) else None,
        novel_id=novel_id,
        novel_title=novel.title,
    )


@router.put("/{novel_id}/progress", response_model=NovelDetail)
def save_progress(
    novel_id: int,
    payload: ReadingProgress,
    session: Session = Depends(get_session),
    storage: ChapterStorage = Depends(get_storage),
) -> NovelDetail:
    """Remember where the reader got to.

    Stored server-side so the position follows the user between devices,
    which is also what a future mobile app will read.
    """
    repo = NovelRepository(session)
    novel = repo.get(novel_id)
    if novel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Novel not found")
    if ChapterRepository(session).get_by_number(novel_id, payload.chapter) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chapter not found")

    novel = repo.update(
        novel, last_read_chapter=payload.chapter, last_read_at=utcnow()
    )
    return _detail(novel, ChapterRepository(session), storage)


@router.get("/{novel_id}/export")
def export_novel(
    novel_id: int,
    fmt: ExportFormat = Query(ExportFormat.epub, alias="format"),
    translated: bool = Query(False, description="Export the translation when there is one"),
    volume_size: int | None = Query(
        None,
        ge=50,
        le=5000,
        description="Split into parts of this many chapters and return a zip",
    ),
    session: Session = Depends(get_session),
    storage: ChapterStorage = Depends(get_storage),
) -> FileResponse:
    """Build the file and return it.

    Generation is synchronous: a few thousand chapters take a couple of
    seconds, which is faster than making the client poll a job.
    """
    if NovelRepository(session).get(novel_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Novel not found")

    service = ExportService(storage=storage)
    try:
        result = service.export(
            novel_id, fmt, translated=translated, volume_size=volume_size
        )
    except NothingToExport as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    return FileResponse(
        result.path,
        media_type=result.media_type,
        filename=result.filename,
        headers={
            "X-Export-Chapters": str(result.chapters),
            "X-Export-Parts": str(result.parts),
        },
    )


@router.get("/{novel_id}/chapters", response_model=ChapterListResponse)
def list_chapters(
    novel_id: int,
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    chapter_status: ChapterStatus | None = Query(None, alias="status"),
    session: Session = Depends(get_session),
) -> ChapterListResponse:
    if NovelRepository(session).get(novel_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Novel not found")
    repo = ChapterRepository(session)
    items = repo.list_for_novel(novel_id, limit=limit, offset=offset, status=chapter_status)
    counts = repo.status_counts(novel_id)
    total = counts.get(chapter_status.value, 0) if chapter_status else sum(counts.values())
    return ChapterListResponse(
        items=[ChapterSummary.model_validate(c) for c in items],
        total=total,
        limit=limit,
        offset=offset,
    )
