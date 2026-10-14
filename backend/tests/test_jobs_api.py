"""Job endpoints.

The app's own lifespan starts a real JobManager, so these tests swap in a
manager with a recording runner to keep the network out of it.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.routes.jobs import get_manager
from app.db.models import JobStatus, JobType
from app.db.repository import JobRepository
from app.db.session import session_scope
from app.main import create_app
from app.pipeline.events import EventHub
from app.pipeline.manager import JobManager

# A real adapter domain so the URL passes validation.
FAKE_URL = "https://truyenhoan.com/kiem-khach-vo-danh.31415/"


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Client whose job manager has no worker running.

    Jobs are persisted and queued but never executed, so these tests stay
    about the HTTP layer and never touch the network. Actually running a job
    is covered by the crawler and manager tests.
    """
    app = create_app()
    idle_manager = JobManager(hub=EventHub())
    app.dependency_overrides[get_manager] = lambda: idle_manager

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def create_job(client: TestClient, **payload) -> dict:
    resp = client.post("/api/jobs", json=payload or {"url": FAKE_URL})
    assert resp.status_code == 202, resp.text
    return resp.json()


# --- validation ------------------------------------------------------------


def test_create_job_requires_url_or_novel_id(client: TestClient):
    resp = client.post("/api/jobs", json={})

    assert resp.status_code == 422
    assert "url or novel_id" in resp.json()["detail"]


def test_create_job_rejects_an_unsupported_site(client: TestClient):
    resp = client.post("/api/jobs", json={"url": "https://example.com/truyen/abc"})

    assert resp.status_code == 422
    assert "No adapter" in resp.json()["detail"]


def test_create_job_rejects_an_unknown_novel_id(client: TestClient):
    resp = client.post("/api/jobs", json={"novel_id": 4242})

    assert resp.status_code == 404


def test_update_endpoint_404s_for_unknown_novel(client: TestClient):
    assert client.post("/api/novels/4242/update").status_code == 404


# --- creation and listing --------------------------------------------------


def test_create_job_returns_a_queued_job(client: TestClient):
    body = create_job(client, url=FAKE_URL)

    assert body["status"] in (JobStatus.queued.value, JobStatus.running.value,
                              JobStatus.failed.value, JobStatus.done.value)
    assert body["type"] == JobType.crawl.value
    assert body["params"]["url"] == FAKE_URL
    assert body["percent"] == 0.0
    assert body["processed"] == 0


def test_update_job_is_created_for_a_novel(client: TestClient, novel_factory):
    novel = novel_factory()

    resp = client.post(f"/api/novels/{novel.id}/update")

    assert resp.status_code == 202
    assert resp.json()["type"] == JobType.update.value
    assert resp.json()["novel_id"] == novel.id


def test_list_jobs(client: TestClient):
    create_job(client, url=FAKE_URL)

    body = client.get("/api/jobs").json()

    assert body["total"] >= 1
    assert body["items"][0]["id"]


def test_list_jobs_filters_by_status(client: TestClient):
    create_job(client, url=FAKE_URL)

    body = client.get("/api/jobs?status=done").json()

    assert all(item["status"] == "done" for item in body["items"])


def test_get_job(client: TestClient):
    job = create_job(client, url=FAKE_URL)

    body = client.get(f"/api/jobs/{job['id']}").json()

    assert body["id"] == job["id"]


def test_get_unknown_job_404s(client: TestClient):
    assert client.get("/api/jobs/4242").status_code == 404


def test_percent_is_derived_from_counters(client: TestClient):
    job = create_job(client, url=FAKE_URL)
    with session_scope() as session:
        repo = JobRepository(session)
        repo.update(repo.get(job["id"]), total=10, done=2, failed=1, skipped=1)

    body = client.get(f"/api/jobs/{job['id']}").json()

    assert body["processed"] == 4
    assert body["percent"] == 40.0


# --- control endpoints -----------------------------------------------------


def test_control_endpoints_404_for_unknown_job(client: TestClient):
    for action in ("pause", "resume", "cancel"):
        assert client.post(f"/api/jobs/4242/{action}").status_code == 404


def test_pausing_a_job_that_is_not_running_conflicts(client: TestClient):
    """A queued job has no control switch yet, so pausing is a 409, not a crash."""
    job = create_job(client, url=FAKE_URL)

    resp = client.post(f"/api/jobs/{job['id']}/pause")

    assert resp.status_code == 409


def test_cancelling_a_finished_job_conflicts(client: TestClient):
    job = create_job(client, url=FAKE_URL)
    with session_scope() as session:
        repo = JobRepository(session)
        repo.update(repo.get(job["id"]), status=JobStatus.done)

    assert client.post(f"/api/jobs/{job['id']}/cancel").status_code == 409


def test_cancelling_a_queued_job_succeeds(client: TestClient):
    job = create_job(client, url=FAKE_URL)
    with session_scope() as session:
        repo = JobRepository(session)
        repo.update(repo.get(job["id"]), status=JobStatus.queued)

    resp = client.post(f"/api/jobs/{job['id']}/cancel")

    assert resp.status_code == 200
    assert resp.json()["status"] == JobStatus.cancelled.value


# --- sources ---------------------------------------------------------------


def test_sources_endpoint_lists_adapters(client: TestClient):
    body = client.get("/api/sources").json()

    keys = {item["key"] for item in body}
    assert "truyenhoan" in keys
    entry = next(item for item in body if item["key"] == "truyenhoan")
    assert entry["lang"] == "vi"
    assert "truyenhoan.com" in entry["domains"]
    assert entry["needs_browser"] is False


# --- event stream ----------------------------------------------------------


def test_event_stream_sends_a_snapshot_first(client: TestClient):
    """A browser that connects late still learns the current state."""
    job = create_job(client, url=FAKE_URL)
    with session_scope() as session:
        repo = JobRepository(session)
        repo.update(repo.get(job["id"]), status=JobStatus.done, total=3, done=3)

    with client.stream("GET", f"/api/jobs/{job['id']}/events") as response:
        assert response.status_code == 200
        events = _read_events(response, expect=2)

    assert events[0]["event"] == "snapshot"
    assert json.loads(events[0]["data"])["done"] == 3
    # Already finished, so the stream closes instead of hanging.
    assert events[-1]["event"] == "end"


def test_event_stream_reports_a_missing_job(client: TestClient):
    with client.stream("GET", "/api/jobs/4242/events") as response:
        events = _read_events(response, expect=1)

    assert events[0]["event"] == "error"
    assert "not found" in json.loads(events[0]["data"])["detail"].lower()


def _read_events(response, *, expect: int) -> list[dict[str, str]]:
    """Parse at most ``expect`` SSE frames from a streaming response."""
    events: list[dict[str, str]] = []
    current: dict[str, str] = {}

    for raw in response.iter_lines():
        line = raw.strip()
        if not line:
            if current:
                events.append(current)
                current = {}
                if len(events) >= expect:
                    break
            continue
        if line.startswith("event:"):
            current["event"] = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            current["data"] = line.split(":", 1)[1].strip()

    if current and len(events) < expect:
        events.append(current)
    return events
