"""Library API endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.db.models import ChapterStatus
from app.db.repository import ChapterRepository, NovelRepository
from app.db.storage import ChapterStorage


def test_list_empty_library(client: TestClient):
    body = client.get("/api/novels").json()

    assert body == {"items": [], "total": 0, "limit": 50, "offset": 0}


def test_list_returns_seeded_novel(client: TestClient, novel_factory):
    novel_factory(title="Phàm Nhân Tu Tiên")

    body = client.get("/api/novels").json()

    assert body["total"] == 1
    assert body["items"][0]["title"] == "Phàm Nhân Tu Tiên"
    assert body["items"][0]["source"] == "demo"


def test_list_pagination_reports_full_total(client: TestClient, novel_factory):
    for i in range(3):
        novel_factory(title=f"T{i}", source_url=f"https://a.test/{i}")

    body = client.get("/api/novels?limit=2").json()

    assert len(body["items"]) == 2
    assert body["total"] == 3
    assert body["limit"] == 2


def test_list_rejects_out_of_range_limit(client: TestClient):
    assert client.get("/api/novels?limit=0").status_code == 422
    assert client.get("/api/novels?limit=999").status_code == 422


def test_list_filters_followed(client: TestClient, session: Session, novel_factory):
    novel_factory(title="Thường", source_url="https://a.test/1")
    followed = novel_factory(title="Theo dõi", source_url="https://a.test/2")
    NovelRepository(session).update(followed, followed=True)

    body = client.get("/api/novels?followed=true").json()

    assert [n["title"] for n in body["items"]] == ["Theo dõi"]


def test_detail_includes_chapter_tallies_and_disk_usage(
    client: TestClient, session: Session, novel_factory
):
    novel = novel_factory(chapters=3)
    chapters = ChapterRepository(session)
    chapters.update(chapters.get_by_number(novel.id, 2), status=ChapterStatus.failed)
    chapters.update(chapters.get_by_number(novel.id, 3), status=ChapterStatus.skipped_vip)

    body = client.get(f"/api/novels/{novel.id}").json()

    assert body["chapter_count"] == 3
    assert body["chapters_done"] == 1
    assert body["chapters_failed"] == 1
    assert body["chapters_skipped"] == 1
    assert body["chapters_pending"] == 0
    assert body["disk_bytes"] > 0
    assert body["genres"] == ["Tiên hiệp"]


def test_detail_404_for_unknown_novel(client: TestClient):
    resp = client.get("/api/novels/4242")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Novel not found"


def test_patch_updates_allowed_fields(client: TestClient, novel_factory):
    novel = novel_factory()

    body = client.patch(
        f"/api/novels/{novel.id}", json={"followed": True, "translate_enabled": True}
    ).json()

    assert body["followed"] is True
    assert body["translate_enabled"] is True


def test_patch_ignores_unknown_fields(client: TestClient, novel_factory):
    """Extra keys must not let a caller write arbitrary columns."""
    novel = novel_factory()

    resp = client.patch(f"/api/novels/{novel.id}", json={"source": "hacked", "id": 99})

    assert resp.status_code == 200
    assert resp.json()["source"] == "demo"
    assert resp.json()["id"] == novel.id


def test_patch_empty_body_is_a_noop(client: TestClient, novel_factory):
    novel = novel_factory(title="Giữ nguyên")

    body = client.patch(f"/api/novels/{novel.id}", json={}).json()

    assert body["title"] == "Giữ nguyên"


def test_patch_404_for_unknown_novel(client: TestClient):
    assert client.patch("/api/novels/4242", json={"followed": True}).status_code == 404


def test_delete_removes_rows_and_files(
    client: TestClient, session: Session, novel_factory
):
    novel = novel_factory(chapters=2)
    storage = ChapterStorage()
    assert storage.novel_dir(novel.id).exists()

    resp = client.delete(f"/api/novels/{novel.id}")

    assert resp.status_code == 204
    assert client.get(f"/api/novels/{novel.id}").status_code == 404
    assert not storage.novel_dir(novel.id).exists()
    assert ChapterRepository(session).list_for_novel(novel.id) == []


def test_delete_404_for_unknown_novel(client: TestClient):
    assert client.delete("/api/novels/4242").status_code == 404


def test_chapter_list_is_ordered_and_bodyless(client: TestClient, novel_factory):
    novel = novel_factory(chapters=3)

    body = client.get(f"/api/novels/{novel.id}/chapters").json()

    assert [c["number"] for c in body["items"]] == [1, 2, 3]
    assert body["total"] == 3
    # The list view must stay light; text comes from the reader endpoint.
    assert "text" not in body["items"][0]
    assert body["items"][0]["char_count"] > 0


def test_chapter_list_filters_by_status(
    client: TestClient, session: Session, novel_factory
):
    novel = novel_factory(chapters=3)
    chapters = ChapterRepository(session)
    chapters.update(chapters.get_by_number(novel.id, 2), status=ChapterStatus.failed)

    body = client.get(f"/api/novels/{novel.id}/chapters?status=failed").json()

    assert [c["number"] for c in body["items"]] == [2]
    assert body["total"] == 1


def test_chapter_list_pagination(client: TestClient, novel_factory):
    novel = novel_factory(chapters=5)

    body = client.get(f"/api/novels/{novel.id}/chapters?limit=2&offset=2").json()

    assert [c["number"] for c in body["items"]] == [3, 4]
    assert body["total"] == 5


def test_chapter_list_404_for_unknown_novel(client: TestClient):
    assert client.get("/api/novels/4242/chapters").status_code == 404


# --- export ----------------------------------------------------------------


def _seed_text(novel_id: int, chapters: int) -> None:
    storage = ChapterStorage()
    for number in range(1, chapters + 1):
        storage.write(novel_id, number, f"Chương {number}\n\nNội dung đủ dài để xuất bản.")


def test_export_epub_downloads_a_file(client: TestClient, novel_factory):
    novel = novel_factory(title="Kiếm Khách Vô Danh", chapters=2)
    _seed_text(novel.id, 2)

    resp = client.get(f"/api/novels/{novel.id}/export?format=epub")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/epub+zip"
    assert "kiem-khach-vo-danh.epub" in resp.headers["content-disposition"]
    assert resp.headers["x-export-chapters"] == "2"
    # EPUBs are zip archives, so the magic bytes are a cheap sanity check.
    assert resp.content[:2] == b"PK"


def test_export_defaults_to_epub(client: TestClient, novel_factory):
    novel = novel_factory(chapters=1)
    _seed_text(novel.id, 1)

    resp = client.get(f"/api/novels/{novel.id}/export")

    assert resp.headers["content-type"] == "application/epub+zip"


def test_export_txt(client: TestClient, novel_factory):
    novel = novel_factory(title="Tiên Môn", chapters=2)
    _seed_text(novel.id, 2)

    resp = client.get(f"/api/novels/{novel.id}/export?format=txt")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert "Tiên Môn" in resp.text


def test_export_json(client: TestClient, novel_factory):
    novel = novel_factory(chapters=2)
    _seed_text(novel.id, 2)

    resp = client.get(f"/api/novels/{novel.id}/export?format=json")

    assert resp.status_code == 200
    assert resp.json()["export"]["chapter_count"] == 2


def test_export_rejects_an_unknown_format(client: TestClient, novel_factory):
    novel = novel_factory(chapters=1)

    assert client.get(f"/api/novels/{novel.id}/export?format=pdf").status_code == 422


def test_export_validates_volume_size(client: TestClient, novel_factory):
    novel = novel_factory(chapters=1)

    assert client.get(
        f"/api/novels/{novel.id}/export?volume_size=1"
    ).status_code == 422


def test_export_conflicts_when_nothing_is_downloaded(client: TestClient, novel_factory):
    """Rows exist but no text on disk yet: a 409, not an empty book."""
    novel = novel_factory(chapters=2, chapter_status=ChapterStatus.pending)

    resp = client.get(f"/api/novels/{novel.id}/export?format=txt")

    assert resp.status_code == 409
    assert "crawl" in resp.json()["detail"].lower()


def test_export_404s_for_unknown_novel(client: TestClient):
    assert client.get("/api/novels/4242/export").status_code == 404
