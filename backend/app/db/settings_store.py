"""Runtime settings the user can change without restarting.

``app.core.settings.Settings`` holds what the process started with (env vars,
``.env``). This store holds overrides saved from the Settings page and keeps
them in the database, so changing a proxy or pasting a cookie takes effect on
the next request instead of after a restart.

Secrets are stored here too. They are never read back out over the API: the
Settings page only learns *whether* a key is set, plus its last few
characters, which is enough to tell two keys apart without exposing either.
"""

from __future__ import annotations

from typing import Any

from sqlmodel import Session

from app.core.logging import get_logger
from app.core.settings import Settings, get_settings
from app.db.repository import SettingRepository

log = get_logger(__name__)

# --- keys ------------------------------------------------------------------

PROXY = "proxy"
BROWSER_ENABLED = "browser_enabled"
TRANSLATE_PROVIDER = "translate_provider"
PER_DOMAIN_DELAY = "per_domain_delay"
PER_DOMAIN_CONCURRENCY = "per_domain_concurrency"
REQUEST_TIMEOUT = "request_timeout"
CHAPTER_RETRY_LIMIT = "chapter_retry_limit"
COOKIES = "cookies"
API_KEYS = "api_keys"
FOLLOW_ENABLED = "follow_enabled"
FOLLOW_INTERVAL_HOURS = "follow_interval_hours"

#: Keys whose value must never leave the server.
SECRET_KEYS = frozenset({API_KEYS})

#: Providers the translation step can use (filled in by the translate task).
API_KEY_PROVIDERS = ("gemini", "openai", "anthropic")


class SettingsStore:
    """Typed access to the runtime settings table."""

    def __init__(self, session: Session, *, base: Settings | None = None) -> None:
        self.repo = SettingRepository(session)
        self.base = base or get_settings()

    # --- plain values ------------------------------------------------------

    @property
    def proxy(self) -> str | None:
        return self.repo.get(PROXY, self.base.proxy) or None

    @property
    def browser_enabled(self) -> bool:
        return bool(self.repo.get(BROWSER_ENABLED, True))

    @property
    def per_domain_delay(self) -> float:
        return float(self.repo.get(PER_DOMAIN_DELAY, self.base.per_domain_delay))

    @property
    def per_domain_concurrency(self) -> int:
        return int(self.repo.get(PER_DOMAIN_CONCURRENCY, self.base.per_domain_concurrency))

    @property
    def request_timeout(self) -> float:
        return float(self.repo.get(REQUEST_TIMEOUT, self.base.request_timeout))

    @property
    def chapter_retry_limit(self) -> int:
        return int(self.repo.get(CHAPTER_RETRY_LIMIT, self.base.chapter_retry_limit))

    @property
    def follow_enabled(self) -> bool:
        """Whether followed novels get checked for new chapters on a timer.

        On by default: following a novel and still having to press a button
        would make the flag pointless.
        """
        return bool(self.repo.get(FOLLOW_ENABLED, True))

    @property
    def follow_interval_hours(self) -> int:
        """How often to check. Ongoing novels post a few chapters a week, so
        anything under an hour is just extra traffic for the site."""
        return max(1, int(self.repo.get(FOLLOW_INTERVAL_HOURS, 6)))

    @property
    def translate_provider(self) -> str:
        """Which engine to try first. Google needs no key, so it is the default."""
        return str(self.repo.get(TRANSLATE_PROVIDER, "google"))

    # --- cookies -----------------------------------------------------------

    @property
    def cookies(self) -> dict[str, str]:
        """Cookie header strings, keyed by domain.

        Stored the way a user copies them out of devtools
        (``name=value; other=value``) rather than as structured cookies.
        """
        value = self.repo.get(COOKIES, {})
        return dict(value) if isinstance(value, dict) else {}

    def set_cookies(self, cookies: dict[str, str]) -> None:
        cleaned = {
            domain.strip().lower().removeprefix("www."): raw.strip()
            for domain, raw in cookies.items()
            if domain.strip() and raw.strip()
        }
        self.repo.set(COOKIES, cleaned)

    def cookies_for(self, host: str) -> dict[str, str]:
        """Parse the stored cookie string for ``host`` into a dict."""
        host = host.lower().removeprefix("www.")
        for domain, raw in self.cookies.items():
            if host == domain or host.endswith(f".{domain}"):
                return _parse_cookie_header(raw)
        return {}

    def playwright_cookies(self) -> list[dict[str, Any]]:
        """Stored cookies in the shape Playwright's ``add_cookies`` wants."""
        out: list[dict[str, Any]] = []
        for domain, raw in self.cookies.items():
            for name, value in _parse_cookie_header(raw).items():
                out.append(
                    {
                        "name": name,
                        "value": value,
                        # A leading dot covers subdomains, which is what a
                        # session cookie copied from a browser usually needs.
                        "domain": f".{domain}",
                        "path": "/",
                    }
                )
        return out

    # --- secrets -----------------------------------------------------------

    def api_key(self, provider: str) -> str | None:
        keys = self.repo.get(API_KEYS, {})
        value = keys.get(provider) if isinstance(keys, dict) else None
        return value or None

    def set_api_key(self, provider: str, key: str | None) -> None:
        keys = dict(self.repo.get(API_KEYS, {}) or {})
        if key:
            keys[provider] = key.strip()
        else:
            keys.pop(provider, None)
        self.repo.set(API_KEYS, keys)

    def api_key_hints(self) -> dict[str, str | None]:
        """Masked view: enough to recognise a key, not enough to use it."""
        return {
            provider: _mask(self.api_key(provider)) for provider in API_KEY_PROVIDERS
        }

    # --- bulk --------------------------------------------------------------

    def effective_settings(self) -> Settings:
        """``Settings`` with the saved overrides applied.

        Lets the fetchers keep taking a plain ``Settings`` object while still
        honouring whatever the user changed in the UI.
        """
        return self.base.model_copy(
            update={
                "proxy": self.proxy,
                "per_domain_delay": self.per_domain_delay,
                "per_domain_concurrency": self.per_domain_concurrency,
                "request_timeout": self.request_timeout,
                "chapter_retry_limit": self.chapter_retry_limit,
            }
        )

    def as_dict(self) -> dict[str, Any]:
        """Everything the Settings page shows, secrets masked."""
        return {
            "proxy": self.proxy,
            "browser_enabled": self.browser_enabled,
            "translate_provider": self.translate_provider,
            "per_domain_delay": self.per_domain_delay,
            "per_domain_concurrency": self.per_domain_concurrency,
            "request_timeout": self.request_timeout,
            "chapter_retry_limit": self.chapter_retry_limit,
            "follow_enabled": self.follow_enabled,
            "follow_interval_hours": self.follow_interval_hours,
            "cookies": self.cookies,
            "api_keys": self.api_key_hints(),
        }

    def update(self, changes: dict[str, Any]) -> None:
        """Apply a partial update from the Settings page."""
        for key in (
            PROXY,
            BROWSER_ENABLED,
            TRANSLATE_PROVIDER,
            PER_DOMAIN_DELAY,
            PER_DOMAIN_CONCURRENCY,
            REQUEST_TIMEOUT,
            CHAPTER_RETRY_LIMIT,
            FOLLOW_ENABLED,
            FOLLOW_INTERVAL_HOURS,
        ):
            if key in changes:
                self.repo.set(key, changes[key])

        if COOKIES in changes and changes[COOKIES] is not None:
            self.set_cookies(changes[COOKIES])

        for provider, value in (changes.get(API_KEYS) or {}).items():
            if provider in API_KEY_PROVIDERS:
                self.set_api_key(provider, value)


# --- helpers ---------------------------------------------------------------


def _parse_cookie_header(raw: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for part in raw.split(";"):
        name, _, value = part.partition("=")
        name, value = name.strip(), value.strip()
        if name and value:
            cookies[name] = value
    return cookies


def _mask(value: str | None) -> str | None:
    if not value:
        return None
    tail = value[-4:] if len(value) > 4 else value
    return f"••••{tail}"
