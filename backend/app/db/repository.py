"""Repository layer.

Call sites (API routes, crawl worker, exporters) talk to these classes instead
of writing queries inline. The abstract bases document the contract so a
Postgres implementation can slot in later without touching callers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, col, delete, select

from app.db.models import (
    Chapter,
    ChapterStatus,
    GlossaryTerm,
    Job,
    JobStatus,
    JobType,
    Novel,
    Setting,
    utcnow,
)

# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


class AbstractNovelRepository(ABC):
    @abstractmethod
    def get(self, novel_id: int) -> Novel | None: ...

    @abstractmethod
    def get_by_source_url(self, source: str, source_url: str) -> Novel | None: ...

    @abstractmethod
    def list(
        self, *, limit: int = 50, offset: int = 0, followed: bool | None = None
    ) -> list[Novel]: ...

    @abstractmethod
    def count(self, *, followed: bool | None = None) -> int: ...

    @abstractmethod
    def add(self, novel: Novel) -> Novel: ...

    @abstractmethod
    def update(self, novel: Novel, **fields: Any) -> Novel: ...

    @abstractmethod
    def delete(self, novel: Novel) -> None: ...


class AbstractChapterRepository(ABC):
    @abstractmethod
    def get(self, chapter_id: int) -> Chapter | None: ...

    @abstractmethod
    def get_by_number(self, novel_id: int, number: int) -> Chapter | None: ...

    @abstractmethod
    def list_for_novel(
        self, novel_id: int, *, limit: int | None = None, offset: int = 0,
        status: ChapterStatus | None = None,
    ) -> list[Chapter]: ...

    @abstractmethod
    def status_counts(self, novel_id: int) -> dict[str, int]: ...

    @abstractmethod
    def add_many(self, chapters: list[Chapter]) -> list[Chapter]: ...

    @abstractmethod
    def update(self, chapter: Chapter, **fields: Any) -> Chapter: ...


class AbstractJobRepository(ABC):
    @abstractmethod
    def get(self, job_id: int) -> Job | None: ...

    @abstractmethod
    def list(
        self, *, limit: int = 50, offset: int = 0, status: JobStatus | None = None
    ) -> list[Job]: ...

    @abstractmethod
    def create(
        self,
        *,
        type: JobType,
        novel_id: int | None = None,
        params: dict[str, Any] | None = None,
    ) -> Job: ...

    @abstractmethod
    def update(self, job: Job, **fields: Any) -> Job: ...


class AbstractSettingRepository(ABC):
    @abstractmethod
    def get(self, key: str, default: Any = None) -> Any: ...

    @abstractmethod
    def set(self, key: str, value: Any) -> None: ...

    @abstractmethod
    def all(self) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# SQL implementations
# ---------------------------------------------------------------------------


class _SqlRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def _save(self, obj: Any) -> Any:
        self.session.add(obj)
        self.session.commit()
        self.session.refresh(obj)
        return obj


class NovelRepository(_SqlRepository, AbstractNovelRepository):
    def get(self, novel_id: int) -> Novel | None:
        return self.session.get(Novel, novel_id)

    def get_by_source_url(self, source: str, source_url: str) -> Novel | None:
        stmt = select(Novel).where(Novel.source == source, Novel.source_url == source_url)
        return self.session.exec(stmt).first()

    def list(
        self, *, limit: int = 50, offset: int = 0, followed: bool | None = None
    ) -> list[Novel]:
        stmt = select(Novel).order_by(col(Novel.updated_at).desc())
        if followed is not None:
            stmt = stmt.where(Novel.followed == followed)
        stmt = stmt.offset(offset).limit(limit)
        return list(self.session.exec(stmt).all())

    def count(self, *, followed: bool | None = None) -> int:
        stmt = select(func.count()).select_from(Novel)
        if followed is not None:
            stmt = stmt.where(Novel.followed == followed)
        return self.session.exec(stmt).one()

    def add(self, novel: Novel) -> Novel:
        return self._save(novel)

    def update(self, novel: Novel, **fields: Any) -> Novel:
        for key, value in fields.items():
            setattr(novel, key, value)
        novel.updated_at = utcnow()
        return self._save(novel)

    def delete(self, novel: Novel) -> None:
        self.session.delete(novel)
        self.session.commit()


class ChapterRepository(_SqlRepository, AbstractChapterRepository):
    def get(self, chapter_id: int) -> Chapter | None:
        return self.session.get(Chapter, chapter_id)

    def get_by_number(self, novel_id: int, number: int) -> Chapter | None:
        stmt = select(Chapter).where(Chapter.novel_id == novel_id, Chapter.number == number)
        return self.session.exec(stmt).first()

    def list_for_novel(
        self,
        novel_id: int,
        *,
        limit: int | None = None,
        offset: int = 0,
        status: ChapterStatus | None = None,
    ) -> list[Chapter]:
        stmt = select(Chapter).where(Chapter.novel_id == novel_id)
        if status is not None:
            stmt = stmt.where(Chapter.status == status)
        stmt = stmt.order_by(col(Chapter.number)).offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self.session.exec(stmt).all())

    def status_counts(self, novel_id: int) -> dict[str, int]:
        """Per-status chapter tally, used for progress display."""
        stmt = (
            select(Chapter.status, func.count())
            .where(Chapter.novel_id == novel_id)
            .group_by(col(Chapter.status))
        )
        counts = {status.value: 0 for status in ChapterStatus}
        for status, total in self.session.exec(stmt).all():
            key = status.value if hasattr(status, "value") else str(status)
            counts[key] = total
        return counts

    def max_number(self, novel_id: int) -> int:
        stmt = select(func.max(Chapter.number)).where(Chapter.novel_id == novel_id)
        return self.session.exec(stmt).one() or 0

    def add_many(self, chapters: list[Chapter]) -> list[Chapter]:
        for chapter in chapters:
            self.session.add(chapter)
        self.session.commit()
        for chapter in chapters:
            self.session.refresh(chapter)
        return chapters

    def update(self, chapter: Chapter, **fields: Any) -> Chapter:
        for key, value in fields.items():
            setattr(chapter, key, value)
        chapter.updated_at = utcnow()
        return self._save(chapter)

    def delete_for_novel(self, novel_id: int) -> None:
        self.session.exec(delete(Chapter).where(col(Chapter.novel_id) == novel_id))
        self.session.commit()


class JobRepository(_SqlRepository, AbstractJobRepository):
    def get(self, job_id: int) -> Job | None:
        return self.session.get(Job, job_id)

    def list(
        self, *, limit: int = 50, offset: int = 0, status: JobStatus | None = None
    ) -> list[Job]:
        stmt = select(Job).order_by(col(Job.created_at).desc())
        if status is not None:
            stmt = stmt.where(Job.status == status)
        stmt = stmt.offset(offset).limit(limit)
        return list(self.session.exec(stmt).all())

    def create(
        self,
        *,
        type: JobType,
        novel_id: int | None = None,
        params: dict[str, Any] | None = None,
    ) -> Job:
        return self._save(Job(type=type, novel_id=novel_id, params=params or {}))

    def update(self, job: Job, **fields: Any) -> Job:
        for key, value in fields.items():
            setattr(job, key, value)
        return self._save(job)

    def claim_resumable(self) -> list[Job]:
        """Jobs left mid-flight by a crash, so a restart can pick them up."""
        stmt = select(Job).where(col(Job.status).in_([JobStatus.queued, JobStatus.running]))
        return list(self.session.exec(stmt).all())


class GlossaryRepository(_SqlRepository):
    """Per-novel term list used to keep names consistent."""

    def list_for_novel(self, novel_id: int) -> list[GlossaryTerm]:
        stmt = (
            select(GlossaryTerm)
            .where(GlossaryTerm.novel_id == novel_id)
            .order_by(col(GlossaryTerm.source))
        )
        return list(self.session.exec(stmt).all())

    def as_mapping(self, novel_id: int) -> dict[str, str]:
        return {term.source: term.target for term in self.list_for_novel(novel_id)}

    def get(self, term_id: int) -> GlossaryTerm | None:
        return self.session.get(GlossaryTerm, term_id)

    def find(self, novel_id: int, source: str) -> GlossaryTerm | None:
        stmt = select(GlossaryTerm).where(
            GlossaryTerm.novel_id == novel_id, GlossaryTerm.source == source
        )
        return self.session.exec(stmt).first()

    def upsert(
        self, novel_id: int, source: str, target: str, note: str | None = None
    ) -> GlossaryTerm:
        """Add a term, or update the reading of one that already exists."""
        existing = self.find(novel_id, source)
        if existing is not None:
            existing.target = target
            existing.note = note
            existing.updated_at = utcnow()
            return self._save(existing)
        return self._save(
            GlossaryTerm(novel_id=novel_id, source=source, target=target, note=note)
        )

    def delete(self, term: GlossaryTerm) -> None:
        self.session.delete(term)
        self.session.commit()

    def replace_all(self, novel_id: int, terms: dict[str, str]) -> int:
        """Swap the whole glossary for a novel. Used by bulk import."""
        self.session.exec(
            delete(GlossaryTerm).where(col(GlossaryTerm.novel_id) == novel_id)
        )
        for source, target in terms.items():
            if source.strip() and target.strip():
                self.session.add(
                    GlossaryTerm(
                        novel_id=novel_id, source=source.strip(), target=target.strip()
                    )
                )
        self.session.commit()
        return len(self.list_for_novel(novel_id))


class SettingRepository(_SqlRepository, AbstractSettingRepository):
    def get(self, key: str, default: Any = None) -> Any:
        row = self.session.get(Setting, key)
        return default if row is None else row.value

    def set(self, key: str, value: Any) -> None:
        row = self.session.get(Setting, key)
        if row is None:
            row = Setting(key=key, value=value)
        else:
            row.value = value
            row.updated_at = utcnow()
        self._save(row)

    def all(self) -> dict[str, Any]:
        rows = self.session.exec(select(Setting)).all()
        return {row.key: row.value for row in rows}
