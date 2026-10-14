"""Runtime settings store."""

from __future__ import annotations

from sqlmodel import Session

from app.core.settings import get_settings
from app.db.settings_store import SettingsStore

COOKIE_HEADER = "sid=abc123; remember_web=xyz; path_noise="


def store_for(session: Session) -> SettingsStore:
    return SettingsStore(session)


# --- defaults --------------------------------------------------------------


def test_unset_values_fall_back_to_process_settings(session: Session):
    base = get_settings()
    store = store_for(session)

    assert store.per_domain_delay == base.per_domain_delay
    assert store.per_domain_concurrency == base.per_domain_concurrency
    assert store.request_timeout == base.request_timeout
    assert store.proxy == base.proxy
    assert store.browser_enabled is True


def test_saved_values_win_over_process_settings(session: Session):
    store = store_for(session)

    store.update({"per_domain_delay": 2.5, "proxy": "http://127.0.0.1:1080"})

    assert store.per_domain_delay == 2.5
    assert store.proxy == "http://127.0.0.1:1080"


def test_update_only_touches_the_fields_sent(session: Session):
    store = store_for(session)
    store.update({"per_domain_delay": 2.0, "per_domain_concurrency": 8})

    store.update({"per_domain_delay": 3.0})

    assert store.per_domain_delay == 3.0
    assert store.per_domain_concurrency == 8


def test_empty_proxy_reads_back_as_none(session: Session):
    """An empty text box means "no proxy", not a proxy called ""."""
    store = store_for(session)

    store.update({"proxy": ""})

    assert store.proxy is None


def test_effective_settings_carries_overrides_to_the_fetchers(session: Session):
    store = store_for(session)
    store.update(
        {
            "proxy": "http://proxy.test:8080",
            "per_domain_delay": 1.5,
            "per_domain_concurrency": 2,
            "request_timeout": 45.0,
            "chapter_retry_limit": 5,
        }
    )

    effective = store.effective_settings()

    assert effective.proxy == "http://proxy.test:8080"
    assert effective.per_domain_delay == 1.5
    assert effective.per_domain_concurrency == 2
    assert effective.request_timeout == 45.0
    assert effective.chapter_retry_limit == 5
    # Untouched fields keep their process values.
    assert effective.user_agent == get_settings().user_agent


# --- cookies ---------------------------------------------------------------


def test_cookies_are_stored_per_domain(session: Session):
    store = store_for(session)

    store.set_cookies({"metruyencv.com": COOKIE_HEADER})

    assert store.cookies == {"metruyencv.com": COOKIE_HEADER}


def test_cookie_domains_are_normalised(session: Session):
    store = store_for(session)

    store.set_cookies({"  WWW.MeTruyenCV.com  ": COOKIE_HEADER})

    assert "metruyencv.com" in store.cookies


def test_blank_cookie_entries_are_dropped(session: Session):
    store = store_for(session)

    store.set_cookies({"a.test": "sid=1", "b.test": "   ", "": "sid=2"})

    assert store.cookies == {"a.test": "sid=1"}


def test_cookie_header_is_parsed_into_pairs(session: Session):
    store = store_for(session)
    store.set_cookies({"a.test": COOKIE_HEADER})

    assert store.cookies_for("a.test") == {"sid": "abc123", "remember_web": "xyz"}


def test_cookies_apply_to_subdomains(session: Session):
    store = store_for(session)
    store.set_cookies({"a.test": "sid=1"})

    assert store.cookies_for("m.a.test") == {"sid": "1"}
    assert store.cookies_for("www.a.test") == {"sid": "1"}
    assert store.cookies_for("other.test") == {}


def test_playwright_cookie_shape(session: Session):
    """Playwright wants structured cookies, not a header string."""
    store = store_for(session)
    store.set_cookies({"a.test": "sid=abc; other=1"})

    cookies = store.playwright_cookies()

    assert {c["name"] for c in cookies} == {"sid", "other"}
    assert all(c["domain"] == ".a.test" for c in cookies), "leading dot covers subdomains"
    assert all(c["path"] == "/" for c in cookies)


def test_no_cookies_is_an_empty_list(session: Session):
    assert store_for(session).playwright_cookies() == []


# --- secrets ---------------------------------------------------------------


def test_api_key_round_trip(session: Session):
    store = store_for(session)

    store.set_api_key("gemini", "AIzaSecretValue1234")

    assert store.api_key("gemini") == "AIzaSecretValue1234"
    assert store.api_key("openai") is None


def test_api_keys_are_masked_for_display(session: Session):
    store = store_for(session)
    store.set_api_key("gemini", "AIzaSecretValue1234")

    hints = store.api_key_hints()

    assert hints["gemini"] == "••••1234"
    assert "AIzaSecret" not in str(hints)
    assert hints["openai"] is None


def test_api_key_can_be_cleared(session: Session):
    store = store_for(session)
    store.set_api_key("openai", "sk-test")

    store.set_api_key("openai", None)

    assert store.api_key("openai") is None


def test_setting_one_key_keeps_the_others(session: Session):
    store = store_for(session)
    store.set_api_key("gemini", "g-key")

    store.set_api_key("openai", "o-key")

    assert store.api_key("gemini") == "g-key"


def test_as_dict_never_contains_a_raw_key(session: Session):
    store = store_for(session)
    store.set_api_key("anthropic", "sk-ant-verysecret")

    payload = store.as_dict()

    assert "verysecret" not in str(payload)
    assert payload["api_keys"]["anthropic"].startswith("••••")


def test_update_accepts_keys_from_the_settings_page(session: Session):
    store = store_for(session)

    store.update({"api_keys": {"gemini": "new-key", "bogus": "ignored"}})

    assert store.api_key("gemini") == "new-key"
    assert store.api_key("bogus") is None, "unknown providers must be ignored"
