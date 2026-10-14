"""The preview endpoint: what a pasted URL turns out to be."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.db.repository import NovelRepository
from app.db.session import session_scope
from app.main import create_app

FIXTURES = Path(__file__).parent / "fixtures" / "truyenhoan"
NOVEL_URL = "https://truyenhoan.com/kiem-khach-vo-danh.31415/"
CHAPTER_URL = "https://truyenhoan.com/kiem-khach-vo-danh/chuong-1.html"


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@respx.mock
def test_preview_returns_novel_details(client: TestClient):
    respx.get(NOVEL_URL).mock(return_value=httpx.Response(200, html=fixture("novel.html")))

    body = client.post("/api/preview", json={"url": NOVEL_URL}).json()

    assert body["title"] == "Kiếm Khách Vô Danh"
    assert body["author"] == "Mộng Trung Nhân"
    assert body["genres"] == ["Tiên Hiệp", "Kiếm Hiệp"]
    assert body["source"] == "truyenhoan"
    assert body["source_name"] == "Truyện Hoàn"
    assert body["status"] == "ongoing"
    assert body["lang"] == "vi"
    assert body["novel_id"] is None, "nothing should have been saved"


@respx.mock
def test_preview_does_not_save_the_novel(client: TestClient):
    respx.get(NOVEL_URL).mock(return_value=httpx.Response(200, html=fixture("novel.html")))

    client.post("/api/preview", json={"url": NOVEL_URL})

    with session_scope() as session:
        assert NovelRepository(session).list() == []


@respx.mock
def test_preview_flags_a_novel_already_in_the_library(client: TestClient, novel_factory):
    existing = novel_factory(source="truyenhoan", source_url=NOVEL_URL)
    respx.get(NOVEL_URL).mock(return_value=httpx.Response(200, html=fixture("novel.html")))

    body = client.post("/api/preview", json={"url": NOVEL_URL}).json()

    assert body["novel_id"] == existing.id


@respx.mock
def test_preview_follows_a_pasted_chapter_url_back_to_the_novel(client: TestClient):
    """People paste the chapter they are reading, not the index page."""
    respx.get(CHAPTER_URL).mock(
        return_value=httpx.Response(200, html=fixture("chapter.html"))
    )
    respx.get(NOVEL_URL).mock(return_value=httpx.Response(200, html=fixture("novel.html")))

    body = client.post("/api/preview", json={"url": CHAPTER_URL}).json()

    assert body["url"] == NOVEL_URL
    assert body["title"] == "Kiếm Khách Vô Danh"


def test_preview_rejects_an_unsupported_site(client: TestClient):
    resp = client.post("/api/preview", json={"url": "https://example.com/truyen/abc"})

    assert resp.status_code == 422
    assert "No adapter" in resp.json()["detail"]


@respx.mock
def test_preview_reports_a_blocked_site_with_a_hint(client: TestClient):
    respx.get(NOVEL_URL).mock(return_value=httpx.Response(403))

    resp = client.post("/api/preview", json={"url": NOVEL_URL})

    assert resp.status_code == 502
    detail = resp.json()["detail"]
    assert "refused" in detail.lower()
    assert "browser" in detail.lower(), "the user needs to know what would fix it"


@respx.mock
def test_preview_reports_a_layout_change(client: TestClient):
    """The site answers 200 with its homepage when the novel id is unknown."""
    respx.get(NOVEL_URL).mock(
        return_value=httpx.Response(200, html=fixture("homepage.html"))
    )

    resp = client.post("/api/preview", json={"url": NOVEL_URL})

    assert resp.status_code == 502
    assert "layout" in resp.json()["detail"].lower()
