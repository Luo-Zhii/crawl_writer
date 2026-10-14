"""Command line interface.

Useful for poking at the system without the web UI, and for the demo/seed
commands used while building.
"""

from __future__ import annotations

import typer

from app.core.logging import setup_logging
from app.core.settings import get_settings
from app.db.models import Chapter, ChapterStatus, Lang, Novel, NovelStatus
from app.db.repository import ChapterRepository, NovelRepository
from app.db.session import create_db_and_tables, session_scope
from app.db.storage import ChapterStorage

app = typer.Typer(help="crawl_writer admin CLI", no_args_is_help=True)
db_app = typer.Typer(help="Database maintenance", no_args_is_help=True)
app.add_typer(db_app, name="db")


@db_app.command("init")
def db_init() -> None:
    """Create the database and tables if they do not exist."""
    setup_logging()
    settings = get_settings()
    create_db_and_tables()
    typer.echo(f"database ready at {settings.db_path}")


@db_app.command("seed-demo")
def db_seed_demo(chapters: int = typer.Option(5, help="How many fake chapters to create")) -> None:
    """Insert one fake novel so the library endpoints have something to show."""
    setup_logging()
    create_db_and_tables()
    storage = ChapterStorage()

    with session_scope() as session:
        novels = NovelRepository(session)
        source_url = "https://example.test/truyen/demo"

        existing = novels.get_by_source_url("demo", source_url)
        if existing is not None:
            typer.echo(f"demo novel already exists with id {existing.id}")
            raise typer.Exit()

        novel = novels.add(
            Novel(
                source="demo",
                source_url=source_url,
                title="Truyện Demo",
                author="Tác giả Demo",
                description="Truyện giả dùng để kiểm tra API thư viện.",
                lang=Lang.vi,
                status=NovelStatus.ongoing,
                genres=["Tiên hiệp", "Huyền huyễn"],
            )
        )

        # Read the id while the session is still open; the instance detaches
        # once the scope exits.
        novel_id = novel.id

        rows = []
        for number in range(1, chapters + 1):
            text = f"Chương {number}\n\nĐây là nội dung giả của chương {number}.\n"
            char_count = storage.write(novel_id, number, text)
            rows.append(
                Chapter(
                    novel_id=novel_id,
                    number=number,
                    title=f"Chương {number}: Khởi đầu",
                    source_url=f"{source_url}/chuong-{number}",
                    status=ChapterStatus.done,
                    char_count=char_count,
                )
            )
        ChapterRepository(session).add_many(rows)

    typer.echo(f"seeded novel id {novel_id} with {chapters} chapters")


@app.command("paths")
def show_paths() -> None:
    """Print where data is stored. Handy when something looks missing."""
    settings = get_settings()
    typer.echo(f"data dir : {settings.data_dir}")
    typer.echo(f"database : {settings.db_path}")
    typer.echo(f"novels   : {settings.novels_dir}")
    typer.echo(f"exports  : {settings.exports_dir}")


if __name__ == "__main__":
    app()
