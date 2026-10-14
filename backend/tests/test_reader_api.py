"""Reader endpoints: chapter text and reading position."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db.models import Chapter, ChapterStatus
from app.db.repository import ChapterRepository
from app.db.storage import ChapterStorage

BODY = "Đoạn một.\n\nĐoạn hai."


def seed_text(novel_id: int, numbers: list[int]) -> None:
    storage = ChapterStorage()
    for number in numbers:
        storage.write(novel_id, number, f"Chương {number}\n\n{BODY}")


# --- reading a chapter -----------------------------------------------------


def test_chapter_text_is_returned(client: TestClient, novel_factory):
    novel = novel_factory(title="Kiếm Khách Vô Danh", chapters=3)
    seed_text(novel.id, [1, 2, 3])

    body = client.get(f"/api/novels/{novel.id}/chapters/2").json()

    assert body["number"] == 2
    assert "Đoạn một." in body["text"]
    assert body["novel_title"] == "Kiếm Khách Vô Danh"
    assert body["translated"] is False


def test_neighbours_come_from_the_real_chapter_list(
    client: TestClient, session: Session, novel_factory
):
    """Numbering has gaps on most sites, so prev/next cannot be number±1."""
    novel = novel_factory(chapters=0)
    ChapterRepository(session).add_many(
        [
            Chapter(novel_id=novel.id, number=number, title=f"C{number}", source_url="u",
                    status=ChapterStatus.done)
            for number in (1, 5, 9)
        ]
    )
    seed_text(novel.id, [1, 5, 9])

    body = client.get(f"/api/novels/{novel.id}/chapters/5").json()

    assert body["prev_number"] == 1
    assert body["next_number"] == 9


def test_the_first_and_last_chapters_have_no_neighbour(client: TestClient, novel_factory):
    novel = novel_factory(chapters=2)
    seed_text(novel.id, [1, 2])

    first = client.get(f"/api/novels/{novel.id}/chapters/1").json()
    last = client.get(f"/api/novels/{novel.id}/chapters/2").json()

    assert first["prev_number"] is None
    assert last["next_number"] is None


def test_translation_is_served_when_asked_for(client: TestClient, session: Session, novel_factory):
    novel = novel_factory(chapters=1)
    storage = ChapterStorage()
    storage.write(novel.id, 1, "原文")
    storage.write(novel.id, 1, "Bản dịch", translated=True)
    repo = ChapterRepository(session)
    repo.update(repo.get_by_number(novel.id, 1), has_translation=True)

    body = client.get(f"/api/novels/{novel.id}/chapters/1?translated=true").json()

    assert body["text"] == "Bản dịch"
    assert body["translated"] is True
    assert body["has_translation"] is True


def test_asking_for_a_missing_translation_falls_back_to_the_original(
    client: TestClient, novel_factory
):
    """Better to show the original than an empty reader."""
    novel = novel_factory(chapters=1)
    seed_text(novel.id, [1])

    body = client.get(f"/api/novels/{novel.id}/chapters/1?translated=true").json()

    assert "Đoạn một." in body["text"]
    assert body["translated"] is False


def test_a_chapter_that_was_never_downloaded_conflicts(
    client: TestClient, novel_factory
):
    novel = novel_factory(chapters=2, chapter_status=ChapterStatus.pending)

    resp = client.get(f"/api/novels/{novel.id}/chapters/1")

    assert resp.status_code == 409
    assert "not been downloaded" in resp.json()["detail"]


def test_unknown_chapter_and_novel_404(client: TestClient, novel_factory):
    novel = novel_factory(chapters=1)

    assert client.get(f"/api/novels/{novel.id}/chapters/99").status_code == 404
    assert client.get("/api/novels/4242/chapters/1").status_code == 404


# --- reading position ------------------------------------------------------


def test_progress_starts_empty(client: TestClient, novel_factory):
    novel = novel_factory(chapters=2)

    assert client.get(f"/api/novels/{novel.id}").json()["last_read_chapter"] is None


def test_progress_is_saved_and_read_back(client: TestClient, novel_factory):
    """Stored server-side so the position follows the user between devices."""
    novel = novel_factory(chapters=5)

    body = client.put(f"/api/novels/{novel.id}/progress", json={"chapter": 3}).json()

    assert body["last_read_chapter"] == 3
    assert client.get(f"/api/novels/{novel.id}").json()["last_read_chapter"] == 3


def test_progress_appears_in_the_library_list(client: TestClient, novel_factory):
    novel = novel_factory(chapters=5)
    client.put(f"/api/novels/{novel.id}/progress", json={"chapter": 4})

    items = client.get("/api/novels").json()["items"]

    assert items[0]["last_read_chapter"] == 4


def test_progress_can_move_backwards(client: TestClient, novel_factory):
    """Re-reading an earlier chapter should update the marker, not be ignored."""
    novel = novel_factory(chapters=5)
    client.put(f"/api/novels/{novel.id}/progress", json={"chapter": 4})

    body = client.put(f"/api/novels/{novel.id}/progress", json={"chapter": 2}).json()

    assert body["last_read_chapter"] == 2


def test_progress_rejects_a_chapter_the_novel_does_not_have(
    client: TestClient, novel_factory
):
    novel = novel_factory(chapters=2)

    assert client.put(
        f"/api/novels/{novel.id}/progress", json={"chapter": 99}
    ).status_code == 404


def test_progress_404s_for_unknown_novel(client: TestClient):
    assert client.put("/api/novels/4242/progress", json={"chapter": 1}).status_code == 404
