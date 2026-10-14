"""The worker queue.

One background task pulls job ids off an in-memory queue and runs them. Jobs
are durable rows, so the queue is only a hint about what to do next: on
startup anything left ``queued`` or ``running`` is put back, which is what
makes a crawl survive a restart.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from app.core.logging import get_logger
from app.core.settings import Settings, get_settings
from app.db.models import Job, JobStatus, JobType, utcnow
from app.db.repository import JobRepository
from app.db.session import session_scope
from app.db.settings_store import SettingsStore
from app.fetch.browser import BrowserFetcher
from app.fetch.http import HttpFetcher
from app.fetch.smart import SmartFetcher
from app.pipeline.control import JobControl
from app.pipeline.crawler import CrawlRunner
from app.pipeline.events import EventHub, Progress
from app.pipeline.translator import TranslateRunner

log = get_logger(__name__)

RunnerFactory = Callable[[], CrawlRunner]


class JobManager:
    """Owns the worker task, the queue, and the per-job control switches."""

    def __init__(
        self,
        *,
        hub: EventHub | None = None,
        settings: Settings | None = None,
        runner_factory: RunnerFactory | None = None,
        translate_runner_factory=None,
        workers: int = 1,
    ) -> None:
        self.hub = hub or EventHub()
        self.settings = settings or get_settings()
        self._runner_factory = runner_factory
        self._translate_runner_factory = translate_runner_factory
        self._workers = max(workers, 1)
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._tasks: list[asyncio.Task[None]] = []
        self._controls: dict[int, JobControl] = {}
        self._owned_fetcher: SmartFetcher | None = None
        self._effective_settings: Settings | None = None
        self._running = False

    # --- lifecycle ---------------------------------------------------------

    async def start(self, *, resume: bool = True) -> None:
        if self._running:
            return
        self._running = True
        self._tasks = [
            asyncio.create_task(self._loop(), name=f"job-worker-{index}")
            for index in range(self._workers)
        ]
        if resume:
            self.requeue_unfinished()

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        if self._owned_fetcher is not None:
            await self._owned_fetcher.aclose()
            self._owned_fetcher = None

    def requeue_unfinished(self) -> int:
        """Re-enqueue jobs a previous run left mid-flight."""
        with session_scope() as session:
            repo = JobRepository(session)
            jobs = repo.claim_resumable()
            ids = []
            for job in jobs:
                # Back to queued so the UI does not show a "running" job that
                # nothing is working on.
                repo.update(job, status=JobStatus.queued)
                ids.append(job.id)

        for job_id in ids:
            self._queue.put_nowait(job_id)
        if ids:
            log.info("resuming %d unfinished job(s): %s", len(ids), ids)
        return len(ids)

    # --- submitting work ---------------------------------------------------

    def create_job(
        self,
        *,
        url: str | None = None,
        novel_id: int | None = None,
        job_type: JobType = JobType.crawl,
        params: dict[str, Any] | None = None,
    ) -> Job:
        """Persist a job and queue it."""
        payload = dict(params or {})
        if url:
            payload["url"] = url

        with session_scope() as session:
            job = JobRepository(session).create(
                type=job_type, novel_id=novel_id, params=payload
            )
            job_id = job.id
            session.expunge(job)

        self._queue.put_nowait(job_id)
        self.hub.publish(
            Progress(job_id=job_id, status=JobStatus.queued.value, message="queued")
        )
        return job

    # --- control -----------------------------------------------------------

    def pause(self, job_id: int) -> bool:
        control = self._controls.get(job_id)
        if control is None:
            return False
        control.pause()
        self._set_status(job_id, JobStatus.paused)
        self.hub.publish(
            Progress(job_id=job_id, status=JobStatus.paused.value, message="paused")
        )
        return True

    def resume_job(self, job_id: int) -> bool:
        control = self._controls.get(job_id)
        if control is not None:
            control.resume()
            self._set_status(job_id, JobStatus.running)
            self.hub.publish(
                Progress(job_id=job_id, status=JobStatus.running.value, message="resumed")
            )
            return True

        # Not in flight: a paused job from before a restart just goes back in
        # the queue, where it will skip whatever is already on disk.
        with session_scope() as session:
            repo = JobRepository(session)
            job = repo.get(job_id)
            if job is None or job.status not in (JobStatus.paused, JobStatus.failed):
                return False
            repo.update(job, status=JobStatus.queued, finished_at=None)

        self._queue.put_nowait(job_id)
        return True

    def cancel(self, job_id: int) -> bool:
        control = self._controls.get(job_id)
        if control is not None:
            control.cancel()
            return True

        # Still waiting in the queue: mark it so the worker drops it.
        with session_scope() as session:
            repo = JobRepository(session)
            job = repo.get(job_id)
            if job is None or job.status in (
                JobStatus.done,
                JobStatus.failed,
                JobStatus.cancelled,
            ):
                return False
            repo.update(job, status=JobStatus.cancelled, finished_at=utcnow())

        self.hub.publish(
            Progress(job_id=job_id, status=JobStatus.cancelled.value, message="cancelled")
        )
        self.hub.close(job_id)
        return True

    def is_active(self, job_id: int) -> bool:
        return job_id in self._controls

    # --- internals ---------------------------------------------------------

    async def _loop(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                await self._run_one(job_id)
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - the runner handles its own
                log.exception("worker failed on job %s", job_id)
            finally:
                self._queue.task_done()

    async def _run_one(self, job_id: int) -> None:
        with session_scope() as session:
            job = JobRepository(session).get(job_id)
            if job is None:
                return
            # Cancelled while it sat in the queue.
            if job.status is JobStatus.cancelled:
                log.info("skipping job %s: cancelled before it started", job_id)
                return

            job_type = job.type

        control = JobControl()
        self._controls[job_id] = control
        try:
            await self._runner_for(job_type).run(job_id, control)
        finally:
            self._controls.pop(job_id, None)

    def _runner_for(self, job_type: JobType):
        """Pick the runner for a job type.

        Translation is a separate runner because it touches no network beyond
        the translation API and must never re-download a chapter.
        """
        if job_type is JobType.translate:
            if self._translate_runner_factory is not None:
                return self._translate_runner_factory()
            return TranslateRunner(hub=self.hub, settings=self.settings)
        return self._runner()

    def _runner(self) -> CrawlRunner:
        if self._runner_factory is not None:
            return self._runner_factory()

        if self._owned_fetcher is None:
            # Built once per process: connections stay warm, the per-host
            # throttle is shared across jobs, and a browser launched for one
            # protected site is reused by the next.
            with session_scope() as session:
                store = SettingsStore(session)
                settings = store.effective_settings()
                cookies = store.playwright_cookies()
                browser_enabled = store.browser_enabled

            self._owned_fetcher = SmartFetcher(
                http=HttpFetcher(settings=settings),
                browser=BrowserFetcher(settings=settings, cookies=cookies)
                if browser_enabled
                else None,
                settings=settings,
                browser_enabled=browser_enabled,
            )
            self._effective_settings = settings

        return CrawlRunner(
            fetcher=self._owned_fetcher,
            hub=self.hub,
            settings=self._effective_settings or self.settings,
        )

    async def reload_fetcher(self) -> None:
        """Drop the cached fetcher so saved settings take effect.

        Called after the Settings page saves: the next job builds a fresh
        fetcher with the new proxy, cookies and limits.
        """
        fetcher, self._owned_fetcher = self._owned_fetcher, None
        self._effective_settings = None
        if fetcher is not None:
            await fetcher.aclose()

    def _set_status(self, job_id: int, status: JobStatus) -> None:
        with session_scope() as session:
            repo = JobRepository(session)
            job = repo.get(job_id)
            if job is not None:
                repo.update(job, status=status)

    # --- test/ops helper ---------------------------------------------------

    async def wait_idle(self) -> None:
        """Block until the queue is drained. Used by tests and the CLI."""
        await self._queue.join()
