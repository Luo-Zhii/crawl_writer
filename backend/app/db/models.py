"""Database models.

Design note: the database holds *metadata and state* only. Chapter bodies live
on disk (see ``app.db.storage``) because a long novel is tens of thousands of
chapters and keeping that text out of SQLite keeps the db small, makes the
files greppable, and lets exports stream straight from disk.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Optional

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class Lang(StrEnum):
    """Language of the source text."""

    vi = "vi"
    zh = "zh"


class NovelStatus(StrEnum):
    unknown = "unknown"
    ongoing = "ongoing"
    completed = "completed"


class ChapterStatus(StrEnum):
    pending = "pending"
    done = "done"
    failed = "failed"
    # Paid/locked chapter: not an error, just not ours to download.
    skipped_vip = "skipped_vip"


class JobType(StrEnum):
    crawl = "crawl"
    update = "update"
    translate = "translate"
    export = "export"


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    paused = "paused"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class Novel(SQLModel, table=True):
    __tablename__ = "novel"
    __table_args__ = (
        UniqueConstraint("source", "source_url", name="uq_novel_source_url"),
    )

    id: int | None = Field(default=None, primary_key=True)

    # Which adapter produced this, plus the canonical URL it came from.
    source: str = Field(index=True)
    source_url: str

    title: str = Field(index=True)
    author: str | None = None
    cover_url: str | None = None
    description: str | None = None

    lang: Lang = Field(default=Lang.vi)
    status: NovelStatus = Field(default=NovelStatus.unknown)
    genres: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))

    # Translation is opt-in per novel (only meaningful for lang=zh).
    translate_enabled: bool = Field(default=False)

    # Follow = re-check periodically for new chapters.
    followed: bool = Field(default=False)
    last_checked_at: datetime | None = None

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    chapters: list["Chapter"] = Relationship(
        back_populates="novel",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "passive_deletes": True},
    )


class Chapter(SQLModel, table=True):
    __tablename__ = "chapter"
    __table_args__ = (
        UniqueConstraint("novel_id", "number", name="uq_chapter_novel_number"),
    )

    id: int | None = Field(default=None, primary_key=True)
    novel_id: int = Field(foreign_key="novel.id", index=True, ondelete="CASCADE")

    # 1-based position in reading order. Stable across re-crawls.
    number: int
    title: str
    source_url: str
    volume: str | None = None

    status: ChapterStatus = Field(default=ChapterStatus.pending, index=True)
    attempts: int = Field(default=0)
    error: str | None = None
    char_count: int = Field(default=0)

    has_translation: bool = Field(default=False)
    fetched_at: datetime | None = None

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    novel: Optional[Novel] = Relationship(back_populates="chapters")  # noqa: UP045


class Job(SQLModel, table=True):
    """A unit of background work, durable so it survives a restart."""

    __tablename__ = "job"

    id: int | None = Field(default=None, primary_key=True)
    novel_id: int | None = Field(
        default=None, foreign_key="novel.id", index=True, ondelete="CASCADE"
    )

    type: JobType
    status: JobStatus = Field(default=JobStatus.queued, index=True)

    total: int = Field(default=0)
    done: int = Field(default=0)
    failed: int = Field(default=0)
    skipped: int = Field(default=0)

    error: str | None = None
    params: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))

    created_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class Setting(SQLModel, table=True):
    """Key/value store for runtime config (proxy, cookies, API keys, limits).

    Kept in the db rather than only in .env so the Settings page can change
    them without a restart.
    """

    __tablename__ = "setting"

    key: str = Field(primary_key=True)
    value: Any = Field(default=None, sa_column=Column(JSON))
    updated_at: datetime = Field(default_factory=utcnow)
