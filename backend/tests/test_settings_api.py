"""Settings endpoints."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.db.session import session_scope
from app.db.settings_store import SettingsStore
from app.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client


def test_defaults_are_returned_before_anything_is_saved(client: TestClient):
    body = client.get("/api/settings").json()

    assert body["browser_enabled"] is True
    assert body["per_domain_delay"] > 0
    assert body["cookies"] == {}
    assert body["api_keys"] == {"gemini": None, "openai": None, "anthropic": None}


def test_saving_and_reading_back(client: TestClient):
    client.put(
        "/api/settings",
        json={"proxy": "http://127.0.0.1:1080", "per_domain_delay": 1.2},
    )

    body = client.get("/api/settings").json()

    assert body["proxy"] == "http://127.0.0.1:1080"
    assert body["per_domain_delay"] == 1.2


def test_put_returns_the_updated_settings(client: TestClient):
    body = client.put("/api/settings", json={"browser_enabled": False}).json()

    assert body["browser_enabled"] is False


def test_partial_update_leaves_other_fields_alone(client: TestClient):
    client.put("/api/settings", json={"per_domain_delay": 2.0, "per_domain_concurrency": 6})

    client.put("/api/settings", json={"per_domain_delay": 3.0})

    body = client.get("/api/settings").json()
    assert body["per_domain_delay"] == 3.0
    assert body["per_domain_concurrency"] == 6


@pytest.mark.parametrize(
    "payload",
    [
        {"per_domain_delay": -1},
        {"per_domain_delay": 999},
        {"per_domain_concurrency": 0},
        {"per_domain_concurrency": 100},
        {"request_timeout": 1},
        {"chapter_retry_limit": -1},
    ],
)
def test_out_of_range_values_are_rejected(client: TestClient, payload: dict):
    """Guards against setting a delay of 0 and getting the site to ban you."""
    assert client.put("/api/settings", json=payload).status_code == 422


def test_cookies_are_saved_per_domain(client: TestClient):
    body = client.put(
        "/api/settings",
        json={"cookies": {"metruyencv.com": "sid=abc123; remember=1"}},
    ).json()

    assert body["cookies"] == {"metruyencv.com": "sid=abc123; remember=1"}


def test_cookie_for_a_domain_can_be_deleted(client: TestClient):
    client.put("/api/settings", json={"cookies": {"a.test": "sid=1", "b.test": "sid=2"}})

    body = client.delete("/api/settings/cookies/a.test").json()

    assert "a.test" not in body["cookies"]
    assert "b.test" in body["cookies"]


def test_deleting_an_unknown_cookie_404s(client: TestClient):
    assert client.delete("/api/settings/cookies/nope.test").status_code == 404


def test_api_keys_are_stored_but_never_returned(client: TestClient):
    """The page must be able to show "a key is set" without leaking it."""
    client.put("/api/settings", json={"api_keys": {"gemini": "AIzaSuperSecret9876"}})

    body = client.get("/api/settings").json()

    assert body["api_keys"]["gemini"] == "••••9876"
    assert "SuperSecret" not in client.get("/api/settings").text

    # The real value is still usable server-side.
    with session_scope() as session:
        assert SettingsStore(session).api_key("gemini") == "AIzaSuperSecret9876"


def test_api_key_can_be_cleared_through_the_api(client: TestClient):
    client.put("/api/settings", json={"api_keys": {"openai": "sk-test"}})

    client.put("/api/settings", json={"api_keys": {"openai": None}})

    assert client.get("/api/settings").json()["api_keys"]["openai"] is None


async def test_browser_check_reports_whether_chromium_runs():
    """Playwright needs a separate browser download; this is the "is it there" button.

    Called directly rather than through TestClient: driving Playwright's async
    API from inside the test client's portal thread deadlocks.
    """
    from app.api.routes.settings import check_browser

    result = await check_browser()

    assert isinstance(result.available, bool)
    assert result.detail
    if not result.available:
        # A failure must say what to do about it.
        assert "playwright" in result.detail.lower() or "chromium" in result.detail.lower()
