"""API response and request shapes.

Kept separate from the db models so the wire format stays stable even when the
tables change, and so internal fields never leak by accident.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, computed_field

from app.db.models import ChapterStatus, JobStatus, JobType, Lang, NovelStatus


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


class JobCreate(BaseModel):
    """Start a crawl, either from a URL or for a novel already in the library."""

    url: str | None = None
    novel_id: int | None = None
    type: JobType = JobType.crawl


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: JobType
    status: JobStatus
    novel_id: int | None = None
    total: int
    done: int
    failed: int
    skipped: int
    error: str | None = None
    params: dict[str, Any] = {}
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @computed_field
    @property
    def processed(self) -> int:
        return self.done + self.failed + self.skipped

    @computed_field
    @property
    def percent(self) -> float:
        return round(self.processed / self.total * 100, 1) if self.total else 0.0


class JobListResponse(BaseModel):
    items: list[JobRead]
    total: int
    limit: int
    offset: int


class SourceInfo(BaseModel):
    """A registered adapter, for the "which sites work" screen."""

    key: str
    name: str
    domains: list[str]
    lang: Lang
    needs_browser: bool
