"""Crawl job endpoints, including the progress stream."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlmodel import Session
from sse_starlette.sse import EventSourceResponse

from app.api.schemas import (
    JobCreate,
    JobListResponse,
    JobRead,
    PreviewRequest,
    PreviewResponse,
    SourceInfo,
)
from app.db.models import JobStatus, JobType
from app.db.repository import JobRepository, NovelRepository
from app.db.session import get_session, session_scope
from app.fetch import Blocked, FetchError, HttpFetcher
from app.pipeline.manager import JobManager
from app.sources import SourceError, all_sources, find_for_url

router = APIRouter(tags=["jobs"])

# How often to send a comment so proxies do not close an idle stream.
_KEEPALIVE_SECONDS = 15.0


def get_manager(request: Request) -> JobManager:
    manager = getattr(request.app.state, "job_manager", None)
    if manager is None:  # pragma: no cover - set up in the app lifespan
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "Background worker is not running"
        )
    return manager


@router.get("/sources", response_model=list[SourceInfo], tags=["meta"])
def list_sources() -> list[SourceInfo]:
    """Which sites this build can crawl."""
    return [
        SourceInfo(
            key=cls.key,
            name=cls.name,
            domains=list(cls.domains),
            lang=cls.lang,
            needs_browser=cls.needs_browser,
        )
        for cls in sorted(all_sources(), key=lambda c: c.key)
    ]


@router.post("/preview", response_model=PreviewResponse, tags=["meta"])
async def preview_url(
    payload: PreviewRequest,
    session: Session = Depends(get_session),
) -> PreviewResponse:
    """Look up a pasted URL without saving anything.

    Lets the user confirm they got the right novel before starting a crawl
    that could run for several minutes.
    """
    source_cls = find_for_url(payload.url)
    if source_cls is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"No adapter handles this URL: {payload.url}",
        )

    fetcher = HttpFetcher()
    try:
        source = source_cls(fetcher)
        url = payload.url
        if getattr(source, "is_chapter_url", None) and source.is_chapter_url(url):
            url = await source.novel_url_from_chapter(url)
        info = await source.novel_info(source.canonical_url(url))
    except Blocked as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Site refused the request: {exc.reason}. "
            "This source needs a browser, a proxy or cookies.",
        ) from exc
    except SourceError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Could not read that page: {exc}. The site layout may have changed.",
        ) from exc
    except FetchError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    finally:
        await fetcher.aclose()

    existing = NovelRepository(session).get_by_source_url(source_cls.key, info.url)
    return PreviewResponse(
        source=source_cls.key,
        source_name=source_cls.name,
        url=info.url,
        title=info.title,
        author=info.author,
        cover_url=info.cover_url,
        description=info.description,
        genres=info.genres,
        status=info.status,
        lang=info.lang,
        novel_id=existing.id if existing else None,
    )


@router.post("/jobs", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
def create_job(
    payload: JobCreate,
    manager: JobManager = Depends(get_manager),
    session: Session = Depends(get_session),
) -> JobRead:
    """Queue a crawl. Returns immediately; follow progress on the event stream."""
    if not payload.url and payload.novel_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Provide either url or novel_id"
        )

    if payload.url and find_for_url(payload.url) is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"No adapter handles this URL: {payload.url}",
        )

    if payload.novel_id is not None and NovelRepository(session).get(payload.novel_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Novel not found")

    job = manager.create_job(
        url=payload.url, novel_id=payload.novel_id, job_type=payload.type
    )
    return JobRead.model_validate(job)


@router.get("/jobs", response_model=JobListResponse)
def list_jobs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    job_status: JobStatus | None = Query(None, alias="status"),
    session: Session = Depends(get_session),
) -> JobListResponse:
    repo = JobRepository(session)
    items = repo.list(limit=limit, offset=offset, status=job_status)
    return JobListResponse(
        items=[JobRead.model_validate(job) for job in items],
        total=len(repo.list(limit=200, offset=0, status=job_status)),
        limit=limit,
        offset=offset,
    )


@router.get("/jobs/{job_id}", response_model=JobRead)
def get_job(job_id: int, session: Session = Depends(get_session)) -> JobRead:
    job = JobRepository(session).get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return JobRead.model_validate(job)


@router.post("/jobs/{job_id}/pause", response_model=JobRead)
def pause_job(
    job_id: int,
    manager: JobManager = Depends(get_manager),
    session: Session = Depends(get_session),
) -> JobRead:
    job = JobRepository(session).get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    if not manager.pause(job_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Job is not running")
    session.refresh(job)
    return JobRead.model_validate(job)


@router.post("/jobs/{job_id}/resume", response_model=JobRead)
def resume_job(
    job_id: int,
    manager: JobManager = Depends(get_manager),
    session: Session = Depends(get_session),
) -> JobRead:
    job = JobRepository(session).get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    if not manager.resume_job(job_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Job cannot be resumed")
    session.refresh(job)
    return JobRead.model_validate(job)


@router.post("/jobs/{job_id}/cancel", response_model=JobRead)
def cancel_job(
    job_id: int,
    manager: JobManager = Depends(get_manager),
    session: Session = Depends(get_session),
) -> JobRead:
    job = JobRepository(session).get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    if not manager.cancel(job_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Job has already finished")
    session.refresh(job)
    return JobRead.model_validate(job)


@router.get("/jobs/{job_id}/events")
async def job_events(
    job_id: int,
    request: Request,
    manager: JobManager = Depends(get_manager),
) -> EventSourceResponse:
    """Server-sent events for one job.

    The first event is the current state read from the database, so a client
    that connects late (or reconnects) sees where things stand without having
    to poll.
    """
    async def stream() -> AsyncIterator[dict[str, str]]:
        with session_scope() as session:
            job = JobRepository(session).get(job_id)
            if job is None:
                yield {"event": "error", "data": json.dumps({"detail": "Job not found"})}
                return
            snapshot = JobRead.model_validate(job).model_dump(mode="json")

        yield {"event": "snapshot", "data": json.dumps(snapshot)}

        if snapshot["status"] in (
            JobStatus.done.value,
            JobStatus.failed.value,
            JobStatus.cancelled.value,
        ):
            # Nothing more will happen; let the client close cleanly.
            yield {"event": "end", "data": json.dumps(snapshot)}
            return

        async with manager.hub.subscribe(job_id) as queue:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_SECONDS)
                except TimeoutError:
                    yield {"event": "ping", "data": "{}"}
                    continue

                if event is None:
                    yield {"event": "end", "data": "{}"}
                    return
                yield {"event": "progress", "data": json.dumps(event.to_dict())}

    return EventSourceResponse(stream())


@router.post("/novels/{novel_id}/update", response_model=JobRead, status_code=202)
def update_novel_chapters(
    novel_id: int,
    manager: JobManager = Depends(get_manager),
    session: Session = Depends(get_session),
) -> JobRead:
    """Re-check a novel for new chapters and fetch whatever is missing."""
    if NovelRepository(session).get(novel_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Novel not found")

    job = manager.create_job(novel_id=novel_id, job_type=JobType.update)
    return JobRead.model_validate(job)
