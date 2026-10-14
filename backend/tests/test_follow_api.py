"""Follow endpoints: status, manual check, clearing the new-chapter badge."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db.models import utcnow
from app.db.repository import NovelRepository
from app.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


# --- status ----------------------------------------------------------------


def test_status_reports_the_defaults(client: TestClient):
    body = client.get("/api/follow/status").json()

    assert body["enabled"] is True
    assert body["interval_hours"] == 6
    assert body["running"] is True
    assert body["next_run_at"] is not None
    assert body["followed_count"] == 0
    assert body["new_chapters"] == 0


def test_status_counts_followed_novels_and_unseen_chapters(
    client: TestClient, session: Session, novel_factory
):
    repo = NovelRepository(session)
    repo.update(novel_factory(title="A"), followed=True, new_chapters=4)
    repo.update(novel_factory(title="B"), followed=True, new_chapters=1)
    repo.update(novel_factory(title="C"), followed=False, new_chapters=0)

    body = client.get("/api/follow/status").json()

    assert body["followed_count"] == 2
    assert body["new_chapters"] == 5


def test_turning_following_off_stops_the_timer(client: TestClient):
    client.put("/api/settings", json={"follow_enabled": False})

    body = client.get("/api/follow/status").json()

    assert body["enabled"] is False
    assert body["running"] is False
    assert body["next_run_at"] is None


def test_changing_the_interval_reschedules(client: TestClient):
    before = client.get("/api/follow/status").json()["next_run_at"]

    client.put("/api/settings", json={"follow_interval_hours": 48})
    after = client.get("/api/follow/status").json()

    assert after["interval_hours"] == 48
    assert after["running"] is True
    assert after["next_run_at"] > before


def test_the_interval_is_capped(client: TestClient):
    assert client.put("/api/settings", json={"follow_interval_hours": 0}).status_code == 422
    assert client.put("/api/settings", json={"follow_interval_hours": 500}).status_code == 422


# --- check now -------------------------------------------------------------


def test_check_now_queues_due_followed_novels(
    client: TestClient, session: Session, novel_factory
):
    novel = NovelRepository(session).update(
        novel_factory(), followed=True, last_checked_at=None
    )

    body = client.post("/api/follow/check-now").json()

    assert body["considered"] == 1
    assert len(body["job_ids"]) == 1

    job = client.get(f"/api/jobs/{body['job_ids'][0]}").json()
    assert job["novel_id"] == novel.id
    assert job["type"] == "update"


def test_check_now_reports_nothing_when_no_novel_is_due(
    client: TestClient, session: Session, novel_factory
):
    NovelRepository(session).update(
        novel_factory(), followed=True, last_checked_at=utcnow()
    )

    body = client.post("/api/follow/check-now").json()

    assert body["job_ids"] == []
    assert body["considered"] == 1


def test_check_now_works_while_following_is_disabled(
    client: TestClient, session: Session, novel_factory
):
    client.put("/api/settings", json={"follow_enabled": False})
    NovelRepository(session).update(novel_factory(), followed=True, last_checked_at=None)

    body = client.post("/api/follow/check-now").json()

    # The button is also how someone who dislikes background jobs updates.
    assert len(body["job_ids"]) == 1


# --- marking as seen -------------------------------------------------------


def test_marking_a_novel_seen_clears_the_badge(
    client: TestClient, session: Session, novel_factory
):
    novel = NovelRepository(session).update(novel_factory(), new_chapters=7)

    assert client.post(f"/api/follow/{novel.id}/seen").status_code == 204

    assert client.get(f"/api/novels/{novel.id}").json()["new_chapters"] == 0


def test_marking_an_unknown_novel_seen_is_a_404(client: TestClient):
    assert client.post("/api/follow/999/seen").status_code == 404


def test_the_badge_shows_up_in_the_library_listing(
    client: TestClient, session: Session, novel_factory
):
    NovelRepository(session).update(novel_factory(), new_chapters=3)

    items = client.get("/api/novels").json()["items"]

    assert items[0]["new_chapters"] == 3
