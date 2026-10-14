"""The translate runner: turns a downloaded Chinese novel into Vietnamese.

Shaped like the crawl runner on purpose. Each chapter is independent, a
translation already on disk is left alone so a restart resumes, and one
chapter that a provider chokes on does not abort the job.
"""

from __future__ import annotations

import asyncio

from app.core.logging import get_logger
from app.core.settings import Settings, get_settings
from app.db.models import ChapterStatus, JobStatus, Lang, utcnow
from app.db.repository import ChapterRepository, JobRepository, NovelRepository
from app.db.session import session_scope
from app.db.settings_store import SettingsStore
from app.db.storage import ChapterStorage
from app.pipeline.control import JobCancelled, JobControl
from app.pipeline.events import EventHub, Progress
from app.translate.base import TranslationError
from app.translate.service import TranslationService, build_providers, glossary_for

log = get_logger(__name__)


class TranslateRunner:
    """Executes translate jobs."""

    def __init__(
        self,
        *,
        storage: ChapterStorage | None = None,
        hub: EventHub | None = None,
        settings: Settings | None = None,
        service_factory=None,
    ) -> None:
        self.storage = storage or ChapterStorage()
        self.hub = hub or EventHub()
        self.settings = settings or get_settings()
        # Injectable so tests never call a real translation API.
        self._service_factory = service_factory

    # --- entry point -------------------------------------------------------

    async def run(self, job_id: int, control: JobControl) -> None:
        with session_scope() as session:
            job = JobRepository(session).get(job_id)
            if job is None:
                log.warning("translate job %s vanished before it started", job_id)
                return
            novel_id = job.novel_id
            force = bool(job.params.get("force"))
            JobRepository(session).update(
                job,
                status=JobStatus.running,
                started_at=job.started_at or utcnow(),
                error=None,
            )

        service = None
        try:
            if novel_id is None:
                raise TranslationError(
                    "translate jobs need a novel", provider="-", retryable=False
                )
            service = self._build_service(novel_id)
            await self._translate_novel(job_id, novel_id, service, force, control)
        except JobCancelled:
            self._finish(job_id, JobStatus.cancelled, message="cancelled")
        except TranslationError as exc:
            log.warning("translate job %s failed: %s", job_id, exc)
            self._finish(job_id, JobStatus.failed, error=str(exc))
        except Exception as exc:  # pragma: no cover - unexpected bug
            log.exception("translate job %s crashed", job_id)
            self._finish(job_id, JobStatus.failed, error=f"{type(exc).__name__}: {exc}")
        else:
            self._finish(job_id, JobStatus.done, message="finished")
        finally:
            if service is not None:
                await service.aclose()

    # --- the work ----------------------------------------------------------

    def _build_service(self, novel_id: int) -> TranslationService:
        if self._service_factory is not None:
            return self._service_factory(novel_id)

        with session_scope() as session:
            store = SettingsStore(session)
            preferred = store.translate_provider
            keys = {
                provider: store.api_key(provider)
                for provider in ("gemini", "openai", "anthropic")
            }

        return TranslationService(
            build_providers(preferred=preferred, api_keys=keys),
            glossary=glossary_for(novel_id),
        )

    async def _translate_novel(
        self,
        job_id: int,
        novel_id: int,
        service: TranslationService,
        force: bool,
        control: JobControl,
    ) -> None:
        await control.checkpoint()

        with session_scope() as session:
            novel = NovelRepository(session).get(novel_id)
            if novel is None:
                raise TranslationError("novel no longer exists", provider="-", retryable=False)
            if novel.lang is Lang.vi:
                raise TranslationError(
                    "this novel is already in Vietnamese", provider="-", retryable=False
                )
            rows = ChapterRepository(session).list_for_novel(novel_id)
            pending = [
                row.number
                for row in rows
                if row.status is ChapterStatus.done
                and (force or not self.storage.exists(novel_id, row.number, translated=True))
            ]

        progress = Progress(
            job_id=job_id,
            status=JobStatus.running.value,
            total=len(pending),
            message=(
                f"{len(pending)} chapters to translate with {service.primary.name}"
            ),
        )
        self.hub.publish(progress)
        self._persist(job_id, progress)

        if not pending:
            return

        try:
            for number in pending:
                await control.checkpoint()
                await self._translate_chapter(job_id, novel_id, number, service, progress)
        finally:
            # The periodic save only fires every ten chapters, so without this
            # a short novel would finish with its counters still at zero — and
            # a cancelled job would lose the count of what it did finish.
            self._persist(job_id, progress)

    async def _translate_chapter(
        self,
        job_id: int,
        novel_id: int,
        number: int,
        service: TranslationService,
        progress: Progress,
    ) -> None:
        original = self.storage.read(novel_id, number)
        if not original:
            progress.skipped += 1
            return

        try:
            result = await service.translate(original)
        except TranslationError as exc:
            # One bad chapter must not end the job; the rest may be fine.
            log.warning("chapter %s failed to translate: %s", number, exc.message)
            progress.failed += 1
            self._record_error(novel_id, number, str(exc))
        else:
            self.storage.write(novel_id, number, result.text, translated=True)
            self._mark_translated(novel_id, number)
            progress.done += 1
            progress.extra = {"provider": result.provider, "cached_chunks": result.cached}

        progress.chapter = number
        self.hub.publish(
            Progress(
                job_id=job_id,
                status=JobStatus.running.value,
                total=progress.total,
                done=progress.done,
                failed=progress.failed,
                skipped=progress.skipped,
                chapter=number,
                message=f"chương {number}",
            )
        )

        if progress.processed % 10 == 0:
            self._persist(job_id, progress)

        # Being gentle with a free endpoint is what keeps it working.
        await asyncio.sleep(0)

    # --- database ----------------------------------------------------------

    def _mark_translated(self, novel_id: int, number: int) -> None:
        with session_scope() as session:
            repo = ChapterRepository(session)
            chapter = repo.get_by_number(novel_id, number)
            if chapter is not None:
                repo.update(chapter, has_translation=True, error=None)

    def _record_error(self, novel_id: int, number: int, message: str) -> None:
        with session_scope() as session:
            repo = ChapterRepository(session)
            chapter = repo.get_by_number(novel_id, number)
            if chapter is not None:
                repo.update(chapter, error=message[:500])

    def _persist(self, job_id: int, progress: Progress) -> None:
        with session_scope() as session:
            repo = JobRepository(session)
            job = repo.get(job_id)
            if job is not None:
                repo.update(
                    job,
                    total=progress.total,
                    done=progress.done,
                    failed=progress.failed,
                    skipped=progress.skipped,
                )

    def _finish(
        self,
        job_id: int,
        status: JobStatus,
        *,
        message: str | None = None,
        error: str | None = None,
    ) -> None:
        with session_scope() as session:
            repo = JobRepository(session)
            job = repo.get(job_id)
            if job is not None:
                job = repo.update(job, status=status, error=error, finished_at=utcnow())
                snapshot = Progress(
                    job_id=job_id,
                    status=status.value,
                    total=job.total,
                    done=job.done,
                    failed=job.failed,
                    skipped=job.skipped,
                    message=error or message,
                )
            else:  # pragma: no cover
                snapshot = Progress(job_id=job_id, status=status.value, message=error or message)

        self.hub.publish(snapshot)
        self.hub.close(job_id)
