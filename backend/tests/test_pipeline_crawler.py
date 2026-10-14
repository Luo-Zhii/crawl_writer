"""The crawl runner.

A fake adapter stands in for a real site so the tests can make chapters fail,
lock, or hang on demand. The adapter is injected through ``source_factory``
rather than registered globally, so the real registry stays untouched.
"""

from __future__ import annotations

import asyncio

import pytest

from app.db.models import ChapterStatus, JobStatus, JobType, Lang, NovelStatus
from app.db.repository import ChapterRepository, JobRepository, NovelRepository
from app.db.session import session_scope
from app.db.storage import ChapterStorage
from app.fetch.errors import Blocked, TransientError
from app.pipeline.control import JobControl
from app.pipeline.crawler import CrawlRunner
from app.pipeline.events import EventHub
from app.sources.base import ChapterLocked, ChapterRef, NovelInfo, Source, SourceError

NOVEL_URL = "https://fake.test/truyen/abc.1/"

BODY = "Một đoạn văn dài vừa đủ để vượt ngưỡng kiểm tra nội dung. " * 6


class FakeSource(Source):
    key = "faketest"
    name = "Fake Test"
    domains = ("fake.test",)
    lang = Lang.vi

    def __init__(
        self,
        fetcher=None,
        *,
        chapters: int = 3,
        fail: set[int] | None = None,
        locked: set[int] | None = None,
        slow: set[int] | None = None,
        titles: dict[int, str] | None = None,
        numbers: list[int] | None = None,
    ) -> None:
        super().__init__(fetcher)
        self.numbers = numbers or list(range(1, chapters + 1))
        self.fail = fail or set()
        self.locked = locked or set()
        self.slow = slow or set()
        self.titles = titles or {}
        self.fetched: list[int] = []

    def canonical_url(self, url: str) -> str:
        return NOVEL_URL

    async def novel_info(self, url: str) -> NovelInfo:
        return NovelInfo(
            title="Truyện Giả",
            url=NOVEL_URL,
            author="Tác giả Giả",
            description="Mô tả.",
            genres=["Tiên hiệp"],
            status=NovelStatus.ongoing,
            lang=self.lang,
        )

    async def chapter_list(self, url: str) -> list[ChapterRef]:
        return [
            ChapterRef(
                number=number,
                title=self.titles.get(number, f"Chương {number}"),
                url=f"https://fake.test/truyen/abc/chuong-{number}.html",
            )
            for number in self.numbers
        ]

    async def chapter_content(self, url: str) -> str:
        number = int(url.rsplit("chuong-", 1)[1].split(".")[0])
        self.fetched.append(number)

        if number in self.slow:
            await asyncio.sleep(5)
        if number in self.locked:
            raise ChapterLocked("Chương VIP", url=url)
        if number in self.fail:
            raise TransientError("Server error", url=url, status=502)
        return f"Chương {number}\n\n{BODY}"


def make_runner(source: FakeSource, **kwargs) -> CrawlRunner:
    return CrawlRunner(
        fetcher=None,
        hub=kwargs.pop("hub", EventHub()),
        source_factory=lambda url, fetcher: source,
        **kwargs,
    )


def new_job(url: str = NOVEL_URL, job_type: JobType = JobType.crawl) -> int:
    with session_scope() as session:
        job = JobRepository(session).create(type=job_type, params={"url": url})
        return job.id


def job_row(job_id: int):
    with session_scope() as session:
        job = JobRepository(session).get(job_id)
        session.expunge(job)
        return job


def chapters_of(novel_id: int):
    with session_scope() as session:
        rows = ChapterRepository(session).list_for_novel(novel_id)
        for row in rows:
            session.expunge(row)
        return rows


def only_novel():
    with session_scope() as session:
        novels = NovelRepository(session).list()
        assert len(novels) == 1
        session.expunge(novels[0])
        return novels[0]


# --- happy path ------------------------------------------------------------


async def test_crawl_saves_novel_chapters_and_files():
    source = FakeSource(chapters=3)
    job_id = new_job()

    await make_runner(source).run(job_id, JobControl())

    novel = only_novel()
    assert novel.title == "Truyện Giả"
    assert novel.source == "faketest"
    assert novel.genres == ["Tiên hiệp"]
    assert novel.last_checked_at is not None

    rows = chapters_of(novel.id)
    assert [c.number for c in rows] == [1, 2, 3]
    assert all(c.status is ChapterStatus.done for c in rows)
    assert all(c.char_count > 0 and c.fetched_at is not None for c in rows)

    storage = ChapterStorage()
    assert all(storage.exists(novel.id, number) for number in (1, 2, 3))
    assert "Chương 2" in storage.read(novel.id, 2)


async def test_job_finishes_with_counters():
    source = FakeSource(chapters=4)
    job_id = new_job()

    await make_runner(source).run(job_id, JobControl())

    job = job_row(job_id)
    assert job.status is JobStatus.done
    assert job.total == 4
    assert job.done == 4
    assert job.failed == 0
    assert job.started_at is not None and job.finished_at is not None


async def test_chapter_numbering_gaps_are_preserved():
    """A site that skips a number must not shift everything after it."""
    source = FakeSource(numbers=[1, 2, 5])
    job_id = new_job()

    await make_runner(source).run(job_id, JobControl())

    novel = only_novel()
    assert [c.number for c in chapters_of(novel.id)] == [1, 2, 5]
    assert ChapterStorage().exists(novel.id, 5)


# --- failures are isolated -------------------------------------------------


async def test_one_failed_chapter_does_not_abort_the_job():
    source = FakeSource(chapters=4, fail={2})
    job_id = new_job()

    await make_runner(source).run(job_id, JobControl())

    job = job_row(job_id)
    assert job.status is JobStatus.done, "the job itself should still complete"
    assert job.done == 3
    assert job.failed == 1

    rows = {c.number: c for c in chapters_of(only_novel().id)}
    assert rows[2].status is ChapterStatus.failed
    assert rows[2].error
    assert rows[3].status is ChapterStatus.done


async def test_locked_chapter_is_skipped_not_failed():
    """A paid chapter is not an error; there is nothing to retry."""
    source = FakeSource(chapters=3, locked={3})
    job_id = new_job()

    await make_runner(source).run(job_id, JobControl())

    job = job_row(job_id)
    assert job.skipped == 1
    assert job.failed == 0

    rows = {c.number: c for c in chapters_of(only_novel().id)}
    assert rows[3].status is ChapterStatus.skipped_vip


async def test_blocked_chapter_records_the_reason():
    class BlockingSource(FakeSource):
        async def chapter_content(self, url: str) -> str:
            raise Blocked("Refused", url=url, status=403, reason="forbidden")

    job_id = new_job()
    await make_runner(BlockingSource(chapters=1)).run(job_id, JobControl())

    rows = chapters_of(only_novel().id)
    assert rows[0].status is ChapterStatus.failed
    assert "blocked" in rows[0].error


async def test_empty_chapter_body_counts_as_a_failure():
    """Guards against storing an error page as a chapter."""

    class EmptySource(FakeSource):
        async def chapter_content(self, url: str) -> str:
            return "   "

    novel_job = new_job()
    await make_runner(EmptySource(chapters=1)).run(novel_job, JobControl())

    novel = only_novel()
    assert chapters_of(novel.id)[0].status is ChapterStatus.failed
    assert not ChapterStorage().exists(novel.id, 1)


async def test_job_fails_when_the_novel_page_cannot_be_parsed():
    class BrokenSource(FakeSource):
        async def novel_info(self, url: str) -> NovelInfo:
            raise SourceError("No novel title found", url=url)

    job_id = new_job()
    await make_runner(BrokenSource()).run(job_id, JobControl())

    job = job_row(job_id)
    assert job.status is JobStatus.failed
    assert "No novel title" in job.error


async def test_unsupported_url_fails_the_job_with_a_reason():
    job_id = new_job(url="https://nowhere.test/abc")
    runner = CrawlRunner(fetcher=None, hub=EventHub())  # real registry

    await runner.run(job_id, JobControl())

    job = job_row(job_id)
    assert job.status is JobStatus.failed
    assert "No adapter" in job.error


# --- resume ----------------------------------------------------------------


async def test_rerun_skips_chapters_already_on_disk():
    source = FakeSource(chapters=3)
    await make_runner(source).run(new_job(), JobControl())
    assert sorted(source.fetched) == [1, 2, 3]

    again = FakeSource(chapters=3)
    await make_runner(again).run(new_job(), JobControl())

    assert again.fetched == [], "nothing should be re-downloaded"


async def test_resume_fetches_only_what_is_missing():
    """Simulates a crawl interrupted after the first chapter."""
    source = FakeSource(chapters=3, fail={2, 3})
    await make_runner(source).run(new_job(), JobControl())

    resumed = FakeSource(chapters=3)
    await make_runner(resumed).run(new_job(), JobControl())

    assert sorted(resumed.fetched) == [2, 3]
    rows = chapters_of(only_novel().id)
    assert all(c.status is ChapterStatus.done for c in rows)


async def test_update_job_picks_up_new_chapters_only():
    await make_runner(FakeSource(chapters=2)).run(new_job(), JobControl())
    novel = only_novel()

    grown = FakeSource(chapters=4)
    with session_scope() as session:
        job = JobRepository(session).create(
            type=JobType.update, novel_id=novel.id, params={}
        )
        update_id = job.id

    await make_runner(grown).run(update_id, JobControl())

    assert sorted(grown.fetched) == [3, 4]
    assert len(chapters_of(novel.id)) == 4


async def test_failed_chapters_stop_being_retried_after_the_limit():
    """Otherwise every update job would re-hammer a permanently broken chapter."""
    source = FakeSource(chapters=2, fail={2})
    runner = make_runner(source)
    await runner.run(new_job(), JobControl())
    novel = only_novel()

    # An update job honours the retry limit; attempts is already 1.
    for _ in range(runner.settings.chapter_retry_limit + 1):
        with session_scope() as session:
            job = JobRepository(session).create(
                type=JobType.update, novel_id=novel.id, params={}
            )
            job_id = job.id
        await make_runner(FakeSource(chapters=2, fail={2})).run(job_id, JobControl())

    with session_scope() as session:
        chapter = ChapterRepository(session).get_by_number(novel.id, 2)
        attempts = chapter.attempts

    assert attempts <= runner.settings.chapter_retry_limit + 1


async def test_a_full_crawl_retries_failed_chapters_regardless_of_attempts():
    source = FakeSource(chapters=2, fail={2})
    await make_runner(source).run(new_job(), JobControl())

    retry = FakeSource(chapters=2)
    await make_runner(retry).run(new_job(job_type=JobType.crawl), JobControl())

    assert retry.fetched == [2]


# --- cancel ----------------------------------------------------------------


async def test_cancel_before_start_marks_the_job_cancelled():
    control = JobControl()
    control.cancel()
    job_id = new_job()

    await make_runner(FakeSource()).run(job_id, control)

    assert job_row(job_id).status is JobStatus.cancelled


async def test_cancel_midway_stops_fetching_and_keeps_finished_work():
    source = FakeSource(chapters=6, slow={3})
    control = JobControl()
    runner = make_runner(source)

    task = asyncio.create_task(runner.run(new_job(), control))
    await asyncio.sleep(0.05)
    control.cancel()
    await asyncio.wait_for(task, timeout=2)

    novel = only_novel()
    done = [c for c in chapters_of(novel.id) if c.status is ChapterStatus.done]
    assert len(done) < 6, "cancel should have cut the crawl short"
    # Whatever finished is still readable.
    assert all(ChapterStorage().exists(novel.id, c.number) for c in done)


# --- progress events -------------------------------------------------------


async def test_progress_events_are_published():
    hub = EventHub()
    received = []

    async def consume() -> None:
        async for event in hub.stream(1):
            received.append(event)

    with session_scope() as session:
        job = JobRepository(session).create(type=JobType.crawl, params={"url": NOVEL_URL})
        job_id = job.id

    watcher = asyncio.create_task(consume())
    await asyncio.sleep(0)
    await make_runner(FakeSource(chapters=2), hub=hub).run(job_id, JobControl())
    await asyncio.wait_for(watcher, timeout=2)

    assert received, "expected progress events"
    assert received[-1].status == JobStatus.done.value
    assert any(e.chapter == 2 for e in received)
    assert received[-1].percent == 100.0


@pytest.mark.parametrize("chapters", [1, 5])
async def test_totals_match_the_chapter_list(chapters: int):
    job_id = new_job()

    await make_runner(FakeSource(chapters=chapters)).run(job_id, JobControl())

    assert job_row(job_id).total == chapters


# --- the new-chapter counter -----------------------------------------------


def update_job(novel_id: int) -> int:
    with session_scope() as session:
        job = JobRepository(session).create(
            type=JobType.update, novel_id=novel_id, params={}
        )
        return job.id


async def test_a_first_crawl_does_not_count_as_new_chapters():
    """Every chapter is new on day one, which would badge the whole library."""
    await make_runner(FakeSource(chapters=3)).run(new_job(), JobControl())

    assert only_novel().new_chapters == 0


async def test_an_update_counts_the_chapters_it_discovered():
    await make_runner(FakeSource(chapters=2)).run(new_job(), JobControl())
    novel = only_novel()

    await make_runner(FakeSource(chapters=5)).run(update_job(novel.id), JobControl())

    assert only_novel().new_chapters == 3


async def test_an_update_with_nothing_new_leaves_the_counter_alone():
    await make_runner(FakeSource(chapters=2)).run(new_job(), JobControl())
    novel = only_novel()

    await make_runner(FakeSource(chapters=2)).run(update_job(novel.id), JobControl())

    assert only_novel().new_chapters == 0


async def test_successive_updates_add_up():
    """Two checks between visits must not have the second hide the first."""
    await make_runner(FakeSource(chapters=1)).run(new_job(), JobControl())
    novel = only_novel()

    await make_runner(FakeSource(chapters=3)).run(update_job(novel.id), JobControl())
    await make_runner(FakeSource(chapters=4)).run(update_job(novel.id), JobControl())

    assert only_novel().new_chapters == 3
