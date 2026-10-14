"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.router import api_router
from app.core.logging import get_logger, setup_logging
from app.core.settings import get_settings
from app.db.session import upgrade_to_head
from app.pipeline.manager import JobManager
from app.scheduler import FollowScheduler

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = get_settings()
    settings.ensure_dirs()
    # Migrations rather than create_all: the latter cannot add a column to an
    # existing table, which would leave the schema behind and break queries.
    upgrade_to_head()
    log.info("crawl_writer %s starting, data dir: %s", __version__, settings.data_dir)

    # The worker lives for the life of the process. Starting it here also
    # picks up any crawl a previous run left unfinished.
    manager = JobManager(settings=settings)
    app.state.job_manager = manager
    await manager.start()

    # Started after the worker, because a due check enqueues jobs the worker
    # has to be there to pick up.
    follow = FollowScheduler(manager)
    app.state.follow_scheduler = follow
    follow.start()

    try:
        yield
    finally:
        follow.shutdown()
        await manager.stop()
        log.info("crawl_writer shutting down")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="crawl_writer",
        version=__version__,
        summary="Local-first novel crawler and offline reader.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
