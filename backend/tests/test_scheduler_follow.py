"""The follow scheduler: which novels get queued, and when."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from app.db.models import Job, JobStatus, JobType, utcnow
from app.db.repository import JobRepository, NovelRepository
from app.db.session import session_scope
from app.db.settings_store import SettingsStore
from app.scheduler import JOB_ID, FollowScheduler


class FakeManager:
    """Records what the scheduler asked for instead of crawling anything."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._next_id = 100

    def create_job(self, **kwargs: Any) -> Job:
        self.calls.append(kwargs)
        self._next_id += 1
        return Job(id=self._next_id, type=kwargs["job_type"], novel_id=kwargs["novel_id"])


@pytest.fixture
def manager() -> FakeManager:
    return FakeManager()


@pytest.fixture
def scheduler(manager: FakeManager) -> FollowScheduler:
    return FollowScheduler(manager)


def _set(session, novel, **fields):
    return NovelRepository(session).update(novel, **fields)


# --- which novels are due --------------------------------------------------


@pytest.mark.asyncio
async def test_a_never_checked_followed_novel_is_due(
    novel_factory, session, scheduler: FollowScheduler, manager: FakeManager
):
    novel = _set(session, novel_factory(), followed=True, last_checked_at=None)

    result = await scheduler.check_now()

    assert result.job_ids
    assert result.considered == 1
    assert manager.calls == [{"novel_id": novel.id, "job_type": JobType.update}]


@pytest.mark.asyncio
async def test_an_unfollowed_novel_is_left_alone(
    novel_factory, session, scheduler: FollowScheduler, manager: FakeManager
):
    _set(session, novel_factory(), followed=False, last_checked_at=None)

    result = await scheduler.check_now()

    assert result == ([], 0)
    assert manager.calls == []


@pytest.mark.asyncio
async def test_a_novel_checked_recently_is_skipped(
    novel_factory, session, scheduler: FollowScheduler, manager: FakeManager
):
    _set(session, novel_factory(), followed=True, last_checked_at=utcnow())

    result = await scheduler.check_now()

    # Considered, but not due: the badge should not re-trigger a crawl that
    # just finished.
    assert result.considered == 1
    assert result.job_ids == []


@pytest.mark.asyncio
async def test_a_novel_past_the_interval_is_due_again(
    novel_factory, session, scheduler: FollowScheduler, manager: FakeManager
):
    with session_scope() as s:
        SettingsStore(s).update({"follow_interval_hours": 2})
    stale = utcnow() - timedelta(hours=3)
    _set(session, novel_factory(), followed=True, last_checked_at=stale)

    result = await scheduler.check_now()

    assert len(result.job_ids) == 1


@pytest.mark.asyncio
async def test_the_interval_setting_is_honoured(
    novel_factory, session, scheduler: FollowScheduler
):
    with session_scope() as s:
        SettingsStore(s).update({"follow_interval_hours": 24})
    _set(session, novel_factory(), followed=True, last_checked_at=utcnow() - timedelta(hours=3))

    result = await scheduler.check_now()

    assert result.job_ids == []


# --- not queueing the same novel twice -------------------------------------


@pytest.mark.parametrize("status", [JobStatus.queued, JobStatus.running])
@pytest.mark.asyncio
async def test_a_novel_with_a_job_in_flight_is_not_queued_again(
    status, novel_factory, session, scheduler: FollowScheduler, manager: FakeManager
):
    novel = _set(session, novel_factory(), followed=True, last_checked_at=None)
    job = JobRepository(session).create(type=JobType.update, novel_id=novel.id)
    JobRepository(session).update(job, status=status)

    result = await scheduler.check_now()

    assert result.job_ids == []
    assert manager.calls == []


@pytest.mark.asyncio
async def test_a_finished_job_does_not_block_the_next_check(
    novel_factory, session, scheduler: FollowScheduler, manager: FakeManager
):
    novel = _set(session, novel_factory(), followed=True, last_checked_at=None)
    job = JobRepository(session).create(type=JobType.update, novel_id=novel.id)
    JobRepository(session).update(job, status=JobStatus.done)

    result = await scheduler.check_now()

    assert len(result.job_ids) == 1


@pytest.mark.asyncio
async def test_several_due_novels_each_get_their_own_job(
    novel_factory, session, scheduler: FollowScheduler, manager: FakeManager
):
    for index in range(3):
        _set(session, novel_factory(title=f"T{index}"), followed=True, last_checked_at=None)

    result = await scheduler.check_now()

    assert len(result.job_ids) == 3
    assert len(set(result.job_ids)) == 3


# --- lifecycle -------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_schedules_a_job_when_following_is_enabled(scheduler: FollowScheduler):
    scheduler.start()
    try:
        assert scheduler.running
        assert scheduler.next_run() is not None
    finally:
        scheduler.shutdown()


@pytest.mark.asyncio
async def test_the_first_run_waits_one_interval(scheduler: FollowScheduler):
    with session_scope() as s:
        SettingsStore(s).update({"follow_interval_hours": 3})

    scheduler.start()
    try:
        # Booting the server should not immediately hit every followed site.
        assert scheduler.next_run() > utcnow() + timedelta(hours=2)
    finally:
        scheduler.shutdown()


@pytest.mark.asyncio
async def test_start_does_nothing_when_following_is_disabled(scheduler: FollowScheduler):
    with session_scope() as s:
        SettingsStore(s).update({"follow_enabled": False})

    scheduler.start()

    assert not scheduler.running
    assert scheduler.next_run() is None


@pytest.mark.asyncio
async def test_reload_picks_up_a_disabled_setting(scheduler: FollowScheduler):
    scheduler.start()
    try:
        assert scheduler.running

        with session_scope() as s:
            SettingsStore(s).update({"follow_enabled": False})
        scheduler.reload()

        assert not scheduler.running
    finally:
        scheduler.shutdown()


@pytest.mark.asyncio
async def test_reload_applies_a_new_interval(scheduler: FollowScheduler):
    with session_scope() as s:
        SettingsStore(s).update({"follow_interval_hours": 1})
    scheduler.start()
    try:
        first = scheduler.next_run()

        with session_scope() as s:
            SettingsStore(s).update({"follow_interval_hours": 48})
        scheduler.reload()

        assert scheduler.next_run() > first
        assert scheduler._scheduler.get_job(JOB_ID) is not None
    finally:
        scheduler.shutdown()


@pytest.mark.asyncio
async def test_shutdown_is_safe_to_call_twice(scheduler: FollowScheduler):
    scheduler.start()
    scheduler.shutdown()
    scheduler.shutdown()

    assert not scheduler.running


# --- the attempt is what starts the clock ----------------------------------


@pytest.mark.asyncio
async def test_queueing_stamps_the_check_time(
    novel_factory, session, scheduler: FollowScheduler
):
    novel = _set(session, novel_factory(), followed=True, last_checked_at=None)

    await scheduler.check_now()

    with session_scope() as s:
        assert NovelRepository(s).get(novel.id).last_checked_at is not None


@pytest.mark.asyncio
async def test_a_broken_novel_is_not_requeued_on_the_next_check(
    novel_factory, session, scheduler: FollowScheduler, manager: FakeManager
):
    """The interval has to gate retries even when the crawl never succeeds.

    A failed update never reaches the step that records a check, so without
    stamping at queue time the novel would come up due every single pass.
    """
    novel = _set(session, novel_factory(), followed=True, last_checked_at=None)

    first = await scheduler.check_now()
    # The job failed, so nothing is in flight to block a second attempt.
    with session_scope() as s:
        job = JobRepository(s).create(type=JobType.update, novel_id=novel.id)
        JobRepository(s).update(job, status=JobStatus.failed)
    second = await scheduler.check_now()

    assert len(first.job_ids) == 1
    assert second.job_ids == []
    assert len(manager.calls) == 1


@pytest.mark.asyncio
async def test_a_novel_that_was_skipped_keeps_its_old_check_time(
    novel_factory, session, scheduler: FollowScheduler
):
    """Only novels actually queued get stamped."""
    novel = _set(session, novel_factory(), followed=True, last_checked_at=None)
    job = JobRepository(session).create(type=JobType.update, novel_id=novel.id)
    JobRepository(session).update(job, status=JobStatus.running)

    await scheduler.check_now()

    with session_scope() as s:
        assert NovelRepository(s).get(novel.id).last_checked_at is None
