"""Repository layer behaviour."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.db.models import (
    Chapter,
    ChapterStatus,
    JobStatus,
    JobType,
    Lang,
    Novel,
)
from app.db.repository import (
    ChapterRepository,
    JobRepository,
    NovelRepository,
    SettingRepository,
)

# --- novels ----------------------------------------------------------------


def test_add_and_get_novel(session: Session):
    repo = NovelRepository(session)
    novel = repo.add(Novel(source="demo", source_url="https://a.test/1", title="Một"))

    assert novel.id is not None
    assert repo.get(novel.id).title == "Một"


def test_get_by_source_url_finds_existing(session: Session):
    repo = NovelRepository(session)
    repo.add(Novel(source="demo", source_url="https://a.test/1", title="Một"))

    found = repo.get_by_source_url("demo", "https://a.test/1")

    assert found is not None
    # Same URL on a different source is a different novel.
    assert repo.get_by_source_url("other", "https://a.test/1") is None


def test_same_url_twice_on_one_source_is_rejected(session: Session):
    """Re-adding a novel must not silently create a duplicate library entry."""
    repo = NovelRepository(session)
    repo.add(Novel(source="demo", source_url="https://a.test/1", title="Một"))

    with pytest.raises(IntegrityError):
        repo.add(Novel(source="demo", source_url="https://a.test/1", title="Trùng"))


def test_list_is_newest_updated_first(session: Session, novel_factory):
    novel_factory(title="Cũ", source_url="https://a.test/old")
    newer = novel_factory(title="Mới", source_url="https://a.test/new")

    NovelRepository(session).update(newer, title="Mới hơn")
    titles = [n.title for n in NovelRepository(session).list()]

    assert titles[0] == "Mới hơn"


def test_list_filters_followed(session: Session, novel_factory):
    plain = novel_factory(title="Thường", source_url="https://a.test/1")
    followed = novel_factory(title="Theo dõi", source_url="https://a.test/2")
    repo = NovelRepository(session)
    repo.update(followed, followed=True)

    assert [n.id for n in repo.list(followed=True)] == [followed.id]
    assert [n.id for n in repo.list(followed=False)] == [plain.id]
    assert repo.count() == 2
    assert repo.count(followed=True) == 1


def test_list_pagination(session: Session, novel_factory):
    for i in range(5):
        novel_factory(title=f"T{i}", source_url=f"https://a.test/{i}")
    repo = NovelRepository(session)

    assert len(repo.list(limit=2)) == 2
    assert len(repo.list(limit=2, offset=4)) == 1


def test_update_bumps_updated_at(session: Session, novel_factory):
    novel = novel_factory()
    before = novel.updated_at

    updated = NovelRepository(session).update(novel, title="Tên mới")

    assert updated.title == "Tên mới"
    assert updated.updated_at >= before


def test_delete_novel_cascades_to_chapters(session: Session, novel_factory):
    novel = novel_factory(chapters=3)
    novel_id = novel.id
    assert len(ChapterRepository(session).list_for_novel(novel_id)) == 3

    NovelRepository(session).delete(novel)

    assert NovelRepository(session).get(novel_id) is None
    assert ChapterRepository(session).list_for_novel(novel_id) == []


# --- chapters --------------------------------------------------------------


def test_chapters_come_back_in_reading_order(session: Session, novel_factory):
    novel = novel_factory()
    repo = ChapterRepository(session)
    # Inserted out of order on purpose.
    repo.add_many(
        [
            Chapter(novel_id=novel.id, number=number, title=f"C{number}", source_url="u")
            for number in (3, 1, 2)
        ]
    )

    assert [c.number for c in repo.list_for_novel(novel.id)] == [1, 2, 3]


def test_duplicate_chapter_number_is_rejected(session: Session, novel_factory):
    novel = novel_factory(chapters=1)

    with pytest.raises(IntegrityError):
        ChapterRepository(session).add_many(
            [Chapter(novel_id=novel.id, number=1, title="Trùng", source_url="u")]
        )


def test_get_by_number(session: Session, novel_factory):
    novel = novel_factory(chapters=2)
    repo = ChapterRepository(session)

    assert repo.get_by_number(novel.id, 2).title == "Chương 2"
    assert repo.get_by_number(novel.id, 99) is None


def test_status_counts_covers_every_status(session: Session, novel_factory):
    novel = novel_factory(chapters=2)
    repo = ChapterRepository(session)
    repo.update(repo.get_by_number(novel.id, 2), status=ChapterStatus.failed)

    counts = repo.status_counts(novel.id)

    assert counts[ChapterStatus.done.value] == 1
    assert counts[ChapterStatus.failed.value] == 1
    # Statuses with no rows still report zero, so callers need no .get fallback.
    assert counts[ChapterStatus.skipped_vip.value] == 0
    assert counts[ChapterStatus.pending.value] == 0


def test_list_for_novel_filters_by_status(session: Session, novel_factory):
    novel = novel_factory(chapters=3)
    repo = ChapterRepository(session)
    repo.update(repo.get_by_number(novel.id, 1), status=ChapterStatus.pending)

    pending = repo.list_for_novel(novel.id, status=ChapterStatus.pending)

    assert [c.number for c in pending] == [1]


def test_max_number_drives_update_detection(session: Session, novel_factory):
    """Follow/update compares the site's chapter list against this."""
    novel = novel_factory(chapters=4)
    repo = ChapterRepository(session)

    assert repo.max_number(novel.id) == 4
    assert repo.max_number(novel_factory(source_url="https://a.test/empty").id) == 0


def test_delete_for_novel_clears_chapters_only(session: Session, novel_factory):
    novel = novel_factory(chapters=2)
    repo = ChapterRepository(session)

    repo.delete_for_novel(novel.id)

    assert repo.list_for_novel(novel.id) == []
    assert NovelRepository(session).get(novel.id) is not None


# --- jobs ------------------------------------------------------------------


def test_create_job_defaults_to_queued(session: Session, novel_factory):
    novel = novel_factory()
    job = JobRepository(session).create(type=JobType.crawl, novel_id=novel.id)

    assert job.status is JobStatus.queued
    assert job.params == {}
    assert job.done == 0


def test_job_params_survive_roundtrip(session: Session):
    repo = JobRepository(session)
    job = repo.create(type=JobType.export, params={"format": "epub", "volumes": True})

    assert repo.get(job.id).params == {"format": "epub", "volumes": True}


def test_job_list_filters_by_status(session: Session):
    repo = JobRepository(session)
    running = repo.create(type=JobType.crawl)
    repo.create(type=JobType.crawl)
    repo.update(running, status=JobStatus.running)

    assert [j.id for j in repo.list(status=JobStatus.running)] == [running.id]


def test_claim_resumable_returns_unfinished_jobs(session: Session):
    """After a crash these are the jobs the worker should pick back up."""
    repo = JobRepository(session)
    queued = repo.create(type=JobType.crawl)
    running = repo.update(repo.create(type=JobType.crawl), status=JobStatus.running)
    repo.update(repo.create(type=JobType.crawl), status=JobStatus.done)
    repo.update(repo.create(type=JobType.crawl), status=JobStatus.cancelled)

    resumable = {j.id for j in repo.claim_resumable()}

    assert resumable == {queued.id, running.id}


def test_deleting_novel_removes_its_jobs(session: Session, novel_factory):
    novel = novel_factory()
    job_id = JobRepository(session).create(type=JobType.crawl, novel_id=novel.id).id

    NovelRepository(session).delete(novel)
    # Drop the identity map so we read the row back from the database rather
    # than the stale in-memory copy. Each API request gets a fresh session,
    # so this mirrors how the delete is observed in production.
    session.expunge_all()

    assert JobRepository(session).get(job_id) is None


# --- settings --------------------------------------------------------------


def test_setting_get_returns_default_when_unset(session: Session):
    assert SettingRepository(session).get("proxy") is None
    assert SettingRepository(session).get("proxy", "none") == "none"


def test_setting_set_then_get(session: Session):
    repo = SettingRepository(session)
    repo.set("per_domain_delay", 1.5)

    assert repo.get("per_domain_delay") == 1.5


def test_setting_set_overwrites(session: Session):
    repo = SettingRepository(session)
    repo.set("translate_provider", "google")
    repo.set("translate_provider", "gemini")

    assert repo.get("translate_provider") == "gemini"
    assert repo.all() == {"translate_provider": "gemini"}


def test_setting_stores_structured_values(session: Session):
    """Cookies and headers are nested, so JSON values must round-trip."""
    repo = SettingRepository(session)
    cookies = {"tangthuvien.net": {"sid": "abc", "remember": True}}
    repo.set("cookies", cookies)

    assert repo.get("cookies") == cookies


# --- model defaults --------------------------------------------------------


def test_novel_defaults(session: Session):
    novel = NovelRepository(session).add(
        Novel(source="demo", source_url="https://a.test/x", title="X")
    )

    assert novel.lang is Lang.vi
    assert novel.genres == []
    assert novel.followed is False
    assert novel.translate_enabled is False


def test_chapter_defaults(session: Session, novel_factory):
    novel = novel_factory()
    chapter = ChapterRepository(session).add_many(
        [Chapter(novel_id=novel.id, number=1, title="C1", source_url="u")]
    )[0]

    assert chapter.status is ChapterStatus.pending
    assert chapter.attempts == 0
    assert chapter.has_translation is False
    assert chapter.fetched_at is None
