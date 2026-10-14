"""API response and request shapes.

Kept separate from the db models so the wire format stays stable even when the
tables change, and so internal fields never leak by accident.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models import ChapterStatus, Lang, NovelStatus


class ChapterSummary(BaseModel):
    """Chapter without its body. The reader fetches text separately."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    number: int
    title: str
    volume: str | None = None
    status: ChapterStatus
    char_count: int
    has_translation: bool
    fetched_at: datetime | None = None


class NovelSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    source_url: str
    title: str
    author: str | None = None
    cover_url: str | None = None
    lang: Lang
    status: NovelStatus
    translate_enabled: bool
    followed: bool
    created_at: datetime
    updated_at: datetime


class NovelDetail(NovelSummary):
    description: str | None = None
    genres: list[str] = []
    last_checked_at: datetime | None = None

    # Derived, not stored: chapter tallies by status.
    chapter_count: int = 0
    chapters_done: int = 0
    chapters_pending: int = 0
    chapters_failed: int = 0
    chapters_skipped: int = 0
    disk_bytes: int = 0


class NovelListResponse(BaseModel):
    items: list[NovelSummary]
    total: int
    limit: int
    offset: int


class ChapterListResponse(BaseModel):
    items: list[ChapterSummary]
    total: int
    limit: int
    offset: int


class NovelUpdate(BaseModel):
    """Fields the user is allowed to change by hand."""

    title: str | None = None
    author: str | None = None
    followed: bool | None = None
    translate_enabled: bool | None = None
