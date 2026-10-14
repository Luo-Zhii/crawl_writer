"""The translate runner: resume, per-chapter isolation, cancel."""

from __future__ import annotations

import asyncio

from sqlmodel import Session

from app.db.models import ChapterStatus, JobStatus, JobType, Lang
from app.db.repository import ChapterRepository, GlossaryRepository, JobRepository
from app.db.session import session_scope
from app.db.storage import ChapterStorage
from app.pipeline.control import JobControl
from app.pipeline.events import EventHub
from app.pipeline.translator import TranslateRunner
from app.translate.base import TranslateProvider, TranslationError
from app.translate.glossary import Glossary
from app.translate.service import TranslationService

RAW = "第一段原文。\n\n第二段原文。"


class FakeProvider(TranslateProvider):
    key = "fake"
    name = "Fake"
    chunk_limit = 500

    def __init__(self, *, fail_on: set[str] | None = None, slow: bool = False) -> None:
        self.fail_on = fail_on or set()
        self.slow = slow
        self.calls: list[str] = []

    async def translate(self, text, *, source_lang, target_lang, glossary=None):
        self.calls.append(text)
        if self.slow:
            await asyncio.sleep(5)
        if any(marker in text for marker in self.fail_on):
            raise TranslationError("nope", provider=self.key)
        return "[vi] " + text


def make_runner(provider: FakeProvider, *, hub: EventHub | None = None,
                glossary: Glossary | None = None) -> TranslateRunner:
    return TranslateRunner(
        hub=hub or EventHub(),
        service_factory=lambda novel_id: TranslationService(
            [provider], glossary=glossary, use_cache=False
        ),
    )


def zh_novel(novel_factory, session: Session, *, chapters: int = 3):
    """A Chinese novel whose chapters are downloaded and on disk."""
    novel = novel_factory(title="雲端劍客", lang=Lang.zh, chapters=chapters)
    storage = ChapterStorage()
    for number in range(1, chapters + 1):
        storage.write(novel.id, number, f"第{number}章\n\n{RAW}")
    return novel


def new_job(novel_id: int, *, force: bool = False) -> int:
    with session_scope() as session:
        job = JobRepository(session).create(
            type=JobType.translate, novel_id=novel_id, params={"force": force}
        )
        return job.id


def job_row(job_id: int):
    with session_scope() as session:
        job = JobRepository(session).get(job_id)
        session.expunge(job)
        return job


# --- the happy path --------------------------------------------------------


async def test_translates_every_downloaded_chapter(novel_factory, session: Session):
    novel = zh_novel(novel_factory, session, chapters=3)
    provider = FakeProvider()

    await make_runner(provider).run(new_job(novel.id), JobControl())

    storage = ChapterStorage()
    for number in (1, 2, 3):
        translated = storage.read(novel.id, number, translated=True)
        assert translated is not None
        assert translated.startswith("[vi]")
    assert job_row(new_job(novel.id)) is not None


async def test_the_original_is_left_untouched(novel_factory, session: Session):
    """Re-translating must never risk the source text."""
    novel = zh_novel(novel_factory, session, chapters=1)

    await make_runner(FakeProvider()).run(new_job(novel.id), JobControl())

    assert RAW in ChapterStorage().read(novel.id, 1)


async def test_chapters_are_marked_as_translated(novel_factory, session: Session):
    novel = zh_novel(novel_factory, session, chapters=2)

    await make_runner(FakeProvider()).run(new_job(novel.id), JobControl())

    with session_scope() as fresh:
        rows = ChapterRepository(fresh).list_for_novel(novel.id)
        assert all(row.has_translation for row in rows)


async def test_job_counters_and_status(novel_factory, session: Session):
    novel = zh_novel(novel_factory, session, chapters=3)
    job_id = new_job(novel.id)

    await make_runner(FakeProvider()).run(job_id, JobControl())

    job = job_row(job_id)
    assert job.status is JobStatus.done
    assert job.total == 3
    assert job.done == 3
    assert job.failed == 0


# --- resume ----------------------------------------------------------------


async def test_already_translated_chapters_are_skipped(novel_factory, session: Session):
    novel = zh_novel(novel_factory, session, chapters=3)
    await make_runner(FakeProvider()).run(new_job(novel.id), JobControl())

    again = FakeProvider()
    await make_runner(again).run(new_job(novel.id), JobControl())

    assert again.calls == [], "nothing should be re-translated"


async def test_force_retranslates_everything(novel_factory, session: Session):
    novel = zh_novel(novel_factory, session, chapters=2)
    await make_runner(FakeProvider()).run(new_job(novel.id), JobControl())

    again = FakeProvider()
    await make_runner(again).run(new_job(novel.id, force=True), JobControl())

    assert len(again.calls) == 2


async def test_only_downloaded_chapters_are_considered(novel_factory, session: Session):
    novel = zh_novel(novel_factory, session, chapters=3)
    with session_scope() as fresh:
        repo = ChapterRepository(fresh)
        repo.update(repo.get_by_number(novel.id, 2), status=ChapterStatus.failed)

    provider = FakeProvider()
    await make_runner(provider).run(new_job(novel.id), JobControl())

    assert ChapterStorage().read(novel.id, 2, translated=True) is None
    assert len(provider.calls) == 2


# --- failures are isolated -------------------------------------------------


async def test_one_failed_chapter_does_not_stop_the_job(novel_factory, session: Session):
    novel = zh_novel(novel_factory, session, chapters=3)
    provider = FakeProvider(fail_on={"第2章"})
    job_id = new_job(novel.id)

    await make_runner(provider).run(job_id, JobControl())

    job = job_row(job_id)
    assert job.status is JobStatus.done
    assert job.done == 2
    assert job.failed == 1
    storage = ChapterStorage()
    assert storage.read(novel.id, 1, translated=True) is not None
    assert storage.read(novel.id, 2, translated=True) is None


async def test_the_failure_reason_is_recorded_on_the_chapter(
    novel_factory, session: Session
):
    novel = zh_novel(novel_factory, session, chapters=1)
    provider = FakeProvider(fail_on={"第1章"})

    await make_runner(provider).run(new_job(novel.id), JobControl())

    with session_scope() as fresh:
        chapter = ChapterRepository(fresh).get_by_number(novel.id, 1)
        assert chapter.error and "nope" in chapter.error
        assert chapter.has_translation is False


async def test_a_vietnamese_novel_is_refused(novel_factory, session: Session):
    """Nothing to translate, and doing it anyway would overwrite the text."""
    novel = novel_factory(lang=Lang.vi, chapters=1)
    job_id = new_job(novel.id)

    await make_runner(FakeProvider()).run(job_id, JobControl())

    job = job_row(job_id)
    assert job.status is JobStatus.failed
    assert "already in Vietnamese" in job.error


async def test_a_novel_with_nothing_downloaded_finishes_cleanly(
    novel_factory, session: Session
):
    novel = novel_factory(lang=Lang.zh, chapters=2, chapter_status=ChapterStatus.pending)
    job_id = new_job(novel.id)

    await make_runner(FakeProvider()).run(job_id, JobControl())

    assert job_row(job_id).status is JobStatus.done


# --- glossary --------------------------------------------------------------


async def test_the_novels_glossary_is_applied(novel_factory, session: Session):
    novel = zh_novel(novel_factory, session, chapters=1)
    ChapterStorage().write(novel.id, 1, "萧炎走了进来。")
    GlossaryRepository(session).upsert(novel.id, "萧炎", "Tiêu Viêm")

    provider = FakeProvider()
    runner = TranslateRunner(
        service_factory=lambda novel_id: TranslationService(
            [provider],
            glossary=Glossary(GlossaryRepository(session).as_mapping(novel_id)),
            use_cache=False,
        )
    )
    await runner.run(new_job(novel.id), JobControl())

    assert "Tiêu Viêm" in provider.calls[0]
    assert "Tiêu Viêm" in ChapterStorage().read(novel.id, 1, translated=True)


# --- cancel ----------------------------------------------------------------


async def test_cancelling_stops_the_job_and_keeps_finished_work(
    novel_factory, session: Session
):
    novel = zh_novel(novel_factory, session, chapters=5)
    control = JobControl()
    job_id = new_job(novel.id)

    task = asyncio.create_task(make_runner(FakeProvider()).run(job_id, control))
    await asyncio.sleep(0)
    control.cancel()
    await asyncio.wait_for(task, timeout=5)

    assert job_row(job_id).status is JobStatus.cancelled


# --- progress --------------------------------------------------------------


async def test_progress_events_are_published(novel_factory, session: Session):
    novel = zh_novel(novel_factory, session, chapters=2)
    hub = EventHub()
    received = []
    job_id = new_job(novel.id)

    async def consume() -> None:
        async for event in hub.stream(job_id):
            received.append(event)

    watcher = asyncio.create_task(consume())
    await asyncio.sleep(0)
    await make_runner(FakeProvider(), hub=hub).run(job_id, JobControl())
    await asyncio.wait_for(watcher, timeout=5)

    assert received
    assert received[-1].status == JobStatus.done.value
    assert any(event.chapter == 2 for event in received)
