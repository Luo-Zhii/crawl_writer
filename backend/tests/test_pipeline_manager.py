"""The worker queue: scheduling, control, and restart recovery."""

from __future__ import annotations

import asyncio

from app.db.models import JobStatus, JobType
from app.db.repository import JobRepository
from app.db.session import session_scope
from app.pipeline.control import JobCancelled, JobControl
from app.pipeline.events import EventHub, Progress
from app.pipeline.manager import JobManager


class RecordingRunner:
    """Stands in for CrawlRunner: records runs, optionally waits for a signal."""

    def __init__(self, hub: EventHub, *, gate: asyncio.Event | None = None) -> None:
        self.hub = hub
        self.gate = gate
        self.ran: list[int] = []
        self.started = asyncio.Event()

    async def run(self, job_id: int, control: JobControl) -> None:
        self.ran.append(job_id)
        self.started.set()
        try:
            if self.gate is not None:
                await self.gate.wait()
            await control.checkpoint()
        except JobCancelled:
            self._finish(job_id, JobStatus.cancelled)
            return
        self._finish(job_id, JobStatus.done)

    def _finish(self, job_id: int, status: JobStatus) -> None:
        with session_scope() as session:
            repo = JobRepository(session)
            job = repo.get(job_id)
            if job is not None:
                repo.update(job, status=status)
        self.hub.publish(Progress(job_id=job_id, status=status.value))
        self.hub.close(job_id)


def make_manager(gate: asyncio.Event | None = None) -> tuple[JobManager, RecordingRunner]:
    hub = EventHub()
    runner = RecordingRunner(hub, gate=gate)
    manager = JobManager(hub=hub, runner_factory=lambda: runner)
    return manager, runner


def status_of(job_id: int) -> JobStatus:
    with session_scope() as session:
        return JobRepository(session).get(job_id).status


# --- queueing --------------------------------------------------------------


async def test_created_job_is_persisted_and_queued():
    manager, runner = make_manager()
    await manager.start(resume=False)

    job = manager.create_job(url="https://fake.test/a.1/")
    await manager.wait_idle()
    await manager.stop()

    assert job.id is not None
    assert job.params["url"] == "https://fake.test/a.1/"
    assert runner.ran == [job.id]
    assert status_of(job.id) is JobStatus.done


async def test_jobs_run_in_order():
    manager, runner = make_manager()
    await manager.start(resume=False)

    first = manager.create_job(url="https://fake.test/a.1/")
    second = manager.create_job(url="https://fake.test/b.2/")
    await manager.wait_idle()
    await manager.stop()

    assert runner.ran == [first.id, second.id]


async def test_create_job_emits_a_queued_event():
    manager, _ = make_manager()
    received = []

    job = manager.create_job(url="https://fake.test/a.1/")

    async def consume() -> None:
        async for event in manager.hub.stream(job.id):
            received.append(event)

    # Subscribing after creation is the normal case for a browser, so the
    # queued event is allowed to be missed; the SSE route sends a snapshot.
    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    manager.hub.close(job.id)
    await asyncio.wait_for(task, timeout=1)

    assert status_of(job.id) is JobStatus.queued


# --- control ---------------------------------------------------------------


async def test_pause_and_resume_a_running_job():
    gate = asyncio.Event()
    manager, runner = make_manager(gate)
    await manager.start(resume=False)
    job = manager.create_job(url="https://fake.test/a.1/")
    await asyncio.wait_for(runner.started.wait(), timeout=1)

    assert manager.pause(job.id) is True
    assert status_of(job.id) is JobStatus.paused
    assert manager.is_active(job.id) is True

    assert manager.resume_job(job.id) is True
    assert status_of(job.id) is JobStatus.running

    gate.set()
    await manager.wait_idle()
    await manager.stop()

    assert status_of(job.id) is JobStatus.done


async def test_cancel_a_running_job():
    gate = asyncio.Event()
    manager, runner = make_manager(gate)
    await manager.start(resume=False)
    job = manager.create_job(url="https://fake.test/a.1/")
    await asyncio.wait_for(runner.started.wait(), timeout=1)

    assert manager.cancel(job.id) is True
    gate.set()
    await manager.wait_idle()
    await manager.stop()

    assert status_of(job.id) is JobStatus.cancelled


async def test_cancelling_a_queued_job_stops_it_from_running():
    gate = asyncio.Event()
    manager, runner = make_manager(gate)
    await manager.start(resume=False)

    running = manager.create_job(url="https://fake.test/a.1/")
    waiting = manager.create_job(url="https://fake.test/b.2/")
    await asyncio.wait_for(runner.started.wait(), timeout=1)

    assert manager.cancel(waiting.id) is True
    gate.set()
    await manager.wait_idle()
    await manager.stop()

    assert status_of(waiting.id) is JobStatus.cancelled
    assert waiting.id not in runner.ran, "a cancelled job should never start"
    assert running.id in runner.ran


async def test_pausing_a_job_that_is_not_running_is_rejected():
    manager, _ = make_manager()

    job = manager.create_job(url="https://fake.test/a.1/")

    assert manager.pause(job.id) is False


async def test_cancelling_a_finished_job_is_rejected():
    manager, _ = make_manager()
    await manager.start(resume=False)
    job = manager.create_job(url="https://fake.test/a.1/")
    await manager.wait_idle()
    await manager.stop()

    assert manager.cancel(job.id) is False


async def test_resuming_a_paused_job_after_a_restart_requeues_it():
    """No control switch exists any more, so it goes back through the queue."""
    with session_scope() as session:
        job = JobRepository(session).create(type=JobType.crawl, params={"url": "x"})
        JobRepository(session).update(job, status=JobStatus.paused)
        job_id = job.id

    manager, runner = make_manager()
    await manager.start(resume=False)

    assert manager.resume_job(job_id) is True
    await manager.wait_idle()
    await manager.stop()

    assert runner.ran == [job_id]


# --- restart recovery ------------------------------------------------------


async def test_unfinished_jobs_are_requeued_on_start():
    """The core of resume: a crawl interrupted by a restart continues."""
    with session_scope() as session:
        repo = JobRepository(session)
        queued = repo.create(type=JobType.crawl, params={"url": "a"})
        running = repo.create(type=JobType.crawl, params={"url": "b"})
        repo.update(running, status=JobStatus.running)
        finished = repo.create(type=JobType.crawl, params={"url": "c"})
        repo.update(finished, status=JobStatus.done)
        ids = (queued.id, running.id, finished.id)

    manager, runner = make_manager()
    await manager.start()
    await manager.wait_idle()
    await manager.stop()

    assert sorted(runner.ran) == sorted(ids[:2])
    assert ids[2] not in runner.ran, "a finished job must not run again"


async def test_requeued_jobs_are_marked_queued_not_left_running():
    """Otherwise the UI shows a running job that nothing is working on."""
    with session_scope() as session:
        repo = JobRepository(session)
        job = repo.create(type=JobType.crawl, params={"url": "a"})
        repo.update(job, status=JobStatus.running)
        job_id = job.id

    gate = asyncio.Event()
    manager, _ = make_manager(gate)
    count = manager.requeue_unfinished()

    assert count == 1
    assert status_of(job_id) is JobStatus.queued


async def test_start_is_idempotent():
    manager, runner = make_manager()
    await manager.start(resume=False)
    await manager.start(resume=False)

    job = manager.create_job(url="https://fake.test/a.1/")
    await manager.wait_idle()
    await manager.stop()

    assert runner.ran == [job.id], "a second start must not double-process jobs"
