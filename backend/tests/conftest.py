"""Shared test fixtures.

Every test runs against a throwaway data dir so nothing touches the real
library in ``data/``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.settings import get_settings
from app.db import session as db_session
from app.db.models import Chapter, ChapterStatus, Lang, Novel, NovelStatus
from app.db.repository import ChapterRepository, NovelRepository
from app.db.storage import ChapterStorage


@pytest.fixture(autouse=True)
def temp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point settings at a temp dir and give each test a fresh database."""
    monkeypatch.setenv("CRAWLW_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    db_session.reset_engine()

    get_settings().ensure_dirs()
    db_session.create_db_and_tables()

    yield tmp_path

    db_session.reset_engine()
    get_settings.cache_clear()


@pytest.fixture
def session() -> Iterator[Session]:
    with Session(db_session.get_engine()) as session:
        yield session


@pytest.fixture
def storage(temp_data_dir: Path) -> ChapterStorage:
    return ChapterStorage(temp_data_dir / "novels")


@pytest.fixture
def client() -> Iterator[TestClient]:
    from app.main import create_app

    with TestClient(create_app()) as client:
        yield client


@pytest.fixture
def novel_factory(session: Session):
    """Create a novel, optionally with chapters whose text is on disk."""

    def _make(
        *,
        title: str = "Truyện Thử",
        source: str = "demo",
        source_url: str | None = None,
        lang: Lang = Lang.vi,
        chapters: int = 0,
        chapter_status: ChapterStatus = ChapterStatus.done,
    ) -> Novel:
        novels = NovelRepository(session)
        novel = novels.add(
            Novel(
                source=source,
                source_url=source_url or f"https://example.test/{title}",
                title=title,
                author="Tác giả",
                lang=lang,
                status=NovelStatus.ongoing,
                genres=["Tiên hiệp"],
            )
        )

        if chapters:
            store = ChapterStorage()
            rows = []
            for number in range(1, chapters + 1):
                char_count = 0
                if chapter_status is ChapterStatus.done:
                    char_count = store.write(
                        novel.id, number, f"Nội dung chương {number}.\n"
                    )
                rows.append(
                    Chapter(
                        novel_id=novel.id,
                        number=number,
                        title=f"Chương {number}",
                        source_url=f"{novel.source_url}/chuong-{number}",
                        status=chapter_status,
                        char_count=char_count,
                    )
                )
            ChapterRepository(session).add_many(rows)

        return novel

    return _make
