"""The crawl runner: turns one job row into a downloaded novel.

Shape of a crawl:

1. resolve the adapter for the URL
2. read the novel metadata and upsert the library row
3. read the chapter list and insert rows for chapters we do not have
4. fetch the chapters still pending, writing text to disk

Step 4 is where everything interesting happens. Each chapter is independent:
one failure never aborts the job, a paid chapter is recorded as skipped rather
than failed, and a chapter already on disk is left alone so a restart resumes
instead of re-downloading.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from pathlib import Path
from urllib.parse import urlsplit

from app.core.logging import get_logger
from app.core.settings import Settings, get_settings
from app.db.models import (
    Chapter,
    ChapterStatus,
    JobStatus,
    JobType,
    Novel,
    utcnow,
)
from app.db.repository import ChapterRepository, JobRepository, NovelRepository
from app.db.session import session_scope
from app.db.storage import ChapterStorage
from app.fetch.base import Fetcher
from app.fetch.errors import Blocked, FetchError, NotFound
from app.pipeline.control import JobCancelled, JobControl
from app.pipeline.events import EventHub, Progress
from app.sources.base import ChapterLocked, ChapterRef, NovelInfo, Source, SourceError
from app.sources.registry import UnsupportedSite, resolve
from app.sources.text import looks_like_content

log = get_logger(__name__)

SourceFactory = Callable[[str, Fetcher], Source]

# Below this a chapter body is almost certainly an error page, not prose.
_MIN_CHAPTER_CHARS = 50


class CrawlRunner:
    """Executes crawl and update jobs."""

    def __init__(
        self,
        *,
        fetcher: Fetcher,
        storage: ChapterStorage | None = None,
        hub: EventHub | None = None,
        settings: Settings | None = None,
        source_factory: SourceFactory = resolve,
    ) -> None:
        self.fetcher = fetcher
        self.storage = storage or ChapterStorage()
        self.hub = hub or EventHub()
        self.settings = settings or get_settings()
        self.source_factory = source_factory

    # --- entry point -------------------------------------------------------

    async def run(self, job_id: int, control: JobControl) -> None:
        """Run one job to completion, recording the outcome on the job row."""
        with session_scope() as session:
            job = JobRepository(session).get(job_id)
            if job is None:
                log.warning("job %s vanished before it started", job_id)
                return
            url = str(job.params.get("url") or "")
            novel_id = job.novel_id
            job_type = job.type
            JobRepository(session).update(
                job, status=JobStatus.running, started_at=job.started_at or utcnow(), error=None
            )

        self._publish(job_id, JobStatus.running, message="starting")

        try:
            await self._run_crawl(job_id, job_type, url, novel_id, control)
        except JobCancelled:
            self._finish(job_id, JobStatus.cancelled, message="cancelled")
        except (UnsupportedSite, SourceError, FetchError) as exc:
            # Expected, diagnosable failures: record the reason for the UI.
            log.warning("job %s failed: %s", job_id, exc)
            self._finish(job_id, JobStatus.failed, error=str(exc))
        except Exception as exc:  # pragma: no cover - unexpected bug
            log.exception("job %s crashed", job_id)
            self._finish(job_id, JobStatus.failed, error=f"{type(exc).__name__}: {exc}")
        else:
            self._finish(job_id, JobStatus.done, message="finished")

    # --- the work ----------------------------------------------------------

    async def _run_crawl(
        self,
        job_id: int,
        job_type: JobType,
        url: str,
        novel_id: int | None,
        control: JobControl,
    ) -> None:
        await control.checkpoint()

        if not url and novel_id is not None:
            with session_scope() as session:
                novel = NovelRepository(session).get(novel_id)
                if novel is None:
                    raise SourceError("Novel no longer exists", url="")
                url = novel.source_url

        source = self.source_factory(url, self.fetcher)

        # A pasted chapter link still has to become a novel crawl.
        if getattr(source, "is_chapter_url", None) and source.is_chapter_url(url):
            url = await source.novel_url_from_chapter(url)

        url = source.canonical_url(url)

        self._publish(job_id, JobStatus.running, message="reading novel info")
        info = await source.novel_info(url)
        novel_id = self._upsert_novel(source.key, info)
        await self._ensure_cover(novel_id, info.cover_url, referer=url)

        await control.checkpoint()

        self._publish(job_id, JobStatus.running, message="reading chapter list")
        refs = await source.chapter_list(url)
        added = self._sync_chapters(novel_id, refs)
        log.info("job %s: %d chapters listed, %d new", job_id, len(refs), added)

        pending = self._pending_chapters(novel_id, refs, full_refresh=job_type is JobType.crawl)
        counts = self._status_counts(novel_id)

        progress = Progress(
            job_id=job_id,
            status=JobStatus.running.value,
            total=len(refs),
            done=counts[ChapterStatus.done.value],
            failed=0,
            skipped=counts[ChapterStatus.skipped_vip.value],
            message=f"{len(pending)} chapters to fetch",
        )
        self._persist_progress(job_id, progress)
        self.hub.publish(progress)

        if pending:
            await self._fetch_all(job_id, novel_id, source, pending, progress, control)

    async def _fetch_all(
        self,
        job_id: int,
        novel_id: int,
        source: Source,
        pending: list[ChapterRef],
        progress: Progress,
        control: JobControl,
    ) -> None:
        """Fetch chapters concurrently, bounded by the per-site concurrency."""
        queue: asyncio.Queue[ChapterRef] = asyncio.Queue()
        for ref in pending:
            queue.put_nowait(ref)

        workers = min(self.settings.per_domain_concurrency, len(pending)) or 1
        # The throttle inside the fetcher is what actually paces requests; this
        # only decides how many chapters are in flight.
        tasks = [
            asyncio.create_task(
                self._worker(job_id, novel_id, source, queue, progress, control),
                name=f"crawl-{job_id}-{index}",
            )
            for index in range(workers)
        ]
        fetching = asyncio.gather(*tasks)
        # Watching for cancellation separately means a chapter stuck on a slow
        # request gets interrupted, instead of the job hanging until the
        # request times out. Chapter files are written atomically, so an
        # interrupted write leaves nothing half-saved.
        cancelled = asyncio.create_task(control.wait_cancelled(), name=f"crawl-{job_id}-cancel")

        try:
            await asyncio.wait({fetching, cancelled}, return_when=asyncio.FIRST_COMPLETED)

            if cancelled.done():
                fetching.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise JobCancelled

            await fetching  # re-raise whatever a worker failed with
        except JobCancelled:
            fetching.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        finally:
            cancelled.cancel()
            self._persist_progress(job_id, progress)

    async def _worker(
        self,
        job_id: int,
        novel_id: int,
        source: Source,
        queue: asyncio.Queue[ChapterRef],
        progress: Progress,
        control: JobControl,
    ) -> None:
        while True:
            try:
                ref = queue.get_nowait()
            except asyncio.QueueEmpty:
                return

            await control.checkpoint()
            await self._fetch_one(job_id, novel_id, source, ref, progress)

    async def _fetch_one(
        self,
        job_id: int,
        novel_id: int,
        source: Source,
        ref: ChapterRef,
        progress: Progress,
    ) -> None:
        status = ChapterStatus.done
        error: str | None = None
        char_count = 0

        try:
            text = await source.chapter_content(ref.url)
            if not looks_like_content(text, minimum=_MIN_CHAPTER_CHARS):
                raise SourceError("Chapter body looks empty", url=ref.url)
            char_count = self.storage.write(novel_id, ref.number, text)

        except ChapterLocked as exc:
            # Paid or members-only: nothing to retry, so do not call it an error.
            status = ChapterStatus.skipped_vip
            error = str(exc)
        except Blocked as exc:
            status = ChapterStatus.failed
            error = f"blocked: {exc.reason}"
        except NotFound:
            status = ChapterStatus.failed
            error = "chapter page is gone"
        except (FetchError, SourceError) as exc:
            status = ChapterStatus.failed
            error = str(exc)

        self._record_chapter(novel_id, ref, status, error, char_count)

        if status is ChapterStatus.done:
            progress.done += 1
        elif status is ChapterStatus.skipped_vip:
            progress.skipped += 1
        else:
            progress.failed += 1

        progress.chapter = ref.number
        progress.message = error or f"chương {ref.number}"
        self.hub.publish(
            Progress(
                job_id=job_id,
                status=JobStatus.running.value,
                total=progress.total,
                done=progress.done,
                failed=progress.failed,
                skipped=progress.skipped,
                chapter=ref.number,
                message=progress.message,
            )
        )

        # Persisting on every chapter would be a write per request; every few
        # is enough for the UI to survive a restart.
        if progress.processed % 10 == 0:
            self._persist_progress(job_id, progress)

    # --- database helpers --------------------------------------------------

    def _upsert_novel(self, source_key: str, info: NovelInfo) -> int:
        with session_scope() as session:
            repo = NovelRepository(session)
            novel = repo.get_by_source_url(source_key, info.url)
            fields = {
                "title": info.title,
                "author": info.author,
                "cover_url": info.cover_url,
                "description": info.description,
                "genres": info.genres,
                "status": info.status,
                "lang": info.lang,
                "last_checked_at": utcnow(),
            }
            if novel is None:
                novel = repo.add(
                    Novel(source=source_key, source_url=info.url, **fields)
                )
            else:
                novel = repo.update(novel, **fields)
            return novel.id

    async def _ensure_cover(
        self, novel_id: int, cover_url: str | None, *, referer: str | None = None
    ) -> None:
        """Download the cover once, for the EPUB export to embed later.

        Entirely optional: a missing cover is a cosmetic problem, so any
        failure here is logged and ignored rather than failing the crawl.
        """
        if not cover_url or self.storage.find_cover(novel_id) is not None:
            return

        get_bytes = getattr(self.fetcher, "get_bytes", None)
        if get_bytes is None:
            return

        try:
            data = await get_bytes(cover_url, referer=referer)
        except Exception as exc:  # noqa: BLE001 - cover is never worth failing for
            log.debug("could not fetch cover %s: %s", cover_url, exc)
            return

        if not data:
            return

        suffix = Path(urlsplit(cover_url).path).suffix.lower()
        if suffix not in (".jpg", ".jpeg", ".png", ".webp"):
            suffix = ".jpg"
        self.storage.write_cover(novel_id, data, suffix=suffix)

    def _sync_chapters(self, novel_id: int, refs: Iterable[ChapterRef]) -> int:
        """Insert rows for chapters we have never seen. Returns how many."""
        with session_scope() as session:
            repo = ChapterRepository(session)
            known = {c.number for c in repo.list_for_novel(novel_id)}
            new_rows = [
                Chapter(
                    novel_id=novel_id,
                    number=ref.number,
                    title=ref.title,
                    source_url=ref.url,
                    volume=ref.volume,
                )
                for ref in refs
                if ref.number not in known
            ]
            if new_rows:
                repo.add_many(new_rows)
            return len(new_rows)

    def _pending_chapters(
        self, novel_id: int, refs: list[ChapterRef], *, full_refresh: bool
    ) -> list[ChapterRef]:
        """Which chapters still need fetching.

        Chapters already on disk are skipped, which is what makes a restart
        resume rather than start over. Failed ones are retried up to a limit;
        paid ones are left alone.
        """
        by_number = {ref.number: ref for ref in refs}
        pending: list[ChapterRef] = []

        with session_scope() as session:
            repo = ChapterRepository(session)
            for chapter in repo.list_for_novel(novel_id):
                ref = by_number.get(chapter.number)
                if ref is None:
                    continue
                if chapter.status is ChapterStatus.skipped_vip:
                    continue
                if chapter.status is ChapterStatus.done and self.storage.exists(
                    novel_id, chapter.number
                ):
                    continue
                if (
                    chapter.status is ChapterStatus.failed
                    and not full_refresh
                    and chapter.attempts >= self.settings.chapter_retry_limit
                ):
                    continue
                pending.append(ref)

        pending.sort(key=lambda ref: ref.number)
        return pending

    def _record_chapter(
        self,
        novel_id: int,
        ref: ChapterRef,
        status: ChapterStatus,
        error: str | None,
        char_count: int,
    ) -> None:
        with session_scope() as session:
            repo = ChapterRepository(session)
            chapter = repo.get_by_number(novel_id, ref.number)
            if chapter is None:  # pragma: no cover - synced moments earlier
                return
            repo.update(
                chapter,
                status=status,
                error=error,
                char_count=char_count or chapter.char_count,
                attempts=chapter.attempts + 1,
                title=ref.title or chapter.title,
                source_url=ref.url,
                fetched_at=utcnow() if status is ChapterStatus.done else chapter.fetched_at,
            )

    def _status_counts(self, novel_id: int) -> dict[str, int]:
        with session_scope() as session:
            return ChapterRepository(session).status_counts(novel_id)

    # --- job row -----------------------------------------------------------

    def _persist_progress(self, job_id: int, progress: Progress) -> None:
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

    def _publish(
        self, job_id: int, status: JobStatus, *, message: str | None = None
    ) -> None:
        self.hub.publish(Progress(job_id=job_id, status=status.value, message=message))
