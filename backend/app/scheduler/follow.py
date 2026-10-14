"""Periodic checks for followed novels.

An ongoing novel gets a few chapters a week, so the point of following one is
not having to remember to press a button. The scheduler only *enqueues* update
jobs — the existing worker does the fetching — so a check that lands while a
crawl is running simply queues behind it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import NamedTuple

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.logging import get_logger
from app.db.models import JobStatus, JobType, utcnow
from app.db.repository import JobRepository, NovelRepository
from app.db.session import session_scope
from app.db.settings_store import SettingsStore

log = get_logger(__name__)

JOB_ID = "follow-check"


class CheckResult(NamedTuple):
    """What one pass over the followed novels did."""

    #: Jobs queued, one per novel that was due and idle.
    job_ids: list[int]
    #: Followed novels looked at, including the ones skipped.
    considered: int


class FollowScheduler:
    """Runs an update check for followed novels on an interval."""

    def __init__(self, manager, *, scheduler: AsyncIOScheduler | None = None) -> None:
        self.manager = manager
        self._scheduler = scheduler or AsyncIOScheduler()
        self._started = False

    # --- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        with session_scope() as session:
            store = SettingsStore(session)
            enabled = store.follow_enabled
            hours = store.follow_interval_hours

        if not enabled:
            log.info("follow checks are disabled")
            return

        self._scheduler.add_job(
            self.check_now,
            trigger=IntervalTrigger(hours=hours),
            id=JOB_ID,
            replace_existing=True,
            # A check that overruns should not pile up behind itself.
            max_instances=1,
            coalesce=True,
            # Wait one interval before the first run: starting the server
            # should not immediately hammer every followed site.
            next_run_time=utcnow() + timedelta(hours=hours),
        )
        self._scheduler.start()
        self._started = True
        log.info("follow checks every %d hour(s)", hours)

    def shutdown(self) -> None:
        if self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False

    @property
    def running(self) -> bool:
        return self._started

    def next_run(self) -> datetime | None:
        if not self._started:
            return None
        job = self._scheduler.get_job(JOB_ID)
        return getattr(job, "next_run_time", None) if job else None

    def reload(self) -> None:
        """Re-read the settings and reschedule.

        A fresh scheduler rather than a rescheduled job: APScheduler will not
        restart one that has been shut down, and the settings change may be
        turning the whole thing off.
        """
        self.shutdown()
        self._scheduler = AsyncIOScheduler()
        self.start()

    # --- the check ---------------------------------------------------------

    async def check_now(self) -> CheckResult:
        """Queue an update job for every followed novel that is due.

        Runs regardless of ``follow_enabled`` so the "check now" button still
        works when the timer is switched off.
        """
        with session_scope() as session:
            store = SettingsStore(session)
            interval = timedelta(hours=store.follow_interval_hours)
            novels = NovelRepository(session).list(limit=500, followed=True)
            considered = len(novels)
            now = utcnow()

            due: list[int] = []
            for novel in novels:
                last = novel.last_checked_at
                if last is None or now - last >= interval:
                    due.append(novel.id)

            if not due:
                log.debug("no followed novels are due for a check")
                return CheckResult(job_ids=[], considered=considered)

            # A novel already waiting in the queue must not be queued twice.
            pending = {
                job.novel_id
                for job in JobRepository(session).list(limit=200)
                if job.status in (JobStatus.queued, JobStatus.running)
                and job.novel_id is not None
            }

        created: list[int] = []
        queued_for: list[int] = []
        for novel_id in due:
            if novel_id in pending:
                log.debug("novel %s already has a job in flight", novel_id)
                continue
            job = self.manager.create_job(novel_id=novel_id, job_type=JobType.update)
            created.append(job.id)
            queued_for.append(novel_id)

        # Stamp the attempt, not the success. The crawl sets this too, but only
        # when it gets as far as reading the novel page: without stamping here,
        # a novel whose source is broken would come up due on every single
        # check, and two presses of "check now" would queue it twice.
        if queued_for:
            with session_scope() as session:
                repo = NovelRepository(session)
                for novel_id in queued_for:
                    novel = repo.get(novel_id)
                    if novel is not None:
                        repo.update(novel, last_checked_at=now)

        if created:
            log.info("queued %d update job(s) for followed novels", len(created))
        return CheckResult(job_ids=created, considered=considered)
