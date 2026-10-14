"""API response and request shapes.

Kept separate from the db models so the wire format stays stable even when the
tables change, and so internal fields never leak by accident.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field

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
    last_read_chapter: int | None = None
    created_at: datetime
    updated_at: datetime


class ChapterRead(BaseModel):
    """A chapter with its text, for the reader."""

    number: int
    title: str
    text: str
    #: True when the text returned is the translation rather than the original.
    translated: bool
    has_translation: bool
    #: Neighbours that actually exist, so the reader can disable the buttons.
    prev_number: int | None = None
    next_number: int | None = None
    novel_id: int
    novel_title: str


class ReadingProgress(BaseModel):
    chapter: int


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


class SettingsRead(BaseModel):
    """Runtime settings, with secrets reduced to a hint."""

    proxy: str | None = None
    browser_enabled: bool = True
    per_domain_delay: float
    per_domain_concurrency: int
    request_timeout: float
    chapter_retry_limit: int
    #: Cookie header strings keyed by domain.
    cookies: dict[str, str] = {}
    #: Provider -> masked key, or None when unset.
    api_keys: dict[str, str | None] = {}


class SettingsUpdate(BaseModel):
    """Partial update. Only the fields sent are changed."""

    proxy: str | None = None
    browser_enabled: bool | None = None
    per_domain_delay: float | None = Field(None, ge=0, le=30)
    per_domain_concurrency: int | None = Field(None, ge=1, le=16)
    request_timeout: float | None = Field(None, ge=5, le=180)
    chapter_retry_limit: int | None = Field(None, ge=0, le=10)
    cookies: dict[str, str] | None = None
    #: Provider -> key, or null to clear it.
    api_keys: dict[str, str | None] | None = None


class BrowserCheck(BaseModel):
    available: bool
    detail: str


class GlossaryTermRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    target: str
    note: str | None = None


class GlossaryTermCreate(BaseModel):
    source: str = Field(min_length=1, max_length=120)
    target: str = Field(min_length=1, max_length=200)
    note: str | None = None


class GlossaryBulk(BaseModel):
    """Whole glossary at once, as source -> target."""

    terms: dict[str, str]


class TranslateRequest(BaseModel):
    #: Re-translate chapters that already have a translation.
    force: bool = False


class PreviewRequest(BaseModel):
    url: str


class PreviewResponse(BaseModel):
    """What a pasted URL turns out to be, before anything is saved.

    Deliberately does not include the chapter list: that can mean fetching
    several pages, which is too slow for a preview.
    """

    source: str
    source_name: str
    url: str
    title: str
    author: str | None = None
    cover_url: str | None = None
    description: str | None = None
    genres: list[str] = []
    status: NovelStatus
    lang: Lang
    #: Set when this novel is already in the library.
    novel_id: int | None = None
