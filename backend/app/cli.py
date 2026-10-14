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


@app.command("fetch")
def fetch_url(
    url: str = typer.Argument(..., help="Page to fetch"),
    encoding: str | None = typer.Option(None, help="Force a charset, e.g. gb18030"),
    head: int = typer.Option(600, help="How many characters of the body to print"),
) -> None:
    """Fetch one page and report what came back, or why it did not.

    This is the quickest way to tell whether a site is reachable at all before
    writing an adapter for it.
    """
    import asyncio

    from app.fetch import Blocked, FetchError, HttpFetcher

    setup_logging()

    async def run() -> int:
        fetcher = HttpFetcher()
        try:
            resp = await fetcher.get(url, encoding=encoding)
        except Blocked as exc:
            typer.secho(f"BLOCKED  {exc.reason}", fg=typer.colors.RED)
            typer.echo(f"url      {exc.url}")
            typer.echo("hint     needs the browser fetcher, a proxy, or cookies")
            return 2
        except FetchError as exc:
            typer.secho(f"FAILED   {exc}", fg=typer.colors.RED)
            return 1
        finally:
            await fetcher.aclose()

        typer.secho(f"OK       HTTP {resp.status}", fg=typer.colors.GREEN)
        typer.echo(f"url      {resp.url}")
        typer.echo(f"encoding {resp.encoding}")
        typer.echo(f"length   {len(resp.text)} chars")
        typer.echo(f"title    {_page_title(resp.text)}")
        if head > 0:
            typer.echo("-" * 60)
            typer.echo(resp.text[:head])
        return 0

    raise typer.Exit(asyncio.run(run()))


def _page_title(html: str) -> str:
    import re

    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else "(no title)"


crawl_app = typer.Typer(help="Inspect a site through its adapter", no_args_is_help=True)
app.add_typer(crawl_app, name="crawl")


def _run_with_source(url: str, action):
    """Resolve the adapter for ``url`` and run ``action(source)``."""
    import asyncio

    from app.fetch import Blocked, FetchError, HttpFetcher
    from app.sources import SourceError, UnsupportedSite, resolve

    setup_logging()

    async def run() -> int:
        fetcher = HttpFetcher()
        try:
            source = resolve(url, fetcher)
        except UnsupportedSite as exc:
            typer.secho(str(exc), fg=typer.colors.RED)
            await fetcher.aclose()
            return 3

        typer.secho(f"source   {source.key} ({source.name})", fg=typer.colors.CYAN)
        try:
            await action(source)
        except Blocked as exc:
            typer.secho(f"BLOCKED  {exc.reason}", fg=typer.colors.RED)
            typer.echo("hint     needs the browser fetcher, a proxy, or cookies")
            return 2
        except SourceError as exc:
            typer.secho(f"LAYOUT   {exc}", fg=typer.colors.YELLOW)
            typer.echo("hint     the site markup changed; selectors need updating")
            return 4
        except FetchError as exc:
            typer.secho(f"FAILED   {exc}", fg=typer.colors.RED)
            return 1
        finally:
            await fetcher.aclose()
        return 0

    raise typer.Exit(asyncio.run(run()))


@crawl_app.command("info")
def crawl_info(url: str = typer.Argument(..., help="Novel page URL")) -> None:
    """Print a novel's metadata as the adapter sees it."""

    async def action(source) -> None:
        info = await source.novel_info(url)
        typer.secho(f"title    {info.title}", fg=typer.colors.GREEN)
        typer.echo(f"author   {info.author}")
        typer.echo(f"status   {info.status.value}")
        typer.echo(f"lang     {info.lang.value}")
        typer.echo(f"genres   {', '.join(info.genres) or '-'}")
        typer.echo(f"cover    {info.cover_url or '-'}")
        typer.echo(f"url      {info.url}")
        if info.description:
            typer.echo(f"desc     {info.description[:200]}")

    _run_with_source(url, action)


@crawl_app.command("chapters")
def crawl_chapters(
    url: str = typer.Argument(..., help="Novel page URL"),
    show: int = typer.Option(5, help="How many chapters to list"),
) -> None:
    """List the chapters the adapter can see, including any numbering gaps."""

    async def action(source) -> None:
        chapters = await source.chapter_list(url)
        typer.secho(f"found    {len(chapters)} chapters", fg=typer.colors.GREEN)
        if chapters:
            numbers = [c.number for c in chapters]
            typer.echo(f"range    {numbers[0]} .. {numbers[-1]}")
            missing = sorted(set(range(numbers[0], numbers[-1] + 1)) - set(numbers))
            if missing:
                typer.echo(f"gaps     {len(missing)} missing, e.g. {missing[:8]}")
        for chapter in chapters[:show]:
            typer.echo(f"  {chapter.number:>5}  {chapter.title[:60]}")
            typer.echo(f"         {chapter.url}")

    _run_with_source(url, action)


@crawl_app.command("chapter")
def crawl_chapter(
    url: str = typer.Argument(..., help="Chapter URL"),
    head: int = typer.Option(500, help="How many characters to print"),
) -> None:
    """Fetch one chapter and print the cleaned text."""

    async def action(source) -> None:
        from app.sources.text import looks_like_content

        text = await source.chapter_content(url)
        ok = looks_like_content(text)
        colour = typer.colors.GREEN if ok else typer.colors.YELLOW
        typer.secho(f"length   {len(text)} chars (usable: {ok})", fg=colour)
        paragraphs = [p for p in text.split("\n\n") if p.strip()]
        typer.echo(f"paras    {len(paragraphs)}")
        typer.echo("-" * 60)
        typer.echo(text[:head])

    _run_with_source(url, action)


@crawl_app.command("search")
def crawl_search(
    query: str = typer.Argument(..., help="Novel name to look for"),
    site: str = typer.Option("truyenhoan", help="Source key to search"),
    limit: int = typer.Option(10, help="Max results"),
) -> None:
    """Search one site by name."""
    import asyncio

    from app.fetch import FetchError, HttpFetcher
    from app.sources import get_by_key

    setup_logging()

    source_cls = get_by_key(site)
    if source_cls is None:
        typer.secho(f"Unknown source: {site}", fg=typer.colors.RED)
        raise typer.Exit(3)

    async def run() -> int:
        fetcher = HttpFetcher()
        try:
            results = await source_cls(fetcher).search(query, limit=limit)
        except FetchError as exc:
            typer.secho(f"FAILED   {exc}", fg=typer.colors.RED)
            return 1
        finally:
            await fetcher.aclose()

        typer.secho(f"{len(results)} results", fg=typer.colors.GREEN)
        for ref in results:
            typer.echo(f"  {ref.title}")
            typer.echo(f"    {ref.url}  ({ref.author or '-'})")
        return 0

    raise typer.Exit(asyncio.run(run()))


@crawl_app.command("download")
def crawl_download(
    url: str = typer.Argument(..., help="Novel page URL"),
    limit: int | None = typer.Option(None, help="Stop after this many chapters"),
) -> None:
    """Run a full crawl in the foreground, printing progress as it goes.

    Same pipeline the web UI drives, just without the server. Re-running it
    picks up where the last run stopped.
    """
    import asyncio

    from app.db.session import create_db_and_tables
    from app.fetch import HttpFetcher
    from app.pipeline import CrawlRunner, EventHub, JobControl
    from app.pipeline.manager import JobManager

    setup_logging()
    create_db_and_tables()

    async def run() -> int:
        hub = EventHub()
        manager = JobManager(hub=hub)
        job = manager.create_job(url=url, params={"limit": limit} if limit else None)
        job_id = job.id

        fetcher = HttpFetcher()
        runner = CrawlRunner(fetcher=fetcher, hub=hub)

        async def show() -> None:
            async for event in hub.stream(job_id):
                line = f"[{event.status}] {event.percent:5.1f}%  " \
                       f"done={event.done} failed={event.failed} skipped={event.skipped}"
                if event.message:
                    line += f"  {event.message[:60]}"
                typer.echo(line)

        watcher = asyncio.create_task(show())
        try:
            await runner.run(job_id, JobControl())
        finally:
            await fetcher.aclose()
            await watcher

        with session_scope() as session:
            from app.db.repository import JobRepository

            final = JobRepository(session).get(job_id)
            typer.secho(
                f"job {job_id}: {final.status.value} "
                f"({final.done} done, {final.failed} failed, {final.skipped} skipped)",
                fg=typer.colors.GREEN
                if final.status.value == "done"
                else typer.colors.YELLOW,
            )
            return 0 if final.status.value == "done" else 1

    raise typer.Exit(asyncio.run(run()))


@app.command("export")
def export_novel(
    novel_id: int = typer.Argument(..., help="Novel id (see the library)"),
    fmt: str = typer.Option("epub", "--format", help="epub, txt or json"),
    translated: bool = typer.Option(False, help="Export the translation if there is one"),
    volume_size: int | None = typer.Option(
        None, help="Split EPUB into parts of this many chapters"
    ),
) -> None:
    """Write a downloaded novel out as EPUB, TXT or JSON."""
    from app.export import ExportFormat, ExportService, NothingToExport

    setup_logging()

    try:
        chosen = ExportFormat(fmt.lower())
    except ValueError:
        typer.secho(
            f"Unknown format: {fmt} (use epub, txt or json)", fg=typer.colors.RED
        )
        raise typer.Exit(2) from None

    try:
        result = ExportService().export(
            novel_id, chosen, translated=translated, volume_size=volume_size
        )
    except LookupError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(3) from None
    except NothingToExport as exc:
        typer.secho(str(exc), fg=typer.colors.YELLOW)
        raise typer.Exit(4) from None

    typer.secho(f"wrote {result.path}", fg=typer.colors.GREEN)
    typer.echo(f"chapters {result.chapters}")
    typer.echo(f"parts    {result.parts}")
    typer.echo(f"size     {result.size_bytes / 1024:.0f} KiB")
    if result.missing:
        typer.echo(
            f"missing  {len(result.missing)} chapter(s) had no text, e.g. "
            f"{result.missing[:8]}"
        )


@app.command("jobs")
def list_jobs(limit: int = typer.Option(10, help="How many jobs to show")) -> None:
    """Show recent jobs and their outcome."""
    from app.db.repository import JobRepository

    setup_logging()
    with session_scope() as session:
        for job in JobRepository(session).list(limit=limit):
            typer.echo(
                f"#{job.id:<4} {job.type.value:<9} {job.status.value:<10} "
                f"total={job.total:<5} done={job.done:<5} failed={job.failed:<4} "
                f"skipped={job.skipped:<4} {job.error or ''}"[:140]
            )


@app.command("sources")
def list_sources() -> None:
    """Show every registered adapter."""
    from app.sources import all_sources

    for source_cls in sorted(all_sources(), key=lambda c: c.key):
        browser = " [needs browser]" if source_cls.needs_browser else ""
        typer.echo(f"{source_cls.key:14} {source_cls.lang.value}  "
                   f"{', '.join(source_cls.domains)}{browser}")


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
