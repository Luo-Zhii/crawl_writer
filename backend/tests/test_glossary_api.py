"""Glossary and translate endpoints."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.routes.glossary import get_manager
from app.db.models import JobType, Lang
from app.main import create_app
from app.pipeline.events import EventHub
from app.pipeline.manager import JobManager


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Client whose worker never runs, so jobs stay queued and nothing
    reaches a translation API."""
    app = create_app()
    idle = JobManager(hub=EventHub())
    app.dependency_overrides[get_manager] = lambda: idle

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


# --- glossary CRUD ---------------------------------------------------------


def test_a_new_novel_has_no_terms(client: TestClient, novel_factory):
    novel = novel_factory(lang=Lang.zh)

    assert client.get(f"/api/novels/{novel.id}/glossary").json() == []


def test_adding_a_term(client: TestClient, novel_factory):
    novel = novel_factory(lang=Lang.zh)

    resp = client.post(
        f"/api/novels/{novel.id}/glossary",
        json={"source": "萧炎", "target": "Tiêu Viêm", "note": "nhân vật chính"},
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["source"] == "萧炎"
    assert body["target"] == "Tiêu Viêm"
    assert body["note"] == "nhân vật chính"


def test_adding_the_same_source_updates_it(client: TestClient, novel_factory):
    """Fixing a reading should not leave two conflicting entries."""
    novel = novel_factory(lang=Lang.zh)
    client.post(
        f"/api/novels/{novel.id}/glossary", json={"source": "萧炎", "target": "Tiêu Diễm"}
    )

    client.post(
        f"/api/novels/{novel.id}/glossary", json={"source": "萧炎", "target": "Tiêu Viêm"}
    )

    terms = client.get(f"/api/novels/{novel.id}/glossary").json()
    assert len(terms) == 1
    assert terms[0]["target"] == "Tiêu Viêm"


def test_terms_are_trimmed(client: TestClient, novel_factory):
    novel = novel_factory(lang=Lang.zh)

    body = client.post(
        f"/api/novels/{novel.id}/glossary",
        json={"source": "  萧炎  ", "target": "  Tiêu Viêm  "},
    ).json()

    assert body["source"] == "萧炎"
    assert body["target"] == "Tiêu Viêm"


@pytest.mark.parametrize(
    "payload",
    [{"source": "", "target": "x"}, {"source": "x", "target": ""}, {"source": "x"}],
)
def test_incomplete_terms_are_rejected(client: TestClient, novel_factory, payload: dict):
    novel = novel_factory(lang=Lang.zh)

    assert client.post(f"/api/novels/{novel.id}/glossary", json=payload).status_code == 422


def test_replacing_the_whole_glossary(client: TestClient, novel_factory):
    """Pasting a list is how a long glossary actually gets entered."""
    novel = novel_factory(lang=Lang.zh)
    client.post(f"/api/novels/{novel.id}/glossary", json={"source": "cũ", "target": "old"})

    body = client.put(
        f"/api/novels/{novel.id}/glossary",
        json={"terms": {"萧炎": "Tiêu Viêm", "药老": "Dược Lão"}},
    ).json()

    assert {term["source"] for term in body} == {"萧炎", "药老"}
    assert "cũ" not in {term["source"] for term in body}


def test_deleting_a_term(client: TestClient, novel_factory):
    novel = novel_factory(lang=Lang.zh)
    term = client.post(
        f"/api/novels/{novel.id}/glossary", json={"source": "萧炎", "target": "Tiêu Viêm"}
    ).json()

    assert client.delete(f"/api/novels/{novel.id}/glossary/{term['id']}").status_code == 204
    assert client.get(f"/api/novels/{novel.id}/glossary").json() == []


def test_deleting_an_unknown_term_404s(client: TestClient, novel_factory):
    novel = novel_factory(lang=Lang.zh)

    assert client.delete(f"/api/novels/{novel.id}/glossary/999").status_code == 404


def test_a_term_cannot_be_deleted_through_another_novel(client: TestClient, novel_factory):
    """Guards against one novel's id letting you edit another's glossary."""
    first = novel_factory(lang=Lang.zh, source_url="https://a.test/1")
    second = novel_factory(lang=Lang.zh, source_url="https://a.test/2")
    term = client.post(
        f"/api/novels/{first.id}/glossary", json={"source": "萧炎", "target": "Tiêu Viêm"}
    ).json()

    assert client.delete(f"/api/novels/{second.id}/glossary/{term['id']}").status_code == 404


def test_glossary_endpoints_404_for_unknown_novel(client: TestClient):
    assert client.get("/api/novels/4242/glossary").status_code == 404
    assert client.post(
        "/api/novels/4242/glossary", json={"source": "a", "target": "b"}
    ).status_code == 404


def test_terms_are_removed_with_the_novel(client: TestClient, novel_factory):
    novel = novel_factory(lang=Lang.zh)
    client.post(
        f"/api/novels/{novel.id}/glossary", json={"source": "萧炎", "target": "Tiêu Viêm"}
    )

    client.delete(f"/api/novels/{novel.id}")

    assert client.get(f"/api/novels/{novel.id}/glossary").status_code == 404


# --- starting a translation ------------------------------------------------


def test_translation_can_be_queued_for_a_chinese_novel(client: TestClient, novel_factory):
    novel = novel_factory(lang=Lang.zh, chapters=2)

    resp = client.post(f"/api/novels/{novel.id}/translate", json={"force": False})

    assert resp.status_code == 202
    body = resp.json()
    assert body["type"] == JobType.translate.value
    assert body["novel_id"] == novel.id
    assert body["params"]["force"] is False


def test_force_is_passed_through(client: TestClient, novel_factory):
    novel = novel_factory(lang=Lang.zh, chapters=1)

    body = client.post(f"/api/novels/{novel.id}/translate", json={"force": True}).json()

    assert body["params"]["force"] is True


def test_translating_a_vietnamese_novel_is_refused(client: TestClient, novel_factory):
    """It would overwrite readable text with a pointless round trip."""
    novel = novel_factory(lang=Lang.vi, chapters=1)

    resp = client.post(f"/api/novels/{novel.id}/translate")

    assert resp.status_code == 409
    assert "already in Vietnamese" in resp.json()["detail"]


def test_translate_404s_for_unknown_novel(client: TestClient):
    assert client.post("/api/novels/4242/translate").status_code == 404
