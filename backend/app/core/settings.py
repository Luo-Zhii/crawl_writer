"""Application settings.

Everything is local-first: SQLite under ``data/`` and chapter text on disk.
Values can be overridden with ``CRAWLW_`` prefixed environment variables or a
``.env`` file at the repository root.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/settings.py -> repo root is three parents up from `app`
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CRAWLW_",
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Paths -------------------------------------------------------------
    data_dir: Path = REPO_ROOT / "data"

    # --- API ---------------------------------------------------------------
    api_prefix: str = "/api"
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # --- Fetching ----------------------------------------------------------
    user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    request_timeout: float = 30.0
    max_retries: int = 3
    # Politeness: minimum delay between two requests to the same host.
    per_domain_delay: float = 0.6
    # How many chapters to fetch in parallel per host.
    per_domain_concurrency: int = 4
    proxy: str | None = None

    # --- Crawl -------------------------------------------------------------
    chapter_retry_limit: int = 3

    @property
    def db_path(self) -> Path:
        return self.data_dir / "crawlw.db"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def novels_dir(self) -> Path:
        return self.data_dir / "novels"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.novels_dir, self.exports_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
