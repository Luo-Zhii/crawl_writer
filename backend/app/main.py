"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.router import api_router
from app.core.logging import get_logger, setup_logging
from app.core.settings import get_settings

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = get_settings()
    settings.ensure_dirs()
    log.info("crawl_writer %s starting, data dir: %s", __version__, settings.data_dir)
    yield
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
